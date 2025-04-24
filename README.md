# awsspawner

Spawns JupyterHub single user servers in Docker containers running in AWS ECS Tasks (including EC2, Fargate, and Fargate Spot).

## Features

- Run JupyterHub single user servers in AWS ECS Tasks
- Support for EC2, Fargate, and Fargate Spot launch types
- Configurable resource allocation (CPU, memory)
- User profiles for different resource configurations
- Automatic tagging of tasks with configurable owner tag (using username)
- Support for custom Docker images

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
c.AWSSpawner.launch_type = 'FARGATE'  # Options: 'EC2', 'FARGATE'

# Option 2: Use Fargate Spot
c.AWSSpawner.launch_type = 'FARGATE_SPOT'

# Option 3: Use capacity provider strategy
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
]
```

## Prerequisites

Before using this spawner, ensure you have:

1. An AWS ECS cluster set up
2. Appropriate task definitions created for your Jupyter notebooks
3. Proper IAM permissions for the JupyterHub server to interact with ECS
4. Network configuration (VPC, subnets, security groups) that allows communication between JupyterHub and the ECS tasks

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
