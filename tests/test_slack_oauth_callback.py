"""Offline tests for the public Slack OAuth callback: fakes for Slack and SSM."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from contracts.slack_oauth_state import sign_state
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "containers" / "slack-oauth-callback" / "service"))

from slack_oauth_callback.callback import (
    CallbackConfig,
    CallbackError,
    InstallationResult,
    complete_installation,
)
from slack_oauth_callback import handler as handler_module


AGENT = "github-assistant"
WORKSPACE = "T0BKR092ATB"
APP_ID = "A0BMSFX33T5"
REDIRECT_URI = "https://callback.example/slack/oauth/callback"
SIGNING_KEY = "k" * 32
BINDING_PATH = f"/agent-core/slack/agents/{AGENT}/binding"
CREDENTIALS_PATH = f"/agent-core/slack/agents/{AGENT}/credentials"


def binding(**overrides: str) -> dict[str, str]:
    fields = {
        "agent_name": AGENT,
        "workspace_id": WORKSPACE,
        "app_id": APP_ID,
        "manifest_digest": "digest",
        "installation_state": "approval_required",
        "last_successful_reconcile_at": "2026-08-01T00:00:00Z",
    }
    fields.update(overrides)
    return fields


def credentials(**overrides: str) -> dict[str, str]:
    fields = {
        "client_id": "client",
        "client_secret": "client-secret",
        "signing_secret": "signing-secret",
        "state_signing_key": SIGNING_KEY,
    }
    fields.update(overrides)
    return fields


def valid_state(**overrides: object) -> str:
    fields = dict(agent_name=AGENT, workspace_id=WORKSPACE, app_id=APP_ID, redirect_uri=REDIRECT_URI, signing_key=SIGNING_KEY)
    fields.update(overrides)
    return sign_state(**fields)


class FakeParameters:
    def __init__(self, values: dict[str, str] | None = None, *, fail_credentials: bool = False, fail_binding: bool = False) -> None:
        self.values = values or {}
        self.puts: list[tuple[str, dict[str, str], str]] = []
        self.reads: list[tuple[str, bool]] = []
        self.fail_credentials = fail_credentials
        self.fail_binding = fail_binding

    def get(self, name: str, *, decrypt: bool) -> str | None:
        self.reads.append((name, decrypt))
        return self.values.get(name)

    def put_secure_json(self, name: str, value: dict[str, str]) -> None:
        if self.fail_credentials:
            raise RuntimeError("injected")
        self.puts.append((name, dict(value), "SecureString"))
        self.values[name] = json.dumps(value)

    def put_binding(self, name: str, value: dict[str, str]) -> None:
        if self.fail_binding:
            raise RuntimeError("injected")
        self.puts.append((name, dict(value), "String"))
        self.values[name] = json.dumps(value)


def default_parameters(**overrides: str) -> FakeParameters:
    values = {BINDING_PATH: json.dumps(binding()), CREDENTIALS_PATH: json.dumps(credentials())}
    values.update(overrides)
    return FakeParameters(values)


class FakeOAuth:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[tuple[str, str, str, str]] = []

    def exchange(self, client_id: str, client_secret: str, code: str, redirect_uri: str) -> dict[str, object]:
        self.calls.append((client_id, client_secret, code, redirect_uri))
        response = self.response(len(self.calls)) if callable(self.response) else self.response
        return response


def success_response(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "ok": True,
        "app_id": APP_ID,
        "team": {"id": WORKSPACE},
        "access_token": "xoxb-super-secret",
        "bot_user_id": "U0BOTUSER",
        "scope": "chat:write,app_mentions:read",
    }
    fields.update(overrides)
    return fields


def config() -> CallbackConfig:
    return CallbackConfig(workspace_id=WORKSPACE, redirect_uri=REDIRECT_URI)


class CompleteInstallationTests(unittest.TestCase):
    def test_successful_installation_persists_bot_token_and_marks_binding_installed(self) -> None:
        parameters = default_parameters()
        oauth = FakeOAuth(success_response())
        result = complete_installation(
            {"code": "authorization-code", "state": valid_state()}, parameters, oauth, config(), now=lambda: "2026-08-04T12:00:00Z"
        )
        self.assertEqual(
            result,
            InstallationResult(
                agent_name=AGENT,
                workspace_id=WORKSPACE,
                app_id=APP_ID,
                bot_user_id="U0BOTUSER",
                granted_scopes=("chat:write", "app_mentions:read"),
                installed_at="2026-08-04T12:00:00Z",
            ),
        )
        self.assertEqual(oauth.calls, [("client", "client-secret", "authorization-code", REDIRECT_URI)])
        stored_credentials = json.loads(parameters.values[CREDENTIALS_PATH])
        self.assertEqual(stored_credentials["bot_token"], "xoxb-super-secret")
        self.assertNotIn("authorization-code", json.dumps(stored_credentials))
        stored_binding = json.loads(parameters.values[BINDING_PATH])
        self.assertEqual(stored_binding["installation_state"], "installed")
        self.assertEqual(stored_binding["bot_user_id"], "U0BOTUSER")
        self.assertEqual(stored_binding["granted_scopes"], "chat:write,app_mentions:read")
        self.assertEqual([put[2] for put in parameters.puts], ["SecureString", "String"])
        self.assertEqual(parameters.puts[0][0], CREDENTIALS_PATH)
        self.assertEqual(parameters.puts[1][0], BINDING_PATH)

    def test_writes_occur_only_after_the_slack_exchange_succeeds(self) -> None:
        parameters = default_parameters()
        oauth = FakeOAuth({"ok": False, "error": "invalid_code"})
        with self.assertRaises(CallbackError) as failure:
            complete_installation({"code": "bad-code", "state": valid_state()}, parameters, oauth, config())
        self.assertEqual(failure.exception.log_class, "exchange_failed")
        self.assertEqual(parameters.puts, [])

    def test_a_replayed_callback_after_a_successful_install_fails_without_corrupting_it(self) -> None:
        parameters = default_parameters()
        query = {"code": "authorization-code", "state": valid_state()}

        def responses(call_number: int) -> dict[str, object]:
            return success_response() if call_number == 1 else {"ok": False, "error": "invalid_code"}

        oauth = FakeOAuth(responses)
        first = complete_installation(query, parameters, oauth, config(), now=lambda: "2026-08-04T12:00:00Z")
        self.assertEqual(first.bot_user_id, "U0BOTUSER")
        snapshot = dict(parameters.values)

        with self.assertRaises(CallbackError) as failure:
            complete_installation(query, parameters, oauth, config(), now=lambda: "2026-08-04T12:05:00Z")
        self.assertEqual(failure.exception.log_class, "exchange_failed")
        self.assertEqual(parameters.values, snapshot)

    def test_missing_code_or_state_is_rejected(self) -> None:
        parameters = default_parameters()
        oauth = FakeOAuth(success_response())
        with self.assertRaises(CallbackError) as failure:
            complete_installation({"state": valid_state()}, parameters, oauth, config())
        self.assertEqual(failure.exception.log_class, "request_invalid")
        with self.assertRaises(CallbackError) as failure:
            complete_installation({"code": "abc"}, parameters, oauth, config())
        self.assertEqual(failure.exception.log_class, "request_invalid")
        self.assertEqual(oauth.calls, [])

    def test_known_slack_denial_is_classified_separately_from_other_errors(self) -> None:
        with self.assertRaises(CallbackError) as denied:
            complete_installation({"error": "access_denied"}, default_parameters(), FakeOAuth(success_response()), config())
        self.assertEqual(denied.exception.log_class, "user_denied")
        with self.assertRaises(CallbackError) as other:
            complete_installation({"error": "something_unexpected"}, default_parameters(), FakeOAuth(success_response()), config())
        self.assertEqual(other.exception.log_class, "provider_error")

    def test_malformed_state_is_rejected_before_any_ssm_read(self) -> None:
        parameters = default_parameters()
        with self.assertRaises(CallbackError) as failure:
            complete_installation({"code": "abc", "state": "not-a-real-token"}, parameters, FakeOAuth(success_response()), config())
        self.assertEqual(failure.exception.log_class, "state_malformed")
        self.assertEqual(parameters.reads, [])

    def test_unknown_agent_binding_is_rejected(self) -> None:
        parameters = FakeParameters({})
        with self.assertRaises(CallbackError) as failure:
            complete_installation({"code": "abc", "state": valid_state()}, parameters, FakeOAuth(success_response()), config())
        self.assertEqual(failure.exception.log_class, "binding_missing")

    def test_tampered_state_signature_is_rejected(self) -> None:
        parameters = default_parameters()
        state = valid_state(signing_key="x" * 32)
        with self.assertRaises(CallbackError) as failure:
            complete_installation({"code": "abc", "state": state}, parameters, FakeOAuth(success_response()), config())
        self.assertEqual(failure.exception.log_class, "state_invalid")

    def test_expired_state_is_rejected(self) -> None:
        parameters = default_parameters()
        state = valid_state(now=1, ttl_seconds=1)
        with self.assertRaises(CallbackError) as failure:
            complete_installation({"code": "abc", "state": state}, parameters, FakeOAuth(success_response()), config())
        self.assertEqual(failure.exception.log_class, "state_invalid")

    def test_state_bound_to_a_different_workspace_is_rejected(self) -> None:
        parameters = default_parameters()
        state = valid_state(workspace_id="TDIFFERENTWORK")
        with self.assertRaises(CallbackError) as failure:
            complete_installation({"code": "abc", "state": state}, parameters, FakeOAuth(success_response()), config())
        self.assertEqual(failure.exception.log_class, "state_invalid")

    def test_state_bound_to_a_different_app_than_the_binding_is_rejected(self) -> None:
        parameters = default_parameters()
        state = valid_state(app_id="ADIFFERENTAPPX")
        with self.assertRaises(CallbackError) as failure:
            complete_installation({"code": "abc", "state": state}, parameters, FakeOAuth(success_response()), config())
        self.assertEqual(failure.exception.log_class, "state_invalid")

    def test_slack_response_app_id_must_match_the_binding(self) -> None:
        parameters = default_parameters()
        oauth = FakeOAuth(success_response(app_id="ADIFFERENTAPPX"))
        with self.assertRaises(CallbackError) as failure:
            complete_installation({"code": "abc", "state": valid_state()}, parameters, oauth, config())
        self.assertEqual(failure.exception.log_class, "app_mismatch")
        self.assertEqual(parameters.puts, [])

    def test_slack_response_workspace_must_match_the_configured_workspace(self) -> None:
        parameters = default_parameters()
        oauth = FakeOAuth(success_response(team={"id": "TDIFFERENTWORK"}))
        with self.assertRaises(CallbackError) as failure:
            complete_installation({"code": "abc", "state": valid_state()}, parameters, oauth, config())
        self.assertEqual(failure.exception.log_class, "workspace_mismatch")
        self.assertEqual(parameters.puts, [])

    def test_missing_bot_token_fails_closed(self) -> None:
        parameters = default_parameters()
        response = success_response()
        del response["access_token"]
        oauth = FakeOAuth(response)
        with self.assertRaises(CallbackError) as failure:
            complete_installation({"code": "abc", "state": valid_state()}, parameters, oauth, config())
        self.assertEqual(failure.exception.log_class, "bot_token_missing")
        self.assertEqual(parameters.puts, [])

    def test_credentials_missing_state_signing_key_is_rejected(self) -> None:
        parameters = default_parameters()
        parameters.values[CREDENTIALS_PATH] = json.dumps({"client_id": "client", "client_secret": "client-secret", "signing_secret": "signing-secret"})
        with self.assertRaises(CallbackError) as failure:
            complete_installation({"code": "abc", "state": valid_state()}, parameters, FakeOAuth(success_response()), config())
        self.assertEqual(failure.exception.log_class, "signing_key_missing")

    def test_credentials_with_an_unknown_field_are_rejected(self) -> None:
        parameters = default_parameters()
        parameters.values[CREDENTIALS_PATH] = json.dumps({**credentials(), "unexpected_field": "value"})
        with self.assertRaises(CallbackError) as failure:
            complete_installation({"code": "abc", "state": valid_state()}, parameters, FakeOAuth(success_response()), config())
        self.assertEqual(failure.exception.log_class, "credentials_corrupt")

    def test_legacy_socket_token_is_removed_on_installation(self) -> None:
        parameters = default_parameters()
        parameters.values[CREDENTIALS_PATH] = json.dumps({**credentials(), "app_token": "legacy"})
        complete_installation(
            {"code": "abc", "state": valid_state()},
            parameters,
            FakeOAuth(success_response()),
            config(),
        )
        self.assertNotIn("app_token", json.loads(parameters.values[CREDENTIALS_PATH]))

    def test_binding_with_an_invalid_app_id_is_rejected(self) -> None:
        parameters = default_parameters()
        parameters.values[BINDING_PATH] = json.dumps(binding(app_id="not-an-app-id"))
        with self.assertRaises(CallbackError) as failure:
            complete_installation({"code": "abc", "state": valid_state()}, parameters, FakeOAuth(success_response()), config())
        self.assertEqual(failure.exception.log_class, "binding_corrupt")

    def test_ssm_paths_are_the_canonical_per_agent_hierarchy(self) -> None:
        parameters = default_parameters()
        complete_installation({"code": "abc", "state": valid_state()}, parameters, FakeOAuth(success_response()), config(), now=lambda: "t")
        self.assertEqual({name for name, _ in parameters.reads}, {BINDING_PATH, CREDENTIALS_PATH})
        self.assertEqual([name for name, _, _ in parameters.puts], [CREDENTIALS_PATH, BINDING_PATH])

    def test_credentials_write_failure_stops_before_binding_write(self) -> None:
        parameters = default_parameters(); parameters.fail_credentials = True
        with self.assertRaises(CallbackError) as failure:
            complete_installation({"code": "abc", "state": valid_state()}, parameters, FakeOAuth(success_response()), config())
        self.assertEqual(failure.exception.log_class, "credentials_write_failed")
        self.assertNotIn(BINDING_PATH, [p[0] for p in parameters.puts])

    def test_binding_write_failure_preserves_the_saved_bot_token(self) -> None:
        parameters = default_parameters(); parameters.fail_binding = True
        with self.assertRaises(CallbackError) as failure:
            complete_installation({"code": "abc", "state": valid_state()}, parameters, FakeOAuth(success_response()), config())
        self.assertEqual(failure.exception.log_class, "binding_write_failed")
        self.assertEqual(json.loads(parameters.values[CREDENTIALS_PATH])["bot_token"], "xoxb-super-secret")

    def test_config_rejects_a_non_https_redirect_uri(self) -> None:
        with patch.dict("os.environ", {"SLACK_WORKSPACE_ID": WORKSPACE, "SLACK_OAUTH_REDIRECT_URI": "http://insecure.example"}, clear=False):
            with self.assertRaises(CallbackError) as failure:
                CallbackConfig.from_environment()
            self.assertEqual(failure.exception.log_class, "config_invalid")

    def test_config_rejects_an_invalid_workspace_id(self) -> None:
        with patch.dict("os.environ", {"SLACK_WORKSPACE_ID": "not-a-workspace", "SLACK_OAUTH_REDIRECT_URI": REDIRECT_URI}, clear=False):
            with self.assertRaises(CallbackError) as failure:
                CallbackConfig.from_environment()
            self.assertEqual(failure.exception.log_class, "config_invalid")


class HandlerTests(unittest.TestCase):
    class FakeContext:
        aws_request_id = "req-123"

    def setUp(self) -> None:
        self._env_patch = patch.dict(
            "os.environ", {"SLACK_WORKSPACE_ID": WORKSPACE, "SLACK_OAUTH_REDIRECT_URI": REDIRECT_URI}, clear=False
        )
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)
        self._ssm_patch = patch("slack_oauth_callback.handler._ssm_client", return_value=object())
        self._ssm_patch.start()
        self.addCleanup(self._ssm_patch.stop)

    def test_success_renders_a_minimal_html_page_without_secrets(self) -> None:
        result = InstallationResult(AGENT, WORKSPACE, APP_ID, "U0BOTUSER", ("chat:write",), "2026-08-04T12:00:00Z")
        with patch("slack_oauth_callback.handler.complete_installation", return_value=result):
            response = handler_module.lambda_handler({"queryStringParameters": {"code": "c", "state": "s"}}, self.FakeContext())
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("text/html", response["headers"]["Content-Type"])
        self.assertIn("installed", response["body"].lower())
        for secret in ("xoxb", "client-secret", "signing-secret", SIGNING_KEY):
            self.assertNotIn(secret, response["body"])

    def test_callback_error_renders_the_safe_message_and_correlation_id_at_400(self) -> None:
        with patch(
            "slack_oauth_callback.handler.complete_installation",
            side_effect=CallbackError("This installation link is invalid.", log_class="state_invalid"),
        ):
            response = handler_module.lambda_handler({"queryStringParameters": {"code": "c", "state": "s"}}, self.FakeContext())
        self.assertEqual(response["statusCode"], 400)
        self.assertIn("This installation link is invalid.", response["body"])
        self.assertIn("req-123", response["body"])

    def test_unexpected_exception_renders_a_generic_500_without_leaking_details(self) -> None:
        with patch("slack_oauth_callback.handler.complete_installation", side_effect=RuntimeError("boom with secret xoxb-leak")):
            response = handler_module.lambda_handler({"queryStringParameters": {"code": "c", "state": "s"}}, self.FakeContext())
        self.assertEqual(response["statusCode"], 500)
        self.assertNotIn("boom", response["body"])
        self.assertNotIn("xoxb-leak", response["body"])

    def test_success_and_failure_logging_never_contains_the_raw_query_or_secrets(self) -> None:
        result = InstallationResult(AGENT, WORKSPACE, APP_ID, "U0BOTUSER", ("chat:write",), "2026-08-04T12:00:00Z")
        query = {"code": "super-secret-authorization-code", "state": "super-secret-state-token"}
        with self.assertLogs("slack_oauth_callback.handler", level="INFO") as captured:
            with patch("slack_oauth_callback.handler.complete_installation", return_value=result):
                handler_module.lambda_handler({"queryStringParameters": query}, self.FakeContext())
        joined = "\n".join(captured.output)
        self.assertNotIn("super-secret-authorization-code", joined)
        self.assertNotIn("super-secret-state-token", joined)
        self.assertIn("result=success", joined)

        with self.assertLogs("slack_oauth_callback.handler", level="WARNING") as captured:
            with patch(
                "slack_oauth_callback.handler.complete_installation",
                side_effect=CallbackError("This installation link is invalid.", log_class="state_invalid"),
            ):
                handler_module.lambda_handler({"queryStringParameters": query}, self.FakeContext())
        joined = "\n".join(captured.output)
        self.assertNotIn("super-secret-authorization-code", joined)
        self.assertNotIn("super-secret-state-token", joined)
        self.assertIn("state_invalid", joined)

    def test_non_dict_query_parameters_do_not_crash_the_handler(self) -> None:
        with patch(
            "slack_oauth_callback.handler.complete_installation",
            side_effect=CallbackError("This installation link is invalid or incomplete.", log_class="request_invalid"),
        ):
            response = handler_module.lambda_handler({}, self.FakeContext())
        self.assertEqual(response["statusCode"], 400)


if __name__ == "__main__":
    unittest.main()
