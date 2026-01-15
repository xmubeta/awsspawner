# awsspawner

Spawns JupyterHub single user servers in Docker containers running in AWS ECS Tasks (including EC2, Fargate, Fargate Spot, and ECS Anywhere).

## Features

- Run JupyterHub single user servers in AWS ECS Tasks
- Support for EC2, Fargate, Fargate Spot, and ECS Anywhere launch types
- Dynamic port allocation for ECS Anywhere to prevent conflicts
- Configurable resource allocation (CPU, memory)
- User profiles for different resource configurations
- Automatic tagging of tasks with configurable owner tag (using username)
- Support for custom Docker images
- Placement constraints for ECS Anywhere deployments

## Installation

You can install the package using pip:

```bash
pip install jupyterhub-awsspawner
```

Or using poetry:

```bash
poetry add jupyterhub-awsspawner
```

## Configuration

To use `awsspawner` in your JupyterHub deployment, you need to configure it in your `jupyterhub_config.py` file:

```python
c.JupyterHub.spawner_class = 'awsspawner.AWSSpawner'

# Required: AWS Region
c.AWSSpawner.aws_region = 'us-east-1'

# Required: ECS Cluster configuration
c.AWSSpawner.task_cluster_name = 'your-ecs-cluster-name'
c.AWSSpawner.task_definition_family = 'jupyter-notebook'
c.AWSSpawner.task_container_name = 'notebook'

# Optional: Specify task definition ARN directly (bypasses find/create logic)
# c.AWSSpawner.task_definition_arn = 'arn:aws:ecs:us-east-1:123456789012:task-definition/jupyter-notebook:1'

# Network configuration
c.AWSSpawner.task_security_groups = ['sg-xxxxxxxxxxxxxxxxx']
c.AWSSpawner.task_subnets = ['subnet-xxxxxxxxxxxxxxxxx']
c.AWSSpawner.assign_public_ip = True  # Set to False for private subnets

# Launch type configuration
# Option 1: Use a specific launch type
c.AWSSpawner.launch_type = 'FARGATE'  # Options: 'EC2', 'FARGATE', 'EXTERNAL'

# Option 2: Use Fargate Spot
c.AWSSpawner.launch_type = 'FARGATE_SPOT'

# Option 3: Use ECS Anywhere
c.AWSSpawner.launch_type = 'EXTERNAL'

# Option 4: Use capacity provider strategy
c.AWSSpawner.launch_type = [
    {'capacityProvider': 'FARGATE_SPOT', 'weight': 1, 'base': 1}
]

# Resource allocation (optional)
c.AWSSpawner.cpu = 1024  # 1 vCPU
c.AWSSpawner.memory = 2048  # 2 GB
c.AWSSpawner.memory_reservation = 1024  # 1 GB

# Notebook configuration
c.AWSSpawner.notebook_scheme = 'http'  # or 'https' if using SSL
c.AWSSpawner.notebook_args = ['--NotebookApp.allow_origin=*']

# IAM Role (optional)
c.AWSSpawner.task_role_arn = 'arn:aws:iam::123456789012:role/your-task-role'

# Docker image (optional - will use the one from task definition if not specified)
c.AWSSpawner.image = 'jupyter/minimal-notebook:latest'

# Task tagging (optional)
c.AWSSpawner.task_owner_tag_name = 'Jupyter-User'  # Default value

# ECS task settings (optional)
c.AWSSpawner.propagate_tags = 'TASK_DEFINITION'  # Options: 'TASK_DEFINITION', 'SERVICE', 'NONE'
c.AWSSpawner.enable_ecs_managed_tags = True  # Enable ECS managed tags

# ECS Anywhere specific settings (optional)
c.AWSSpawner.port_range_start = 8000  # Start of port range for dynamic allocation
c.AWSSpawner.port_range_end = 9000    # End of port range for dynamic allocation
c.AWSSpawner.use_dynamic_port = True  # Use dynamic port allocation
c.AWSSpawner.placement_constraints = [
    {'type': 'memberOf', 'expression': 'attribute:ecs.instance-type =~ t3.*'}
]

# Hub connectivity (required for ECS Anywhere)
c.AWSSpawner.hub_connect_url = 'http://your-jupyterhub-server:8000'  # External URL for containers to reach JupyterHub
```

## Authentication

The spawner supports different authentication methods for AWS:

