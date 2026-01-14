import datetime

import boto3
import traitlets
from jupyterhub.spawner import Spawner
from tornado import gen
from tornado.concurrent import Future
from traitlets import Bool, Dict, Instance, Int, List, TraitType, Tuple, Type, Unicode, Union, default
from traitlets.config.configurable import Configurable


class Datetime(TraitType):
    klass = datetime.datetime
    default_value = datetime.datetime(1900, 1, 1)


class AWSSpawnerAuthentication(Configurable):
    def get_session(self, region) -> boto3.Session:
        return boto3.Session(region_name=region)


class AWSSpawnerSecretAccessKeyAuthentication(AWSSpawnerAuthentication):

    aws_access_key_id = Unicode(config=True)
    aws_secret_access_key = Unicode(config=True)

    def get_session(self, region) -> boto3.Session:
        return boto3.Session(region_name=region, aws_access_key_id=self.aws_access_key_id, aws_secret_access_key=self.aws_secret_access_key)


class AWSSpawner(Spawner):
    cpu = Int(default_value=-1, config=True)
    memory = Int(default_value=-1, config=True)
    memory_reservation = Int(default_value=-1, config=True)
    aws_region = Unicode(config=True)
    launch_type = Union([List(), Unicode()], config=True)
    assign_public_ip = Bool(False, config=True)
    task_role_arn = Unicode(config=True)
    task_cluster_name = Unicode(config=True)
    task_container_name = Unicode(config=True)
    task_definition_family = Unicode(config=True)
    task_definition_arn = Unicode("", config=True, help="ARN of the task definition to use directly")
    task_security_groups = List(trait=Unicode(), config=True)
    task_subnets = List(trait=Unicode(), config=True)
    notebook_scheme = Unicode(config=True)
    notebook_args = List(trait=Unicode(), config=True)
    args_join = Unicode(config=True)
    image = Unicode("", config=True)
    task_owner_tag_name = Unicode("Jupyter-User", config=True, help="Name of the tag used to identify the owner of the task")
    propagate_tags = Unicode("TASK_DEFINITION", config=True, help="How to propagate tags. Options: 'TASK_DEFINITION', 'SERVICE', 'NONE'")
    enable_ecs_managed_tags = Bool(True, config=True, help="Whether to enable Amazon ECS managed tags for the task")
    
    # ECS Anywhere specific configurations
    port_range_start = Int(default_value=8000, config=True, help="Start of port range for ECS Anywhere dynamic allocation")
    port_range_end = Int(default_value=9000, config=True, help="End of port range for ECS Anywhere dynamic allocation")
    use_dynamic_port = Bool(default_value=True, config=True, help="Use dynamic port allocation for ECS Anywhere")
    external_instance_id = Unicode(config=True, help="ECS Anywhere instance ID for placement constraints")
    placement_constraints = List(config=True, help="Placement constraints for ECS Anywhere tasks")

    authentication_class = Type(AWSSpawnerAuthentication, config=True)
    authentication = Instance(AWSSpawnerAuthentication)

    @default("authentication")
    def _default_authentication(self):
        return self.authentication_class(parent=self)

    task_arn = Unicode("")
    allocated_port = Int(default_value=0)  # Store allocated port for ECS Anywhere

    # options form
    profiles = List(
        trait=Tuple(Unicode(), Unicode(), Dict()),
        default_value=[],
        minlen=0,
        config=True,
        help="""List of profiles to offer for selection. Signature is:
            List(Tuple( Unicode, Unicode, Dict )) corresponding to
            profile display name, unique key, Spawner class, dictionary of spawner config options.
            The first three values will be exposed in the input_template as {display}, {key}, and {type}""",
    )

    config = Dict(default_value={}, config=True, help="Dictionary of config values to apply to wrapped spawner class.")

    form_template = Unicode(
        """<label for="profile">Select a job profile:</label>
        <select class="form-control" name="profile" required autofocus>
        {input_template}
        </select>
        """,
        config=True,
        help="""Template to use to construct options_form text. {input_template} is replaced with
            the result of formatting input_template against each item in the profiles list.""",
    )

    first_template = Unicode("selected", config=True, help="Text to substitute as {first} in input_template")

    input_template = Unicode(
        """
        <option value="{key}" {first}>{display}</option>""",
        config=True,
        help="""Template to construct {input_template} in form_template. This text will be formatted
            against each item in the profiles list, in order, using the following key names:
            ( display, key, type ) for the first three items in the tuple, and additionally
            first = "checked" (taken from first_template) for the first item in the list, so that
            the first item starts selected.""",
    )

    @default("options_form")
    def _options_form_default(self):
        if len(self.profiles) == 0:
            return None
        temp_keys = [dict(display=p[0], key=p[1], type=p[2], first="") for p in self.profiles]
        temp_keys[0]["first"] = self.first_template
        text = "".join([self.input_template.format(**tk) for tk in temp_keys])
        return self.form_template.format(input_template=text)

    def options_from_form(self, formdata):
        # Default to first profile if somehow none is provided
        return dict(profile=formdata.get("profile", [self.profiles[0][1]])[0])

    # load/get/clear : save/restore child_profile (and on load, use it to update child class/config)

    def select_profile(self, profile):
        # Select matching profile, or do nothing (leaving previous or default config in place)
        for p in self.profiles:
            if p[1] == profile:
                return p[2]
        return None

    def _is_ecs_anywhere(self):
        """Check if using ECS Anywhere launch type"""
        return (self.launch_type == "EXTERNAL" or 
                (isinstance(self.launch_type, list) and 
                 any(cp.get("capacityProvider") == "EXTERNAL" for cp in self.launch_type)))
    
    async def _allocate_port_for_node(self):
        """Allocate available port for ECS Anywhere node"""
        if not self.use_dynamic_port:
            return self._deterministic_port_allocation()
            
        session = self.authentication.get_session(self.aws_region)
        
        # Get used ports on the same node
        used_ports = await self._get_used_ports_on_node(session)
        
        # Find available port in range
        for port in range(self.port_range_start, self.port_range_end + 1):
            if port not in used_ports:
                self.log.info(f"Allocated port {port} for user {self.user.name}")
                self.allocated_port = port
                return port
        
        raise Exception(f"No available ports in range {self.port_range_start}-{self.port_range_end}")
    
    def _deterministic_port_allocation(self):
        """Generate deterministic port based on username"""
        import hashlib
        
        # Generate hash from username
        user_hash = hashlib.md5(self.user.name.encode()).hexdigest()
        port_offset = int(user_hash[:4], 16) % (self.port_range_end - self.port_range_start)
        port = self.port_range_start + port_offset
        
        self.log.info(f"Assigned deterministic port {port} for user {self.user.name}")
        self.allocated_port = port
        return port
    
    async def _get_used_ports_on_node(self, session):
        """Get ports already in use on ECS Anywhere nodes"""
        client = session.client("ecs")
        used_ports = set()
        
        try:
            # List all tasks in the cluster
            response = client.list_tasks(cluster=self.task_cluster_name)
            
            if response["taskArns"]:
                # Describe all tasks
                tasks_response = client.describe_tasks(
                    cluster=self.task_cluster_name,
                    tasks=response["taskArns"]
                )
                
                for task in tasks_response["tasks"]:
                    # Only check tasks running on ECS Anywhere nodes
                    if (task.get("launchType") == "EXTERNAL" and 
                        task.get("lastStatus") in ["RUNNING", "PENDING"]):
                        
                        # Extract port information from task
                        ports = self._extract_ports_from_task(task)
                        used_ports.update(ports)
                        
        except Exception as e:
            self.log.error(f"Failed to get used ports: {e}")
        
        return used_ports
    
    def _extract_ports_from_task(self, task):
        """Extract used ports from task definition"""
        ports = set()
        
        # Extract port mappings from containers
        for container in task.get("containers", []):
            for port_mapping in container.get("networkBindings", []):
                if port_mapping.get("hostPort"):
                    ports.add(port_mapping["hostPort"])
        
        return ports

    # We mostly are able to call the AWS API to determine status. However, when we yield the
    # event loop to create the task, if there is a poll before the creation is complete,
    # we must behave as though we are running/starting, but we have no IDs to use with which
    # to check the task.
    calling_run_task = Bool(False)

    progress_buffer = None

    def load_state(self, state):
        """Load state from database, including allocated port for ECS Anywhere"""
        super().load_state(state)
        # Called when first created: we might have no state from a previous invocation
        self.task_arn = state.get("task_arn", "")
        self.allocated_port = state.get("allocated_port", 0)

    def get_state(self):
        """Save state to database, including allocated port for ECS Anywhere"""
        state = super().get_state()
        state["task_arn"] = self.task_arn
        state["allocated_port"] = getattr(self, 'allocated_port', 0)
        return state

    async def poll(self):
        # Return values, as dictacted by the Jupyterhub framework:
        # 0                   == not running, or not starting up, i.e. we need to call start
        # None                == running, or not finished starting
        # 1, or anything else == error
        session = self.authentication.get_session(self.aws_region)

        return (
            None
            if self.calling_run_task
            else 0
            if self.task_arn == ""
            else None
            if (_get_task_status(self.log, session, self.task_cluster_name, self.task_arn)) in ALLOWED_STATUSES
            else 1
        )

    async def start(self):
        self.log.debug("Starting spawner")

        profile = self.user_options.get("profile")
        self.log.debug(f"profile {profile}")

        if profile:
            options = self.select_profile(profile)
            for key, value in options.items():
                attr = getattr(self, key)
                if isinstance(attr, dict):
                    attr.update(value)
                else:
                    setattr(self, key, value)

        # Handle port allocation for ECS Anywhere
        if self._is_ecs_anywhere():
            if self.allocated_port == 0:  # No port allocated yet
                task_port = await self._allocate_port_for_node()
            else:
                task_port = self.allocated_port  # Use previously allocated port
        else:
            task_port = self.port  # Use default port for Fargate
            
        session = self.authentication.get_session(self.aws_region)

        if self.task_definition_arn:
            # Use the specified task definition ARN directly
            task_definition = {"found": True, "arn": self.task_definition_arn}
        else:
            # Find or create task definition if not specified
            task_definition = _find_or_create_task_definition(self.log, session, self.task_definition_family, self.task_container_name, self.image)

        if task_definition["arn"] is None:
            raise Exception("TaskDefinition not found.")

        self.progress_buffer.write({"progress": 0.5, "message": "Run task..."})
        try:
            self.calling_run_task = True
            args = self.get_args() + self.notebook_args
            run_response = _run_task(
                self.log,
                session,
                self.launch_type,
                self.assign_public_ip,
                self.task_role_arn,
                self.task_cluster_name,
                self.task_container_name,
                task_definition["arn"],
                self.task_security_groups,
                self.task_subnets,
                self.cmd + args,
                self.get_env(),
                self.cpu,
                self.memory,
                self.memory_reservation,
                self.args_join,
                self.user.name,  # Pass the username for tagging
                self.task_owner_tag_name,  # Pass the tag name
                self.propagate_tags,  # Pass propagate_tags parameter
                self.enable_ecs_managed_tags,  # Pass enable_ecs_managed_tags parameter
                self.placement_constraints,  # Pass placement constraints for ECS Anywhere
            )
            task_arn = run_response["tasks"][0]["taskArn"]
            self.progress_buffer.write({"progress": 1})
        finally:
            self.calling_run_task = False

        self.task_arn = task_arn

        max_polls = self.start_timeout / 2
        num_polls = 0
        task_ip = ""
        while task_ip == "":
            num_polls += 1
            if num_polls >= max_polls:
                raise Exception("Task {} took too long to find IP address".format(self.task_arn))

            task_ip = _get_task_ip(self.log, session, self.task_cluster_name, task_arn)
            await gen.sleep(1)
            self.progress_buffer.write({"progress": 1 + num_polls / max_polls * 10, "message": "Getting network address.."})

        self.progress_buffer.write({"progress": 2})

        max_polls = self.start_timeout - num_polls
        num_polls = 0
        status = ""
        while status != "RUNNING":
            num_polls += 1
            if num_polls >= max_polls:
                raise Exception("Task {} took too long to become running".format(self.task_arn))

            status = _get_task_status(self.log, session, self.task_cluster_name, task_arn)
            if status not in ALLOWED_STATUSES:
                raise Exception("Task {} is {}".format(self.task_arn, status))

            await gen.sleep(1)
            self.progress_buffer.write({"progress": 10 + num_polls / max_polls * 90, "message": "Waiting for server to become running.."})

        self.progress_buffer.write({"progress": 100, "message": "Server started"})
        await gen.sleep(1)

        self.progress_buffer.close()

        return f"{self.notebook_scheme}://{task_ip}:{task_port}"

    async def stop(self, now=False):
        if self.task_arn == "":
            return
        session = self.authentication.get_session(self.aws_region)

        self.log.debug("Stopping task (%s)...", self.task_arn)
        _ensure_stopped_task(self.log, session, self.task_cluster_name, self.task_arn)
        self.log.debug("Stopped task (%s)... (done)", self.task_arn)

    def clear_state(self):
        super().clear_state()
        self.log.debug("Clearing state: (%s)", self.task_arn)
        self.task_arn = ""
        self.allocated_port = 0  # Reset allocated port
        self.progress_buffer = AsyncIteratorBuffer()

    async def progress(self):
        async for progress_message in self.progress_buffer:
            yield progress_message


