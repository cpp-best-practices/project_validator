"""The Go profile's rules, judged by the generic checks in every Go project layout."""

import json
import unittest

from project_validator.checks.code_formatting import code_formatting
from project_validator.checks.compiler_warnings import compiler_warnings
from project_validator.checks.coverage import coverage
from project_validator.checks.function_limits import function_limits
from project_validator.checks.hardening import hardening
from project_validator.checks.platform_matrix import platform_matrix
from project_validator.checks.static_analysis import static_analysis
from project_validator.checks.tests_run import tests_run
from project_validator.checks.vcs_ignore import vcs_ignore
from project_validator.core import Check, Result, Status
from project_validator.ecosystems.go import GO
from tests.support import GITHUB_WORKFLOW, github_job, run_as

TEST_FILE = {"app_test.go": 'package app\n\nimport "testing"\n\nfunc TestAdd(t *testing.T) {}\n'}
FUNLEN_CONFIG = {".golangci.yml": "linters:\n  enable:\n    - funlen\n"}


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


class GoTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_as(self, selected, files, GO)

    def test_formatting_is_enforced_by_any_gofmt_style_tool(self) -> None:
        for command in ('test -z "$(gofmt -l .)"', "gofumpt -l .", "goimports -l .", "golangci-lint fmt --diff"):
            with self.subTest(command=command):
                self.assertEqual(self._run(code_formatting, _ci(command)).status, Status.PASS)
        self.assertEqual(self._run(code_formatting, _ci("golangci-lint run")).status, Status.FAIL)
        self.assertEqual(self._run(code_formatting, _ci("gofmt -w . && go fmt ./...")).status, Status.FAIL)

    def test_go_run_launches_the_program_its_package_names(self) -> None:
        pinned = _ci("go run github.com/golangci/golangci-lint/v2/cmd/golangci-lint@v2.6.1 run ./...")
        config = {".golangci.yml": "linters:\n  enable: [revive]\n"}
        self.assertEqual(
            self._run(static_analysis, {**config, **pinned}), Result.passed("golangci-lint (.golangci.yml) runs")
        )
        # The project's own code (`go run .`) is no tool.
        self.assertEqual(self._run(static_analysis, {**config, **_ci("go run . lint", "go run")}).status, Status.WARN)

    def test_golangci_lint_runs_the_formatters_its_configuration_enables(self) -> None:
        action = {
            GITHUB_WORKFLOW: json.dumps(
                {
                    "jobs": {
                        "lint": {"runs-on": "ubuntu-latest", "steps": [{"uses": "golangci/golangci-lint-action@v8"}]}
                    }
                }
            )
        }
        for config, text in (
            (".golangci.yml", "version: '2'\nformatters:\n  enable: [gofumpt, goimports]\n"),
            (".golangci.toml", "[linters]\nenable = ['gofmt']\n"),
            (".golangci.json", '{"formatters": {"enable": ["gci"]}}'),
        ):
            with self.subTest(config=config):
                result = self._run(code_formatting, {config: text, **action})
                self.assertEqual(result, Result.passed("CI enforces the gofmt style"))
        linters_only = {".golangci.yml": "linters:\n  enable: [govet]\n", **action}
        self.assertEqual(self._run(code_formatting, linters_only).status, Status.FAIL)
        broken = {".golangci.yml": "formatters: [", **action}
        self.assertEqual(self._run(code_formatting, broken).status, Status.ERROR)

    def test_golangci_lint_runs_both_required_linters(self) -> None:
        result = self._run(compiler_warnings, _ci("golangci-lint run ./..."))
        self.assertEqual(result, Result.passed("strict Go linters are enabled: go vet, staticcheck"))

    def test_go_vet_alone_is_not_enough(self) -> None:
        result = self._run(compiler_warnings, _ci("go vet ./..."))
        self.assertEqual(result.status, Status.WARN)
        self.assertEqual(result.message, "missing Go linters: staticcheck")

    def test_coverage_needs_a_cover_flag(self) -> None:
        self.assertEqual(self._run(coverage, _ci("go test ./...")).status, Status.FAIL)
        result = self._run(coverage, _ci("go test -covermode=atomic ./..."))
        self.assertEqual(result, Result.passed("statement coverage is reported with go test -cover"))

    def test_tests_are_test_functions_in_test_files(self) -> None:
        self.assertEqual(self._run(tests_run, {"app_test.go": "package app\n"}).status, Status.FAIL)
        self.assertEqual(self._run(tests_run, {"app.go": "func TestAdd(t *testing.T) {}\n"}).status, Status.FAIL)
        result = self._run(tests_run, TEST_FILE)
        self.assertEqual(result.status, Status.WARN)
        self.assertIn("no CI configuration runs go test", result.message)
        self.assertEqual(self._run(tests_run, {**TEST_FILE, **_ci("gotestsum ./...")}).status, Status.PASS)

    def test_programs_must_be_position_independent_executables(self) -> None:
        self.assertEqual(self._run(hardening, _ci("go build ./...")).status, Status.FAIL)
        for build in ("go build -buildmode=pie ./...", "GOFLAGS: -buildmode=pie"):
            with self.subTest(build):
                result = self._run(hardening, _ci(build))
                self.assertEqual(result, Result.passed("hardening options are enabled: -buildmode=pie"))
        goreleaser = {".goreleaser.yaml": "builds:\n  - buildmode: pie\n"}
        self.assertEqual(self._run(hardening, goreleaser).status, Status.PASS)

    def test_a_library_builds_no_binary_to_harden(self) -> None:
        result = self._run(hardening, {"main.go": "package app\n", "cmd/tool/main_test.go": "package main\n"})
        self.assertEqual(result.status, Status.SKIP)
        self.assertIn("no Go program", result.message)

    # Vulnerability scans and security lints are not binary hardening.
    def test_govulncheck_and_gosec_are_not_hardening(self) -> None:
        self.assertEqual(self._run(hardening, _ci("govulncheck ./...", "gosec ./...")).status, Status.FAIL)

    def test_funlen_limits_functions_when_golangci_lint_runs(self) -> None:
        result = self._run(function_limits, {**FUNLEN_CONFIG, **_ci("golangci-lint run")})
        self.assertEqual(result, Result.passed("function length is limited with golangci-lint funlen (.golangci.yml)"))

    def test_funlen_without_golangci_lint_in_ci_warns(self) -> None:
        result = self._run(function_limits, FUNLEN_CONFIG)
        self.assertEqual(result, Result.warned("funlen is enabled in .golangci.yml but CI does not run golangci-lint"))

    def test_without_funlen_or_lizard_function_length_is_not_limited(self) -> None:
        result = self._run(function_limits, _ci("golangci-lint run"))
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn("funlen", result.message)

    def test_test_binaries_and_profiles_must_be_ignored(self) -> None:
        self.assertEqual(self._run(vcs_ignore, {".gitignore": "*.test\n"}).status, Status.PASS)
        self.assertEqual(self._run(vcs_ignore, {".gitignore": "node_modules/\n"}).status, Status.WARN)

    def test_the_platform_matrix_counts_go_versions(self) -> None:
        files = {
            GITHUB_WORKFLOW: """\
                jobs:
                  test:
                    runs-on: ${{ matrix.os }}
                    strategy:
                      matrix:
                        os: [ubuntu-latest, windows-latest]
                        go: ["1.22", "1.23"]
                    steps:
                      - uses: actions/setup-go@v5
                        with:
                          go-version: ${{ matrix.go }}
                """
        }
        result = self._run(platform_matrix, files)
        self.assertIn("2 Go version(s) (1.22, 1.23)", result.message)
