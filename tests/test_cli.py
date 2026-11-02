import contextlib
import io
import json
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from project_validator import pretty, yaml_support
from project_validator.cli import EXIT_FAILURE, EXIT_SUCCESS, EXIT_USAGE, main
from tests.support import (
    C_FAMILY_LAYOUTS,
    C_FAMILY_ONLY_LAYOUTS,
    CI_FILES,
    FIXTURES,
    OTHER_LANGUAGE_LAYOUTS,
    PROJECT_LAYOUTS,
    WELL_CONFIGURED_PYTHON,
    WELL_CONFIGURED_RUST,
    fixture_files,
    layout_project,
    requires_rich,
)

WELL_CONFIGURED = fixture_files("well_configured")
BARE_PROJECT = fixture_files("bare_project")
COMPILER_CHECKS = "ci-build-types,compiler-warnings,coverage,ctest-runs,cxx-extensions,platform-matrix"
# Language -> the checks that do not apply to it: only C/C++ has compiler extensions, and Python has no build types.
NOT_APPLICABLE = {"Python": {"ci-build-types", "cxx-extensions"}, "Rust": {"cxx-extensions"}}


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


def run_cli(*arguments: str, terminal: bool = False) -> tuple[int, str, str]:
    stdout, stderr = Terminal() if terminal else io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(list(arguments))
    return code, stdout.getvalue(), stderr.getvalue()


