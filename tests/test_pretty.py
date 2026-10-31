import io
import unittest
from unittest import mock

from project_validator import pretty
from project_validator.core import Check, Result, Status
from project_validator.runner import Report
from tests.support import requires_rich

ANSI_ESCAPE = "\x1b["


def _report(name: str, result: Result) -> Report:
    return Report(check=Check(name=name, description=name, run=lambda context: result), result=result)


REPORTS = [
    _report("ci-present", Result.passed("CI configuration found", ".github/workflows/ci.yml")),
    _report("coverage", Result.warned("no path coverage")),
    _report("platform-matrix", Result.failed("too few compilers")),
]


def _render(reports: list[Report]) -> str:
    stream = io.StringIO()
    pretty.print_reports(reports, stream)
    return stream.getvalue()


@requires_rich
class PrettyTests(unittest.TestCase):
    def test_output_is_colored(self) -> None:
        self.assertIn(ANSI_ESCAPE, _render(REPORTS))

    def test_every_result_and_detail_is_shown(self) -> None:
        output = _render(REPORTS)
        for text in ("ci-present", "CI configuration found", ".github/workflows/ci.yml", "too few compilers"):
            self.assertIn(text, output)

    def test_summary_counts_each_status(self) -> None:
        self.assertIn("1 passed", _render(REPORTS))
        self.assertIn("1 warned", _render(REPORTS))
        self.assertIn("1 failed", _render(REPORTS))

    def test_summary_counts_skipped_checks(self) -> None:
        skipped = _report("ctest-runs", Result(status=Status.SKIP, message="not applicable to Rust"))
        self.assertIn("1 skipped", _render([*REPORTS, skipped]))

    def test_summary_without_checks(self) -> None:
        self.assertIn("no checks were run", _render([]))

    def test_messages_are_not_treated_as_markup(self) -> None:
        self.assertIn("[bold]literal[/bold]", _render([_report("markup", Result.passed("[bold]literal[/bold]"))]))


class PrettyUnavailableTests(unittest.TestCase):
    def test_printing_without_rich_is_an_error(self) -> None:
        with mock.patch.object(pretty, "_rich", None):
            self.assertFalse(pretty.available())
            with self.assertRaisesRegex(pretty.PrettyError, "rich is not available"):
                _render(REPORTS)