ALLOWED_STATUSES = ("", "PROVISIONING", "PENDING", "RUNNING")


def _ensure_stopped_task(_, session, task_cluster_name, task_arn):
    client = session.client("ecs")
    client.stop_task(cluster=task_cluster_name, task=task_arn)


def _get_task_ip(logger, session, task_cluster_name, task_arn):
    """Get IP address for task, supporting both Fargate and ECS Anywhere"""
    described_task = _describe_task(logger, session, task_cluster_name, task_arn)
    
    if not described_task:
        return ""
    
    # Check if this is ECS Anywhere (EXTERNAL launch type)
    launch_type = described_task.get("launchType", "")
    
    if launch_type == "EXTERNAL":
        # For ECS Anywhere, get IP from container instance
        container_instance_arn = described_task.get("containerInstanceArn")
        if container_instance_arn:
            return _get_container_instance_ip(logger, session, task_cluster_name, container_instance_arn)
    else:
        # Original Fargate logic: get IP from ENI attachments
        ip_address_attachements = (
            [attachment["value"] for attachment in described_task["attachments"][0]["details"] 
             if attachment["name"] == "privateIPv4Address"]
            if described_task and "attachments" in described_task and described_task["attachments"]
            else []
        )
        if ip_address_attachements:
            return ip_address_attachements[0]
    
    return ""


