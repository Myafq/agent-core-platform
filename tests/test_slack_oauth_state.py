"""Signed OAuth state: roundtrip, tamper, expiry, and malformed-input tests."""

from __future__ import annotations

import json
import unittest

from contracts.slack_oauth_state import (
    DEFAULT_TTL_SECONDS,
    OAuthState,
    StateError,
    _b64url_encode,
    sign_state,
    unverified_agent_name,
    verify_state,
)


KEY = "a" * 32
OTHER_KEY = "b" * 32


def token(**overrides: object) -> str:
    fields = dict(
        agent_name="github-assistant",
        workspace_id="T0BKR092ATB",
        app_id="A0BMSFX33T5",
        redirect_uri="https://callback.example/slack/oauth/callback",
        signing_key=KEY,
    )
    fields.update(overrides)
    return sign_state(**fields)


class SignStateTests(unittest.TestCase):
    def test_rejects_invalid_agent_name(self) -> None:
        with self.assertRaisesRegex(StateError, "agent name"):
            token(agent_name="Not_Valid")

    def test_rejects_invalid_workspace_id(self) -> None:
        with self.assertRaisesRegex(StateError, "workspace id"):
            token(workspace_id="not-a-workspace")

    def test_rejects_invalid_app_id(self) -> None:
        with self.assertRaisesRegex(StateError, "app id"):
            token(app_id="not-an-app")

    def test_rejects_non_https_redirect_uri(self) -> None:
        with self.assertRaisesRegex(StateError, "redirect uri"):
            token(redirect_uri="http://callback.example/slack/oauth/callback")

    def test_rejects_short_signing_key(self) -> None:
        with self.assertRaisesRegex(StateError, "signing key"):
            token(signing_key="short")


class VerifyStateTests(unittest.TestCase):
    def test_valid_token_roundtrips(self) -> None:
        state = verify_state(token(), signing_key=KEY)
        self.assertEqual(
            state,
            OAuthState(
                agent_name="github-assistant",
                workspace_id="T0BKR092ATB",
                app_id="A0BMSFX33T5",
                redirect_uri="https://callback.example/slack/oauth/callback",
                issued_at=state.issued_at,
                expires_at=state.issued_at + DEFAULT_TTL_SECONDS,
            ),
        )

    def test_missing_state_is_rejected(self) -> None:
        with self.assertRaisesRegex(StateError, "malformed"):
            verify_state("", signing_key=KEY)

    def test_state_without_a_signature_separator_is_rejected(self) -> None:
        with self.assertRaisesRegex(StateError, "malformed"):
            verify_state("not-a-valid-token", signing_key=KEY)

    def test_non_base64_payload_is_rejected(self) -> None:
        # The signature is checked against the raw payload string before it is
        # ever base64-decoded, so a corrupt payload fails the signature check
        # first -- untrusted bytes are never parsed before authentication.
        with self.assertRaisesRegex(StateError, "signature"):
            verify_state("not!base64.also-not-base64", signing_key=KEY)

    def test_tampered_payload_fails_signature_check(self) -> None:
        raw = token()
        payload_b64, signature_b64 = raw.split(".")
        tampered_payload = json.loads(__import__("base64").urlsafe_b64decode(payload_b64 + "=="))
        tampered_payload["workspace_id"] = "TEVILWORKSPACE"
        tampered_b64 = _b64url_encode(json.dumps(tampered_payload, separators=(",", ":"), sort_keys=True).encode())
        with self.assertRaisesRegex(StateError, "signature"):
            verify_state(f"{tampered_b64}.{signature_b64}", signing_key=KEY)

    def test_tampered_signature_is_rejected(self) -> None:
        raw = token()
        payload_b64, signature_b64 = raw.split(".")
        flipped = signature_b64[:-1] + ("A" if signature_b64[-1] != "A" else "B")
        with self.assertRaisesRegex(StateError, "signature"):
            verify_state(f"{payload_b64}.{flipped}", signing_key=KEY)

    def test_wrong_signing_key_is_rejected(self) -> None:
        with self.assertRaisesRegex(StateError, "signature"):
            verify_state(token(), signing_key=OTHER_KEY)

    def test_expired_state_is_rejected(self) -> None:
        raw = token()
        with self.assertRaisesRegex(StateError, "expired"):
            verify_state(raw, signing_key=KEY, now=int(__import__("time").time()) + DEFAULT_TTL_SECONDS + 1)

    def test_not_yet_valid_state_is_rejected(self) -> None:
        raw = sign_state(
            agent_name="github-assistant",
            workspace_id="T0BKR092ATB",
            app_id="A0BMSFX33T5",
            redirect_uri="https://callback.example/slack/oauth/callback",
            signing_key=KEY,
            now=10_000,
        )
        with self.assertRaisesRegex(StateError, "malformed"):
            verify_state(raw, signing_key=KEY, now=9_000)

    def test_workspace_mismatch_is_rejected(self) -> None:
        with self.assertRaisesRegex(StateError, "workspace"):
            verify_state(token(), signing_key=KEY, workspace_id="TOTHERWORKSPC")

    def test_app_mismatch_is_rejected(self) -> None:
        with self.assertRaisesRegex(StateError, "app"):
            verify_state(token(), signing_key=KEY, app_id="AOTHERAPPXXXX")

    def test_redirect_uri_mismatch_is_rejected(self) -> None:
        with self.assertRaisesRegex(StateError, "redirect"):
            verify_state(token(), signing_key=KEY, redirect_uri="https://different.example/callback")

    def test_two_tokens_for_the_same_inputs_are_not_identical(self) -> None:
        self.assertNotEqual(token(), token())


class UnverifiedAgentNameTests(unittest.TestCase):
    def test_reads_agent_name_without_checking_signature(self) -> None:
        self.assertEqual(unverified_agent_name(token(signing_key=OTHER_KEY)), "github-assistant")

    def test_rejects_malformed_token(self) -> None:
        with self.assertRaisesRegex(StateError, "malformed"):
            unverified_agent_name("garbage")


if __name__ == "__main__":
    unittest.main()
