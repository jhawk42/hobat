from __future__ import annotations

import tempfile
import unittest
import json
import builtins
import multiprocessing
import os
import queue
import stat
import sys
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

import util_data


def _atomic_writer_worker(kind, name, filename, staged, release, paths, results, failure):
    real_open = builtins.open
    real_replace = os.replace
    streams = []

    class FailingStream:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def write(self, value):
            self.stream.write(value[:1])
            self.stream.flush()
            paths.put(self.stream.name)
            staged.set()
            if not release.wait(10):
                raise TimeoutError("write release")
            raise ValueError("injected partial serialization")

    def open_staging(path, mode="r", *args, **kwargs):
        stream = real_open(path, mode, *args, **kwargs)
        if mode in ("w", "x"):
            streams.append(stream)
            if failure == "write":
                return FailingStream(stream)
        return stream

    def replace(source, destination):
        assert all(stream.closed for stream in streams)
        paths.put(os.fspath(source))
        staged.set()
        if not release.wait(10):
            raise TimeoutError("replace release")
        if failure == "replace":
            raise PermissionError("injected replace failure")
        real_replace(source, destination)

    try:
        # Patching the module's open avoids process-global changes between threads.
        with patch.object(util_data, "open", open_staging, create=True), patch.object(
            util_data, "os", wraps=os
        ) as local_os:
            local_os.replace = replace
            if kind == "json":
                util_data.save_json_atomic(
                    {"writer": name, "payload": name * 4000},
                    filename, indent=2, add_trailing_newline=True,
                )
            else:
                util_data.save_text_atomic(f"{name}:é\n" * 4000, filename)
        results.put(None)
    except Exception as exc:
        results.put(type(exc).__name__)


@pytest.mark.parametrize("backend", ["thread", "process"])
@pytest.mark.parametrize("kind", ["json", "text"])
@pytest.mark.parametrize("failure", [None, "write", "replace"])
def test_atomic_ordered_writers(backend, kind, failure):
    # Each thread needs its own module globals for the injected I/O schedule.
    import importlib.util

    with tempfile.TemporaryDirectory(dir=".") as directory:
        filename = Path(directory).resolve() / f"snapshot.{kind}"
        sentinel = Path(f"{filename}.tmp")
        sentinel.write_text("unowned", encoding="utf-8")
        payload = lambda name: (
            json.dumps({"writer": name, "payload": name * 4000}, indent=2) + "\n"
            if kind == "json" else f"{name}:é\n" * 4000
        )
        filename.write_text(payload("old"), encoding="utf-8")
        ctx = multiprocessing.get_context("spawn") if backend == "process" else None
        event = ctx.Event if ctx else threading.Event
        channel = ctx.Queue if ctx else queue.Queue
        stages, releases = [event(), event()], [event(), event()]
        paths, results = [channel(), channel()], [channel(), channel()]
        workers = []
        stage_paths = []
        for index, name in enumerate(("A", "B")):
            args = (kind, name, filename, stages[index], releases[index],
                    paths[index], results[index], failure if index == 0 else None)
            if ctx:
                worker = ctx.Process(target=_atomic_writer_worker, args=args)
            else:
                spec = importlib.util.spec_from_file_location(
                    f"_atomic_test_{name}", util_data.__file__
                )
                module = importlib.util.module_from_spec(spec)
                # dataclasses resolves its module through sys.modules.
                sys.modules[spec.name] = module
                spec.loader.exec_module(module)
                worker_fn = type(_atomic_writer_worker)(
                    _atomic_writer_worker.__code__,
                    {**globals(), "util_data": module},
                )
                worker = threading.Thread(target=worker_fn, args=args, daemon=True)
            workers.append(worker)
        try:
            for index, worker in enumerate(workers):
                worker.start()
                assert stages[index].wait(10), f"writer {index} never staged"
                stage_paths.append(Path(paths[index].get(timeout=2)))
            assert filename.read_text(encoding="utf-8") == payload("old")
            releases[0].set()
            workers[0].join(10)
            assert not workers[0].is_alive()
            assert results[0].get(timeout=2) == {
                None: None, "write": "ValueError", "replace": "PermissionError"
            }[failure]
            assert filename.read_text(encoding="utf-8") == payload("A" if failure is None else "old")
            assert stage_paths[1].exists(), "A cleanup removed B staging"
            releases[1].set()
            workers[1].join(10)
            assert not workers[1].is_alive()
            assert results[1].get(timeout=2) is None
            assert filename.read_text(encoding="utf-8") == payload("B")
            assert stage_paths[0] != stage_paths[1]
            assert all(path.parent == filename.parent for path in stage_paths)
            assert sentinel.read_text(encoding="utf-8") == "unowned"
            assert set(filename.parent.iterdir()) == {filename, sentinel}
        finally:
            for release in releases:
                release.set()
            for worker in workers:
                if worker.ident is not None:
                    worker.join(12)
                    if ctx and worker.is_alive():
                        worker.terminate()
                        worker.join(5)
            if ctx:
                for item in paths + results:
                    item.close()
                    item.join_thread()
            else:
                for name in ("A", "B"):
                    sys.modules.pop(f"_atomic_test_{name}", None)


