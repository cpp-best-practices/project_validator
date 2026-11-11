from __future__ import annotations

import json
import unittest
from collections.abc import Mapping

from project_validator.checks.dependency_audit import dependency_audit
from project_validator.core import Result, Status
from project_validator.ecosystems import C_FAMILY, Ecosystem
from project_validator.ecosystems.go import GO
from project_validator.ecosystems.python import PYTHON
from project_validator.ecosystems.rust import RUST
from project_validator.facts import Facts
from project_validator.facts.audit import AUDIT, RUNS
from project_validator.policy.audit import judge_audit
from project_validator.questions.tooling import tool_answer
from tests.support import CI_FILES, GITHUB_WORKFLOW, WELL_CONFIGURED_PYTHON, ci_running, github_job, run_as

ECOSYSTEMS = (PYTHON, RUST, GO)


def _steps(*steps: Mapping[str, object]) -> dict[str, str]:
    return {GITHUB_WORKFLOW: json.dumps({"jobs": {"audit": {"runs-on": "ubuntu-latest", "steps": list(steps)}}})}


class DependencyAuditTests(unittest.TestCase):
    def _run(self, ecosystem: Ecosystem, files: dict[str, str]) -> Result:
        return run_as(self, dependency_audit, files, ecosystem)

    def test_declares_the_languages_it_judges(self) -> None:
        # Profiles and plugins add languages, so only the stable ones are pinned.
        self.assertLessEqual({"Python", "Rust", "Go"}, dependency_audit.languages)
        # C and C++ have no common dependency manifest to audit.
        self.assertFalse(C_FAMILY & dependency_audit.languages)

    def test_each_ecosystems_auditor_counts(self) -> None:
        auditors = {
            PYTHON: {
                "pip-audit": {"run": "pip-audit -r requirements.txt"},
                "pip-audit action": {"uses": "pypa/gh-action-pip-audit@v1"},
                "safety": {"run": "safety scan"},
            },
            RUST: {
                "cargo audit": {"run": "cargo audit"},
                "audit action": {"uses": "rustsec/audit-check@v2"},
                "cargo deny": {"run": "cargo deny check"},
                "cargo deny advisories": {"run": "cargo deny --all-features check advisories"},
                "cargo deny action": {"uses": "EmbarkStudios/cargo-deny-action@v2"},
            },
            GO: {
                "govulncheck": {"run": "govulncheck ./..."},
                "pinned govulncheck": {"run": "go run golang.org/x/vuln/cmd/govulncheck@latest ./..."},
                "govulncheck action": {"uses": "golang/govulncheck-action@v1"},
            },
        }
        for ecosystem, commands in auditors.items():
            for name, command in commands.items():
                with self.subTest(ecosystem=ecosystem.label, tool=name):
                    result = self._run(ecosystem, _steps(command))
                    self.assertEqual(result.status, Status.PASS)

    def test_multi_ecosystem_scanners_count_for_every_ecosystem(self) -> None:
        steps = (
            {"run": "osv-scanner scan source -r ."},
            {"run": "trivy fs ."},
            {"run": "snyk test --all-projects"},
            {"uses": "google/osv-scanner-action/osv-scanner-action@v2"},
            {"uses": "aquasecurity/trivy-action@0.30.0", "with": {"scan-type": "fs"}},
            {"uses": "snyk/actions/python@v1"},
        )
        for step in steps:
            for ecosystem in ECOSYSTEMS:
                with self.subTest(step=step, ecosystem=ecosystem.label):
                    self.assertEqual(self._run(ecosystem, _steps(step)).status, Status.PASS)
        # trivy's action scans an image unless told to scan the file system.
        image = _steps({"uses": "aquasecurity/trivy-action@0.30.0", "with": {"image-ref": "app:latest"}})
        self.assertEqual(self._run(PYTHON, image).status, Status.WARN)

    def test_auditing_in_any_ci_counts(self) -> None:
        for provider in CI_FILES:
            with self.subTest(ci=provider):
                result = self._run(GO, ci_running(provider, "govulncheck ./..."))
                self.assertEqual(result, Result.passed("CI audits the dependencies with govulncheck"))

    def test_warns_without_an_audit(self) -> None:
        for ecosystem in ECOSYSTEMS:
            with self.subTest(ecosystem=ecosystem.label):
                result = self._run(ecosystem, github_job("ubuntu-latest", "echo no audit"))
                self.assertEqual(result.status, Status.WARN)
                self.assertEqual(result.message, "no dependency vulnerability audit found in CI configuration")

    def test_cargo_deny_without_its_advisories_check_does_not_count(self) -> None:
        for command in ("cargo deny check bans", "cargo-deny check licenses sources"):
            with self.subTest(command):
                result = self._run(RUST, github_job("ubuntu-latest", command))
                self.assertEqual(result.status, Status.WARN)

    def test_another_ecosystems_auditor_does_not_count(self) -> None:
        self.assertEqual(self._run(RUST, github_job("ubuntu-latest", "pip-audit")).status, Status.WARN)

    def test_passes_with_the_well_configured_fixture(self) -> None:
        result = self._run(PYTHON, dict(WELL_CONFIGURED_PYTHON))
        self.assertEqual(result, Result.passed("CI audits the dependencies with pip-audit"))


class AnswerTests(unittest.TestCase):
    def test_a_language_no_known_auditor_handles_is_skipped(self) -> None:
        answer = tool_answer(AUDIT, RUNS, "Lang", Facts(()), ())
        self.assertEqual(judge_audit(answer).status, Status.SKIP)
