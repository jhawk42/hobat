import os
import subprocess
import re
import json

DEFAULT_OT_CONTAINER_NAME = "otbr"  # Default container name for OTBR Docker image

def run_ot_ctl_command_stdio(ot_command, container_name:None, ):
    """
    Executes an ot-ctl command inside a running OTBR Docker container.
    """
    
    # Construct the docker exec command
    # 'sh -c' is often used to ensure the command executes correctly in the container shell
    full_command_docker_container = [
        "docker", "exec", container_name, 
        "sh", "-c", f"ot-ctl {ot_command}"
    ]

    ## TODO add command line option support to run ot-ctl command without docker exec
    full_command_no_docker = [
        f"ot-ctl {ot_command}"
    ]
    
    if container_name is not None:
        # Use the docker command for now, but this can be extended to support non-docker execution 
        # in the future
        full_command = full_command_docker_container
    else:   
        full_command = full_command_no_docker  

    # Debug: Print the command being executed
    print(f"[DEBUG] {full_command}")

    try:
        # Run the command and capture output    
        result = subprocess.run(
            full_command, 
            capture_output=True, 
            text=True, 
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return f"Error: {e.stderr.strip()}"

def run_ot_ctl_stdio(command, container_name:None = DEFAULT_OT_CONTAINER_NAME):
    """
    Wrapper to execute ot-ctl command and return output.
    Inject docker container name and run ot-ctl command

    Keeps the container name management in one place and easily switch between 
    docker and non-docker execution in the future.
   
    Note:  Default container name "otbr" used by the OpenThread Border Router (OTBR) 
           Docker image. This can be overridden by setting the OT_CONTAINER_NAME environment variable.
    """

    # TODO add command line option support to run ot-ctl command without docker exec

    # get container name from environment variable or use default
    container_name_env = os.getenv("OT_CONTAINER_NAME")
    if container_name_env:
        container_name = container_name_env

    # use the provided container name or default if not provided   
    output = run_ot_ctl_command_stdio(command, container_name)
    return output