def _get_container_instance_ip(logger, session, task_cluster_name, container_instance_arn):
    """Get IP address of ECS Anywhere container instance"""
    client = session.client("ecs")
    
    try:
        # Describe container instance
        response = client.describe_container_instances(
            cluster=task_cluster_name,
            containerInstances=[container_instance_arn]
        )
        
        if response["containerInstances"]:
            container_instance = response["containerInstances"][0]
            
            # Method 1: Get IP from attributes
            for attribute in container_instance.get("attributes", []):
                if attribute["name"] == "ecs.instance-ipv4-address":
                    return attribute["value"]
            
            # Method 2: If EC2 instance ID exists, get IP via EC2 API
            ec2_instance_id = container_instance.get("ec2InstanceId")
            if ec2_instance_id:
                return _get_ec2_instance_ip(logger, session, ec2_instance_id)
                
    except Exception as e:
        logger.error(f"Failed to get container instance IP: {e}")
    
    return ""


def _get_ec2_instance_ip(logger, session, instance_id):
    """Get IP address via EC2 instance ID"""
    try:
        ec2_client = session.client("ec2")
        response = ec2_client.describe_instances(InstanceIds=[instance_id])
        
        if response["Reservations"]:
            instance = response["Reservations"][0]["Instances"][0]
            # Return private IP first, fallback to public IP
            return (instance.get("PrivateIpAddress") or 
                   instance.get("PublicIpAddress") or "")
                   
    except Exception as e:
        logger.error(f"Failed to get EC2 instance IP: {e}")
    
    return ""


