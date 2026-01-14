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

# AWS Region
c.AWSSpawner.aws_region = 'us-east-1'

# ECS Cluster configuration
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

# Optional: Add placement constraints
c.AWSSpawner.placement_constraints = [
    {'type': 'memberOf', 'expression': 'attribute:gpu-enabled == true'}
]
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

## License

This project is licensed under the MIT License - see the LICENSE file for details.
