"""Offline reconciliation tests with fake SSM and Slack API clients."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest
from urllib.parse import parse_qs, urlparse

import yaml

from clients.slack.reconciliation import (
    AdoptionRequired,
    ParameterPaths,
    ReconciliationError,
    SSM_KEY_ID,
    SSM_STANDARD_VALUE_BYTES,
    SlackReconciler,
)
from contracts.slack_oauth_state import verify_state


ROOT = Path(__file__).parents[1]
SPEC = yaml.safe_load((ROOT / "agents/github-assistant/agent.yaml").read_text(encoding="utf-8"))
PATHS = ParameterPaths("/slack/provisioner", "/slack/agents/github-assistant/binding", "/slack/agents/github-assistant/credentials")
REDIRECT_URI = "https://callback.example/slack/oauth/callback"
EVENTS_URL = "https://events.example/slack/events"


class FakeParameters:
    def __init__(self, values: dict[str, str] | None = None, *, fail_binding: bool = False) -> None:
        self.values = values or {}
        self.calls: list[tuple[str, str, dict[str, str], str, str | None]] = []
        self.reads: list[tuple[str, bool]] = []
        self.fail_binding = fail_binding

    def get(self, name: str, *, decrypt: bool) -> str | None:
        self.reads.append((name, decrypt))
        self.calls.append(("get", name, {}, "", None))
        return self.values.get(name)

    def put_secure_json(self, name: str, value: dict[str, str]) -> None:
        self.calls.append(("put", name, dict(value), "SecureString", SSM_KEY_ID))
        self.values[name] = json.dumps(value)

    def put_binding(self, name: str, value: dict[str, str]) -> None:
        if self.fail_binding:
            raise RuntimeError("injected")
        self.calls.append(("put", name, dict(value), "String", None))
        self.values[name] = json.dumps(value)


class FakeSlack:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.create_response: dict[str, object] = {
            "app_id": "A123",
            "credentials": {"client_id": "client", "client_secret": "client-secret", "signing_secret": "signing-secret"},
        }

    def rotate_configuration_token(self, refresh_token: str) -> dict[str, str]:
        self.calls.append(("rotate", refresh_token))
        return {"token": "config-token-new", "refresh_token": "config-refresh-new", "team_id": "T1"}

    def create_manifest(self, configuration_token: str, manifest: dict[str, object]) -> dict[str, object]:
        self.calls.append(("create", configuration_token, manifest))
        return self.create_response

    def update_manifest(self, configuration_token: str, app_id: str, manifest: dict[str, object]) -> dict[str, object]:
        self.calls.append(("update", configuration_token, app_id, manifest))
        return {"app_id": app_id}

    def exchange_oauth_code(self, client_id: str, client_secret: str, code: str, redirect_uri: str) -> dict[str, object]:
        self.calls.append(("oauth", client_id, client_secret, code, redirect_uri))
        return {"app_id": "A123", "team": {"id": "T1"}, "access_token": "bot-token"}


def initial_values() -> dict[str, str]:
    return {PATHS.provisioner: json.dumps({"token": "config-token-old", "refresh_token": "config-refresh-old"})}


class SlackReconciliationTests(unittest.TestCase):
    def reconciler(self, parameters: FakeParameters, slack: FakeSlack | None = None) -> SlackReconciler:
        return SlackReconciler(parameters, slack, now=lambda: "2026-08-04T12:00:00Z")

    def test_plan_creates_first_binding_without_secrets(self) -> None:
        parameters = FakeParameters(initial_values())
        plan = self.reconciler(parameters).plan(SPEC, "T1", PATHS, REDIRECT_URI, EVENTS_URL)
        self.assertEqual(plan.action, "create")
        self.assertIsNone(plan.app_id)
        self.assertNotIn("config-token-old", json.dumps(plan.safe_output()))

    def test_apply_creates_once_rotates_pair_and_emits_a_signed_install_url(self) -> None:
        parameters = FakeParameters(initial_values())
        slack = FakeSlack()
        result = self.reconciler(parameters, slack).apply(SPEC, "T1", PATHS, REDIRECT_URI, EVENTS_URL)

        self.assertEqual(result.plan.action, "create")
        self.assertEqual(result.plan.app_id, "A123")
        self.assertEqual([call[0] for call in slack.calls], ["rotate", "create"])
        provisioner_writes = [call for call in parameters.calls if call[0] == "put" and call[1] == PATHS.provisioner]
        self.assertEqual(provisioner_writes[0][2], {"token": "config-token-new", "refresh_token": "config-refresh-new"})
        self.assertEqual(provisioner_writes[0][3:], ("SecureString", SSM_KEY_ID))
        credentials = json.loads(parameters.values[PATHS.credentials])
        self.assertEqual(set(credentials), {"client_id", "client_secret", "signing_secret", "state_signing_key"})
        self.assertEqual(credentials["client_id"], "client")
        self.assertEqual(credentials["client_secret"], "client-secret")
        self.assertEqual(credentials["signing_secret"], "signing-secret")
        self.assertEqual(len(credentials["state_signing_key"]), 64)
        binding = json.loads(parameters.values[PATHS.binding])
        self.assertEqual(binding["agent_name"], "github-assistant")
        self.assertEqual(binding["workspace_id"], "T1")
        self.assertEqual(binding["app_id"], "A123")
        self.assertEqual(binding["installation_state"], "approval_required")
        self.assertNotIn("client-secret", json.dumps(result.safe_output()))
        self.assertNotIn("client-secret", result.install_url)
        self.assertNotIn(credentials["state_signing_key"], result.install_url)

        parsed = urlparse(result.install_url)
        self.assertEqual(f"{parsed.scheme}://{parsed.netloc}{parsed.path}", "https://slack.com/oauth/v2/authorize")
        query = parse_qs(parsed.query)
        self.assertEqual(query["client_id"], ["client"])
        self.assertEqual(query["redirect_uri"], [REDIRECT_URI])
        self.assertIn("app_mentions:read", query["scope"][0])
        state = verify_state(query["state"][0], signing_key=credentials["state_signing_key"], workspace_id="T1", app_id="A123", redirect_uri=REDIRECT_URI)
        self.assertEqual(state.agent_name, "github-assistant")

    def test_second_apply_updates_recorded_app_and_preserves_bot_credentials(self) -> None:
        values = initial_values()
        values[PATHS.credentials] = json.dumps({"client_id": "client", "client_secret": "client-secret", "signing_secret": "signing-secret", "state_signing_key": "s" * 64, "bot_token": "bot"})
        values[PATHS.binding] = json.dumps({"agent_name": "github-assistant", "workspace_id": "T1", "app_id": "A123", "manifest_digest": "old", "installation_state": "installed", "last_successful_reconcile_at": "2026-08-03T00:00:00Z", "bot_user_id": "U123", "granted_scopes": "app_mentions:read,chat:write"})
        parameters = FakeParameters(values)
        slack = FakeSlack()
        result = self.reconciler(parameters, slack).apply(SPEC, "T1", PATHS, REDIRECT_URI, EVENTS_URL)

        self.assertEqual(result.plan.action, "update")
        self.assertIsNone(result.install_url)
        self.assertEqual([call[0] for call in slack.calls], ["rotate", "update"])
        self.assertEqual(slack.calls[1][2], "A123")
        self.assertEqual(json.loads(parameters.values[PATHS.credentials])["bot_token"], "bot")
        updated_binding = json.loads(parameters.values[PATHS.binding])
        self.assertEqual(updated_binding["bot_user_id"], "U123")
        self.assertEqual(updated_binding["granted_scopes"], "app_mentions:read,chat:write")

    def test_manifest_update_removes_the_legacy_app_credential_and_marks_the_bot_installed(self) -> None:
        values = initial_values()
        legacy_key = "app_token"
        values[PATHS.credentials] = json.dumps(
            {
                "client_id": "client",
                "client_secret": "client-secret",
                "signing_secret": "signing-secret",
                "state_signing_key": "s" * 64,
                "bot_token": "bot",
                legacy_key: "legacy",
            }
        )
        values[PATHS.binding] = json.dumps(
            {
                "agent_name": "github-assistant",
                "workspace_id": "T1",
                "app_id": "A123",
                "manifest_digest": "old",
                "installation_state": "legacy_ready",
                "last_successful_reconcile_at": "2026-08-03T00:00:00Z",
            }
        )
        parameters = FakeParameters(values)
        result = self.reconciler(parameters, FakeSlack()).apply(SPEC, "T1", PATHS, REDIRECT_URI, EVENTS_URL)

        self.assertEqual(result.plan.installation_state, "installed")
        self.assertNotIn(legacy_key, json.loads(parameters.values[PATHS.credentials]))

    def test_update_migrates_existing_app_to_signed_oauth_state_before_manifest_change(self) -> None:
        values = initial_values()
        values[PATHS.credentials] = json.dumps(
            {
                "client_id": "client",
                "client_secret": "client-secret",
                "signing_secret": "signing-secret",
                "bot_token": "bot",
            }
        )
        values[PATHS.binding] = json.dumps(
            {
                "agent_name": "github-assistant",
                "workspace_id": "T1",
                "app_id": "A123",
                "manifest_digest": "old",
                "installation_state": "installed",
                "last_successful_reconcile_at": "2026-08-03T00:00:00Z",
            }
        )
        parameters = FakeParameters(values)
        slack = FakeSlack()

        self.reconciler(parameters, slack).apply(SPEC, "T1", PATHS, REDIRECT_URI, EVENTS_URL)

        credentials = json.loads(parameters.values[PATHS.credentials])
        self.assertEqual(len(credentials["state_signing_key"]), 64)
        self.assertEqual(credentials["bot_token"], "bot")
        state_key_write = next(
            call for call in parameters.calls if call[0] == "put" and call[1] == PATHS.credentials
        )
        update_index = next(index for index, call in enumerate(slack.calls) if call[0] == "update")
        self.assertEqual(state_key_write[3:], ("SecureString", SSM_KEY_ID))
        self.assertEqual(update_index, 1)

    def test_identical_manifest_is_a_noop_without_decrypting_credentials_or_calling_slack(self) -> None:
        created_parameters = FakeParameters(initial_values())
        slack = FakeSlack()
        created = self.reconciler(created_parameters, slack).apply(SPEC, "T1", PATHS, REDIRECT_URI, EVENTS_URL)
        values = dict(created_parameters.values)
        parameters = FakeParameters(values)
        plan = self.reconciler(parameters).plan(SPEC, "T1", PATHS, REDIRECT_URI, EVENTS_URL)
        self.assertEqual(plan.action, "noop")
        self.assertEqual(parameters.reads, [(PATHS.binding, False), (PATHS.credentials, False)])
        result = self.reconciler(parameters, slack).apply(SPEC, "T1", PATHS, REDIRECT_URI, EVENTS_URL)
        self.assertEqual(result.plan.action, "noop")
        self.assertEqual([call[0] for call in slack.calls], ["rotate", "create"])

    def test_existing_credentials_without_binding_stop_for_exact_adoption(self) -> None:
        values = initial_values()
        values[PATHS.credentials] = json.dumps({"client_id": "client", "client_secret": "client-secret", "signing_secret": "signing-secret"})
        parameters = FakeParameters(values)
        with self.assertRaises(AdoptionRequired):
            self.reconciler(parameters).plan(SPEC, "T1", PATHS, REDIRECT_URI, EVENTS_URL)
        plan = self.reconciler(parameters).plan(SPEC, "T1", PATHS, REDIRECT_URI, EVENTS_URL, adopt_app_id="A456")
        self.assertEqual(plan.action, "adopt")
        self.assertEqual(plan.app_id, "A456")

    def test_corrupt_binding_requires_exact_adoption_not_display_name_lookup(self) -> None:
        values = initial_values()
        values[PATHS.binding] = "not-json"
        parameters = FakeParameters(values)
        with self.assertRaises(AdoptionRequired):
            self.reconciler(parameters).plan(SPEC, "T1", PATHS, REDIRECT_URI, EVENTS_URL)
        plan = self.reconciler(parameters).plan(SPEC, "T1", PATHS, REDIRECT_URI, EVENTS_URL, adopt_app_id="A900")
        self.assertEqual((plan.action, plan.app_id), ("adopt", "A900"))

    def test_workspace_mismatch_allows_only_deliberate_exact_id_adoption(self) -> None:
        values = initial_values()
        values[PATHS.binding] = json.dumps({"agent_name": "github-assistant", "workspace_id": "T2", "app_id": "A123", "manifest_digest": "old", "installation_state": "installed", "last_successful_reconcile_at": "2026-08-03T00:00:00Z"})
        parameters = FakeParameters(values)
        with self.assertRaises(AdoptionRequired):
            self.reconciler(parameters).plan(SPEC, "T1", PATHS, REDIRECT_URI, EVENTS_URL)
        plan = self.reconciler(parameters).plan(SPEC, "T1", PATHS, REDIRECT_URI, EVENTS_URL, adopt_app_id="A321")
        self.assertEqual((plan.action, plan.app_id), ("adopt", "A321"))

    def test_create_binding_failure_requires_adoption_and_never_retries_create(self) -> None:
        parameters = FakeParameters(initial_values(), fail_binding=True)
        slack = FakeSlack()
        with self.assertRaises(AdoptionRequired):
            self.reconciler(parameters, slack).apply(SPEC, "T1", PATHS, REDIRECT_URI, EVENTS_URL)
        self.assertEqual([call[0] for call in slack.calls], ["rotate", "create"])
        self.assertIn(PATHS.credentials, parameters.values)

    def test_adoption_updates_exact_app_and_persists_binding(self) -> None:
        values = initial_values()
        values[PATHS.credentials] = json.dumps({"client_id": "client", "client_secret": "client-secret", "signing_secret": "signing-secret"})
        parameters = FakeParameters(values)
        slack = FakeSlack()
        result = self.reconciler(parameters, slack).apply(SPEC, "T1", PATHS, REDIRECT_URI, EVENTS_URL, adopt_app_id="A777")
        self.assertEqual(result.plan.action, "adopt")
        self.assertEqual(slack.calls[1][0:3], ("update", "config-token-new", "A777"))
        self.assertEqual(json.loads(parameters.values[PATHS.binding])["app_id"], "A777")

    def test_oauth_completion_updates_only_bot_credential_after_bound_identity_check(self) -> None:
        values = initial_values()
        values[PATHS.credentials] = json.dumps({"client_id": "client", "client_secret": "client-secret", "signing_secret": "signing-secret"})
        values[PATHS.binding] = json.dumps({"agent_name": "github-assistant", "workspace_id": "T1", "app_id": "A123", "manifest_digest": "digest", "installation_state": "approval_required", "last_successful_reconcile_at": "2026-08-03T00:00:00Z"})
        parameters = FakeParameters(values)
        slack = FakeSlack()
        binding = self.reconciler(parameters, slack).complete_oauth("T1", PATHS, "oauth-code", REDIRECT_URI)
        self.assertEqual(binding.installation_state, "installed")
        self.assertEqual(json.loads(parameters.values[PATHS.credentials])["bot_token"], "bot-token")
        self.assertEqual(slack.calls[0], ("oauth", "client", "client-secret", "oauth-code", REDIRECT_URI))

    def test_workspace_mismatch_and_token_response_mismatch_stop_before_manifest_mutation(self) -> None:
        parameters = FakeParameters(initial_values())
        slack = FakeSlack()
        slack.rotate_configuration_token = lambda _: {"token": "new", "refresh_token": "new-refresh", "team_id": "T2"}  # type: ignore[method-assign]
        with self.assertRaisesRegex(ReconciliationError, "workspace"):
            self.reconciler(parameters, slack).apply(SPEC, "T1", PATHS, REDIRECT_URI, EVENTS_URL)
        self.assertEqual(len(slack.calls), 0)

    def test_no_token_field_names_are_written_to_safe_plan_output(self) -> None:
        plan = self.reconciler(FakeParameters(initial_values())).plan(copy.deepcopy(SPEC), "T1", PATHS, REDIRECT_URI, EVENTS_URL)
        safe = json.dumps(plan.safe_output())
        self.assertNotIn("token", safe)
        self.assertNotIn("secret", safe)

    def test_standard_tier_size_limit_is_enforced_by_the_ssm_adapter(self) -> None:
        from clients.slack.reconciliation import _parameter_json

        with self.assertRaisesRegex(ReconciliationError, "Standard-tier"):
            _parameter_json({"token": "x" * SSM_STANDARD_VALUE_BYTES})


class InstallationUrlTests(unittest.TestCase):
    def reconciler(self, parameters: FakeParameters) -> SlackReconciler:
        return SlackReconciler(parameters, now=lambda: "2026-08-04T12:00:00Z")

    def applied(self) -> tuple[FakeParameters, dict[str, str]]:
        parameters = FakeParameters(initial_values())
        SlackReconciler(parameters, FakeSlack(), now=lambda: "2026-08-04T12:00:00Z").apply(SPEC, "T1", PATHS, REDIRECT_URI, EVENTS_URL)
        return parameters, json.loads(parameters.values[PATHS.credentials])

    def test_mints_a_fresh_url_without_any_slack_or_ssm_write(self) -> None:
        parameters, credentials = self.applied()
        writes_before = len(parameters.calls)
        url = self.reconciler(parameters).installation_url(SPEC, "T1", PATHS, REDIRECT_URI, EVENTS_URL)
        self.assertEqual(len(parameters.calls), writes_before + 2)  # binding + credentials reads only
        self.assertTrue(all(call[0] == "get" for call in parameters.calls[writes_before:]))
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        state = verify_state(query["state"][0], signing_key=credentials["state_signing_key"], workspace_id="T1", app_id="A123", redirect_uri=REDIRECT_URI)
        self.assertEqual(state.agent_name, "github-assistant")

    def test_each_call_mints_a_distinct_state(self) -> None:
        parameters, _ = self.applied()
        reconciler = self.reconciler(parameters)
        first = reconciler.installation_url(SPEC, "T1", PATHS, REDIRECT_URI, EVENTS_URL)
        second = reconciler.installation_url(SPEC, "T1", PATHS, REDIRECT_URI, EVENTS_URL)
        self.assertNotEqual(first, second)

    def test_rejects_a_redirect_uri_that_was_never_reconciled(self) -> None:
        parameters, _ = self.applied()
        with self.assertRaisesRegex(ReconciliationError, "not reconciled"):
            self.reconciler(parameters).installation_url(SPEC, "T1", PATHS, "https://different.example/callback", EVENTS_URL)

    def test_requires_an_existing_binding(self) -> None:
        parameters = FakeParameters(initial_values())
        with self.assertRaises(AdoptionRequired):
            self.reconciler(parameters).installation_url(SPEC, "T1", PATHS, REDIRECT_URI, EVENTS_URL)


if __name__ == "__main__":
    unittest.main()
