"""Offline reconciliation tests with fake SSM and Slack API clients."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

import yaml

from clients.slack.reconciliation import (
    AdoptionRequired,
    ParameterPaths,
    ReconciliationError,
    SSM_KEY_ID,
    SSM_STANDARD_VALUE_BYTES,
    SlackReconciler,
)


ROOT = Path(__file__).parents[1]
SPEC = yaml.safe_load((ROOT / "agents/github-assistant/agent.yaml").read_text(encoding="utf-8"))
PATHS = ParameterPaths("/slack/provisioner", "/slack/agents/github-assistant/binding", "/slack/agents/github-assistant/credentials")


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
            "oauth_authorize_url": "https://slack.example/install",
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

    def exchange_oauth_code(self, client_id: str, client_secret: str, code: str) -> dict[str, object]:
        self.calls.append(("oauth", client_id, client_secret, code))
        return {"app_id": "A123", "team": {"id": "T1"}, "access_token": "bot-token"}


def initial_values() -> dict[str, str]:
    return {PATHS.provisioner: json.dumps({"token": "config-token-old", "refresh_token": "config-refresh-old"})}


class SlackReconciliationTests(unittest.TestCase):
    def reconciler(self, parameters: FakeParameters, slack: FakeSlack | None = None) -> SlackReconciler:
        return SlackReconciler(parameters, slack, now=lambda: "2026-08-04T12:00:00Z")

    def test_plan_creates_first_binding_without_secrets(self) -> None:
        parameters = FakeParameters(initial_values())
        plan = self.reconciler(parameters).plan(SPEC, "T1", PATHS)
        self.assertEqual(plan.action, "create")
        self.assertIsNone(plan.app_id)
        self.assertNotIn("config-token-old", json.dumps(plan.safe_output()))

    def test_apply_creates_once_rotates_pair_and_emits_install_url(self) -> None:
        parameters = FakeParameters(initial_values())
        slack = FakeSlack()
        result = self.reconciler(parameters, slack).apply(SPEC, "T1", PATHS)

        self.assertEqual(result.plan.action, "create")
        self.assertEqual(result.plan.app_id, "A123")
        self.assertEqual(result.install_url, "https://slack.example/install")
        self.assertEqual([call[0] for call in slack.calls], ["rotate", "create"])
        provisioner_writes = [call for call in parameters.calls if call[0] == "put" and call[1] == PATHS.provisioner]
        self.assertEqual(provisioner_writes[0][2], {"token": "config-token-new", "refresh_token": "config-refresh-new"})
        self.assertEqual(provisioner_writes[0][3:], ("SecureString", SSM_KEY_ID))
        credentials = json.loads(parameters.values[PATHS.credentials])
        self.assertEqual(credentials, {"client_id": "client", "client_secret": "client-secret", "signing_secret": "signing-secret"})
        binding = json.loads(parameters.values[PATHS.binding])
        self.assertEqual(binding["agent_name"], "github-assistant")
        self.assertEqual(binding["workspace_id"], "T1")
        self.assertEqual(binding["app_id"], "A123")
        self.assertEqual(binding["installation_state"], "approval_required")
        self.assertNotIn("client-secret", json.dumps(result.safe_output()))

    def test_second_apply_updates_recorded_app_and_preserves_bot_credentials(self) -> None:
        values = initial_values()
        values[PATHS.credentials] = json.dumps({"client_id": "client", "client_secret": "client-secret", "signing_secret": "signing-secret", "bot_token": "bot", "app_token": "app"})
        values[PATHS.binding] = json.dumps({"agent_name": "github-assistant", "workspace_id": "T1", "app_id": "A123", "manifest_digest": "old", "installation_state": "installed", "last_successful_reconcile_at": "2026-08-03T00:00:00Z"})
        parameters = FakeParameters(values)
        slack = FakeSlack()
        result = self.reconciler(parameters, slack).apply(SPEC, "T1", PATHS)

        self.assertEqual(result.plan.action, "update")
        self.assertEqual([call[0] for call in slack.calls], ["rotate", "update"])
        self.assertEqual(slack.calls[1][2], "A123")
        self.assertEqual(json.loads(parameters.values[PATHS.credentials])["bot_token"], "bot")
        self.assertEqual(json.loads(parameters.values[PATHS.credentials])["app_token"], "app")

    def test_identical_manifest_is_a_noop_without_decrypting_credentials_or_calling_slack(self) -> None:
        created_parameters = FakeParameters(initial_values())
        slack = FakeSlack()
        created = self.reconciler(created_parameters, slack).apply(SPEC, "T1", PATHS)
        values = dict(created_parameters.values)
        parameters = FakeParameters(values)
        plan = self.reconciler(parameters).plan(SPEC, "T1", PATHS)
        self.assertEqual(plan.action, "noop")
        self.assertEqual(parameters.reads, [(PATHS.binding, False), (PATHS.credentials, False)])
        result = self.reconciler(parameters, slack).apply(SPEC, "T1", PATHS)
        self.assertEqual(result.plan.action, "noop")
        self.assertEqual([call[0] for call in slack.calls], ["rotate", "create"])

    def test_existing_credentials_without_binding_stop_for_exact_adoption(self) -> None:
        values = initial_values()
        values[PATHS.credentials] = json.dumps({"client_id": "client", "client_secret": "client-secret", "signing_secret": "signing-secret"})
        parameters = FakeParameters(values)
        with self.assertRaises(AdoptionRequired):
            self.reconciler(parameters).plan(SPEC, "T1", PATHS)
        plan = self.reconciler(parameters).plan(SPEC, "T1", PATHS, adopt_app_id="A456")
        self.assertEqual(plan.action, "adopt")
        self.assertEqual(plan.app_id, "A456")

    def test_corrupt_binding_requires_exact_adoption_not_display_name_lookup(self) -> None:
        values = initial_values()
        values[PATHS.binding] = "not-json"
        parameters = FakeParameters(values)
        with self.assertRaises(AdoptionRequired):
            self.reconciler(parameters).plan(SPEC, "T1", PATHS)
        plan = self.reconciler(parameters).plan(SPEC, "T1", PATHS, adopt_app_id="A900")
        self.assertEqual((plan.action, plan.app_id), ("adopt", "A900"))

    def test_workspace_mismatch_allows_only_deliberate_exact_id_adoption(self) -> None:
        values = initial_values()
        values[PATHS.binding] = json.dumps({"agent_name": "github-assistant", "workspace_id": "T2", "app_id": "A123", "manifest_digest": "old", "installation_state": "installed", "last_successful_reconcile_at": "2026-08-03T00:00:00Z"})
        parameters = FakeParameters(values)
        with self.assertRaises(AdoptionRequired):
            self.reconciler(parameters).plan(SPEC, "T1", PATHS)
        plan = self.reconciler(parameters).plan(SPEC, "T1", PATHS, adopt_app_id="A321")
        self.assertEqual((plan.action, plan.app_id), ("adopt", "A321"))

    def test_create_binding_failure_requires_adoption_and_never_retries_create(self) -> None:
        parameters = FakeParameters(initial_values(), fail_binding=True)
        slack = FakeSlack()
        with self.assertRaises(AdoptionRequired):
            self.reconciler(parameters, slack).apply(SPEC, "T1", PATHS)
        self.assertEqual([call[0] for call in slack.calls], ["rotate", "create"])
        self.assertIn(PATHS.credentials, parameters.values)

    def test_adoption_updates_exact_app_and_persists_binding(self) -> None:
        values = initial_values()
        values[PATHS.credentials] = json.dumps({"client_id": "client", "client_secret": "client-secret", "signing_secret": "signing-secret"})
        parameters = FakeParameters(values)
        slack = FakeSlack()
        result = self.reconciler(parameters, slack).apply(SPEC, "T1", PATHS, adopt_app_id="A777")
        self.assertEqual(result.plan.action, "adopt")
        self.assertEqual(slack.calls[1][0:3], ("update", "config-token-new", "A777"))
        self.assertEqual(json.loads(parameters.values[PATHS.binding])["app_id"], "A777")

    def test_oauth_completion_updates_only_bot_credential_after_bound_identity_check(self) -> None:
        values = initial_values()
        values[PATHS.credentials] = json.dumps({"client_id": "client", "client_secret": "client-secret", "signing_secret": "signing-secret", "app_token": "app"})
        values[PATHS.binding] = json.dumps({"agent_name": "github-assistant", "workspace_id": "T1", "app_id": "A123", "manifest_digest": "digest", "installation_state": "approval_required", "last_successful_reconcile_at": "2026-08-03T00:00:00Z"})
        parameters = FakeParameters(values)
        slack = FakeSlack()
        binding = self.reconciler(parameters, slack).complete_oauth("T1", PATHS, "oauth-code")
        self.assertEqual(binding.installation_state, "installed")
        self.assertEqual(json.loads(parameters.values[PATHS.credentials])["bot_token"], "bot-token")
        self.assertEqual(json.loads(parameters.values[PATHS.credentials])["app_token"], "app")
        self.assertEqual(slack.calls[0], ("oauth", "client", "client-secret", "oauth-code"))

    def test_app_token_update_preserves_existing_credentials_without_api_call(self) -> None:
        values = initial_values()
        values[PATHS.credentials] = json.dumps({"client_id": "client", "client_secret": "client-secret", "signing_secret": "signing-secret", "bot_token": "bot"})
        values[PATHS.binding] = json.dumps({"agent_name": "github-assistant", "workspace_id": "T1", "app_id": "A123", "manifest_digest": "digest", "installation_state": "installed", "last_successful_reconcile_at": "2026-08-03T00:00:00Z"})
        parameters = FakeParameters(values)
        binding = self.reconciler(parameters).set_app_token("T1", PATHS, "app-token")
        self.assertEqual(binding.app_id, "A123")
        self.assertEqual(binding.installation_state, "socket_mode_ready")
        self.assertEqual(json.loads(parameters.values[PATHS.credentials])["app_token"], "app-token")

    def test_workspace_mismatch_and_token_response_mismatch_stop_before_manifest_mutation(self) -> None:
        parameters = FakeParameters(initial_values())
        slack = FakeSlack()
        slack.rotate_configuration_token = lambda _: {"token": "new", "refresh_token": "new-refresh", "team_id": "T2"}  # type: ignore[method-assign]
        with self.assertRaisesRegex(ReconciliationError, "workspace"):
            self.reconciler(parameters, slack).apply(SPEC, "T1", PATHS)
        self.assertEqual(len(slack.calls), 0)

    def test_no_token_field_names_are_written_to_safe_plan_output(self) -> None:
        plan = self.reconciler(FakeParameters(initial_values())).plan(copy.deepcopy(SPEC), "T1", PATHS)
        safe = json.dumps(plan.safe_output())
        self.assertNotIn("token", safe)
        self.assertNotIn("secret", safe)

    def test_standard_tier_size_limit_is_enforced_by_the_ssm_adapter(self) -> None:
        from clients.slack.reconciliation import _parameter_json

        with self.assertRaisesRegex(ReconciliationError, "Standard-tier"):
            _parameter_json({"token": "x" * SSM_STANDARD_VALUE_BYTES})


if __name__ == "__main__":
    unittest.main()
