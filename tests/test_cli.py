import contextlib
import io
import json
import unittest

from project_validator.cli import EXIT_FAILURE, EXIT_SUCCESS, EXIT_USAGE, main
from tests.support import FIXTURES


def run_cli(*arguments: str) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
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
        skipped = "ci-present,coverage,ctest-runs,platform-matrix"
        self.assertEqual(run_cli("--skip", skipped, str(FIXTURES / "bare_project"))[0], EXIT_SUCCESS)

    def test_usage_errors(self) -> None:
        self.assertEqual(run_cli("--only", "nope", ".")[0], EXIT_USAGE)
        self.assertEqual(run_cli(str(FIXTURES / "missing"))[0], EXIT_USAGE)
