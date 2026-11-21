"""Policies compared on the whole results they give, message and details, not only the status (upstream #305)."""

from __future__ import annotations

import unittest

from project_validator.core import Result
from project_validator.policy.declaration import judge_schema_declared
from project_validator.policy.license import judge_license
from project_validator.policy.limits import judge_limits
from project_validator.questions import Answer
from project_validator.questions.declaration import DeclarationAnswer
from project_validator.questions.license import LicenseAnswer
from project_validator.questions.tooling import KnownTool, Ran, ToolAnswer

NOTED = "test data, not judged: t/x.json: no $schema"


class SchemaDeclaredResultTests(unittest.TestCase):
    def judge(
        self, *, declared: tuple[str, ...] = (), problems: tuple[str, ...] = (), outdated: tuple[str, ...] = ()
    ) -> Result:
        answer = DeclarationAnswer(
            language="JSON Schema",
            what="$schema",
            declared=declared,
            problems=problems,
            outdated=outdated,
            test_problems=("t/x.json: no $schema",),
        )
        return judge_schema_declared(answer, allow_unknown=False)

    def test_undeclared_schemas_fail_with_each_problem_then_the_outdated_and_the_test_data(self) -> None:
        self.assertEqual(
            self.judge(problems=("a.json: no $schema", "b.json: no $schema"), outdated=("c.json: draft-04",)),
            Result.failed(
                "2 JSON Schema files do not declare their $schema",
                "a.json: no $schema",
                "b.json: no $schema",
                "c.json: draft-04",
                NOTED,
            ),
        )

    def test_nothing_to_judge_passes_noting_the_test_data(self) -> None:
        self.assertEqual(self.judge(), Result.passed("no JSON Schema file to judge", NOTED))

    def test_a_superseded_dialect_warns_with_each_file_and_the_test_data(self) -> None:
        self.assertEqual(
            self.judge(declared=("a.json", "b.json"), outdated=("b.json: draft-04",)),
            Result.warned("1 JSON Schema file declares a superseded $schema", "b.json: draft-04", NOTED),
        )
        self.assertEqual(
            self.judge(declared=("a.json",)), Result.passed("1 JSON Schema file declares its $schema", NOTED)
        )


class LicenseResultTests(unittest.TestCase):
    def test_an_unrecognised_license_file_warns_naming_the_others_licenses(self) -> None:
        files: tuple[tuple[str, frozenset[str]], ...] = (
            ("LICENSE.note", frozenset()),
            ("LICENSE", frozenset({"MIT"})),
            ("COPYING", frozenset({"Apache-2.0"})),
        )
        answer = LicenseAnswer(language="R", answer=Answer.NO, files=files)
        self.assertEqual(
            judge_license(answer, allow_unknown=False),
            Result.warned(
                "the license in LICENSE.note is not recognised (the others hold Apache-2.0, MIT)",
                "use the license's standard text, or add an SPDX-License-Identifier line",
            ),
        )
        alone = LicenseAnswer(language="R", answer=Answer.NO, files=(("A", frozenset()), ("B", frozenset())))
        self.assertEqual(judge_license(alone, allow_unknown=False).message, "the license in A, B is not recognised")


class LimitsResultTests(unittest.TestCase):
    def test_limiters_ci_runs_without_their_limit_on_fail_naming_each(self) -> None:
        known = (
            KnownTool(name="lizard", can={"limits": "lizard -L 50"}, describe="lizard -L"),
            KnownTool(
                name="eslint's max-lines-per-function", can={"limits": "eslint"}, describe="max-lines-per-function"
            ),
            KnownTool(name="other", can={"limits": "other"}, describe="other's limit"),
        )
        runs = (
            Ran(name="lizard", levels=frozenset()),
            Ran(name="eslint's max-lines-per-function", levels=frozenset({"runs"})),
        )
        answer = ToolAnswer(
            aspect="limits", language="JavaScript", level="limits", answer=Answer.NO, runs=runs, known=known
        )
        self.assertEqual(
            judge_limits(answer, allow_unknown=False),
            Result.failed(
                "CI runs lizard, but without a function length limit; eslint, but its max-lines-per-function rule"
                " is off or has no limit; set lizard -L or max-lines-per-function"
            ),
        )


if __name__ == "__main__":
    unittest.main()
