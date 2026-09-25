from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import util_data
import td_webserver
import otbr_restapi_download


class DataDirResolutionTests(unittest.TestCase):
    """Verification coverage for matrix cases around path resolution."""

    def test_case_2b_cli_relative_datadir_resolves_from_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            resolved = util_data.resolve_data_dir(
                data_dir="relative-data",
                env={},
                cwd=tmpdir,
            )
            self.assertEqual(
                resolved, (Path(tmpdir) / "relative-data").resolve())

    def test_case_2c_missing_user_supplied_datadir_is_not_auto_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "does-not-exist"
            resolved = util_data.resolve_data_dir(
                data_dir=str(missing),
                env={},
                cwd=tmpdir,
            )
            self.assertEqual(resolved, missing.resolve())
            self.assertFalse(resolved.exists())

    def test_case_3b_local_default_creation_permission_error_bubbles(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch("util_data.Path.exists", return_value=False),
                patch(
                    "util_data.Path.mkdir",
                    side_effect=PermissionError("permission denied"),
                ),
            ):
                with self.assertRaises(PermissionError):
                    util_data.resolve_data_dir(
                        data_dir=None, env={}, cwd=tmpdir)


class DirectModuleInvocationTests(unittest.TestCase):
    """Verification coverage for direct module entry points bypassing td_cli."""

    def test_case_6b_restapi_download_main_uses_datadir_arg_directly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.dict("os.environ", {}, clear=False) as env_patch:
            env_patch.pop("TD_DATA_DIR", None)
            datadir = Path(tmpdir) / "direct-entry-dir"
            expected = datadir.resolve()

            def _assert_datadir_and_return(*_args, **_kwargs) -> int:
                self.assertEqual(
                    otbr_restapi_download._ACTIVE_TD_DATA_DIR, expected)
                return 0

            with patch.object(
                otbr_restapi_download,
                "download_all_restapi_endpoints",
                side_effect=_assert_datadir_and_return,
            ):
                rc = otbr_restapi_download.main(["--datadir", str(datadir)])

            self.assertEqual(rc, 0)
            self.assertIsNone(otbr_restapi_download._ACTIVE_TD_DATA_DIR)


if __name__ == "__main__":
    unittest.main()
