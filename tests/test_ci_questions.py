"""The questions about CI itself (not about a language): are its reusable steps pinned, does it lint its own
configuration, does it scan for secrets; each answered from facts, and judged by its policy."""

from __future__ import annotations

import unittest

from project_validator.core import Result, Status
from project_validator.facts import StepReference
from project_validator.policy.ci_lint import judge_ci_lint
from project_validator.policy.pinning import judge_pinning
from project_validator.policy.secrets import judge_secret_scanning
from project_validator.questions import Answer
from project_validator.questions.ci_lint import ci_lint_answer
from project_validator.questions.pinning import BRANCH, TAG, UNPINNED, pinning, pinning_answer
from project_validator.questions.secrets import secret_scanning_answer
from tests.support import CI_FILES, GITHUB_WORKFLOW, github_steps, make_context, temp_project

COMMIT = "11d5960a326750d5838078e36cf38b85af677262"


def _workflow(*references: str) -> str:
    steps = "".join(f"      - uses: {reference}\n" for reference in references)
    return f"jobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n{steps}"


class StepReferenceTests(unittest.TestCase):
    def test_every_reference_a_workflow_writes_is_a_fact(self) -> None:
        """Also those of steps whose condition is false and of reusable workflows a job calls: pinning is about what
        is written, not what runs."""
        workflow = (
            "jobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n"
            f"      - uses: actions/checkout@{COMMIT}\n"
            "      - if: false\n        uses: actions/setup-go@v5\n"
            "  b:\n    uses: org/repo/.github/workflows/x.yml@main\n"
        )
        with temp_project({GITHUB_WORKFLOW: workflow}) as root:
            facts = make_context(root).facts
        self.assertEqual(
            sorted(fact.reference for fact in facts.of(StepReference)),
            [f"actions/checkout@{COMMIT}", "actions/setup-go@v5", "org/repo/.github/workflows/x.yml@main"],
        )

    def test_a_provider_without_reusable_steps_has_none(self) -> None:
        with temp_project({CI_FILES["Travis CI"]: "script: make\n"}) as root:
            self.assertEqual(make_context(root).facts.of(StepReference), ())


class PinningTests(unittest.TestCase):
    def test_the_answer_classifies_each_reference(self) -> None:
        files = {GITHUB_WORKFLOW: _workflow(f"actions/checkout@{COMMIT}", "actions/setup-go@v5", "./local", "x/y@main")}
        with temp_project(files) as root:
            answer = pinning_answer(make_context(root).facts)
        self.assertEqual(answer.answer, Answer.NO)
        self.assertEqual(
            [(reference.reference, reference.how) for reference in answer.references],
            [(f"actions/checkout@{COMMIT}", None), ("actions/setup-go@v5", TAG), ("x/y@main", BRANCH)],
        )
        self.assertEqual(pinning("actions/checkout"), UNPINNED)

    def test_the_policy_may_allow_official_tags(self) -> None:
        with temp_project({GITHUB_WORKFLOW: _workflow("actions/setup-go@v5")}) as root:
            answer = pinning_answer(make_context(root).facts)
        self.assertEqual(judge_pinning(answer).status, Status.WARN)
        self.assertEqual(judge_pinning(answer, allow_official_tags=True).status, Status.PASS)

    def test_no_provider_with_reusable_steps_is_impossible(self) -> None:
        with temp_project({CI_FILES["Travis CI"]: "script: make\n"}) as root:
            answer = pinning_answer(make_context(root).facts)
        self.assertEqual(answer.answer, Answer.IMPOSSIBLE)
        self.assertEqual(judge_pinning(answer), Result.skipped("no CI configuration with reusable steps"))


class CiLintTests(unittest.TestCase):
    def test_the_answer_names_each_providers_linters(self) -> None:
        files = {**github_steps("run: actionlint"), CI_FILES["Jenkins"]: "sh 'make'"}
        with temp_project(files) as root:
            answer = ci_lint_answer(make_context(root).facts)
        self.assertEqual(answer.answer, Answer.YES)
        self.assertEqual(
            [(found.provider, found.linters, found.lintable) for found in answer.providers],
            [("GitHub Actions", ("actionlint",), True), ("Jenkins", (), False)],
        )
        self.assertEqual(
            judge_ci_lint(answer), Result.passed("CI lints its configuration (GitHub Actions: actionlint)")
        )

    def test_without_ci_or_without_a_known_linter_the_question_is_impossible(self) -> None:
        with temp_project({}) as root:
            self.assertEqual(ci_lint_answer(make_context(root).facts).answer, Answer.IMPOSSIBLE)
        with temp_project({CI_FILES["Jenkins"]: "sh 'make'"}) as root:
            answer = ci_lint_answer(make_context(root).facts)
        self.assertEqual(answer.answer, Answer.IMPOSSIBLE)
        self.assertEqual(judge_ci_lint(answer), Result.skipped("no configuration linter is known for Jenkins"))


class SecretScanningTests(unittest.TestCase):
    def test_the_answer_names_the_scanners_run_and_configured(self) -> None:
        files = {**github_steps("uses: gitleaks/gitleaks-action@v2"), ".secrets.baseline": "{}"}
        with temp_project(files) as root:
            answer = secret_scanning_answer(make_context(root).facts)
        self.assertEqual(
            (answer.answer, answer.scanners, answer.configured), (Answer.YES, ("gitleaks",), ("detect-secrets",))
        )
        self.assertEqual(judge_secret_scanning(answer), Result.passed("secrets are scanned for with gitleaks"))

    def test_configured_but_not_run_warns(self) -> None:
        with temp_project({".gitleaks.toml": ""}) as root:
            answer = secret_scanning_answer(make_context(root).facts)
        self.assertEqual((answer.answer, answer.scanners, answer.configured), (Answer.NO, (), ("gitleaks",)))
        self.assertEqual(judge_secret_scanning(answer).status, Status.WARN)
        self.assertIn(
            "gitleaks is configured, but neither CI nor a pre-commit hook runs it",
            judge_secret_scanning(answer).message,
        )
