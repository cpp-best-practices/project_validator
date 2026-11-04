import unittest

from project_validator.checks.dependency_audit import dependency_audit
from project_validator.core import Result, Status
from project_validator.ecosystems import C_FAMILY, GO, PYTHON, RUST, Ecosystem
from tests.support import CI_FILES, GITHUB_WORKFLOW, WELL_CONFIGURED_PYTHON, run_as

ECOSYSTEMS = (PYTHON, RUST, GO)


class DependencyAuditTests(unittest.TestCase):
    def _run(self, ecosystem: Ecosystem, files: dict[str, str]) -> Result:
        return run_as(self, dependency_audit, files, ecosystem)

    def test_declares_the_languages_it_judges(self) -> None:
        # Plugins (and later built-in profiles) add languages; the README matrix pins the exact list.
        self.assertLessEqual({"Python", "Rust", "Go"}, dependency_audit.languages)
        # C and C++ have no common dependency manifest to audit.
        self.assertFalse(C_FAMILY & dependency_audit.languages)

    def test_each_ecosystems_auditor_counts(self) -> None:
        auditors = {
            PYTHON: {
                "pip-audit": "run: pip-audit -r requirements.txt",
                "pip-audit action": "uses: pypa/gh-action-pip-audit@v1",
                "safety": "run: safety scan",
            },
            RUST: {
                "cargo audit": "run: cargo audit",
                "audit action": "uses: rustsec/audit-check@v2",
                "cargo deny": "run: cargo deny check",
                "cargo deny advisories": "run: cargo deny --all-features check advisories",
                "cargo deny action": "uses: EmbarkStudios/cargo-deny-action@v2",
            },
            GO: {"govulncheck": "run: govulncheck ./...", "govulncheck action": "uses: golang/govulncheck-action@v1"},
        }
        for ecosystem, commands in auditors.items():
            for name, command in commands.items():
                with self.subTest(ecosystem=ecosystem.label, tool=name):
                    result = self._run(ecosystem, {GITHUB_WORKFLOW: f"steps:\n  - {command}\n"})
                    self.assertEqual(result.status, Status.PASS)

    def test_multi_ecosystem_scanners_count_for_every_ecosystem(self) -> None:
        for command in ("osv-scanner scan source -r .", "trivy fs .", "snyk test --all-projects"):
            for ecosystem in ECOSYSTEMS:
                with self.subTest(command=command, ecosystem=ecosystem.label):
                    result = self._run(ecosystem, {GITHUB_WORKFLOW: f"steps:\n  - run: {command}\n"})
                    self.assertEqual(result.status, Status.PASS)

    def test_auditing_in_any_ci_counts(self) -> None:
        for provider, path in CI_FILES.items():
            with self.subTest(ci=provider):
                result = self._run(GO, {path: "script: govulncheck ./...\n"})
                self.assertEqual(result, Result.passed("CI audits the dependencies with govulncheck"))

    def test_warns_without_an_audit(self) -> None:
        for ecosystem in ECOSYSTEMS:
            with self.subTest(ecosystem=ecosystem.label):
                result = self._run(ecosystem, {GITHUB_WORKFLOW: "steps:\n  - run: make test\n"})
                self.assertEqual(result.status, Status.WARN)
                self.assertEqual(result.message, "no dependency vulnerability audit found in CI configuration")

    def test_cargo_deny_without_its_advisories_check_does_not_count(self) -> None:
        for command in ("cargo deny check bans", "cargo-deny check licenses sources"):
            with self.subTest(command):
                result = self._run(RUST, {GITHUB_WORKFLOW: f"steps:\n  - run: {command}\n"})
                self.assertEqual(result.status, Status.WARN)

    def test_another_ecosystems_auditor_does_not_count(self) -> None:
        self.assertEqual(self._run(RUST, {GITHUB_WORKFLOW: "steps:\n  - run: pip-audit\n"}).status, Status.WARN)

    def test_passes_with_the_well_configured_fixture(self) -> None:
        result = self._run(PYTHON, dict(WELL_CONFIGURED_PYTHON))
        self.assertEqual(result, Result.passed("CI audits the dependencies with pip-audit"))