def _find_or_create_task_definition(logger, session, task_definition_family, task_container_name, image):
    client = session.client("ecs")
    task_definitions = client.list_task_definitions(familyPrefix=task_definition_family, status="ACTIVE", sort="DESC")

    create_definition = None

    for arn in task_definitions["taskDefinitionArns"]:
        definition = client.describe_task_definition(taskDefinition=arn)
        container_definition = next(filter(lambda x: x["name"] == task_container_name, definition["taskDefinition"]["containerDefinitions"]), None)

        if container_definition:
            if image == "" or container_definition["image"] == image:
                return {"found": True, "arn": arn}
            elif create_definition is None:
                container_definition["image"] = image
                create_definition = definition["taskDefinition"]

    if create_definition:
        del (
            create_definition["taskDefinitionArn"],
            create_definition["revision"],
            create_definition["status"],
            create_definition["requiresAttributes"],
            create_definition["compatibilities"],
            create_definition["registeredAt"],
            create_definition["registeredBy"],
        )
        # create
        res = client.register_task_definition(**create_definition)
        arn = res["taskDefinition"]["taskDefinitionArn"]

        return {"found": False, "arn": arn}

    return {"found": False, "arn": None}


def _get_task_status(logger, session, task_cluster_name, task_arn):
    described_task = _describe_task(logger, session, task_cluster_name, task_arn)
    status = described_task["lastStatus"] if described_task else ""
    return status


