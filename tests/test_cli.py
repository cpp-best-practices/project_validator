import contextlib
import io
import json
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from project_validator import pretty, yaml_support
from project_validator.cli import EXIT_FAILURE, EXIT_SUCCESS, EXIT_USAGE, main
from tests.support import FIXTURES, requires_rich


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
        code, output, _ = run_cli(str(FIXTURES / "well_configured"))
        self.assertEqual(code, EXIT_SUCCESS, output)
        self.assertIn("[PASS] coverage:", output)

    def test_bare_project_fails(self) -> None:
        code, output, _ = run_cli(str(FIXTURES / "bare_project"))
        self.assertEqual(code, EXIT_FAILURE)
        self.assertIn("[FAIL] ci-present:", output)

    def test_json_output_with_only(self) -> None:
        code, output, _ = run_cli("--format", "json", "--only", "ci-present,coverage", str(FIXTURES / "bare_project"))
        self.assertEqual(code, EXIT_FAILURE)
        self.assertEqual([entry["check"] for entry in json.loads(output)], ["ci-present", "coverage"])

    def test_skipping_every_failure_succeeds(self) -> None:
        skipped = "ci-present,coverage,ctest-runs,platform-matrix,warnings-as-errors"
        self.assertEqual(run_cli("--skip", skipped, str(FIXTURES / "bare_project"))[0], EXIT_SUCCESS)

    def test_usage_errors(self) -> None:
        self.assertEqual(run_cli("--only", "nope", ".")[0], EXIT_USAGE)
        self.assertEqual(run_cli(str(FIXTURES / "missing"))[0], EXIT_USAGE)

    @requires_rich
    def test_color_always_beautifies_the_output(self) -> None:
        code, output, _ = run_cli("--color", "always", str(FIXTURES / "well_configured"))
        self.assertEqual(code, EXIT_SUCCESS, output)
        self.assertIn("\x1b[", output)
        self.assertIn("6 passed", output)

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
