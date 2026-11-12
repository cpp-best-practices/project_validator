"""The Terraform profile's rules, judged by the generic checks in a Terraform project."""

from __future__ import annotations

import json
import unittest

from project_validator.checks.code_formatting import code_formatting
from project_validator.checks.committed_artifacts import committed_artifacts
from project_validator.checks.dependency_management import dependency_management
from project_validator.checks.platform_matrix import platform_matrix
from project_validator.checks.security_scanning import security_scanning
from project_validator.checks.static_analysis import static_analysis
from project_validator.checks.tests_run import tests_run
from project_validator.checks.vcs_ignore import vcs_ignore
from project_validator.core import Check, Result, Status
from project_validator.ecosystems.terraform import TERRAFORM_ECOSYSTEM
from tests.support import GITHUB_WORKFLOW, github_job, github_steps, make_context, run_as, temp_project, uses

PROVIDERS = {
    "main.tf": 'terraform {\n  required_providers {\n    random = { source = "hashicorp/random" }\n  }\n}\n',
}
LOCKFILE = {".terraform.lock.hcl": 'provider "registry.terraform.io/hashicorp/random" {\n  version = "3.6.3"\n}\n'}
TEST_FILE = {"tests/name.tftest.hcl": 'run "plans" {\n  command = plan\n}\n'}
PRE_COMMIT = {
    ".pre-commit-config.yaml": (
        "repos:\n  - repo: https://github.com/antonbabenko/pre-commit-terraform\n    rev: v1.96.1\n"
        "    hooks:\n      - id: terraform_fmt\n      - id: terraform_validate\n      - id: terraform_trivy\n"
    )
}


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


def _action(name: str, **inputs: str) -> dict[str, str]:
    step = {"uses": name, "with": inputs} if inputs else {"uses": name}
    return {GITHUB_WORKFLOW: json.dumps({"jobs": {"scan": {"runs-on": "ubuntu-latest", "steps": [step]}}})}


class RecognitionTests(unittest.TestCase):
    def test_configuration_variables_and_hcl_files_are_terraform(self) -> None:
        files = {"main.tf": "", "extra.tofu": "", "prod.tfvars": "", "tests/a.tftest.hcl": "", "x.hcl": ""}
        with temp_project(files) as root:
            structure = make_context(root).structure
        self.assertEqual(structure.languages, frozenset({"Terraform"}))
        self.assertEqual(structure.unrecognised_suffixes, ())
        self.assertEqual(structure.build_systems, frozenset())

    def test_hcl_alone_is_not_terraform(self) -> None:
        with temp_project({"packer.pkr.hcl": "", "README.md": ""}) as root:
            structure = make_context(root).structure
        self.assertEqual(structure.languages, frozenset())
        self.assertIn(".hcl", dict(structure.unrecognised_suffixes))


class TerraformTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_as(self, selected, files, TERRAFORM_ECOSYSTEM)

    def test_fmt_check_enforces_the_formatting_and_plain_fmt_does_not(self) -> None:
        for command in ("terraform fmt -check -recursive", "tofu fmt -check"):
            with self.subTest(command=command):
                self.assertEqual(self._run(code_formatting, _ci(command)).status, Status.PASS)
        self.assertEqual(self._run(code_formatting, _ci("terraform fmt -recursive")).status, Status.FAIL)

    def test_the_pre_commit_terraform_hooks_count(self) -> None:
        files = {**PRE_COMMIT, **_ci("pre-commit run --all-files")}
        self.assertEqual(self._run(code_formatting, files).status, Status.PASS)
        self.assertEqual(self._run(static_analysis, files).status, Status.PASS)
        self.assertEqual(self._run(security_scanning, files).status, Status.PASS)

    def test_validate_tflint_and_the_scanners_are_static_analysis(self) -> None:
        for command in ("terraform init -backend=false && terraform validate", "tofu validate", "checkov -d ."):
            with self.subTest(command=command):
                self.assertEqual(self._run(static_analysis, _ci(command)).status, Status.PASS)
        with_rules = {".tflint.hcl": 'plugin "aws" {\n  enabled = true\n}\n', **_ci("tflint --init", "tflint")}
        self.assertEqual(self._run(static_analysis, with_rules), Result.passed("tflint (.tflint.hcl) runs"))
        self.assertEqual(self._run(static_analysis, _ci("tflint")), Result.passed("tflint runs"))
        self.assertEqual(self._run(static_analysis, _ci("terraform init", "terraform plan")).status, Status.FAIL)

    def test_a_misconfiguration_scanner_is_security_scanning(self) -> None:
        commands = (
            "checkov -d .",
            "trivy config .",
            "trivy fs --scanners vuln,misconfig .",
            "kics scan -p .",
            "terrascan scan",
            "tfsec .",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(self._run(security_scanning, _ci(command)).status, Status.PASS)
        for command in ("trivy fs .", "trivy image app:latest", "terraform validate"):
            with self.subTest(command=command):
                self.assertEqual(self._run(security_scanning, _ci(command)).status, Status.WARN)

    def test_the_scanners_actions_run_them(self) -> None:
        actions = (
            _action("bridgecrewio/checkov-action@v12", directory="infra"),
            _action("aquasecurity/trivy-action@0.28.0", **{"scan-type": "config", "scan-ref": "."}),
            _action("aquasecurity/trivy-action@0.28.0", **{"scan-type": "fs", "scanners": "misconfig,secret"}),
            _action("checkmarx/kics-github-action@v2"),
            _action("tenable/terrascan-action@v1"),
            _action("aquasecurity/tfsec-action@v1"),
        )
        for files in actions:
            with self.subTest(action=files[GITHUB_WORKFLOW]):
                self.assertEqual(self._run(security_scanning, files).status, Status.PASS)
        # trivy's default scan type is an image, which does not read the configuration.
        self.assertEqual(self._run(security_scanning, _action("aquasecurity/trivy-action@0.28.0")).status, Status.WARN)

    def test_terraform_test_runs_the_tftest_files(self) -> None:
        self.assertEqual(self._run(tests_run, {**TEST_FILE, **_ci("terraform test")}).status, Status.PASS)
        tofu = {"tests/a.tofutest.hcl": "", **_ci("tofu test")}
        self.assertEqual(self._run(tests_run, tofu).status, Status.PASS)
        self.assertEqual(self._run(tests_run, _ci("terraform test")).status, Status.FAIL)
        # Tests that CI never runs.
        self.assertEqual(self._run(tests_run, {**TEST_FILE, **_ci("terraform plan")}).status, Status.WARN)

    def test_providers_are_locked_by_the_lockfile(self) -> None:
        self.assertEqual(self._run(dependency_management, {**PROVIDERS, **LOCKFILE}).status, Status.PASS)
        self.assertEqual(self._run(dependency_management, PROVIDERS).status, Status.WARN)
        implied = {"main.tf": 'provider "aws" {\n  region = "eu-west-1"\n}\n'}
        self.assertEqual(self._run(dependency_management, implied).status, Status.WARN)
        no_providers = {"main.tf": 'variable "name" {\n  type = string\n}\n'}
        self.assertEqual(self._run(dependency_management, no_providers).status, Status.PASS)

    def test_the_ignore_rules_keep_out_the_init_directory_and_the_state(self) -> None:
        ignoring = {".gitignore": "**/.terraform/*\n*.tfstate\n*.tfstate.*\n*.tfplan\ncrash.log\n"}
        self.assertEqual(self._run(vcs_ignore, ignoring).status, Status.PASS)
        result = self._run(vcs_ignore, {".gitignore": ".terraform/\n"})
        self.assertEqual(result.status, Status.WARN)
        self.assertIn("state", result.message)

    def test_a_committed_state_file_fails(self) -> None:
        for path in ("terraform.tfstate", "env/prod.tfstate.backup", "plan.tfplan", "crash.log"):
            with self.subTest(path=path):
                self.assertEqual(self._run(committed_artifacts, {path: ""}).status, Status.FAIL)
        self.assertEqual(self._run(committed_artifacts, {"terraform.tfvars": ""}).status, Status.PASS)

    def test_terraform_versions_are_the_toolchain_axis(self) -> None:
        job = {
            "runs-on": "${{ matrix.os }}",
            "strategy": {"matrix": {"os": ["ubuntu-latest", "windows-latest"], "tf": ["1.9.8", "1.10.3"]}},
            "steps": [
                {"uses": "hashicorp/setup-terraform@v3", "with": {"terraform_version": "${{ matrix.tf }}"}},
                {"run": "terraform validate"},
            ],
        }
        files = {GITHUB_WORKFLOW: json.dumps({"jobs": {"validate": job}})}
        result = self._run(platform_matrix, files)
        self.assertEqual(result.status, Status.PASS)
        self.assertIn("2 Terraform version(s) (1.10.3, 1.9.8)", result.message)

    def test_opentofu_and_the_images_name_versions_too(self) -> None:
        job = github_steps("uses: opentofu/setup-opentofu@v1", "run: tofu validate")
        versions = TERRAFORM_ECOSYSTEM.toolchain.versions if TERRAFORM_ECOSYSTEM.toolchain else ()
        for text in ("tofu_version: 1.8.0", "image: hashicorp/terraform:1.9.8", "ghcr.io/opentofu/opentofu:1.8.1"):
            with self.subTest(text=text):
                self.assertTrue(any(found.search(text) for found in versions))
        self.assertTrue(uses(TERRAFORM_ECOSYSTEM, job[GITHUB_WORKFLOW]))
        self.assertTrue(uses(TERRAFORM_ECOSYSTEM, "checkov -d ."))
        self.assertFalse(uses(TERRAFORM_ECOSYSTEM, "npm test"))