def _describe_task(_, session, task_cluster_name, task_arn):
    client = session.client("ecs")

    described_tasks = client.describe_tasks(cluster=task_cluster_name, tasks=[task_arn])

    # Very strangely, sometimes 'tasks' is returned, sometimes 'task'
    # Also, creating a task seems to be eventually consistent, so it might
    # not be present at all
    task = (
        described_tasks["tasks"][0]
        if "tasks" in described_tasks and described_tasks["tasks"]
        else described_tasks["task"]
        if "task" in described_tasks
        else None
    )
    return task


def _run_task(
    _,
    session,
    launch_type,
    assign_public_ip,
    task_role_arn,
    task_cluster_name,
    task_container_name,
    task_definition_arn,
    task_security_groups,
    task_subnets,
    task_command_and_args,
    task_env,
    cpu,
    memory,
    memory_reservation,
    args_join="",
    username="",
    owner_tag_name="",
    propagate_tags=None,
    enable_ecs_managed_tags=None,
    placement_constraints=None,
):
    if args_join != "":
        task_command_and_args = [args_join.join(task_command_and_args)]

    client = session.client("ecs")

    dict_data = {
        "cluster": task_cluster_name,
        "taskDefinition": task_definition_arn,
        "enableExecuteCommand": True,
        "overrides": {
            "containerOverrides": [
                {
                    "command": task_command_and_args,
                    "environment": [
                        {
                            "name": name,
                            "value": value,
                        }
                        for name, value in task_env.items()
                    ],
                    "name": task_container_name,
                }
            ],
        },
        "count": 1,
        "tags": [{"key": owner_tag_name, "value": username}],
    }

    # Add propagateTags if provided
    if propagate_tags is not None:
        dict_data["propagateTags"] = propagate_tags

    # Add enableECSManagedTags if provided
    if enable_ecs_managed_tags is not None:
        dict_data["enableECSManagedTags"] = enable_ecs_managed_tags

    # Add placement constraints if provided
    if placement_constraints:
        dict_data["placementConstraints"] = placement_constraints

    if task_definition_arn != traitlets.Undefined:
        dict_data["overrides"]["taskRoleArn"] = task_role_arn

    if cpu >= 0:
        dict_data["overrides"]["cpu"] = cpu

    if memory >= 0:
        dict_data["overrides"]["memory"] = memory

    if memory_reservation >= 0:
        dict_data["overrides"]["memoryReservation"] = memory_reservation

    # Handle launch type configuration
    if launch_type != traitlets.Undefined:
        if isinstance(launch_type, list):
            dict_data["capacityProviderStrategy"] = launch_type
        elif launch_type == "FARGATE_SPOT":
            dict_data["capacityProviderStrategy"] = [{"base": 1, "capacityProvider": "FARGATE_SPOT", "weight": 1}]
        elif launch_type == "EXTERNAL":
            dict_data["launchType"] = "EXTERNAL"
            # For ECS Anywhere, network configuration is not needed
        else:
            dict_data["launchType"] = launch_type
            # Add network configuration for Fargate/EC2
            dict_data["networkConfiguration"] = {
                "awsvpcConfiguration": {
                    "assignPublicIp": "ENABLED" if assign_public_ip else "DISABLED",
                    "securityGroups": task_security_groups,
                    "subnets": task_subnets,
                },
            }
    else:
        # Default network configuration for non-EXTERNAL launch types
        dict_data["networkConfiguration"] = {
            "awsvpcConfiguration": {
                "assignPublicIp": "ENABLED" if assign_public_ip else "DISABLED",
                "securityGroups": task_security_groups,
                "subnets": task_subnets,
            },
        }
        
    return client.run_task(**dict_data)


class AsyncIteratorBuffer:
    # The progress streaming endpoint may be requested multiple times, so each
    # call to `__aiter__` must return an iterator that starts from the first message

    class _Iterator:
        def __init__(self, parent):
            self.parent = parent
            self.cursor = 0

        async def __anext__(self):
            future = self.parent.futures[self.cursor]
            self.cursor += 1
            return await future

    def __init__(self):
        self.futures = [Future()]

    def __aiter__(self):
        return self._Iterator(self)

    def close(self):
        self.futures[-1].set_exception(StopAsyncIteration())

    def write(self, item):
        self.futures[-1].set_result(item)
        self.futures.append(Future())
