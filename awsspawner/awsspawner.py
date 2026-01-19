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
    
    # Hub connectivity configuration
    hub_connect_url = Unicode(config=True, help="URL for containers to connect back to JupyterHub. If not set, uses the default hub URL. For ECS Anywhere, this should be the external IP/hostname of the JupyterHub server.")

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

    def get_env(self):
        """Get environment variables for the spawned container, with Hub connectivity fixes"""
        env = super().get_env()
        
        # Log the original environment variables from JupyterHub base class
        self.log.info("=== Original JupyterHub Environment Variables ===")
        for key, value in env.items():
            if key.startswith('JUPYTERHUB_'):
                if 'TOKEN' in key:
                    self.log.info(f"  {key}: [REDACTED - {len(value)} chars]")
                else:
                    self.log.info(f"  {key}: '{value}'")
        self.log.info("=== End Original Environment Variables ===")
        
        # Only fix Hub connectivity if explicitly configured and using ECS Anywhere
        if self.hub_connect_url and self._is_ecs_anywhere():
            # Parse the hub_connect_url to replace the host in JUPYTERHUB_API_URL
            import urllib.parse
            
            # Get the original API URL
            original_api_url = env.get('JUPYTERHUB_API_URL', '')
            
            if original_api_url:
                # Parse both URLs
                original_parsed = urllib.parse.urlparse(original_api_url)
                hub_parsed = urllib.parse.urlparse(self.hub_connect_url)
                
                # Replace the netloc (host:port) but keep the path
                new_api_url = original_parsed._replace(
                    scheme=hub_parsed.scheme or original_parsed.scheme,
                    netloc=hub_parsed.netloc
                ).geturl()
                
                env['JUPYTERHUB_API_URL'] = new_api_url
                self.log.info(f"Updated JUPYTERHUB_API_URL from '{original_api_url}' to '{new_api_url}' for ECS Anywhere")
            
            # Also update JUPYTERHUB_BASE_URL if needed
            original_base_url = env.get('JUPYTERHUB_BASE_URL', '')
            if original_base_url and not original_base_url.startswith('http'):
                # If base URL is relative, make it absolute using hub_connect_url
                hub_parsed = urllib.parse.urlparse(self.hub_connect_url)
                base_scheme_netloc = f"{hub_parsed.scheme}://{hub_parsed.netloc}"
                env['JUPYTERHUB_BASE_URL'] = base_scheme_netloc + original_base_url
                self.log.info(f"Updated JUPYTERHUB_BASE_URL to '{env['JUPYTERHUB_BASE_URL']}' for ECS Anywhere")
        elif self._is_ecs_anywhere():
            # Warn if using ECS Anywhere without hub_connect_url
            self.log.warning("Using ECS Anywhere without hub_connect_url configured. "
                           "If containers fail to connect to JupyterHub, set c.AWSSpawner.hub_connect_url")
        
        return env

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
            # For ECS Anywhere, we'll get the actual port from run_task response
            # Use a placeholder port for now
            task_port = 8888  # This will be updated after task starts
        else:
            task_port = self.port  # Use default port for Fargate
            
        # Initialize actual_task_port early for logging
        actual_task_port = task_port  # Default to original port
            
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


    
            # Handle port allocation for ECS Anywhere
            if self._is_ecs_anywhere():
                # For ECS Anywhere, use port 80 instead of dynamic allocation
                self.port = 80
                self.ip = '0.0.0.0'

            
            args = self.get_args() + self.notebook_args

            # Debug logging for troubleshooting
            self.log.info("=== AWSSpawner Start Parameters ===")
            self.log.info(f"User: '{self.user.name}'")
            self.log.info(f"Task cluster name: '{self.task_cluster_name}'")
            self.log.info(f"Task container name: '{self.task_container_name}'")
            self.log.info(f"Task definition ARN: '{task_definition['arn']}'")
            self.log.info(f"Task definition family: '{self.task_definition_family}'")
            self.log.info(f"Launch type: {self.launch_type}")
            self.log.info(f"AWS region: '{self.aws_region}'")
            self.log.info(f"Image: '{self.image}'")
            self.log.info(f"CPU: {self.cpu}")
            self.log.info(f"Memory: {self.memory}")
            self.log.info(f"Memory reservation: {self.memory_reservation}")
            self.log.info(f"Task port: {task_port}")
            self.log.info(f"Actual task port: {actual_task_port} (may be updated after task starts for ECS Anywhere)")
            self.log.info(f"Notebook scheme: '{self.notebook_scheme}'")
            self.log.info(f"Owner tag name: '{self.task_owner_tag_name}'")
            self.log.info(f"Task role ARN: '{self.task_role_arn}'")
            self.log.info(f"Security groups: {self.task_security_groups}")
            self.log.info(f"Subnets: {self.task_subnets}")
            self.log.info(f"Assign public IP: {self.assign_public_ip}")
            self.log.info(f"Placement constraints: {self.placement_constraints}")
            self.log.info(f"Args join: '{self.args_join}'")
            self.log.info(f"Notebook args: {self.notebook_args}")
            self.log.info(f"Command: {self.cmd}")
            self.log.info(f"Args: {args}")
            self.log.info(f"Final command + args: {self.cmd + args}")
            self.log.info("=== End AWSSpawner Parameters ===")
            
            # Validate required parameters before calling _run_task with specific error messages
            missing_params = []
            
            if not self.task_cluster_name:
                missing_params.append("task_cluster_name (set c.AWSSpawner.task_cluster_name)")
            if not self.task_container_name:
                missing_params.append("task_container_name (set c.AWSSpawner.task_container_name)")
            if not task_definition["arn"]:
                missing_params.append("task_definition_arn (set c.AWSSpawner.task_definition_arn or task_definition_family)")
            
            if missing_params:
                raise ValueError(f"Missing required configuration parameters: {', '.join(missing_params)}")
            
            # Validate environment variables
            env_vars = self.get_env()
            self.log.info(f"Environment variables count: {len(env_vars)}")
            
            empty_env_vars = [name for name, value in env_vars.items() if not name or not name.strip()]
            if empty_env_vars:
                raise ValueError(f"Found environment variables with empty names. This usually indicates a JupyterHub configuration issue. Empty variable names: {empty_env_vars}")
            



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
            
            # Validate run_task response
            if not run_response:
                raise Exception("ECS run_task returned empty response")
            
            if "tasks" not in run_response:
                raise Exception(f"ECS run_task response missing 'tasks' field. Response: {run_response}")
            
            if not run_response["tasks"]:
                # Check for failures
                failures = run_response.get("failures", [])
                if failures:
                    analyzed_failures = _analyze_ecs_failures(failures)
                    raise Exception(f"ECS run_task failed to create tasks. Detailed analysis:\n" + "\n".join(analyzed_failures))
                else:
                    raise Exception("ECS run_task returned no tasks and no failure information. This may indicate:\n"
                                  "1. Insufficient cluster capacity\n"
                                  "2. All container instances are busy\n"
                                  "3. Placement constraints cannot be satisfied\n"
                                  "4. Network configuration issues (for Fargate)\n"
                                  "5. Task definition compatibility issues")
            
            task_arn = run_response["tasks"][0]["taskArn"]
            self.log.info(f"Successfully created ECS task: {task_arn}")
            
            # Log any warnings from the response
            if "failures" in run_response and run_response["failures"]:
                self.log.warning(f"ECS run_task had some failures: {run_response['failures']}")
            
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
            
            self.log.info(f"Found task_ip: {task_ip}")
            
                    
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
        # For ECS Anywhere, also get the actual port from task
        if self._is_ecs_anywhere() and task_ip:
            self.log.info("Trying to find task port")
            port_from_task = _get_task_port(self.log, session, self.task_cluster_name, task_arn, self.task_container_name)
            self.log.info(f"Found task port: {port_from_task}")
            if port_from_task:
                actual_task_port = port_from_task
                self.allocated_port = port_from_task  # Store for state persistence
                self.log.info(f"Updated actual task port to: {actual_task_port}")
                

        self.log.debug(f"{self.notebook_scheme}://{task_ip}:{actual_task_port}")
        return f"{self.notebook_scheme}://{task_ip}:{actual_task_port}"

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


