from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence, TypeVar

from td_const import (
    TD_DATA_DIR_DOCKER_DEFAULT,
    TD_DATA_DIR_ENV_VAR,
    TD_DATA_DIR_LOCAL_DEFAULT,
)


class TDDataDirSource(str, Enum):
    """Origin used to resolve the effective data directory."""

    ENV = "env"
    CLI = "cli"
    DOCKER_DEFAULT = "docker-default"
    LOCAL_DEFAULT = "local-default"


@dataclass(frozen=True)
class TDDataDirResolution:
    """Resolved td_data_dir details used for wiring and logging."""

    path: Path
    source: TDDataDirSource
    created: bool = False


class TDRequiredInputMissingError(FileNotFoundError):
    """Raised when a command requires a local input file that is missing."""

    def __init__(
        self,
        *,
        command_path: str,
        data_dir: Path,
        missing_file: Path,
        classification: str = "required",
        action: str = "fail code=4",
    ) -> None:
        self.command_path = command_path
        self.data_dir = data_dir
        self.missing_file = missing_file
        self.classification = classification
        self.action = action
        super().__init__(
            format_missing_file_message(
                command_path=command_path,
                data_dir=data_dir,
                missing_file=missing_file,
                classification=classification,
                action=action,
            )
        )


@dataclass(frozen=True)
class OptionalInputLoadResult:
    """Result wrapper for optional input loading with fallback metadata."""

    value: Any
    used_fallback: bool
    warning: str | None
    input_path: Path | None


