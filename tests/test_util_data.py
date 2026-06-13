from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

import util_data


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