def _ensure_stopped_task(logger, session, task_cluster_name, task_arn):
    client = session.client("ecs")
    client.stop_task(cluster=task_cluster_name, task=task_arn)


def _get_task_port(logger, session, task_cluster_name, task_arn, container_name):
    """Get the actual port used by the task from run_task response"""
    described_task = _describe_task(logger, session, task_cluster_name, task_arn)
    logger.info(described_task)

    if not described_task:
        return None
    
    # Look for port mappings in containers
    for container in described_task.get("containers", []):
        if container.get("name") == container_name:
            # Get port mappings from network bindings
            for port_binding in container.get("networkBindings", []):
                host_port = port_binding.get("hostPort")
                if host_port:
                    logger.info(f"Found host port {host_port} for container {container_name}")
                    return host_port
            
            # If no network bindings, check if using host network mode
            # In host mode, container port = host port
            for port_mapping in container.get("portMappings", []):
                container_port = port_mapping.get("containerPort")
                if container_port:
                    logger.info(f"Using container port {container_port} (host network mode)")
                    return container_port
    
    return None


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
            
            # Method 1: Get IP from ECS attributes
            for attribute in container_instance.get("attributes", []):
                if attribute["name"] == "ecs.instance-ipv4-address":
                    return attribute["value"]
            
            # Method 2: For ECS Anywhere, try to get IP via SSM
            # ECS Anywhere nodes register with SSM, not EC2
            ec2_instance_id = container_instance.get("ec2InstanceId")
            if ec2_instance_id:
                # Check if this is actually an EC2 instance or ECS Anywhere node
                if ec2_instance_id.startswith("i-"):
                    # This is a real EC2 instance
                    return _get_ec2_instance_ip(logger, session, ec2_instance_id)
                else:
                    # This is likely an ECS Anywhere node with SSM managed instance ID
                    return _get_ssm_managed_instance_ip(logger, session, ec2_instance_id)
            
            # Method 3: Try to get from SSM using container instance ARN
            return _get_ip_from_ssm_by_container_instance(logger, session, container_instance_arn)
                
    except Exception as e:
        logger.error(f"Failed to get container instance IP: {e}")
    
    return ""