### Default Authentication (using instance profile or environment variables)

```python
# Uses the default credential chain (environment variables, instance profile, etc.)
c.AWSSpawner.authentication_class = 'awsspawner.AWSSpawnerAuthentication'
```

### Access Key Authentication

```python
c.AWSSpawner.authentication_class = 'awsspawner.AWSSpawnerSecretAccessKeyAuthentication'
c.AWSSpawnerSecretAccessKeyAuthentication.aws_access_key_id = 'YOUR_ACCESS_KEY'
c.AWSSpawnerSecretAccessKeyAuthentication.aws_secret_access_key = 'YOUR_SECRET_KEY'
```

## User Profiles

You can define multiple profiles to allow users to select different resource configurations:

```python
c.AWSSpawner.profiles = [
    (
        'Small Instance',  # Display name
        'small',          # Profile key
        {                 # Configuration overrides
            'cpu': 512,
            'memory': 1024,
            'image': 'jupyter/minimal-notebook:latest',
        }
    ),
    (
        'Medium Instance',
        'medium',
        {
            'cpu': 1024,
            'memory': 2048,
            'image': 'jupyter/datascience-notebook:latest',
        }
    ),
    (
        'GPU Instance',
        'gpu',
        {
            'cpu': 4096,
            'memory': 8192,
            'image': 'jupyter/tensorflow-notebook:latest',
            'launch_type': 'EC2',  # Override launch type for GPU instances
        }
    ),
    # Scenario 1: Environment-based node selection
    (
        'Development Environment',
        'dev',
        {
            'cpu': 1024,
            'memory': 2048,
            'launch_type': 'EXTERNAL',
            'use_dynamic_port': True,
            'hub_connect_url': 'http://jupyterhub-dev.company.com:8000',
            'placement_constraints': [
                {'type': 'memberOf', 'expression': 'attribute:environment == development'}
            ],
        }
    ),
    (
        'Production Environment', 
        'prod',
        {
            'cpu': 2048,
            'memory': 4096,
            'launch_type': 'EXTERNAL',
            'use_dynamic_port': True,
            'hub_connect_url': 'https://jupyterhub.company.com',
            'placement_constraints': [
                {'type': 'memberOf', 'expression': 'attribute:environment == production'}
            ],
        }
    ),
    # Scenario 2: Hardware-based node selection
    (
        'High Memory Instance',
        'high-mem',
        {
            'cpu': 2048,
            'memory': 8192,
            'launch_type': 'EXTERNAL',
            'use_dynamic_port': True,
            'hub_connect_url': 'http://10.0.1.100:8000',
            'placement_constraints': [
                {'type': 'memberOf', 'expression': 'attribute:memory-optimized == true'}
            ],
        }
    ),
    (
        'GPU Anywhere Instance',
        'gpu-anywhere',
        {
            'cpu': 4096,
            'memory': 8192,
            'launch_type': 'EXTERNAL', 
            'use_dynamic_port': True,
            'hub_connect_url': 'http://10.0.1.100:8000',
            'placement_constraints': [
                {'type': 'memberOf', 'expression': 'attribute:gpu-enabled == true'}
            ],
        }
    ),
]
```

## ECS Anywhere Support

This spawner supports ECS Anywhere, allowing you to run JupyterHub notebooks on your own infrastructure while leveraging ECS orchestration.

### Key Features for ECS Anywhere:

- **Automatic Port Detection**: Automatically detects actual ports used by tasks from ECS task network bindings
- **Smart Node IP Detection**: Automatically detects IP addresses using multiple methods:
  - ECS container instance attributes
  - SSM (Systems Manager) managed instance information
  - SSM inventory data for network interfaces
  - Fallback verification using SSM commands
- **Placement Constraints**: Support for constraining tasks to specific nodes or node attributes
- **No VPC Configuration Required**: ECS Anywhere tasks don't require VPC network configuration
- **Support for Non-EC2 Nodes**: Works with on-premises servers, edge devices, and other cloud providers
- **Network Mode Flexibility**: Works with any network mode defined in your task definition (bridge, host, awsvpc, none)

### Configuration Example:

