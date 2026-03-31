import subprocess
import re
import json

def run_ot_ctl_command_stdio(container_name:None, ot_command):
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
        # Use the docker command for now, but this can be extended to support non-docker execution in the future
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

def run_ot_ctl_stdio(command):
    """
    Wrapper to execute ot-ctl command and return output.
    """
    # Helper to inject docker container name and run ot-ctl command
    # This allows us to keep the container name management in one place and easily switch between docker and non-docker execution in the future.
    # TODO add command line option support to run ot-ctl command without docker exec

    ##TODO expose container name as a parameter or environment variable
    ## otbr is the default container name used by the OpenThread Border Router (OTBR) Docker image, but this can be changed if needed.  
    container = "border-router"  # Ensure this matches your container's name
    output = run_ot_ctl_command_stdio(container, command)
    return output