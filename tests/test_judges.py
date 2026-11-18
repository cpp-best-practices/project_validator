"""Every policy judge must be told whether unknown answers are allowed: an unknown answer is an error unless the
caller says otherwise, so no judge may quietly default to either."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import unittest
from collections.abc import Callable, Iterator

import project_validator.policy as policy_package
from project_validator.policy.tooling import advised, required


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

    @unittest.expectedFailure  # upstream #306
    def test_every_judge_requires_allow_unknown_as_a_keyword(self) -> None:
        for name, judge in (*_module_judges(), *_built_judges()):
            with self.subTest(judge=name):
                parameters = inspect.signature(judge).parameters
                self.assertIn("allow_unknown", parameters)
                parameter = parameters["allow_unknown"]
                self.assertIs(parameter.kind, inspect.Parameter.KEYWORD_ONLY)
                self.assertIs(parameter.default, inspect.Parameter.empty, "defaults allow_unknown")


if __name__ == "__main__":
    unittest.main()
