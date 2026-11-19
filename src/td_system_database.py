"""SQLite database maintenance operations for Hobat."""

from __future__ import annotations

import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from td_health_observation_store import HOBAT_DATABASE_FILENAME


_SQLITE_BUSY_TIMEOUT_SECONDS = 5.0


class DatabaseRepackError(RuntimeError):
    """Raised when the Hobat database cannot be repacked."""


def repack_database(data_dir: Path) -> Path:
    database_path = data_dir / HOBAT_DATABASE_FILENAME
    if not database_path.is_file():
        raise DatabaseRepackError(
            f"Hobat database is not available: {database_path}"
        )

    try:
        resolved_database_path = database_path.resolve()
        required_bytes = resolved_database_path.stat().st_size
        free_bytes = shutil.disk_usage(resolved_database_path.parent).free
    except OSError as exc:
        raise DatabaseRepackError(
            f"Could not check free disk space for Hobat database at {database_path}: {exc}"
        ) from exc
    if free_bytes < required_bytes:
        raise DatabaseRepackError(
            f"Not enough free disk space to repack Hobat database at {database_path}: "
            f"requires at least {required_bytes} bytes; {free_bytes} bytes available. "
            "Free disk space and retry."
        )

    database_uri = f"{resolved_database_path.as_uri()}?mode=rw"
    try:
        with closing(
            sqlite3.connect(
                database_uri,
                timeout=_SQLITE_BUSY_TIMEOUT_SECONDS,
                uri=True,
            )
        ) as connection:
            connection.execute("VACUUM;")
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower() or "busy" in str(exc).lower():
            raise DatabaseRepackError(
                "Hobat database is busy; stop active database users and retry: "
                f"{database_path}"
            ) from exc
        raise DatabaseRepackError(
            f"Could not repack Hobat database at {database_path}: {exc}"
        ) from exc
    except sqlite3.DatabaseError as exc:
        raise DatabaseRepackError(
            f"Could not repack Hobat database at {database_path}: {exc}"
        ) from exc

    return database_path