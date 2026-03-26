import subprocess
import re
import json

def run_ot_ctl_command(container_name, ot_command):
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
    
    # Use the docker command for now
    full_command = full_command_docker_container  

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

def run_ot_ctl(command):
    """
    Wrapper to execute ot-ctl command and return output.
    """

    ##TODO expose container name as a parameter or environment variable
    container = "border-router"  # Ensure this matches your container's name
    output = run_ot_ctl_command(container, command)
    return output