"""Broker tests use fakes and assert no secret reaches results or errors."""

from __future__ import annotations

import base64
import unittest

from services.github_tool.broker import BrokerConfig, BrokerError, GitHubReadBroker
from services.github_tool.handler import gateway_tool_name


class FakeSecrets:
    def get_secret_string(self, secret_arn: str) -> str:
        return "PRIVATE-KEY"


class FakeSigner:
    def sign(self, app_id: str, private_key: str) -> str:
        return "APP-JWT"


class FakeHttp:
    def __init__(self) -> None:
        self.calls = []

    def request(self, method, path, headers, body=None):
        self.calls.append((method, path, headers, body))
        if path.endswith("/access_tokens"):
            return 201, {"token": "INSTALLATION-TOKEN"}
        if path.startswith("/installation/repositories"):
            return 200, {"total_count": 1, "repositories": [{"owner": {"login": "example-org"}, "name": "example-repo", "private": True}]}
        if "/contents/" in path:
            return 200, {"type": "file", "encoding": "base64", "content": base64.b64encode(b"hello\n").decode(), "sha": "abc"}
        return 200, {"owner": {"login": "example-org"}, "name": "example-repo", "private": True, "default_branch": "main"}


class FakeGatewayContext:
    class ClientContext:
        def __init__(self, tool_name: str) -> None:
            self.custom = {"bedrockAgentCoreToolName": tool_name}

    def __init__(self, tool_name: str) -> None:
        self.client_context = self.ClientContext(tool_name)


class GitHubReadBrokerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.http = FakeHttp()
        config = BrokerConfig("1", "2", "arn:secret", "agent.pem")
        self.broker = GitHubReadBroker(config, FakeSecrets(), FakeSigner(), self.http)

    def test_get_file_is_bounded_and_uses_fixed_endpoints(self) -> None:
        result = self.broker.execute({"tool": "getFile", "arguments": {"owner": "example-org", "repo": "example-repo", "path": "README.md", "ref": "main"}})
        self.assertEqual(result["file"]["content"], "hello\n")
        self.assertEqual(self.http.calls[0][1], "/app/installations/2/access_tokens")
        self.assertEqual(self.http.calls[1][1], "/repos/example-org/example-repo/contents/README.md?ref=main")
        self.assertEqual(self.http.calls[0][3], {"repositories": ["example-repo"], "permissions": {"contents": "read"}})
        self.assertEqual(self.http.calls[1][2]["User-Agent"], "agentcore-github-read-broker/1")

    def test_list_repositories_uses_the_current_installation_scope(self) -> None:
        result = self.broker.execute({"tool": "listRepositories", "arguments": {}})
        self.assertEqual(result, {"tool": "listRepositories", "repositories": [{"owner": "example-org", "name": "example-repo", "private": True}], "page": 1, "total_count": 1, "has_more": False})
        self.assertEqual(self.http.calls[0][3], {"permissions": {"contents": "read"}})
        self.assertEqual(self.http.calls[1][1], "/installation/repositories?per_page=100&page=1")

    def test_scopes_each_repository_read_token_to_the_requested_repository(self) -> None:
        self.broker.execute({"tool": "getRepository", "arguments": {"owner": "example-org", "repo": "example-repo"}})
        self.assertEqual(self.http.calls[0][3], {"permissions": {"contents": "read"}, "repositories": ["example-repo"]})

    def test_get_file_accepts_github_base64_line_wrapping(self) -> None:
        self.http.request = lambda method, path, headers, body=None: (
            (201, {"token": "INSTALLATION-TOKEN"})
            if path.endswith("/access_tokens")
            else (200, {"type": "file", "encoding": "base64", "content": "aGVs\nbG8K", "sha": "abc"})
        )
        result = self.broker.execute({"tool": "getFile", "arguments": {"owner": "example-org", "repo": "example-repo", "path": "README.md"}})
        self.assertEqual(result["file"]["content"], "hello\n")

    def test_errors_do_not_include_credentials(self) -> None:
        self.http.request = lambda *args, **kwargs: (401, {})
        with self.assertRaises(BrokerError) as caught:
            self.broker.execute({"tool": "getRepository", "arguments": {"owner": "example-org", "repo": "example-repo"}})
        self.assertNotIn("PRIVATE-KEY", str(caught.exception))
        self.assertNotIn("APP-JWT", str(caught.exception))
        self.assertNotIn("INSTALLATION-TOKEN", str(caught.exception))

    def test_gateway_context_selects_only_the_reviewed_tool_names(self) -> None:
        self.assertEqual(gateway_tool_name(FakeGatewayContext("github-list-repositories___listRepositories")), "listRepositories")
        self.assertEqual(gateway_tool_name(FakeGatewayContext("github-get-file___getFile")), "getFile")
        self.assertEqual(gateway_tool_name(FakeGatewayContext("github-get-repository___getRepository")), "getRepository")
        with self.assertRaisesRegex(BrokerError, "invalid_request"):
            gateway_tool_name(FakeGatewayContext("github-get-file___deleteRepository"))


if __name__ == "__main__":
    unittest.main()
