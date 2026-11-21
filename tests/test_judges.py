"""Every policy judge must be told whether unknown answers are allowed: an unknown answer is an error unless the
caller says otherwise, so no judge may quietly default to either."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import unittest
from collections.abc import Callable, Iterator

import project_validator.policy as policy_package
from project_validator.core import Result, Status
from project_validator.policy.tooling import advised, required
from project_validator.questions import Answer
from project_validator.questions.tooling import KnownTool, Ran, ToolAnswer


def _module_judges() -> Iterator[tuple[str, Callable[..., object]]]:
    for module_info in pkgutil.iter_modules(policy_package.__path__):
        module = importlib.import_module(f"{policy_package.__name__}.{module_info.name}")
        for name, value in vars(module).items():
            if name.startswith("judge_") and inspect.isfunction(value) and value.__module__ == module.__name__:
                yield f"{module.__name__}.{name}", value


def _built_judges() -> Iterator[tuple[str, Callable[..., object]]]:
    words = {"level": "x", "impossible": "x", "passed": "x", "asks": "x", "missing": "x"}
    yield "policy.tooling.required(...)", required(**words)
    yield "policy.tooling.advised(...)", advised(**words)


class JudgeContractTests(unittest.TestCase):
    def test_there_are_judges_to_check(self) -> None:
        self.assertGreater(len(list(_module_judges())), 20)

    def test_every_judge_requires_allow_unknown_as_a_keyword(self) -> None:
        for name, judge in (*_module_judges(), *_built_judges()):
            with self.subTest(judge=name):
                parameters = inspect.signature(judge).parameters
                self.assertIn("allow_unknown", parameters)
                parameter = parameters["allow_unknown"]
                self.assertIs(parameter.kind, inspect.Parameter.KEYWORD_ONLY)
                self.assertIs(parameter.default, inspect.Parameter.empty, "defaults allow_unknown")


WORDS = {
    "level": "checked",
    "impossible": "no link checker reads {language}",
    "passed": "links checked by {tools}",
    "asks": "whether links are checked",
    "missing": "no link checker",
}
KNOWN = (
    KnownTool(name="lychee", can={"checked": "lychee ."}),
    KnownTool(name="markdown-link-check", can={"checked": "markdown-link-check ."}),
    KnownTool(name="helper", can={}),
)
HINT = "consider running in CI: lychee . or markdown-link-check ."


def _answer(answer: Answer, *runs: Ran) -> ToolAnswer:
    return ToolAnswer(
        aspect="links", language="Markdown", level="checked", answer=answer, runs=runs, known=KNOWN, unknowns=("x.yml",)
    )


class OneLevelPolicyTests(unittest.TestCase):
    def test_a_run_providing_the_level_passes_naming_every_tool_that_does(self) -> None:
        runs = (
            Ran(name="lychee", levels=frozenset({"checked"})),
            Ran(name="other", levels=frozenset({"other"})),
            Ran(name="mlc", levels=frozenset({"checked"})),
        )
        for judge in (advised(**WORDS), required(**WORDS)):
            with self.subTest(judge=judge):
                self.assertEqual(
                    judge(_answer(Answer.YES, *runs), allow_unknown=False),
                    Result.passed("links checked by lychee, mlc"),
                )

    def test_none_warns_or_fails_with_how_to_add_one(self) -> None:
        self.assertEqual(
            advised(**WORDS)(_answer(Answer.NO), allow_unknown=False), Result.warned("no link checker", HINT)
        )
        self.assertEqual(
            required(**WORDS)(_answer(Answer.NO), allow_unknown=False), Result.failed("no link checker", HINT)
        )

    def test_no_known_tool_for_the_language_skips(self) -> None:
        result = required(**WORDS)(_answer(Answer.IMPOSSIBLE), allow_unknown=False)
        self.assertEqual(result, Result.skipped("no link checker reads Markdown"))

    def test_an_unknown_answer_is_an_error_unless_unknowns_are_allowed(self) -> None:
        self.assertEqual(
            required(**WORDS)(_answer(Answer.UNKNOWN), allow_unknown=False),
            Result(
                status=Status.ERROR,
                message="whether links are checked is unknown: some of what it runs could not be read",
                details=("not read: x.yml", HINT, "--allow-unknown judges only what could be read"),
            ),
        )
        self.assertEqual(
            required(**WORDS)(_answer(Answer.UNKNOWN), allow_unknown=True), Result.failed("no link checker", HINT)
        )


if __name__ == "__main__":
    unittest.main()