@pytest.mark.parametrize("kind", ["json", "text"])
def test_atomic_cleanup_preserves_original_error(kind, caplog):
    with tempfile.TemporaryDirectory(dir=".") as directory:
        filename = Path(directory) / "snapshot"
        original = ValueError("serialization failed")
        with patch("util_data.os.remove", side_effect=PermissionError("cleanup failed")):
            with pytest.raises(ValueError) as raised:
                if kind == "json":
                    with patch("util_data.json.dump", side_effect=original):
                        util_data.save_json_atomic({}, filename)
                else:
                    with patch("util_data.os.replace", side_effect=original):
                        util_data.save_text_atomic("text", filename)
        assert raised.value is original
        assert "cleanup" in caplog.text.lower()


@pytest.mark.parametrize("kind", ["json", "text"])
def test_atomic_exclusive_collision_does_not_clean_up_unowned_file(kind):
    from types import SimpleNamespace

    with tempfile.TemporaryDirectory(dir=".") as directory:
        filename = Path(directory) / "snapshot"
        staging = Path(f"{filename}.collision.tmp")
        staging.write_text("other writer", encoding="utf-8")
        filename.write_text("completed final", encoding="utf-8")
        with patch("util_data.uuid4", return_value=SimpleNamespace(hex="collision")):
            with pytest.raises(FileExistsError):
                if kind == "json":
                    util_data.save_json_atomic({}, filename)
                else:
                    util_data.save_text_atomic("text", filename)
        assert staging.read_text(encoding="utf-8") == "other writer"
        assert filename.read_text(encoding="utf-8") == "completed final"
        assert set(filename.parent.iterdir()) == {filename, staging}


@pytest.mark.skipif(os.name != "posix", reason="POSIX create/umask semantics")
@pytest.mark.parametrize("kind", ["json", "text"])
def test_atomic_umask_and_exclusive_staging(kind):
    import subprocess

    with tempfile.TemporaryDirectory(dir=".") as directory:
        filename = Path(directory).resolve() / "snapshot"
        script = """
import os, sys
from unittest.mock import patch
import util_data
os.umask(0o027)
real_open = open
def exclusive(path, mode, **kwargs):
    assert mode == 'x'
    return real_open(path, mode, **kwargs)
with patch.object(util_data, 'open', exclusive, create=True):
    if sys.argv[1] == 'json':
        util_data.save_json_atomic({'unicode': 'é'}, sys.argv[2])
    else:
        util_data.save_text_atomic('é', sys.argv[2])
"""
        subprocess.run(
            [sys.executable, "-c", script, kind, str(filename)],
            env={**os.environ, "PYTHONPATH": str(Path(util_data.__file__).parent)},
            check=True, timeout=10,
        )
        assert stat.S_IMODE(filename.stat().st_mode) == 0o640
        assert list(filename.parent.iterdir()) == [filename]


