from __future__ import annotations

import argparse
import logging
import os

from otbr_restapi_util import redact_sensitive_text as _redact_sensitive_text

TD_DEBUG_LEVEL_ENV = "TD_DEBUG_LEVEL"
_LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


def configure_logging(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Apply CLI > environment > INFO logging precedence to the root logger."""
    if getattr(args, "debug", False):
        level = logging.DEBUG
    elif getattr(args, "verbose", False):
        level = logging.INFO
    else:
        configured = os.environ.get(TD_DEBUG_LEVEL_ENV)
        if configured is None:
            level = logging.INFO
        else:
            level_name = configured.strip().upper()
            if level_name not in _LOG_LEVELS:
                parser.error(
                    f"Invalid {TD_DEBUG_LEVEL_ENV}; accepted values: "
                    "DEBUG, INFO, WARNING, ERROR."
                )
            level = _LOG_LEVELS[level_name]

    logging.basicConfig(
        level=level, format="[%(asctime)s] %(levelname)s: %(message)s"
    )
    logging.getLogger().setLevel(level)
    return level


def redact_sensitive_text(text: str) -> str:
    """Redact sensitive-key values in structured or ordinary diagnostic text."""
    return _redact_sensitive_text(text)


def redact_sensitive_output(text: str) -> str:
    """Sanitize captured child output while retaining non-secret diagnostics."""
    return redact_sensitive_text(text)


def redact_command_args(args: list[str]) -> list[str]:
    """Keep command evidence while omitting inline dataset bodies from logs."""
    safe_args: list[str] = []
    redact_next = False
    for argument in args:
        if redact_next:
            safe_args.append("[Redacted input]")
            redact_next = False
        elif argument in {"--json", "--text"}:
            safe_args.append(argument)
            redact_next = True
        elif argument.startswith(("--json=", "--text=")):
            option, _value = argument.split("=", 1)
            safe_args.append(f"{option}=[Redacted input]")
        else:
            safe_args.append(redact_sensitive_text(argument))
    return safe_args