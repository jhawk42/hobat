from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping, Sequence

from const import (
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


def _normalize_path(
    path_value: str | os.PathLike[str], cwd: Path | None = None
) -> Path:
    """Normalize path_value to an absolute Path, resolving relative paths against cwd."""
    path = Path(path_value).expanduser()
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
    datadir_arg: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    cwd: str | os.PathLike[str] | None = None,
) -> TDDataDirResolution:
    """Resolve td_data_dir and include resolution metadata.

    Precedence is environment, then CLI argument, then defaults.
    """
    env_map = os.environ if env is None else env
    base_cwd = _normalize_path(cwd or Path.cwd())

    env_value = _normalize_optional_path(env_map.get(TD_DATA_DIR_ENV_VAR))
    if env_value is not None:
        return TDDataDirResolution(
            path=_normalize_path(env_value, base_cwd),
            source=TDDataDirSource.ENV,
            created=False,
        )

    datadir_value = _normalize_optional_path(datadir_arg)
    if datadir_value is not None:
        return TDDataDirResolution(
            path=_normalize_path(datadir_value, base_cwd),
            source=TDDataDirSource.CLI,
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
    datadir_arg: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    cwd: str | os.PathLike[str] | None = None,
) -> Path:
    """Resolve the TD data directory using ENV -> CLI -> defaults precedence.

    Precedence (exactly as required):
    1. Environment variable TD_DATA_DIR
    2. Command line argument --datadir
    3. Defaults:
       - if /data exists, use /data
       - otherwise create ./data under cwd and use it

    For ENV/CLI values this function resolves and returns the absolute path,
    but does not create directories.
    """
    return resolve_data_dir_with_source(
        datadir_arg=datadir_arg,
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


def resolve_data_file_path(path_or_name: str, td_data_dir: Path) -> Path:
    """Resolve an absolute file path or map a relative name under td_data_dir."""
    normalized = _normalize_optional_path(path_or_name)
    if normalized is None:
        raise ValueError("path_or_name must be a non-empty path")
    value = Path(normalized).expanduser()
    if value.is_absolute():
        return value.resolve()
    return (td_data_dir / value).resolve()