def _get_ssm_managed_instance_ip(logger, session, managed_instance_id):
    """Get IP address from SSM managed instance (ECS Anywhere)"""
    try:
        ssm_client = session.client("ssm")
        
        # Get instance information from SSM
        response = ssm_client.describe_instance_information(
            InstanceInformationFilterList=[
                {
                    'key': 'InstanceIds',
                    'valueSet': [managed_instance_id]
                }
            ]
        )
        
        if response["InstanceInformationList"]:
            instance_info = response["InstanceInformationList"][0]
            
            # Try to get IP from instance information
            ip_address = instance_info.get("IPAddress")
            if ip_address:
                logger.info(f"Found IP {ip_address} for SSM managed instance {managed_instance_id}")
                return ip_address
            
            # Alternative: Get IP from SSM inventory
            return _get_ip_from_ssm_inventory(logger, session, managed_instance_id)
                   
    except Exception as e:
        logger.error(f"Failed to get SSM managed instance IP: {e}")
    
    return ""


def _get_ip_from_ssm_inventory(logger, session, managed_instance_id):
    """Get IP address from SSM inventory data"""
    try:
        ssm_client = session.client("ssm")
        
        # Get network inventory from SSM
        response = ssm_client.get_inventory_entries(
            InstanceId=managed_instance_id,
            TypeName='AWS:Network'
        )
        
        if response["Entries"]:
            for entry in response["Entries"]:
                # Look for primary network interface
                if entry.get("Name") and "eth0" in entry.get("Name", "").lower():
                    ip_address = entry.get("IPV4")
                    if ip_address:
                        logger.info(f"Found IP {ip_address} from SSM inventory for {managed_instance_id}")
                        return ip_address
                        
            # Fallback: use first available IP
            for entry in response["Entries"]:
                ip_address = entry.get("IPV4")
                if ip_address and not ip_address.startswith("127."):
                    logger.info(f"Found fallback IP {ip_address} from SSM inventory for {managed_instance_id}")
                    return ip_address
                   
    except Exception as e:
        logger.error(f"Failed to get IP from SSM inventory: {e}")
    
    return ""


