"""Tests for otbr_restapi_util module."""

import argparse

import pytest

from otbr_restapi_util import (
    DEFAULT_ACCEPT,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    OTBRRestApiClient,
    add_common_rest_client_args,
    build_rest_client_from_args,
)


class TestAddCommonRestClientArgs:
    """Tests for add_common_rest_client_args helper."""
    
    def test_adds_all_required_arguments(self):
        """Should add all standard REST client arguments to parser."""
        parser = argparse.ArgumentParser()
        add_common_rest_client_args(parser)
        
        # Parse with defaults
        args = parser.parse_args([])
        
        assert hasattr(args, "host")
        assert hasattr(args, "port")
        assert hasattr(args, "base_url")
        assert hasattr(args, "timeout")
        assert hasattr(args, "accept")
        assert hasattr(args, "datadir")
    
    def test_host_argument_default(self):
        """Should set default host to DEFAULT_HOST."""
        parser = argparse.ArgumentParser()
        add_common_rest_client_args(parser)
        args = parser.parse_args([])
        
        assert args.host == DEFAULT_HOST
    
    def test_host_argument_custom_value(self):
        """Should accept custom host value."""
        parser = argparse.ArgumentParser()
        add_common_rest_client_args(parser)
        args = parser.parse_args(["--host", "192.168.1.100"])
        
        assert args.host == "192.168.1.100"
    
    def test_port_argument_default(self):
        """Should set default port to DEFAULT_PORT."""
        parser = argparse.ArgumentParser()
        add_common_rest_client_args(parser)
        args = parser.parse_args([])
        
        assert args.port == DEFAULT_PORT
    
    def test_port_argument_custom_value(self):
        """Should accept custom port value as integer."""
        parser = argparse.ArgumentParser()
        add_common_rest_client_args(parser)
        args = parser.parse_args(["--port", "9000"])
        
        assert args.port == 9000
        assert isinstance(args.port, int)
    
    def test_base_url_argument_default(self):
        """Should set base_url to None by default."""
        parser = argparse.ArgumentParser()
        add_common_rest_client_args(parser)
        args = parser.parse_args([])
        
        assert args.base_url is None
    
    def test_base_url_argument_custom_value(self):
        """Should accept custom base URL."""
        parser = argparse.ArgumentParser()
        add_common_rest_client_args(parser)
        args = parser.parse_args(["--base-url", "http://10.0.0.1:8081"])
        
        assert args.base_url == "http://10.0.0.1:8081"
    
    def test_timeout_argument_default(self):
        """Should set default timeout to DEFAULT_TIMEOUT."""
        parser = argparse.ArgumentParser()
        add_common_rest_client_args(parser)
        args = parser.parse_args([])
        
        assert args.timeout == DEFAULT_TIMEOUT
    
    def test_timeout_argument_custom_value(self):
        """Should accept custom timeout value as integer."""
        parser = argparse.ArgumentParser()
        add_common_rest_client_args(parser)
        args = parser.parse_args(["--timeout", "30"])
        
        assert args.timeout == 30
        assert isinstance(args.timeout, int)
    
    def test_accept_argument_default(self):
        """Should set default accept header to DEFAULT_ACCEPT."""
        parser = argparse.ArgumentParser()
        add_common_rest_client_args(parser)
        args = parser.parse_args([])
        
        assert args.accept == DEFAULT_ACCEPT
    
    def test_accept_argument_custom_value(self):
        """Should accept custom Accept header."""
        parser = argparse.ArgumentParser()
        add_common_rest_client_args(parser)
        args = parser.parse_args(["--accept", "application/json"])
        
        assert args.accept == "application/json"
    
    def test_datadir_argument_default(self):
        """Should set datadir to None by default."""
        parser = argparse.ArgumentParser()
        add_common_rest_client_args(parser)
        args = parser.parse_args([])
        
        assert args.datadir is None
    
    def test_datadir_argument_custom_value(self):
        """Should accept custom datadir path."""
        parser = argparse.ArgumentParser()
        add_common_rest_client_args(parser)
        args = parser.parse_args(["--datadir", "/custom/data/dir"])
        
        assert args.datadir == "/custom/data/dir"
    
    def test_multiple_arguments_together(self):
        """Should handle multiple arguments specified together."""
        parser = argparse.ArgumentParser()
        add_common_rest_client_args(parser)
        args = parser.parse_args([
            "--host", "192.168.1.1",
            "--port", "8080",
            "--timeout", "20",
            "--accept", "application/json",
        ])
        
        assert args.host == "192.168.1.1"
        assert args.port == 8080
        assert args.timeout == 20
        assert args.accept == "application/json"
    
    def test_works_with_subparser(self):
        """Should work when added to a subparser."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        subparser = subparsers.add_parser("test-command")
        add_common_rest_client_args(subparser)
        
        args = parser.parse_args(["test-command", "--host", "10.0.0.1"])
        
        assert args.command == "test-command"
        assert args.host == "10.0.0.1"


class TestBuildRestClientFromArgs:
    """Tests for build_rest_client_from_args helper."""
    
    def test_builds_client_with_default_values(self):
        """Should build client with default values from args."""
        parser = argparse.ArgumentParser()
        add_common_rest_client_args(parser)
        args = parser.parse_args([])
        
        client = build_rest_client_from_args(args)
        
        assert isinstance(client, OTBRRestApiClient)
        assert client.base_url == f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"
        assert client.timeout == DEFAULT_TIMEOUT
        assert client.accept == DEFAULT_ACCEPT
    
    def test_builds_client_with_custom_host_and_port(self):
        """Should build client with custom host and port."""
        parser = argparse.ArgumentParser()
        add_common_rest_client_args(parser)
        args = parser.parse_args(["--host", "192.168.1.1", "--port", "9000"])
        
        client = build_rest_client_from_args(args)
        
        assert client.base_url == "http://192.168.1.1:9000"
    
    def test_builds_client_with_base_url(self):
        """Should use base_url when provided (takes precedence over host/port)."""
        parser = argparse.ArgumentParser()
        add_common_rest_client_args(parser)
        args = parser.parse_args([
            "--host", "192.168.1.1",
            "--port", "9000",
            "--base-url", "http://10.0.0.1:8081"
        ])
        
        client = build_rest_client_from_args(args)
        
        # base_url should take precedence
        assert client.base_url == "http://10.0.0.1:8081"
    
    def test_builds_client_with_custom_timeout(self):
        """Should build client with custom timeout."""
        parser = argparse.ArgumentParser()
        add_common_rest_client_args(parser)
        args = parser.parse_args(["--timeout", "30"])
        
        client = build_rest_client_from_args(args)
        
        assert client.timeout == 30
    
    def test_builds_client_with_custom_accept(self):
        """Should build client with custom Accept header."""
        parser = argparse.ArgumentParser()
        add_common_rest_client_args(parser)
        args = parser.parse_args(["--accept", "application/json"])
        
        client = build_rest_client_from_args(args)
        
        assert client.accept == "application/json"
    
    def test_builds_client_with_all_custom_values(self):
        """Should build client with all custom values."""
        parser = argparse.ArgumentParser()
        add_common_rest_client_args(parser)
        args = parser.parse_args([
            "--host", "192.168.1.1",
            "--port", "9000",
            "--timeout", "20",
            "--accept", "application/json",
        ])
        
        client = build_rest_client_from_args(args)
        
        assert client.base_url == "http://192.168.1.1:9000"
        assert client.timeout == 20
        assert client.accept == "application/json"
    
    def test_forwards_additional_kwargs_to_client(self):
        """Should forward additional kwargs to OTBRRestApiClient constructor."""
        parser = argparse.ArgumentParser()
        add_common_rest_client_args(parser)
        args = parser.parse_args([])
        
        client = build_rest_client_from_args(
            args,
            retries=5,
            user_agent="custom-agent/1.0",
            default_raw=True,
        )
        
        assert client.retries == 5
        assert client.user_agent == "custom-agent/1.0"
        assert client._default_raw is True
    
    def test_kwargs_can_override_args_values(self):
        """Should allow kwargs to override values from args."""
        parser = argparse.ArgumentParser()
        add_common_rest_client_args(parser)
        args = parser.parse_args(["--timeout", "10"])
        
        client = build_rest_client_from_args(args, timeout=30)
        
        # kwargs should override args
        assert client.timeout == 30
    
    def test_base_url_precedence(self):
        """Should demonstrate that base_url takes precedence over host/port."""
        parser = argparse.ArgumentParser()
        add_common_rest_client_args(parser)
        
        # Without base_url, uses host+port
        args1 = parser.parse_args(["--host", "192.168.1.1", "--port", "9000"])
        client1 = build_rest_client_from_args(args1)
        assert client1.base_url == "http://192.168.1.1:9000"
        
        # With base_url, ignores host+port
        args2 = parser.parse_args([
            "--host", "192.168.1.1",
            "--port", "9000",
            "--base-url", "http://example.com:8081"
        ])
        client2 = build_rest_client_from_args(args2)
        assert client2.base_url == "http://example.com:8081"
    
    def test_missing_required_attribute_raises_error(self):
        """Should raise AttributeError if required args are missing."""
        # Create args without proper attributes
        args = argparse.Namespace()
        
        with pytest.raises(AttributeError):
            build_rest_client_from_args(args)
    
    def test_works_with_namespace_from_subparser(self):
        """Should work with args from a subparser."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        subparser = subparsers.add_parser("test-command")
        add_common_rest_client_args(subparser)
        
        args = parser.parse_args(["test-command", "--host", "10.0.0.1"])
        client = build_rest_client_from_args(args)
        
        assert client.base_url == "http://10.0.0.1:8081"


