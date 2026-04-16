import os
import subprocess
import re
import json
import logging

TD_OTBR_CONTAINER_NAME_DEFAULT = "otbr"  # Default container name for OTBR Docker image
TD_OTBR_CONTAINER_NAME_ENV = "TD_OTBR_CONTAINER_NAME" # Environment variable name for OTBR container name
TD_OT_CTL_TIMEOUT_ENV = "TD_OT_CTL_TIMEOUT"  # Environment variable name for ot-ctl subprocess timeout
TD_OT_CTL_TIMEOUT_DEFAULT = 30  # Default subprocess timeout in seconds

def run_ot_ctl_command_stdio(ot_command, container_name=None):
    """
    Executes an ot-ctl command inside a running OTBR Docker container.
    """
    
    # Construct the docker exec command
    # 'sh -c' is often used to ensure the command executes correctly in the container shell
    full_command_docker_container = [
        "docker", "exec", container_name, 
        "sh", "-c", f"ot-ctl {ot_command}"
    ]

    ## command line option support to run ot-ctl command without docker exec
    full_command_no_docker = [
        "sh", "-c", f"ot-ctl {ot_command}"
    ]
    
    if container_name is not None:
        # Use the docker command for now, but this can be extended to support non-docker execution 
        # in the future
        full_command = full_command_docker_container
    else:   
        full_command = full_command_no_docker  

    # log the command being executed
    logging.debug(f"[DEBUG] {full_command}")

    try:
        # Run the command and capture output
        _timeout = int(os.environ.get(TD_OT_CTL_TIMEOUT_ENV, TD_OT_CTL_TIMEOUT_DEFAULT))
        result = subprocess.run(
            full_command,
            capture_output=True,
            text=True,
            check=True,
            timeout=_timeout,
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        logging.error(f"[ERROR] ot-ctl command timed out after {_timeout}s: {full_command}")
        return f"Error: command timed out after {_timeout}s"
    except subprocess.CalledProcessError as e:
        err_str = e.stderr.strip() if e.stderr else "Unknown error"
        logging.error(f"[ERROR] {err_str}")
        return f"Error: {err_str}"

def run_ot_ctl_stdio(command, container_name=TD_OTBR_CONTAINER_NAME_DEFAULT):
    """
    Wrapper to execute ot-ctl command and return output.
    Inject docker container name and run ot-ctl command

    Keeps the container name management in one place and easily switch between 
    docker and non-docker execution in the future.
   
    Note:  Default container name "otbr" used by the OpenThread Border Router (OTBR) 
           Docker image. This can be overridden by setting the TD_OTBR_CONTAINER_NAME environment variable.
    """

    # TODO add env & command line option support to run ot-ctl command without docker exec

    # get container name from environment variable or use default
    container_name_env = os.getenv(TD_OTBR_CONTAINER_NAME_ENV)
    if container_name_env:
        container_name = container_name_env

    # use the provided container name or default if not provided   
    output = run_ot_ctl_command_stdio(command, container_name)
    return output