def _get_ip_from_ssm_by_container_instance(logger, session, container_instance_arn):
    """Get IP by finding SSM managed instance associated with container instance"""
    try:
        ssm_client = session.client("ssm")
        
        # Extract container instance ID from ARN
        container_instance_id = container_instance_arn.split("/")[-1]
        
        # Search for SSM managed instances with ECS container instance tag
        response = ssm_client.describe_instance_information(
            InstanceInformationFilterList=[
                {
                    'key': 'tag:ecs:container-instance-id',
                    'valueSet': [container_instance_id]
                }
            ]
        )
        
        if response["InstanceInformationList"]:
            instance_info = response["InstanceInformationList"][0]
            ip_address = instance_info.get("IPAddress")
            if ip_address:
                logger.info(f"Found IP {ip_address} via SSM tag search for container instance {container_instance_id}")
                return ip_address
                
        # Alternative: Search by ECS cluster association
        # This is a fallback method when direct tagging is not available
        response = ssm_client.describe_instance_information()
        
        for instance in response["InstanceInformationList"]:
            # Check if this instance might be associated with our ECS cluster
            # This is a heuristic approach and may need adjustment based on your setup
            if instance.get("PlatformType") == "Linux":
                managed_instance_id = instance["InstanceId"]
                # Try to verify this is our ECS Anywhere node by checking running processes
                if _verify_ecs_anywhere_node(logger, session, managed_instance_id, container_instance_id):
                    ip_address = instance.get("IPAddress")
                    if ip_address:
                        logger.info(f"Found IP {ip_address} via SSM verification for {managed_instance_id}")
                        return ip_address
                   
    except Exception as e:
        logger.error(f"Failed to get IP from SSM by container instance: {e}")
    
    return ""


