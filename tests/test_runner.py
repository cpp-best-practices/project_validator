from __future__ import annotations

import unittest
from collections.abc import Iterator
from typing import NoReturn, cast
from unittest.mock import patch

from project_validator.core import Check, CheckFunction, Context, ExtractionError, Result, Status
from project_validator.facts import Fact
from project_validator.plugins import discover
from project_validator.runner import Report, SelectionError, run_checks, select, succeeded
from tests.support import PROJECT_LAYOUTS, layout_project, make_context, temp_project


def _check(name: str, run: CheckFunction) -> Check:
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

    def test_former_names_select_a_check(self) -> None:
        renamed = Check(name="new-name", description="", run=PASSING.run, aliases=("old-name",))
        self.assertEqual(select([PASSING, renamed], only=["old-name"]), [renamed])
        self.assertEqual(select([PASSING, renamed], skip=["old-name"]), [PASSING])


class RunChecksTests(unittest.TestCase):
    def test_misbehaving_checks_are_errors_and_do_not_stop_the_others(self) -> None:
        def explode(context: Context) -> NoReturn:
            raise ValueError("boom")

        def wrong_type(context: Context) -> Result:
            return cast(Result, "ok")

        checks = [_check("raises", explode), _check("wrong-type", wrong_type), PASSING]
        for layout in PROJECT_LAYOUTS:
            with layout_project(self, layout) as root:
                reports = run_checks(checks, make_context(root))
                self.assertEqual([r.result.status for r in reports], [Status.ERROR, Status.ERROR, Status.PASS])
                self.assertEqual(reports[0].result.message, "check raised ValueError: boom")
                self.assertEqual(reports[1].result.message, "check returned str instead of a Result")


class ExtractionFailureTests(unittest.TestCase):
    def test_a_failing_extractor_is_tried_once_and_judges_nothing_that_needs_the_facts(self) -> None:
        calls: list[object] = []

        def failing(project: object) -> Iterator[Fact]:
            calls.append(project)
            raise RuntimeError("boom")

        files = {"CMakeLists.txt": "project(x CXX)\n", "src/a.cpp": "", "LICENSE": "MIT License\n"}
        with temp_project(files) as root, patch("project_validator.facts.structure.structure_facts", failing):
            context = make_context(root)
            reports = run_checks(discover().checks, context)
        self.assertEqual(len(calls), 1)
        errors = {r.result.message for r in reports if r.result.status is Status.ERROR}
        cause = "the facts could not be extracted: the project's structure raised RuntimeError: boom"
        self.assertEqual(errors, {f"not judged: {cause}"})
        self.assertEqual(str(context.extraction_error), cause)
        judged = {r.check.name for r in reports if r.result.status is not Status.ERROR}
        self.assertIn("ci-present", judged)  # reads no facts
        self.assertGreater(len(reports) - len(judged), 20)

    def test_whatever_else_extraction_raises_is_kept_as_the_one_error(self) -> None:
        with (
            temp_project({"CMakeLists.txt": ""}) as root,
            patch("project_validator.extraction.extract_facts", side_effect=RuntimeError("boom")),
        ):
            context = make_context(root)
            with self.assertRaises(ExtractionError):
                context.facts  # noqa: B018 - the property is what raises
            with self.assertRaises(ExtractionError):
                context.facts  # noqa: B018 - and raises again, without extracting again
        self.assertEqual(
            str(context.extraction_error), "the facts could not be extracted: an extractor raised RuntimeError: boom"
        )

    def test_an_extractor_that_raises_an_extraction_error_names_its_own_stage(self) -> None:
        def failing(project: object) -> Iterator[Fact]:
            raise ExtractionError("a CMake file", ValueError("unreadable"))

        with (
            temp_project({"CMakeLists.txt": ""}) as root,
            patch("project_validator.facts.structure.structure_facts", failing),
        ):
            context = make_context(root)
            with self.assertRaises(ExtractionError) as raised:
                context.facts  # noqa: B018 - the property is what raises
        self.assertEqual(
            str(raised.exception), "the facts could not be extracted: a CMake file raised ValueError: unreadable"
        )
        self.assertIsNone(make_context(root).extraction_error)


class SucceededTests(unittest.TestCase):
    def test_warnings_only_fail_in_strict_mode(self) -> None:
        reports = [Report(check=WARNING, result=Result.warned("hmm"))]
        self.assertTrue(succeeded(reports))
        self.assertFalse(succeeded(reports, strict=True))
