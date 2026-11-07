from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re

from otbr_restapi_util import (
    redact_sensitive_payload as _redact_sensitive_payload,
    redact_sensitive_text as _redact_sensitive_text,
)

TD_DEBUG_LEVEL_ENV = "TD_DEBUG_LEVEL"
RUN_COMMAND_ENV = "TD_RUN_CMD"
_SENSITIVE_OPTION = re.compile(
    r"credential|networkkey|passphrase|password|pskc|pskd|secret|token",
    re.IGNORECASE,
)
_LABELED_SECRET = re.compile(
    r"""(?ix)(["']?\b[\w-]*(?:credential|network[\s_-]*key|passphrase|password|
    pskc|pskd|secret|token)[\w-]*\b["']?\s*[:=]\s*)
    ("(?:\\.|[^"\\])*(?:"|$)|'(?:\\.|[^'\\])*(?:'|$)|
    (?![\[{"'])[^\s,;}]+)"""
)
_URI_CREDENTIALS = re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^/\s?#]*@")
_URI_SECRET = re.compile(
    r"(?i)([?&][^=&\s]*(?:credential|network[_-]*key|passphrase|password|"
    r"pskc|pskd|secret|token)[^=&\s]*=)[^&#\s]*"
)
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
    text = _URI_CREDENTIALS.sub(r"\1[Redacted]@", text)
    text = _URI_SECRET.sub(r"\1[Redacted]", text)
    # Handle quoted whitespace before the transport redactor processes JSON.
    text = _LABELED_SECRET.sub(r'\1"[Redacted]"', text)
    return _redact_sensitive_text(text)


def redact_sensitive_output(text: str) -> str:
    """Sanitize captured child output while retaining non-secret diagnostics."""
    return redact_sensitive_text(text)


def redact_command_args(args: list[str]) -> list[str]:
    """Keep command evidence while omitting inline dataset bodies from logs."""
    safe_args: list[str] = []
    redact_next = False
    dataset_write = any(
        args[index:index + 4] == ["node", "dataset", "active", "set"]
        for index in range(len(args))
    )
    json_flag = any(
        command in args
        for command in ("source-probe", "health", "system", "unify-dataset")
    ) or ("otbr-cli" in args and "device" in args)
    text_flag = any(
        args[index:index + 4] == ["node", "dataset", "active", "get"]
        for index in range(len(args))
    )
    for argument in args:
        option = argument.split("=", 1)[0]
        sensitive_option = (
            option != "--log-thread-secrets"
            and option.startswith("-")
            and _SENSITIVE_OPTION.search(
                option.replace("-", "").replace("_", "")
            )
        )
        payload_option = (
            option == "--json" and (dataset_write or not json_flag)
        ) or (option == "--text" and not text_flag) or argument.startswith(
            ("--json=", "--text=")
        )
        if redact_next:
            safe_args.append("[Redacted input]")
            redact_next = False
        elif sensitive_option or payload_option:
            if "=" in argument:
                safe_args.append(f"{option}=[Redacted input]")
            else:
                safe_args.append(option)
                redact_next = True
        else:
            safe_args.append(redact_sensitive_text(argument))
    return safe_args


def format_event(
    event: str, *, source: str, command: str, stage: str, **fields: object
) -> str:
    """Render log-only facts with escaped values and optional wrapper correlation."""
    values: dict[str, object] = {"event": event}
    run_cmd = os.environ.get(RUN_COMMAND_ENV)
    if run_cmd:
        values["run_cmd"] = run_cmd
    values.update(source=source, command=command, stage=stage)
    values.update(fields)
    parts: list[str] = []
    for key, value in values.items():
        if (
            key == "elapsed_s"
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        ):
            encoded = f"{value:.3f}"
        else:
            encoded = json.dumps(
                _safe_event_value(value), ensure_ascii=True, separators=(",", ":")
            )
        parts.append(f"{key}={encoded}")
    return " ".join(parts)


def _safe_event_value(value: object) -> object:
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, dict):
        return {
            key: _safe_event_value(item)
            for key, item in _redact_sensitive_payload(value).items()
        }
    if isinstance(value, (list, tuple)):
        return [_safe_event_value(item) for item in value]
    return value


def log_event(
    event: str, *, source: str, command: str, stage: str, **fields: object
) -> None:
    """Send collector facts through the configured logger, never JSON stdout."""
    logging.info(
        "%s", format_event(event, source=source, command=command, stage=stage, **fields)
    )