class TestIntegrationWorkflow:
    """Integration tests for typical CLI workflow."""
    
    def test_typical_cli_workflow(self):
        """Should handle typical CLI parser setup and client construction."""
        # Setup parser like a real CLI module would
        parser = argparse.ArgumentParser(description="Test CLI")
        add_common_rest_client_args(parser)
        parser.add_argument("--verbose", action="store_true")
        
        # Parse args
        args = parser.parse_args(["--host", "192.168.1.1", "--verbose"])
        
        # Build client
        client = build_rest_client_from_args(args)
        
        # Verify client is ready to use
        assert isinstance(client, OTBRRestApiClient)
        assert client.base_url == "http://192.168.1.1:8081"
        assert args.verbose is True
    
    def test_subcommand_workflow(self):
        """Should handle subcommand-based CLI workflow."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="subcommand")
        
        # Setup multiple subcommands
        get_cmd = subparsers.add_parser("get")
        add_common_rest_client_args(get_cmd)
        
        list_cmd = subparsers.add_parser("list")
        add_common_rest_client_args(list_cmd)
        
        # Parse and build client for 'get' subcommand
        args = parser.parse_args(["get", "--timeout", "20"])
        client = build_rest_client_from_args(args)
        
        assert args.subcommand == "get"
        assert client.timeout == 20
    
    def test_override_workflow(self):
        """Should handle workflow with base-url override."""
        parser = argparse.ArgumentParser()
        add_common_rest_client_args(parser)
        
        # User provides base-url to override defaults
        args = parser.parse_args([
            "--base-url", "https://otbr.example.com/api",
            "--timeout", "15"
        ])
        
        client = build_rest_client_from_args(args)
        
        assert client.base_url == "https://otbr.example.com/api"
        assert client.timeout == 15
