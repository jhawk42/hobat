import os
import shlex
import subprocess

DEFAULT_CONTAINER_NAME = "otbr"  # Default container name for OTBR Docker image
CONTAINER_NAME_ENV_VAR = "TD_OTBR_CONTAINER_NAME"  # Environment variable name for OTBR container name


def _exec_ot_ctl(command: str, container_name: str | None) -> str:
    """
    Executes an ot-ctl command, optionally inside a running OTBR Docker container.
    """
    if container_name is not None:
        cmd = ["docker", "exec", container_name, "sh", "-c", f"ot-ctl {command}"]
    else:
        cmd = ["ot-ctl"] + shlex.split(command)

    import logging
    logging.debug("Running command: %s", cmd)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return f"Error: {e.stderr.strip()}"


def run_ot_ctl(command: str, container_name: str = DEFAULT_CONTAINER_NAME) -> str:
    """
    Wrapper to execute ot-ctl command and return output.
    Inject docker container name and run ot-ctl command.

    Keeps the container name management in one place and makes it easy to switch
    between docker and non-docker execution.

    Note: Default container name "otbr" used by the OpenThread Border Router (OTBR)
          Docker image. This can be overridden by setting the TD_OTBR_CONTAINER_NAME
          environment variable or passing container_name=None to run without Docker.
    """
    env_container_name = os.getenv(CONTAINER_NAME_ENV_VAR)
    if env_container_name:
        container_name = env_container_name

    return _exec_ot_ctl(command, container_name)


# Backward-compatible alias used by existing callers
run_ot_ctl_stdio = run_ot_ctl
