"""GitLab's `rules:` and `only:`/`except:`, settled as far as the pipeline shows (upstream #361): whether a job runs,
runs in the runs CI makes (on the branch, the pipeline's source), or requires a variable the pipeline does not set,
which GitLab's settings may."""

from __future__ import annotations

import unittest
from collections.abc import Mapping

from project_validator.ci.gitlab_rules import RUNS, job_requirement

VARIABLES = {"COVERAGE": "true", "EMPTY": ""}


def _rules(*rules: Mapping[str, object]) -> str | bool:
    return job_requirement({"rules": list(rules)}, VARIABLES)


class RulesTests(unittest.TestCase):
    def test_a_job_with_no_rules_runs(self) -> None:
        self.assertIs(job_requirement({}, VARIABLES), RUNS)

    def test_the_first_rule_that_matches_decides(self) -> None:
        for rules, expected in (
            (({"if": '$COVERAGE == "true"'},), RUNS),
            (({"if": '$COVERAGE == "false"'},), False),  # no rule matches
            (({"if": "$COVERAGE", "when": "never"}, {"when": "always"}), False),
            (({"if": "$EMPTY", "when": "never"}, {"when": "on_success"}), RUNS),
            (({"if": '$COVERAGE != "true" || $EMPTY'}, {"when": "never"}), False),
            (({"if": "$COVERAGE =~ /^t/"},), RUNS),
            (({"if": "$COVERAGE !~ /^t/i"},), False),
            (({"if": "($COVERAGE == 'true') && $EMPTY == \"\""},), RUNS),
            (({"if": "$COVERAGE != null"},), RUNS),
        ):
            with self.subTest(rules=rules):
                self.assertEqual(_rules(*rules), expected)

    def test_a_rule_on_the_run_holds_in_some_runs(self) -> None:
        for rule in (
            {"if": '$CI_PIPELINE_SOURCE == "merge_request_event"'},
            {"if": "$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH"},
            {"changes": ["src/**/*"]},
            {"if": "$CI_COMMIT_TAG", "when": "never"},  # and then the next
        ):
            with self.subTest(rule=rule):
                self.assertIs(_rules(rule, {"when": "on_success"}), RUNS)

    def test_a_rule_on_a_variable_the_pipeline_does_not_set_is_required(self) -> None:
        self.assertEqual(_rules({"if": '$RUN_LINT == "true"'}), '$RUN_LINT == "true"')
        self.assertEqual(_rules({"if": "$SKIP", "when": "never"}, {"when": "always"}), "not ($SKIP)")
        self.assertEqual(_rules({"if": "$X == ("}), "$X == (")  # not read

    def test_a_manual_job_is_required_of_a_person(self) -> None:
        self.assertEqual(_rules({"when": "manual"}), "someone starts it")
        self.assertEqual(job_requirement({"when": "manual"}, VARIABLES), "someone starts it")
        self.assertIs(job_requirement({"when": "never"}, VARIABLES), False)


class ExpressionTests(unittest.TestCase):
    def test_what_is_not_known_combines_by_what_it_rests_on(self) -> None:
        for condition, expected in (
            ("$CI_COMMIT_TAG || $RUN_LINT", RUNS),  # the run may hold it, whatever the settings say
            ("$CI_COMMIT_TAG && $CI_COMMIT_BRANCH", RUNS),
            ("$CI_COMMIT_TAG && $RUN_LINT", "$CI_COMMIT_TAG && $RUN_LINT"),
            ("$RUN_A || $RUN_B", "$RUN_A || $RUN_B"),
            ("$RUN_LINT || $EMPTY", "$RUN_LINT || $EMPTY"),
            ("$RUN_LINT && $COVERAGE", "$RUN_LINT && $COVERAGE"),
            ("$COVERAGE =~ /^T/i", RUNS),
            ("$COVERAGE =~ /^T/", False),
        ):
            with self.subTest(condition=condition):
                self.assertEqual(_rules({"if": condition}), expected)

    def test_what_does_not_read_is_required(self) -> None:
        for condition in ('$COVERAGE =~ "t"', "$COVERAGE =~ /(/", '$COVERAGE == "a" "b"', "($COVERAGE", "$X ="):
            with self.subTest(condition=condition):
                self.assertEqual(_rules({"if": condition}), condition)


class RuleOrderTests(unittest.TestCase):
    def test_a_rule_never_required_lets_the_rest_decide(self) -> None:
        self.assertIs(_rules({"if": "$SKIP", "when": "never"}), False)
        self.assertEqual(_rules({"if": "$SKIP", "when": "never"}, {"if": "$RUN"}), "not ($SKIP) and $RUN")

    def test_files_that_exist_or_change_say_which_runs(self) -> None:
        self.assertIs(_rules({"exists": ["Dockerfile"], "when": "never"}, {"when": "always"}), RUNS)

    def test_a_rule_that_is_no_mapping_is_passed_over(self) -> None:
        self.assertIs(_rules("junk", {"when": "always"}), RUNS)  # type: ignore[arg-type]


class OnlyExceptTests(unittest.TestCase):
    def test_only_and_except_variables(self) -> None:
        for job, expected in (
            ({"only": {"variables": ['$COVERAGE == "true"']}}, RUNS),
            ({"only": {"variables": ['$COVERAGE == "false"']}}, False),
            ({"except": {"variables": ["$COVERAGE"]}}, False),
            ({"only": {"variables": ["$RUN_LINT"]}}, "$RUN_LINT"),
            ({"except": {"variables": ["$SKIP"]}}, "not ($SKIP)"),
            ({"only": ["main", "merge_requests"]}, RUNS),  # refs: some runs
            ({"only": {"refs": ["tags"], "variables": ["$COVERAGE"]}}, RUNS),
            ({"only": {"refs": ["main"]}}, RUNS),
            ({"only": {"variables": ["$A"]}, "except": {"variables": ["$B"]}}, "$A and not ($B)"),
        ):
            with self.subTest(job=job):
                self.assertEqual(job_requirement(job, VARIABLES), expected)
