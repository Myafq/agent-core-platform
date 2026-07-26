"""Bounded GitHub App read broker for the Gateway Lambda target."""

from __future__ import annotations

import base64
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from contracts.contract_validation import ContractError, validate_tool_invocation, validate_tool_response

LOG = logging.getLogger(__name__)
API_VERSION = "2026-03-10"
USER_AGENT = "agentcore-github-read-broker/1"


class BrokerError(RuntimeError):
    """A safe, classed error suitable for the Gateway caller."""


class SecretReader(Protocol):
    def get_secret_string(self, secret_arn: str) -> str: ...


class JwtSigner(Protocol):
    def sign(self, app_id: str, private_key: str) -> str: ...


class HttpClient(Protocol):
    def request(self, method: str, path: str, headers: dict[str, str], body: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]: ...


class UrllibGitHubClient:
    """Fixed-host GitHub REST client; callers cannot provide URLs or headers."""

    base_url = "https://api.github.com"

    def request(self, method: str, path: str, headers: dict[str, str], body: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        data = None if body is None else json.dumps(body, separators=(",", ":")).encode()
        request = urllib.request.Request(f"{self.base_url}{path}", data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, {}
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise BrokerError("github_unavailable") from error


class PyJwtSigner:
    """Imports crypto support only in the packaged Lambda runtime."""

    def sign(self, app_id: str, private_key: str) -> str:
        try:
            import jwt
        except ImportError as error:  # pragma: no cover - packaging failure
            raise BrokerError("signer_unavailable") from error
        now = int(time.time())
        return jwt.encode({"iat": now - 60, "exp": now + 540, "iss": app_id}, private_key, algorithm="RS256")


@dataclass(frozen=True)
class BrokerConfig:
    app_id: str
    installation_id: str
    private_key_secret_arn: str
    private_key_secret_key: str

    @classmethod
    def from_environment(cls) -> "BrokerConfig":
        return cls(os.environ["GITHUB_APP_ID"], os.environ["GITHUB_APP_INSTALLATION_ID"], os.environ["GITHUB_APP_PRIVATE_KEY_SECRET_ARN"], os.environ["GITHUB_APP_PRIVATE_KEY_SECRET_KEY"])


class GitHubReadBroker:
    def __init__(self, config: BrokerConfig, secrets: SecretReader, signer: JwtSigner, http: HttpClient) -> None:
        self.config, self.secrets, self.signer, self.http = config, secrets, signer, http

    def execute(self, invocation: dict[str, Any]) -> dict[str, Any]:
        try:
            validate_tool_invocation(invocation)
        except ContractError as error:
            raise BrokerError("invalid_request") from error
        arguments = invocation["arguments"]
        repository = None if invocation["tool"] == "listRepositories" else f"{arguments['owner']}/{arguments['repo']}"
        token = self._installation_token(repository)
        try:
            result = self._read(invocation["tool"], arguments, token)
            validate_tool_response(result)
            return result
        except ContractError as error:
            raise BrokerError("invalid_response") from error
        finally:
            token = ""  # do not retain credentials beyond the request

    def _installation_token(self, repository: str | None) -> str:
        jwt_token = self.signer.sign(self.config.app_id, self.secrets.get_secret_string(self.config.private_key_secret_arn))
        headers = self._headers(jwt_token)
        request: dict[str, Any] = {"permissions": {"contents": "read"}}
        if repository is not None:
            request["repositories"] = [repository.rsplit("/", 1)[1]]
        status, body = self.http.request("POST", f"/app/installations/{self.config.installation_id}/access_tokens", headers, request)
        if status != 201 or not isinstance(body.get("token"), str):
            raise BrokerError("github_auth_failed")
        return body["token"]

    def _read(self, tool: str, arguments: dict[str, Any], token: str) -> dict[str, Any]:
        if tool == "listRepositories":
            page = arguments.get("page", 1)
            status, body = self.http.request("GET", f"/installation/repositories?per_page=100&page={page}", self._headers(token))
            repositories, total_count = body.get("repositories"), body.get("total_count")
            if status != 200 or not isinstance(repositories, list) or not isinstance(total_count, int):
                raise BrokerError("github_read_failed")
            try:
                return {
                    "tool": tool,
                    "repositories": [
                        {"owner": repository["owner"]["login"], "name": repository["name"], "private": repository["private"]}
                        for repository in repositories
                    ],
                    "page": page,
                    "total_count": total_count,
                    "has_more": page * 100 < total_count,
                }
            except (KeyError, TypeError) as error:
                raise BrokerError("github_read_failed") from error
        owner, repo = arguments["owner"], arguments["repo"]
        if tool == "getRepository":
            status, body = self.http.request("GET", f"/repos/{owner}/{repo}", self._headers(token))
            if status != 200:
                raise BrokerError("github_not_found" if status == 404 else "github_read_failed")
            return {"tool": tool, "repository": {"owner": body["owner"]["login"], "name": body["name"], "private": body["private"], "default_branch": body["default_branch"]}}
        path = urllib.parse.quote(arguments["path"], safe="/")
        suffix = "" if "ref" not in arguments else "?ref=" + urllib.parse.quote(arguments["ref"], safe="")
        status, body = self.http.request("GET", f"/repos/{owner}/{repo}/contents/{path}{suffix}", self._headers(token))
        if status != 200 or body.get("type") != "file" or body.get("encoding") != "base64":
            raise BrokerError("github_not_found" if status == 404 else "github_read_failed")
        try:
            encoded_content = "".join(body["content"].split())
            content = base64.b64decode(encoded_content, validate=True).decode("utf-8")
        except (KeyError, ValueError, UnicodeDecodeError) as error:
            raise BrokerError("unsupported_file") from error
        return {"tool": tool, "file": {"path": arguments["path"], "ref": arguments.get("ref", body.get("sha", "")), "content": content}}

    @staticmethod
    def _headers(token: str) -> dict[str, str]:
        return {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}", "User-Agent": USER_AGENT, "X-GitHub-Api-Version": API_VERSION}