```python
# Enable ECS Anywhere
c.AWSSpawner.launch_type = 'EXTERNAL'

# Configure port range for dynamic allocation (optional)
c.AWSSpawner.port_range_start = 8000
c.AWSSpawner.port_range_end = 9000
c.AWSSpawner.use_dynamic_port = True

# IMPORTANT: Configure Hub connectivity for ECS Anywhere
c.AWSSpawner.hub_connect_url = 'http://your-jupyterhub-server:8000'

# Optional: Add placement constraints
c.AWSSpawner.placement_constraints = [
    {'type': 'memberOf', 'expression': 'attribute:gpu-enabled == true'}
]
```

### Hub Connectivity for ECS Anywhere

**Critical Configuration**: ECS Anywhere containers need to connect back to JupyterHub, but they can't use `127.0.0.1` or `localhost`. You must configure the external URL:

```python
# Replace with your JupyterHub server's external IP or hostname
c.AWSSpawner.hub_connect_url = 'http://10.0.1.100:8000'  # Internal IP
# or
c.AWSSpawner.hub_connect_url = 'http://jupyterhub.example.com:8000'  # Domain name
# or  
c.AWSSpawner.hub_connect_url = 'https://jupyterhub.example.com'  # HTTPS with domain
```

**How it works**:
- The spawner automatically updates `JUPYTERHUB_API_URL` in container environment
- Replaces `127.0.0.1:8081` with your configured URL
- Maintains the correct API path (`/hub/api`)

**Common scenarios**:

1. **JupyterHub on EC2, ECS Anywhere on-premises**:
   ```python
   c.AWSSpawner.hub_connect_url = 'http://ec2-instance-public-ip:8000'
   ```

2. **JupyterHub behind load balancer**:
   ```python
   c.AWSSpawner.hub_connect_url = 'https://jupyterhub.company.com'
   ```

3. **Same VPC/network**:
   ```python
   c.AWSSpawner.hub_connect_url = 'http://10.0.1.100:8000'  # Private IP
   ```

### Port Management for ECS Anywhere:

The spawner automatically detects the actual ports used by ECS Anywhere tasks from the task's network bindings. This works with any network mode defined in your task definition:

- **Bridge mode**: Uses port mapping, spawner gets the host port from `networkBindings`
- **Host mode**: Container uses host network directly, spawner gets port from container configuration
- **Custom port ranges**: Configure `port_range_start` and `port_range_end` for reference (actual ports determined by ECS)

### Placement Constraints Examples:

Placement constraints allow you to control which nodes your tasks run on based on node attributes:

```python
# Example 1: Run on specific availability zone
placement_constraints = [
    {'type': 'memberOf', 'expression': 'attribute:ecs.availability-zone == us-west-2a'}
]

# Example 2: Run on nodes with specific instance types
placement_constraints = [
    {'type': 'memberOf', 'expression': 'attribute:ecs.instance-type =~ t3.*'}
]

# Example 3: Run on GPU-enabled nodes (custom attribute)
placement_constraints = [
    {'type': 'memberOf', 'expression': 'attribute:gpu-enabled == true'}
]

# Example 4: Multiple constraints (AND relationship)
placement_constraints = [
    {'type': 'memberOf', 'expression': 'attribute:environment == production'},
    {'type': 'memberOf', 'expression': 'attribute:memory-optimized == true'}
]
```

### Adding Custom Attributes to ECS Anywhere Nodes:

When registering ECS Anywhere nodes, you can add custom attributes:

```bash
./ecs-anywhere-install.sh \
  --cluster your-cluster \
  --activation-id activation-id \
  --activation-code activation-code \
  --region us-west-2 \
  --attributes environment=production,gpu-enabled=true,memory-optimized=false
```

### Required IAM Permissions for ECS Anywhere:

The JupyterHub service needs additional IAM permissions when using ECS Anywhere:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "ecs:*",
                "ec2:DescribeInstances",
                "ssm:DescribeInstanceInformation",
                "ssm:GetInventoryEntries",
                "ssm:SendCommand",
                "ssm:GetCommandInvocation",
                "ssm:ListCommandInvocations"
            ],
            "Resource": "*"
        }
    ]
}
```

## Task Definition Management

The spawner automatically manages ECS task definitions based on your configuration:

- **Automatic Discovery**: Uses existing task definitions that match your family and container name
- **Image Updates**: When you change the Docker image, new task definitions are created automatically
- **Network Mode**: Network mode should be pre-configured in your task definition (bridge, host, awsvpc, none)
- **Launch Type Compatibility**: Ensure your task definition has the correct `requiresCompatibilities` for your launch type

### Task Definition Requirements:

```python
# Example task definition for ECS Anywhere with bridge networking:
{
    "family": "jupyter-notebook",
    "networkMode": "bridge",
    "requiresCompatibilities": ["EXTERNAL"],
    "containerDefinitions": [
        {
            "name": "notebook",
            "image": "jupyter/minimal-notebook:latest",
            "portMappings": [
                {
                    "containerPort": 8888,
                    "protocol": "tcp"
                }
            ],
            # ... other container settings
        }
    ]
}

