import unittest

from project_validator.core import Check, Result, Status
from project_validator.runner import Report, SelectionError, run_checks, select, succeeded
from tests.support import PROJECT_LAYOUTS, layout_project, make_context


def _check(name: str, run) -> Check:
    return Check(name=name, description=name, run=run)


PASSING = _check("passing", lambda context: Result.passed("ok"))
WARNING = _check("warning", lambda context: Result.warned("hmm"))


class SelectTests(unittest.TestCase):
    def test_only_and_skip(self) -> None:
        self.assertEqual(select([PASSING, WARNING], only=["warning"]), [WARNING])
        self.assertEqual(select([PASSING, WARNING], skip=["warning"]), [PASSING])

    def test_unknown_names_are_rejected(self) -> None:
        with self.assertRaisesRegex(SelectionError, "nope"):
            select([PASSING], only=["nope"])


class RunChecksTests(unittest.TestCase):
    def test_misbehaving_checks_are_errors_and_do_not_stop_the_others(self) -> None:
        def explode(context):
            raise ValueError("boom")

        checks = [_check("raises", explode), _check("wrong-type", lambda context: "ok"), PASSING]
        for layout in PROJECT_LAYOUTS:
            with layout_project(self, layout) as root:
                reports = run_checks(checks, make_context(root))
                self.assertEqual([r.result.status for r in reports], [Status.ERROR, Status.ERROR, Status.PASS])
                self.assertEqual(reports[0].result.message, "check raised ValueError: boom")
                self.assertEqual(reports[1].result.message, "check returned str instead of a Result")


class SucceededTests(unittest.TestCase):
    def test_warnings_only_fail_in_strict_mode(self) -> None:
        reports = [Report(check=WARNING, result=Result.warned("hmm"))]
        self.assertTrue(succeeded(reports))
        self.assertFalse(succeeded(reports, strict=True))