class CliTests(unittest.TestCase):
    def test_list(self) -> None:
        code, output, _ = run_cli("--list")
        self.assertEqual(code, EXIT_SUCCESS)
        self.assertIn("platform-matrix", output)

    def test_well_configured_project_passes(self) -> None:
        for layout in C_FAMILY_ONLY_LAYOUTS:
            with layout_project(self, layout, WELL_CONFIGURED) as root:
                code, output, _ = run_cli(str(root))
                self.assertEqual(code, EXIT_SUCCESS, output)
                self.assertIn("[PASS] coverage:", output)

    def test_well_configured_projects_in_other_languages_pass_strictly(self) -> None:
        projects = {"Python": WELL_CONFIGURED_PYTHON, "Rust": WELL_CONFIGURED_RUST}
        for layout in OTHER_LANGUAGE_LAYOUTS:
            [language] = layout.languages
            with layout_project(self, layout, projects[language]) as root:
                code, output, _ = run_cli("--strict", str(root))
                self.assertEqual(code, EXIT_SUCCESS, output)
                for name in COMPILER_CHECKS.split(","):
                    status = "SKIP" if name in NOT_APPLICABLE[language] else "PASS"
                    self.assertIn(f"[{status}] {name}:", output)

    def test_mixed_language_project_passes_when_every_language_is_well_configured(self) -> None:
        python = {
            "pyproject.toml": "[tool.coverage.run]\nbranch = true\n",
            "tests/test_bindings.py": "",
            ".github/workflows/python.yml": WELL_CONFIGURED_PYTHON[".github/workflows/ci.yml"],
        }
        mixed = [layout for layout in C_FAMILY_LAYOUTS if layout not in C_FAMILY_ONLY_LAYOUTS]
        # ci-build-types is left out: a Python-only job on a runner counts as a C/C++ build with its default compiler.
        judged_per_language = "compiler-warnings,coverage,ctest-runs,platform-matrix"
        for layout in mixed:
            with layout_project(self, layout, {**WELL_CONFIGURED, **python}) as root:
                code, output, _ = run_cli("--only", judged_per_language, str(root))
                self.assertEqual(code, EXIT_SUCCESS, output)
                self.assertIn("[PASS] coverage: C/C++: branch coverage is reported with gcovr", output)

    def test_bare_project_fails(self) -> None:
        for layout in PROJECT_LAYOUTS:
            with layout_project(self, layout, BARE_PROJECT) as root:
                code, output, _ = run_cli(str(root))
                self.assertEqual(code, EXIT_FAILURE)
                self.assertIn("[FAIL] ci-present:", output)

    def test_json_output_with_only(self) -> None:
        for layout in PROJECT_LAYOUTS:
            with layout_project(self, layout, BARE_PROJECT) as root:
                code, output, _ = run_cli("--format", "json", "--only", "ci-present,coverage", str(root))
                self.assertEqual(code, EXIT_FAILURE)
                self.assertEqual([entry["check"] for entry in json.loads(output)], ["ci-present", "coverage"])

    def test_skipping_every_failure_succeeds(self) -> None:
        for layout in PROJECT_LAYOUTS:
            with layout_project(self, layout, BARE_PROJECT) as root:
                self.assertEqual(run_cli("--skip", f"ci-present,{COMPILER_CHECKS}", str(root))[0], EXIT_SUCCESS)

    def test_map_prints_the_project_structure(self) -> None:
        code, output, _ = run_cli("--map", str(FIXTURES / "well_configured"))
        self.assertEqual(code, EXIT_SUCCESS)
        mapped = json.loads(output)
        self.assertEqual(mapped["languages"], ["C", "C++"])
        self.assertIn("GitHub Actions", mapped["ci"]["providers"])

    def test_map_prints_every_layout_with_every_ci_provider(self) -> None:
        for layout in PROJECT_LAYOUTS:
            for provider, path in CI_FILES.items():
                with layout_project(self, layout, {path: "jobs: {}\n"}, ci=provider) as root:
                    code, output, _ = run_cli("--map", str(root))
                    self.assertEqual(code, EXIT_SUCCESS)
                    mapped = json.loads(output)
                    self.assertEqual(mapped["languages"], sorted(layout.languages))
                    self.assertEqual(mapped["build_systems"], sorted(layout.build_systems))
                    self.assertEqual(mapped["ci"]["providers"], [provider])

    def test_compiler_checks_are_skipped_only_where_they_do_not_apply(self) -> None:
        for layout in OTHER_LANGUAGE_LAYOUTS:
            [language] = layout.languages
            for provider, path in CI_FILES.items():
                with layout_project(self, layout, {path: "jobs: {}\n"}, ci=provider) as root:
                    code, output, _ = run_cli("--only", COMPILER_CHECKS, str(root))
                    self.assertEqual(code, EXIT_FAILURE, output)
                    for name in COMPILER_CHECKS.split(","):
                        skipped = f"[SKIP] {name}:" in output
                        self.assertEqual(skipped, name in NOT_APPLICABLE[language], name)

    def test_compiler_checks_run_for_c_family_and_unrecognised_languages(self) -> None:
        for layout in C_FAMILY_LAYOUTS:
            with layout_project(self, layout, {".github/workflows/ci.yml": "jobs: {}\n"}) as root:
                code, output, _ = run_cli("--only", COMPILER_CHECKS, str(root))
                self.assertEqual(code, EXIT_FAILURE, output)
                self.assertNotIn("[SKIP]", output)

    def test_excluded_directories_are_left_out_of_the_map(self) -> None:
        excluded = {"tests/fixtures/cmake/CMakeLists.txt": "", "tests/fixtures/cmake/main.cpp": ""}
        for layout in PROJECT_LAYOUTS:
            with layout_project(self, layout, excluded) as root:
                code, output, _ = run_cli("--map", "--exclude", "./tests/fixtures/", str(root))
                self.assertEqual(code, EXIT_SUCCESS)
                mapped = json.loads(output)
                self.assertEqual(mapped["languages"], sorted(layout.languages))
                self.assertEqual(mapped["build_systems"], sorted(layout.build_systems))

    def test_usage_errors(self) -> None:
        self.assertEqual(run_cli("--only", "nope", ".")[0], EXIT_USAGE)
        self.assertEqual(run_cli(str(FIXTURES / "missing"))[0], EXIT_USAGE)

    @requires_rich
    def test_color_always_beautifies_the_output(self) -> None:
        code, output, _ = run_cli("--color", "always", str(FIXTURES / "well_configured"))
        self.assertEqual(code, EXIT_SUCCESS, output)
        self.assertIn("\x1b[", output)
        self.assertIn("9 passed", output)

    def test_color_never_and_auto_when_redirected_keep_plain_text(self) -> None:
        for choice in ("never", "auto"):
            _, output, _ = run_cli("--color", choice, str(FIXTURES / "well_configured"))
            self.assertNotIn("\x1b[", output)
            self.assertIn("[PASS] coverage:", output)

    def test_color_auto_is_used_for_a_terminal_unless_no_color_is_set(self) -> None:
        with mock.patch.object(pretty, "available", return_value=False):
            with mock.patch.dict("os.environ", {}, clear=True):
                self.assertIn("install rich", run_cli(str(FIXTURES / "well_configured"), terminal=True)[2])
            with mock.patch.dict("os.environ", {"NO_COLOR": "1"}):
                self.assertEqual(run_cli(str(FIXTURES / "well_configured"), terminal=True)[2], "")

    def test_color_without_rich_falls_back_to_plain_text_and_says_so(self) -> None:
        with mock.patch.object(pretty, "_rich", None):
            code, output, errors = run_cli("--color", "always", str(FIXTURES / "well_configured"))
        self.assertEqual(code, EXIT_SUCCESS, output)
        self.assertIn("[PASS] coverage:", output)
        self.assertIn("install rich", errors)

    def test_missing_pyyaml_is_an_error_instead_of_reduced_accuracy(self) -> None:
        with mock.patch.object(yaml_support, "_yaml", None):
            code, output, error = run_cli(str(FIXTURES / "well_configured"))
        self.assertEqual((code, output), (EXIT_USAGE, ""))
        self.assertIn("PyYAML", error)

    def test_pyyaml_can_not_be_disabled(self) -> None:
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            main(["--no-yaml", str(FIXTURES / "well_configured")])


class DependencyTests(unittest.TestCase):
    def test_pyyaml_is_a_required_dependency(self) -> None:
        pyproject = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertIn("PyYAML>=6.0", pyproject["project"]["dependencies"])
        self.assertNotIn("yaml", pyproject["project"]["optional-dependencies"])
