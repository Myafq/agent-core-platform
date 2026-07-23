import copy
import importlib.util
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = ROOT / "scripts" / "validate_github_contract.py"
OPENAPI_PATH = ROOT / "contracts" / "github" / "openapi.yaml"
WIRING_PATH = ROOT / "contracts" / "github" / "integration.yaml"

spec = importlib.util.spec_from_file_location("validate_github_contract", VALIDATOR_PATH)
validator = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(validator)


class GitHubContractTests(unittest.TestCase):
    def setUp(self):
        self.openapi = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
        self.wiring = yaml.safe_load(WIRING_PATH.read_text(encoding="utf-8"))

    def assertOpenAPIRejected(self, document):
        with self.assertRaises(ValueError):
            validator.validate_openapi(document)

    def assertWiringRejected(self, contract):
        with self.assertRaises(ValueError):
            validator.validate_wiring(contract)

    def test_contract_is_valid(self):
        validator.validate_openapi(self.openapi)
        validator.validate_wiring(self.wiring)

    def test_rejects_non_github_server(self):
        document = copy.deepcopy(self.openapi)
        document["servers"][0]["url"] = "https://example.invalid"
        self.assertOpenAPIRejected(document)

    def test_rejects_extra_paths_and_methods(self):
        document = copy.deepcopy(self.openapi)
        document["paths"]["/repos"] = {}
        self.assertOpenAPIRejected(document)

        document = copy.deepcopy(self.openapi)
        document["paths"]["/user"]["post"] = {}
        self.assertOpenAPIRejected(document)

    def test_rejects_changed_operation_id(self):
        document = copy.deepcopy(self.openapi)
        document["paths"]["/user"]["get"]["operationId"] = "listRepositories"
        self.assertOpenAPIRejected(document)

    def test_rejects_openapi_security_credentials(self):
        document = copy.deepcopy(self.openapi)
        document["components"]["securitySchemes"] = {"oauth": {"type": "oauth2"}}
        self.assertOpenAPIRejected(document)

        document = copy.deepcopy(self.openapi)
        document["paths"]["/user"]["get"]["headers"] = {"X-Token": {}}
        self.assertOpenAPIRejected(document)

    def test_rejects_scope_drift_and_repo_scope(self):
        contract = copy.deepcopy(self.wiring)
        contract["provider"]["scopes"] = ["read:org"]
        self.assertWiringRejected(contract)

        contract = copy.deepcopy(self.wiring)
        contract["provider"]["scopes"] = ["read:user", "repo"]
        self.assertWiringRejected(contract)

    def test_requires_post_consent_return_url_input(self):
        contract = copy.deepcopy(self.wiring)
        del contract["post_consent"]["return_url_input"]
        self.assertWiringRejected(contract)


if __name__ == "__main__":
    unittest.main()