def _verify_ecs_anywhere_node(logger, session, managed_instance_id, container_instance_id):
    """Verify if SSM managed instance is the ECS Anywhere node we're looking for"""
    try:
        ssm_client = session.client("ssm")
        
        # Run a command to check if this node has our container instance
        response = ssm_client.send_command(
            InstanceIds=[managed_instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={
                'commands': [
                    f'docker ps --filter "label=com.amazonaws.ecs.container-instance-id={container_instance_id}" --quiet'
                ]
            },
            TimeoutSeconds=30
        )
        
        command_id = response["Command"]["CommandId"]
        
        # Wait a moment for command to execute
        import time
        time.sleep(2)
        
        # Get command result
        result = ssm_client.get_command_invocation(
            CommandId=command_id,
            InstanceId=managed_instance_id
        )
        
        # If command succeeded and returned container IDs, this is our node
        if result["Status"] == "Success" and result.get("StandardOutputContent", "").strip():
            return True
            
    except Exception as e:
        logger.debug(f"ECS Anywhere node verification failed for {managed_instance_id}: {e}")
    
    return False


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
        # Remove read-only fields
        for field in ["taskDefinitionArn", "revision", "status", "requiresAttributes", 
                     "compatibilities", "registeredAt", "registeredBy"]:
            create_definition.pop(field, None)
        
        # Register new task definition
        res = client.register_task_definition(**create_definition)
        arn = res["taskDefinition"]["taskDefinitionArn"]
        logger.info(f"Created new task definition: {arn}")

        return {"found": False, "arn": arn}

    return {"found": False, "arn": None}


def _get_task_status(logger, session, task_cluster_name, task_arn):
    described_task = _describe_task(logger, session, task_cluster_name, task_arn)
    status = described_task["lastStatus"] if described_task else ""
    return status


def _describe_task(logger, session, task_cluster_name, task_arn):
    client = session.client("ecs")

    described_tasks = client.describe_tasks(cluster=task_cluster_name, tasks=[task_arn])
    logger.info(described_tasks)
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
    logger,
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
    # Validate required parameters with specific error messages
    if not task_cluster_name or not task_cluster_name.strip():
        raise ValueError("task_cluster_name cannot be empty. Please set c.AWSSpawner.task_cluster_name in your JupyterHub config.")
    if not task_container_name or not task_container_name.strip():
        raise ValueError("task_container_name cannot be empty. Please set c.AWSSpawner.task_container_name in your JupyterHub config.")
    if not task_definition_arn or not task_definition_arn.strip():
        raise ValueError("task_definition_arn cannot be empty. Please set c.AWSSpawner.task_definition_arn or ensure task definition family is configured.")
    
    if args_join != "":
        task_command_and_args = [args_join.join(task_command_and_args)]

    client = session.client("ecs")

    # Validate and filter environment variables
    valid_env_vars = []
    invalid_env_vars = []
    
    for name, value in task_env.items():
        if not name or not name.strip():
            invalid_env_vars.append(f"Empty environment variable name with value: '{value}'")
        else:
            valid_env_vars.append({"name": name, "value": value})
    
    if invalid_env_vars:
        raise ValueError(f"Invalid environment variables found: {'; '.join(invalid_env_vars)}")

    dict_data = {
        "cluster": task_cluster_name,
        "taskDefinition": task_definition_arn,
        "enableExecuteCommand": True,
        "overrides": {
            "containerOverrides": [
                {
                    "command": task_command_and_args,
                    "environment": valid_env_vars,
                    "name": task_container_name,
                }
            ],
        },
        "count": 1,
    }
    
    # Validate and add tags if both key and value are not empty
    if owner_tag_name and owner_tag_name.strip():
        if username and username.strip():
            dict_data["tags"] = [{"key": owner_tag_name, "value": username}]
        else:
            raise ValueError(f"username cannot be empty when owner_tag_name is set to '{owner_tag_name}'. Check user configuration.")
    elif owner_tag_name == "":
        # owner_tag_name is explicitly set to empty string, skip tagging
        pass
    else:
        # owner_tag_name is None or not configured, use default behavior
        if username and username.strip():
            dict_data["tags"] = [{"key": "Jupyter-User", "value": username}]

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
            # For capacity provider strategy, check if it includes EXTERNAL
            has_external = any(cp.get("capacityProvider") == "EXTERNAL" for cp in launch_type)
            if has_external:
                # For ECS Anywhere in capacity provider strategy, networkMode should be in task definition
                pass
            else:
                # Use awsvpc for Fargate/EC2 capacity providers
                dict_data["networkConfiguration"] = {
                    "awsvpcConfiguration": {
                        "assignPublicIp": "ENABLED" if assign_public_ip else "DISABLED",
                        "securityGroups": task_security_groups,
                        "subnets": task_subnets,
                    },
                }
        elif launch_type == "FARGATE_SPOT":
            dict_data["capacityProviderStrategy"] = [{"base": 1, "capacityProvider": "FARGATE_SPOT", "weight": 1}]
            # Fargate always uses awsvpc network mode
            dict_data["networkConfiguration"] = {
                "awsvpcConfiguration": {
                    "assignPublicIp": "ENABLED" if assign_public_ip else "DISABLED",
                    "securityGroups": task_security_groups,
                    "subnets": task_subnets,
                },
            }
        elif launch_type == "EXTERNAL":
            dict_data["launchType"] = "EXTERNAL"
            # For ECS Anywhere, networkMode should be set in task definition, not overrides
            # ECS Anywhere doesn't use awsvpc network configuration
        elif launch_type == "FARGATE":
            dict_data["launchType"] = "FARGATE"
            # Fargate always uses awsvpc network mode, don't override
            dict_data["networkConfiguration"] = {
                "awsvpcConfiguration": {
                    "assignPublicIp": "ENABLED" if assign_public_ip else "DISABLED",
                    "securityGroups": task_security_groups,
                    "subnets": task_subnets,
                },
            }
        else:
            # EC2 launch type - network mode is defined in task definition
            dict_data["launchType"] = launch_type
    else:
        # Default network configuration for non-EXTERNAL launch types
        dict_data["networkConfiguration"] = {
            "awsvpcConfiguration": {
                "assignPublicIp": "ENABLED" if assign_public_ip else "DISABLED",
                "securityGroups": task_security_groups,
                "subnets": task_subnets,
            },
        }
        
    # Print all parameters before calling run_task for debugging
    logger.info("=== ECS run_task Parameters ===")
    logger.info(f"cluster: '{task_cluster_name}'")
    logger.info(f"taskDefinition: '{task_definition_arn}'")
    logger.info(f"launch_type: {launch_type}")
    logger.info(f"assign_public_ip: {assign_public_ip}")
    logger.info(f"task_role_arn: '{task_role_arn}'")
    logger.info(f"task_container_name: '{task_container_name}'")
    logger.info(f"task_security_groups: {task_security_groups}")
    logger.info(f"task_subnets: {task_subnets}")
    logger.info(f"task_command_and_args: {task_command_and_args}")
    logger.info(f"cpu: {cpu}")
    logger.info(f"memory: {memory}")
    logger.info(f"memory_reservation: {memory_reservation}")
    logger.info(f"args_join: '{args_join}'")
    logger.info(f"username: '{username}'")
    logger.info(f"owner_tag_name: '{owner_tag_name}'")
    logger.info(f"propagate_tags: {propagate_tags}")
    logger.info(f"enable_ecs_managed_tags: {enable_ecs_managed_tags}")
    logger.info(f"placement_constraints: {placement_constraints}")
    
    logger.info("=== Environment Variables ===")
    for name, value in task_env.items():
        # Don't log sensitive values, just show the key and value length
        #if any(sensitive in name.upper() for sensitive in ['TOKEN', 'KEY', 'SECRET', 'PASSWORD']):
        #    logger.info(f"  {name}: [REDACTED - {len(str(value))} chars]")
        #else:
        logger.info(f"  {name}: '{value}'")
    
    logger.info("=== Final ECS API Request ===")
    # Create a copy for logging (without sensitive data)
    log_dict_data = dict(dict_data)
    #if 'overrides' in log_dict_data and 'containerOverrides' in log_dict_data['overrides']:
        #for container in log_dict_data['overrides']['containerOverrides']:
            #if 'environment' in container:
                #for env_var in container['environment']:
                    #if any(sensitive in env_var['name'].upper() for sensitive in ['TOKEN', 'KEY', 'SECRET', 'PASSWORD']):
                    #    env_var['value'] = f"[REDACTED - {len(env_var['value'])} chars]"
    
    logger.info(f"ECS run_task request payload: {log_dict_data}")
    logger.info("=== End Parameters ===")
    
    try:
        logger.info("Calling ECS run_task...")
        response = client.run_task(**dict_data)
        
        # Log the response for debugging
        logger.info("=== ECS run_task Response ===")
        logger.info(f"Response: {response}")
        logger.info("=== End Response ===")
        
        return response
    except Exception as e:
        logger.error(f"ECS run_task failed with error: {e}")
        _handle_run_task_error(e, dict_data)


def _analyze_ecs_failures(failures):
    """Analyze ECS task failures and provide helpful error messages"""
    common_issues = {
        "RESOURCE:MEMORY": "Insufficient memory available in the cluster. Try reducing memory requirements or scaling up your cluster.",
        "RESOURCE:CPU": "Insufficient CPU available in the cluster. Try reducing CPU requirements or scaling up your cluster.",
        "RESOURCE:PORTS": "Required ports are not available. This often happens with ECS Anywhere when ports are already in use.",
        "ATTRIBUTE": "Task placement constraints cannot be satisfied. Check your placement constraints and node attributes.",
        "AGENT": "ECS agent is not running or not connected. Check your ECS Anywhere node status.",
        "TASK_DEFINITION": "Task definition is invalid or not found. Verify your task definition exists and is active.",
        "SERVICE": "Service-related error. Check your ECS service configuration.",
        "CLUSTER": "Cluster-related error. Verify your cluster exists and is active.",
    }
    
    analyzed_failures = []
    for failure in failures:
        reason = failure.get("reason", "")
        detail = failure.get("detail", "")
        arn = failure.get("arn", "Unknown")
        
        # Try to match common failure patterns
        helpful_msg = None
        for pattern, message in common_issues.items():
            if pattern in reason:
                helpful_msg = message
                break
        
        if helpful_msg:
            analyzed_failures.append(f"ARN: {arn} - {reason}: {detail} (Suggestion: {helpful_msg})")
        else:
            analyzed_failures.append(f"ARN: {arn} - {reason}: {detail}")
    
    return analyzed_failures


def _handle_run_task_error(error, dict_data):
    """Provide detailed error information for RunTask failures"""
    error_msg = str(error)
    
    if "name cannot be blank" in error_msg:
        # Analyze the dict_data to find potential blank names
        issues = []
        
        # Check container name
        container_overrides = dict_data.get("overrides", {}).get("containerOverrides", [])
        for i, container in enumerate(container_overrides):
            if not container.get("name"):
                issues.append(f"Container override #{i} has empty 'name' field")
        
        # Check environment variables
        for i, container in enumerate(container_overrides):
            env_vars = container.get("environment", [])
            for j, env_var in enumerate(env_vars):
                if not env_var.get("name"):
                    issues.append(f"Container #{i}, environment variable #{j} has empty 'name' field")
        
        # Check tags
        tags = dict_data.get("tags", [])
        for i, tag in enumerate(tags):
            if not tag.get("key"):
                issues.append(f"Tag #{i} has empty 'key' field")
        
        if issues:
            detailed_msg = f"ECS RunTask failed with 'name cannot be blank'. Specific issues found: {'; '.join(issues)}"
        else:
            detailed_msg = f"ECS RunTask failed with 'name cannot be blank'. Check your JupyterHub configuration for empty required fields."
        
        raise ValueError(detailed_msg) from error
    
    # Re-raise original error if not a "name cannot be blank" issue
    raise error


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
