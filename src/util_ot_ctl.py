import os
import subprocess
import re
import json
import logging

# Container use flag default value (1 means use container, 0 means do not use container)
TD_OTBR_CONTAINER_USE_DEFAULT = 1
# Environment variable name to determine if default container name should be used
TD_OTBR_CONTAINER_USE_ENV = "TD_OTBR_CONTAINER_USE"

# Default container name for OTBR Docker image
TD_OTBR_CONTAINER_NAME_DEFAULT = "otbr"
TD_OTBR_CONTAINER_NAME_ENV = (
    "TD_OTBR_CONTAINER_NAME"  # Environment variable name for OTBR container name
)
TD_OT_CTL_TIMEOUT_ENV = (
    "TD_OT_CTL_TIMEOUT"  # Environment variable name for ot-ctl subprocess timeout
)
TD_OT_CTL_TIMEOUT_DEFAULT = 30  # Default subprocess timeout in seconds


def exec_ot_ctl_dispatch(cmd, container_name=None):
    """
    Executes an ot-ctl command inside a running OTBR Docker container.
    """

    # Construct the docker exec command
    # 'sh -c' is often used to ensure the command executes correctly in the container shell
    docker_cmd = [
        "docker",
        "exec",
        container_name,
        "sh",
        "-c",
        f"ot-ctl {cmd}",
    ]

    # command line option support to run ot-ctl command without docker exec
    local_cmd = ["sh", "-c", f"ot-ctl {cmd}"]

    if container_name is not None:
        # Use the docker command for now, but this can be extended to support non-docker execution
        # in the future
        command = docker_cmd
    else:
        command = local_cmd

    # log the command being executed
    logging.debug(f"[DEBUG] {command}")

    try:
        # Run the command and capture output
        timeout_sec = int(os.environ.get(
            TD_OT_CTL_TIMEOUT_ENV, TD_OT_CTL_TIMEOUT_DEFAULT))
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout_sec,
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        logging.error(
            f"[ERROR] ot-ctl command timed out after {timeout_sec}s: {command}"
        )
        return f"Error: command timed out after {timeout_sec}s"
    except subprocess.CalledProcessError as e:
        err_str = e.stderr.strip() if e.stderr else "Unknown error"

        # log return code and output for debugging
        logging.error(
            f"[ERROR] ot-ctl command failed: Return code: {e.returncode} Error: {err_str}")
        logging.error(f"[ERROR] Command: {command}")

        logging.error(
            f"[ERROR] Output: {e.output.strip() if e.output else 'No output'}")

        return f"Error: {err_str}"


def exec_ot_ctl(command, container_name=TD_OTBR_CONTAINER_NAME_DEFAULT):
    """
    Wrapper to execute ot-ctl command and return output.
    Inject docker container name and run ot-ctl command

    Keeps the container name management in one place and easily switch between
    docker and non-docker execution in the future.

    Note:  Default container name "otbr" used by the OpenThread Border Router (OTBR)
           Docker image. This can be overridden by setting the TD_OTBR_CONTAINER_NAME environment variable.
    """

    # get container name from environment variable or use default
    env_container_name = os.getenv(TD_OTBR_CONTAINER_NAME_ENV)
    if env_container_name:
        container_name = env_container_name

    # get container use flag from environment variable or use default
    env_container_use = os.getenv(TD_OTBR_CONTAINER_USE_ENV)
    if env_container_use is not None:
        container_use = int(env_container_use)
    else:
        container_use = TD_OTBR_CONTAINER_USE_DEFAULT

    # if container use flag is set to 0, do not use a container name (i.e. run ot-ctl command without docker exec)
    if container_use == 0:
        container_name = None

    # use the provided container name or default if not provided
    output = exec_ot_ctl_dispatch(command, container_name)
    return output