# Example task definition for Fargate:
{
    "family": "jupyter-notebook",
    "networkMode": "awsvpc",
    "requiresCompatibilities": ["FARGATE"],
    "cpu": "256",
    "memory": "512",
    "containerDefinitions": [...]
}
```

## Prerequisites

Before using this spawner, ensure you have:

1. An AWS ECS cluster set up (including ECS Anywhere nodes if using EXTERNAL launch type)
2. Appropriate task definitions created for your Jupyter notebooks
3. Proper IAM permissions for the JupyterHub server to interact with ECS, EC2, and SSM
4. Network configuration (VPC, subnets, security groups) that allows communication between JupyterHub and the ECS tasks (not required for ECS Anywhere)
5. For ECS Anywhere: 
   - Registered external instances with the ECS cluster
   - SSM agent installed and running on ECS Anywhere nodes
   - Proper IAM permissions for SSM operations (ssm:DescribeInstanceInformation, ssm:GetInventoryEntries, ssm:SendCommand, ssm:GetCommandInvocation)

## Development

To set up the development environment:

```bash
# Clone the repository
git clone https://github.com/adacotech/awsspawner.git
cd awsspawner

# Install dependencies using poetry
poetry install

# Run linting
./lint.sh
```

## Troubleshooting

### Common Issues

#### "name cannot be blank" Error

This error occurs when required configuration parameters are missing or empty:

```
InvalidParameterException: name cannot be blank
```

The improved error handling will now show you exactly which parameter is empty:

```
ValueError: Missing required configuration parameters: task_cluster_name (set c.AWSSpawner.task_cluster_name)
```

or

```
ValueError: Container override #0 has empty 'name' field
```

**Common causes and solutions**:

1. **Missing cluster name**:
   ```python
   c.AWSSpawner.task_cluster_name = 'your-ecs-cluster-name'  # Must not be empty
   ```

2. **Missing container name**:
   ```python
   c.AWSSpawner.task_container_name = 'notebook'  # Must not be empty
   ```

3. **Missing task definition**:
   ```python
   c.AWSSpawner.task_definition_family = 'jupyter-notebook'  # Must not be empty
   ```

4. **Empty environment variables** (usually from JupyterHub internals):
   ```
   ValueError: Found environment variables with empty names
   ```
   This usually indicates a JupyterHub configuration issue or bug.

#### "Failed to connect to my Hub" Error

This error occurs when containers can't reach JupyterHub:

```
Failed to connect to my Hub at http://127.0.0.1:8081/hub/api (attempt 1/5). Is it running?
```

**Root cause**: The container is trying to connect to `127.0.0.1`, which doesn't work from inside a container.

**Solution**: Configure the external Hub URL:

```python
# Set the URL that containers can use to reach JupyterHub
c.AWSSpawner.hub_connect_url = 'http://your-jupyterhub-server:8000'
```

**Debugging steps**:

1. **Find your JupyterHub's external IP**:
   ```bash
   # If JupyterHub is on EC2
   curl http://169.254.169.254/latest/meta-data/public-ipv4
   
   # Or check private IP
   curl http://169.254.169.254/latest/meta-data/local-ipv4
   ```

2. **Test connectivity from ECS Anywhere node**:
   ```bash
   # SSH to your ECS Anywhere node and test
   curl http://your-jupyterhub-ip:8000/hub/api
   ```

3. **Check firewall/security groups**:
   - Ensure port 8000 (or your JupyterHub port) is open
   - Security groups allow inbound traffic from ECS Anywhere nodes
   - Network ACLs permit the traffic

4. **Verify the updated environment variables**:
   Enable INFO logging to see the URL transformation:
   ```
   INFO:Updated JUPYTERHUB_API_URL from 'http://127.0.0.1:8081/hub/api' to 'http://10.0.1.100:8000/hub/api'
   ```

#### "list index out of range" Error

This error occurs when ECS `run_task` succeeds but returns no tasks:

```
IndexError: list index out of range
```

The improved error handling will now show you the specific ECS failures:

```
Exception: ECS run_task failed to create tasks. Detailed analysis:
ARN: arn:aws:ecs:us-east-1:123456789012:container-instance/abc123 - RESOURCE:MEMORY: Insufficient memory available (Suggestion: Insufficient memory available in the cluster. Try reducing memory requirements or scaling up your cluster.)
```

**Common causes and solutions**:

1. **Insufficient cluster capacity**:
   - Scale up your ECS cluster
   - Reduce CPU/memory requirements
   - Check cluster utilization

2. **ECS Anywhere node issues**:
   - Verify ECS Anywhere nodes are running and connected
   - Check node capacity and available resources
   - Ensure ECS agent is running on nodes

3. **Placement constraints cannot be satisfied**:
   ```python
   # Check your placement constraints
   c.AWSSpawner.placement_constraints = [
       {'type': 'memberOf', 'expression': 'attribute:ecs.instance-type =~ t3.*'}
   ]
   ```

4. **Network configuration issues** (Fargate only):
   - Verify subnet IDs are correct
   - Check security group configuration
   - Ensure subnets have available IP addresses

5. **Task definition compatibility**:
   - Verify task definition exists and is ACTIVE
   - Check `requiresCompatibilities` matches your launch type
   - Ensure task definition is compatible with your cluster

#### Debug Mode

Enable detailed logging to see all parameters passed to ECS:

```python
# Enable INFO level logging to see all parameters
c.JupyterHub.log_level = 'INFO'

