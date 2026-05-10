from __future__ import annotations

import unittest
from unittest.mock import patch

import td_cli
import td_webserver


class TDCLIDataDirForwardingTests(unittest.TestCase):
    def _parse_known(self, argv: list[str]):
        parser = td_cli.build_parser()
        args, extras = parser.parse_known_args(argv)
        return parser, args, extras

    def test_build_parser_accepts_top_level_datadir(self) -> None:
        _, args, extras = self._parse_known(["--datadir", "/tmp/td-data", "merge-dataset"])
        self.assertEqual(args.datadir, "/tmp/td-data")
        self.assertEqual(extras, [])

    def test_dispatch_forwards_datadir_to_restapi_download(self) -> None:
        parser, args, extras = self._parse_known(
            ["--datadir", "/tmp/td-data", "otbr-restapi", "download"]
        )

        with patch.object(
            td_cli.otbr_restapi_download, "main", return_value=0
        ) as module_main:
            rc = td_cli.dispatch(args, extras, parser)

        self.assertEqual(rc, 0)
        module_main.assert_called_once_with(["--datadir", "/tmp/td-data"])

    def test_dispatch_forwards_datadir_to_mdns(self) -> None:
        parser, args, extras = self._parse_known(
            ["--datadir", "/tmp/td-data", "mdns", "thread"]
        )

        with patch.object(
            td_cli.mdns_thread_scopes, "main", return_value=0
        ) as module_main:
            rc = td_cli.dispatch(args, extras, parser)

        self.assertEqual(rc, 0)
        module_main.assert_called_once()
        forwarded = module_main.call_args.args[0]
        self.assertIn("--datadir", forwarded)
        self.assertIn("/tmp/td-data", forwarded)

    def test_dispatch_forwards_datadir_with_networkdiag_children_flag(self) -> None:
        parser, args, extras = self._parse_known(
            [
                "--datadir",
                "/tmp/td-data",
                "otbr-cli",
                "networkdiag",
                "topology-poll",
                "--children-no",
            ]
        )

        with patch.object(
            td_cli.otbr_cli_networkdiag_topology, "main", return_value=0
        ) as module_main:
            rc = td_cli.dispatch(args, extras, parser)

        self.assertEqual(rc, 0)
        module_main.assert_called_once_with(["--datadir", "/tmp/td-data", "-cno"])

    def test_webserver_main_accepts_datadir(self) -> None:
        with patch.object(
            td_webserver, "main", return_value=0
        ) as module_main:
            rc = td_webserver.main(
                ["--datadir", "/tmp/td-data", "--host", "0.0.0.0", "--port", "9090"]
            )

        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