class ResolveTdDataDirTests(unittest.TestCase):
    def test_cli_arg_has_highest_priority_over_env_var(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_dir = Path(tmpdir) / "env_data"
            cli_dir = Path(tmpdir) / "cli_data"

            resolved = util_data.resolve_data_dir(
                data_dir=str(cli_dir),
                env={"TD_DATA_DIR": str(env_dir)},
                cwd=tmpdir,
            )

            self.assertEqual(resolved, cli_dir.resolve())

            detailed = util_data.resolve_data_dir_with_source(
                data_dir=str(cli_dir),
                env={"TD_DATA_DIR": str(env_dir)},
                cwd=tmpdir,
            )
            self.assertEqual(detailed.source, util_data.TDDataDirSource.CLI)
            self.assertFalse(detailed.created)

    def test_cli_priority_when_env_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cli_dir = Path(tmpdir) / "cli_data"

            resolved = util_data.resolve_data_dir(
                data_dir=str(cli_dir),
                env={},
                cwd=tmpdir,
            )

            self.assertEqual(resolved, cli_dir.resolve())

            detailed = util_data.resolve_data_dir_with_source(
                data_dir=str(cli_dir),
                env={},
                cwd=tmpdir,
            )
            self.assertEqual(detailed.source, util_data.TDDataDirSource.CLI)
            self.assertFalse(detailed.created)

    def test_default_uses_docker_data_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("util_data.Path.exists", return_value=True):
                resolved = util_data.resolve_data_dir(
                    data_dir=None,
                    env={},
                    cwd=tmpdir,
                )
                detailed = util_data.resolve_data_dir_with_source(
                    data_dir=None,
                    env={},
                    cwd=tmpdir,
                )

            self.assertEqual(resolved, Path("/data").resolve())
            self.assertEqual(
                detailed.source, util_data.TDDataDirSource.DOCKER_DEFAULT)
            self.assertFalse(detailed.created)

    def test_default_creates_local_data_when_docker_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("util_data.Path.exists", return_value=False):
                resolved = util_data.resolve_data_dir(
                    data_dir=None,
                    env={},
                    cwd=tmpdir,
                )
                detailed = util_data.resolve_data_dir_with_source(
                    data_dir=None,
                    env={},
                    cwd=tmpdir,
                )

            expected = (Path(tmpdir) / "data").resolve()
            self.assertEqual(resolved, expected)
            self.assertTrue(expected.exists())
            self.assertTrue(expected.is_dir())
            self.assertEqual(
                detailed.source, util_data.TDDataDirSource.LOCAL_DEFAULT)

    def test_blank_env_value_is_ignored_and_cli_is_used(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cli_dir = Path(tmpdir) / "cli_data"
            detailed = util_data.resolve_data_dir_with_source(
                data_dir=str(cli_dir),
                env={"TD_DATA_DIR": "   "},
                cwd=tmpdir,
            )
            self.assertEqual(detailed.path, cli_dir.resolve())
            self.assertEqual(detailed.source, util_data.TDDataDirSource.CLI)


class DataDirectoryHelpersTests(unittest.TestCase):
    def test_ensure_td_data_dir_creates_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "new-data"
            ensured = util_data.ensure_data_dir_exists(target)
            self.assertEqual(ensured, target.resolve())
            self.assertTrue(target.exists())

    def test_format_td_data_dir_log_message(self) -> None:
        resolution = util_data.TDDataDirResolution(
            path=Path("/tmp/td-data"),
            source=util_data.TDDataDirSource.CLI,
            created=True,
        )
        rendered = util_data.format_data_dir_log_message(resolution)
        self.assertIn("td_data_directory=/tmp/td-data", rendered)
        self.assertIn("source=cli", rendered)
        self.assertIn("(created)", rendered)

    def test_extract_datadir_arg_supports_split_form(self) -> None:
        value = util_data.parse_datadir_from_argv(
            ["--foo", "1", "--datadir", "/tmp/data"])
        self.assertEqual(value, "/tmp/data")

    def test_extract_datadir_arg_supports_equals_form(self) -> None:
        value = util_data.parse_datadir_from_argv(["--datadir=/tmp/data"])
        self.assertEqual(value, "/tmp/data")

    def test_extract_datadir_arg_returns_none_when_missing(self) -> None:
        self.assertIsNone(util_data.parse_datadir_from_argv(["--foo", "bar"]))


class DataPathHelpersTests(unittest.TestCase):
    def test_data_file_path_joins_relative_name(self) -> None:
        base = Path("/tmp/td-data")
        self.assertEqual(
            util_data.data_file_path(
                "example.json", base), base / "example.json"
        )

    def test_data_file_path_rejects_absolute(self) -> None:
        with self.assertRaises(ValueError):
            util_data.data_file_path(
                "/tmp/absolute.json", Path("/tmp/td-data"))

    def test_data_file_path_rejects_nested_path(self) -> None:
        with self.assertRaises(ValueError):
            util_data.data_file_path("nested/name.json", Path("/tmp/td-data"))

    def test_data_file_arg_or_default_resolves_absolute(self) -> None:
        absolute = Path("/tmp/custom.json")
        resolved = util_data.resolve_data_file_path(
            str(absolute), Path("/tmp/td-data")
        )
        self.assertEqual(resolved, absolute.resolve())

    def test_data_file_arg_or_default_maps_relative_to_data_dir(self) -> None:
        base = Path("/tmp/td-data")
        resolved = util_data.resolve_data_file_path("name.json", base)
        self.assertEqual(resolved, (base / "name.json").resolve())

    def test_data_file_arg_or_default_rejects_blank(self) -> None:
        with self.assertRaises(ValueError):
            util_data.resolve_data_file_path("   ", Path("/tmp/td-data"))

    def test_create_checkpoint_filename_appends_partial_suffix(self) -> None:
        self.assertEqual(
            util_data.create_checkpoint_filename("td-mdns-scopes-thread.json"),
            "td-mdns-scopes-thread.partial.json",
        )

    def test_create_checkpoint_filename_preserves_leaf_name_only(self) -> None:
        self.assertEqual(
            util_data.create_checkpoint_filename("example"),
            "example.partial.json",
        )


class InputLoaderHelpersTests(unittest.TestCase):
    def test_require_existing_input_file_returns_path_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "input.json"
            file_path.write_text("{}", encoding="utf-8")

            resolved = util_data.require_existing_input_file(
                file_path,
                command_path="merge-dataset",
                data_dir=Path(tmpdir),
            )
            self.assertEqual(resolved, file_path)

    def test_require_existing_input_file_raises_typed_error_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "missing.json"
            with self.assertRaises(util_data.TDRequiredInputMissingError) as ctx:
                util_data.require_existing_input_file(
                    missing,
                    command_path="merge-dataset",
                    data_dir=Path(tmpdir),
                )

            self.assertIn("command_path=merge-dataset", str(ctx.exception))
            self.assertIn("classification=required", str(ctx.exception))

    def test_load_optional_input_returns_loaded_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "input.json"
            payload = {"k": "v"}
            file_path.write_text(json.dumps(payload), encoding="utf-8")

            result = util_data.load_optional_input(
                file_path,
                loader=lambda p: json.loads(p.read_text(encoding="utf-8")),
                default_value={},
                command_path="otbr-cli",
                data_dir=Path(tmpdir),
            )

            self.assertFalse(result.used_fallback)
            self.assertEqual(result.value, payload)
            self.assertIsNone(result.warning)

    def test_load_optional_input_falls_back_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "missing.json"
            default = {"empty": True}

            result = util_data.load_optional_input(
                missing,
                loader=lambda p: json.loads(p.read_text(encoding="utf-8")),
                default_value=default,
                command_path="otbr-cli",
                data_dir=Path(tmpdir),
            )

            self.assertTrue(result.used_fallback)
            self.assertEqual(result.value, default)
            self.assertIsNotNone(result.warning)

    def test_load_optional_input_falls_back_on_json_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "invalid.json"
            file_path.write_text("{ invalid", encoding="utf-8")
            default = {"empty": True}

            result = util_data.load_optional_input(
                file_path,
                loader=lambda p: json.loads(p.read_text(encoding="utf-8")),
                default_value=default,
                command_path="otbr-cli",
                data_dir=Path(tmpdir),
            )

            self.assertTrue(result.used_fallback)
            self.assertEqual(result.value, default)
            self.assertIsNotNone(result.warning)


if __name__ == "__main__":
    unittest.main()