# Or enable DEBUG level for even more details
c.JupyterHub.log_level = 'DEBUG'
```

With INFO level logging, you'll see detailed parameter dumps like:

```
INFO:=== AWSSpawner Start Parameters ===
INFO:User: 'ubuntu'
INFO:Task cluster name: 'my-ecs-cluster'
INFO:Task container name: 'notebook'
INFO:Launch type: EXTERNAL
INFO:CPU: 1024
INFO:Memory: 2048
INFO:=== End AWSSpawner Parameters ===

INFO:=== ECS run_task Parameters ===
INFO:cluster: 'my-ecs-cluster'
INFO:taskDefinition: 'arn:aws:ecs:us-east-1:123456789012:task-definition/jupyter-notebook:1'
INFO:launch_type: EXTERNAL
INFO:task_container_name: 'notebook'
INFO:=== Environment Variables ===
INFO:  JUPYTERHUB_API_TOKEN: [REDACTED - 64 chars]
INFO:  JUPYTERHUB_API_URL: 'http://hub:8081/hub/api'
INFO:  PATH: '/usr/local/bin:/usr/bin:/bin'
INFO:=== Final ECS API Request ===
INFO:ECS run_task request payload: {...}
INFO:=== End Parameters ===
```

This detailed logging will help you identify:
- Missing or incorrect configuration parameters
- Environment variable issues
- ECS API request structure
- Task definition problems

#### Checking ECS Cluster Status

You can check your ECS cluster status using AWS CLI:

```bash
# Check cluster status
aws ecs describe-clusters --clusters your-cluster-name

# Check container instances (for ECS Anywhere)
aws ecs list-container-instances --cluster your-cluster-name
aws ecs describe-container-instances --cluster your-cluster-name --container-instances instance-id

# Check task definitions
aws ecs list-task-definitions --family-prefix jupyter-notebook
aws ecs describe-task-definition --task-definition jupyter-notebook:latest

# Check recent task failures
aws ecs list-tasks --cluster your-cluster-name --desired-status STOPPED
```

#### Task Definition Not Found

If you see errors about task definitions not being found, ensure:

1. The task definition family exists in your ECS cluster
2. The container name matches what's in your task definition
3. You have proper IAM permissions to access ECS

#### Network Configuration Issues

For Fargate tasks, ensure you have:
- Valid subnet IDs
- Valid security group IDs
- Proper VPC configuration

For ECS Anywhere tasks:
- Task definition should have appropriate network mode (bridge, host, etc.)
- No VPC configuration needed

## License

This project is licensed under the MIT License - see the LICENSE file for details.