class CollectionStatus(str, Enum):
    """Collection state used to decide whether generated data may be persisted."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True)
class CollectionWriteOutcome:
    """Explicit collector evidence used to gate final and checkpoint writes."""

    status: CollectionStatus
    has_usable_data: bool = False
    valid_empty_reason: str | None = None

    @classmethod
    def complete(cls, *, valid_empty_reason: str | None = None) -> "CollectionWriteOutcome":
        return cls(
            status=CollectionStatus.COMPLETE,
            valid_empty_reason=valid_empty_reason,
        )

    @classmethod
    def partial(cls, *, has_usable_data: bool) -> "CollectionWriteOutcome":
        return cls(
            status=CollectionStatus.PARTIAL,
            has_usable_data=has_usable_data,
        )

    @classmethod
    def failed(cls) -> "CollectionWriteOutcome":
        return cls(status=CollectionStatus.FAILED)


T = TypeVar("T")


def _normalize_path(
    path: str | os.PathLike[str], cwd: Path | None = None
) -> Path:
    """Normalize path to an absolute Path, resolving relative paths against cwd."""
    path = Path(path).expanduser()
    if not path.is_absolute():
        path = (cwd or Path.cwd()) / path
    return path.resolve()


def _normalize_optional_path(
    value: str | os.PathLike[str] | None,
) -> str | os.PathLike[str] | None:
    """Return None for blank values so callers can safely pass env/CLI text."""
    if value is None:
        return None
    as_text = str(value).strip()
    if not as_text:
        return None
    return value


def parse_datadir_from_argv(argv: Sequence[str] | None) -> str | None:
    """Extract --datadir value from argv without validating unrelated options."""
    if not argv:
        return None

    args = list(argv)
    for index, token in enumerate(args):
        if token == "--datadir":
            if index + 1 < len(args):
                value = args[index + 1].strip()
                return value or None
            return None

        if token.startswith("--datadir="):
            value = token.split("=", 1)[1].strip()
            return value or None

    return None


def resolve_data_dir_with_source(
    data_dir: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    cwd: str | os.PathLike[str] | None = None,
) -> TDDataDirResolution:
    """Resolve td_data_dir and include resolution metadata.

    Precedence: explicit CLI argument, then environment variable, then defaults.
    """
    env_map = os.environ if env is None else env
    base_cwd = _normalize_path(cwd or Path.cwd())

    datadir_value = _normalize_optional_path(data_dir)
    if datadir_value is not None:
        return TDDataDirResolution(
            path=_normalize_path(datadir_value, base_cwd),
            source=TDDataDirSource.CLI,
            created=False,
        )

    env_value = _normalize_optional_path(env_map.get(TD_DATA_DIR_ENV_VAR))
    if env_value is not None:
        return TDDataDirResolution(
            path=_normalize_path(env_value, base_cwd),
            source=TDDataDirSource.ENV,
            created=False,
        )

    docker_default = Path(TD_DATA_DIR_DOCKER_DEFAULT)
    if docker_default.exists():
        return TDDataDirResolution(
            path=docker_default.resolve(),
            source=TDDataDirSource.DOCKER_DEFAULT,
            created=False,
        )

    local_default = (base_cwd / TD_DATA_DIR_LOCAL_DEFAULT).resolve()
    created = not local_default.exists()
    local_default.mkdir(parents=True, exist_ok=True)
    return TDDataDirResolution(
        path=local_default,
        source=TDDataDirSource.LOCAL_DEFAULT,
        created=created,
    )


def resolve_data_dir(
    data_dir: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    cwd: str | os.PathLike[str] | None = None,
) -> Path:
    """Resolve the TD data directory using CLI -> ENV -> defaults precedence.

    Precedence (exactly as required):
    1. Command line argument --datadir
    2. Environment variable TD_DATA_DIR
    3. Defaults:
       - if /data exists, use /data
       - otherwise create ./data under cwd and use it

    For ENV/CLI values this function resolves and returns the absolute path,
    but does not create directories.
    """
    return resolve_data_dir_with_source(
        data_dir=data_dir,
        env=env,
        cwd=cwd,
    ).path


def ensure_data_dir_exists(path: Path) -> Path:
    """Ensure path exists and return it as an absolute Path."""
    resolved = path.expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def format_data_dir_log_message(resolution: TDDataDirResolution) -> str:
    """Format a standard log line for effective td_data_dir diagnostics."""
    suffix = " (created)" if resolution.created else ""
    return (
        f"td_data_directory={resolution.path} source={resolution.source.value}{suffix}"
    )


def data_file_path(filename: str, td_data_dir: Path) -> Path:
    """Resolve a data filename under td_data_dir.

    filename must be a leaf filename (not absolute).
    """
    file_path = Path(filename)
    if file_path.is_absolute():
        raise ValueError("filename must be relative, not absolute")
    if file_path.parent != Path("."):
        raise ValueError("filename must be a leaf name without directories")
    return td_data_dir / file_path


def resolve_data_file_path(file_path: str, td_data_dir: Path) -> Path:
    """Resolve an absolute file path or map a relative name under td_data_dir."""
    normalized = _normalize_optional_path(file_path)
    if normalized is None:
        raise ValueError("file_path must be a non-empty path")
    value = Path(normalized).expanduser()
    if value.is_absolute():
        return value.resolve()
    return (td_data_dir / value).resolve()


def format_missing_file_message(
    *,
    command_path: str,
    data_dir: Path,
    missing_file: Path,
    classification: str,
    action: str,
) -> str:
    """Render a standard missing-file message for logs and exceptions."""
    return (
        "input file not found: "
        f"command_path={command_path} "
        f"data_dir={data_dir} "
        f"missing_file={missing_file} "
        f"classification={classification} "
        f"action={action}"
    )


def require_existing_input_file(
    path: str | os.PathLike[str],
    *,
    command_path: str,
    data_dir: Path,
    classification: str = "required",
    action: str = "fail code=4",
) -> Path:
    """Validate that a required input file exists and is a regular file."""
    input_path = Path(path)
    if input_path.is_file():
        return input_path

    raise TDRequiredInputMissingError(
        command_path=command_path,
        data_dir=data_dir,
        missing_file=input_path,
        classification=classification,
        action=action,
    )


def load_optional_input(
    input_path: str | os.PathLike[str] | None,
    *,
    loader: Callable[[Path], T],
    default_value: T,
    command_path: str,
    data_dir: Path,
    logger: logging.Logger | None = None,
    classification: str = "optional",
    fallback_action: str = "continue fallback=default",
) -> OptionalInputLoadResult:
    """Load optional input via loader; fallback to default with warning metadata."""
    if logger is None:
        logger = logging.getLogger(__name__)

    if input_path is None:
        warning = (
            f"command_path={command_path} "
            f"data_dir={data_dir} "
            f"missing_file=<none> "
            f"classification={classification} "
            f"action={fallback_action}"
        )
        logger.warning(warning)
        return OptionalInputLoadResult(
            value=default_value,
            used_fallback=True,
            warning=warning,
            input_path=None,
        )

    resolved = Path(input_path)
    if not resolved.is_file():
        warning = format_missing_file_message(
            command_path=command_path,
            data_dir=data_dir,
            missing_file=resolved,
            classification=classification,
            action=fallback_action,
        )
        logger.warning(warning)
        return OptionalInputLoadResult(
            value=default_value,
            used_fallback=True,
            warning=warning,
            input_path=resolved,
        )

    try:
        loaded = loader(resolved)
        return OptionalInputLoadResult(
            value=loaded,
            used_fallback=False,
            warning=None,
            input_path=resolved,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        warning = (
            f"command_path={command_path} "
            f"data_dir={data_dir} "
            f"missing_file={resolved} "
            f"classification={classification} "
            f"action={fallback_action} "
            f"reason={type(exc).__name__}: {exc}"
        )
        logger.warning(warning)
        return OptionalInputLoadResult(
            value=default_value,
            used_fallback=True,
            warning=warning,
            input_path=resolved,
        )


def create_checkpoint_filename(filename: str) -> str:
    """Create a checkpoint filename from a base filename.
    
    Strips the extension from the input filename and appends the checkpoint suffix.
    For example: 'td-fetch-all.json' becomes 'td-fetch-all.partial.json'
    
    Args:
        filename: The base filename to create a checkpoint filename from
        
    Returns:
        The checkpoint filename with extension stripped and suffix appended
    """
    from td_const import TD_CHECKPOINT_FILENAME_SUFFIX
    
    base_name = os.path.splitext(filename)[0]
    return base_name + TD_CHECKPOINT_FILENAME_SUFFIX


def save_json_atomic(data, filename: str | os.PathLike, indent: int = 4, add_trailing_newline: bool = False) -> None:
    """Save JSON data to file atomically using temporary file + rename.
    
    Writes to a temporary .tmp file first, then uses os.replace() to atomically
    swap it into place. This prevents incomplete JSON from being read by concurrent
    processes if the write is interrupted.
    
    Args:
        data: Object to serialize to JSON
        filename: Target output filename (string or PathLike)
        indent: JSON indent level (default: 4)
        add_trailing_newline: Add newline after JSON content (default: False)
    
    Raises:
        IOError, json.JSONEncodeError, OSError: On write failure
    """
    tmp_file = os.fspath(filename) + ".tmp"
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent)
            if add_trailing_newline:
                f.write("\n")
        os.replace(tmp_file, filename)
    except Exception as e:
        # Clean up temporary file if it exists
        try:
            os.remove(tmp_file)
        except FileNotFoundError:
            pass
        logging.error(f"Failed to save {filename}: {e}")
        raise


def save_final_json(
    data: Any,
    filename: str | os.PathLike[str],
    outcome: CollectionWriteOutcome,
    *,
    indent: int = 4,
    add_trailing_newline: bool = False,
    writer: Callable[..., None] = save_json_atomic,
) -> bool:
    """Replace a final snapshot after complete or useful partial collection."""
    if outcome.status is CollectionStatus.FAILED or (
        outcome.status is CollectionStatus.PARTIAL
        and not outcome.has_usable_data
    ):
        logging.info(
            "event=final_write_skipped file=%s status=%s",
            filename,
            outcome.status.value,
        )
        return False
    if indent == 4 and not add_trailing_newline:
        writer(data, filename)
    else:
        writer(data, filename, indent=indent, add_trailing_newline=add_trailing_newline)
    return True


def save_checkpoint_json(
    data: Any,
    filename: str | os.PathLike[str],
    outcome: CollectionWriteOutcome,
    *,
    indent: int = 4,
    add_trailing_newline: bool = False,
    writer: Callable[..., None] = save_json_atomic,
) -> bool:
    """Replace a checkpoint only when a partial collection has usable evidence."""
    if (
        outcome.status is not CollectionStatus.PARTIAL
        or not outcome.has_usable_data
    ):
        logging.info(
            "event=checkpoint_write_skipped file=%s status=%s usable=%s",
            filename,
            outcome.status.value,
            outcome.has_usable_data,
        )
        return False
    if indent == 4 and not add_trailing_newline:
        writer(data, filename)
    else:
        writer(data, filename, indent=indent, add_trailing_newline=add_trailing_newline)
    return True


def save_text_atomic(text: str, filename: str | os.PathLike) -> None:
    """Save text atomically using a temporary file and replace."""
    tmp_file = os.fspath(filename) + ".tmp"
    try:
        with open(tmp_file, "w", encoding="utf-8") as file:
            file.write(text)
        os.replace(tmp_file, filename)
    except Exception as exc:
        try:
            os.remove(tmp_file)
        except FileNotFoundError:
            pass
        logging.error("Failed to save %s: %s", filename, exc)
        raise
