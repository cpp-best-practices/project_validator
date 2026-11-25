"""Commands that run only under a condition (upstream #361): a condition the job settles is followed; one on the run
(the event, the branch) holds in the runs CI makes; one on configuration the checkout does not show is required, and
what the command would run is unknown."""

from __future__ import annotations

import json
import unittest

from project_validator.checks.static_analysis import static_analysis
from project_validator.core import Result, Status
from project_validator.facts import Command
from tests.support import GITHUB_WORKFLOW, make_context, temp_project

PYTHON = {"pyproject.toml": "[project]\nname = 'app'\n", "app/__init__.py": ""}
PASSED = Status.PASS


def _workflow(step: dict[str, object], **job: object) -> dict[str, str]:
    steps = [{"run": "pytest"}, {"run": "ruff check .", **step}]
    return {GITHUB_WORKFLOW: json.dumps({"jobs": {"lint": {"runs-on": "ubuntu-latest", "steps": steps, **job}}})}


def _run(files: dict[str, str]) -> Result:
    with temp_project({**PYTHON, **files}) as root:
        return static_analysis.run(make_context(root))


class GithubConditionTests(unittest.TestCase):
    def test_a_step_on_the_event_or_branch_runs(self) -> None:
        for condition in ("github.event_name == 'push'", "github.ref == 'refs/heads/main'", "steps.x.outputs.py"):
            with self.subTest(condition=condition):
                self.assertEqual(_run(_workflow({"if": condition})).status, Status.PASS)

    def test_a_step_on_configuration_is_unknown(self) -> None:
        for workflow in (
            _workflow({"if": "secrets.LINT_TOKEN != ''"}),
            _workflow({}, **{"if": "vars.LINT == 'true'"}),  # the job's condition
        ):
            with self.subTest(workflow=workflow):
                result = _run(workflow)
                self.assertEqual(result.status, Status.ERROR, result)
                self.assertIn("runs only if", result.details[0])

    def test_a_step_on_an_environment_variable_the_job_does_not_set_does_not_run(self) -> None:
        self.assertEqual(_run(_workflow({"if": "env.LINT == 'true'"})).status, Status.FAIL)
        self.assertEqual(_run(_workflow({"if": "env.LINT == 'true'"}, env={"LINT": "true"})).status, Status.PASS)

    def test_what_a_required_step_runs_in_turn_is_required(self) -> None:
        for step in ({"uses": "astral-sh/ruff-action@v3"}, {"run": "make lint"}):
            steps = [{"if": "secrets.T != ''", **step}]
            files = {
                "Makefile": "lint:\n\truff check .\n",
                GITHUB_WORKFLOW: json.dumps({"jobs": {"lint": {"runs-on": "ubuntu-latest", "steps": steps}}}),
            }
            with self.subTest(step=step):
                self.assertEqual(_run(files).status, Status.ERROR)

    def test_an_input_its_caller_computes_is_weighed_by_what_the_caller_tests(self) -> None:
        """poetry's: the caller passes `needs.changes.outputs.tests == 'true'`, which rests on the run."""
        called = {
            "on": {"workflow_call": {"inputs": {"lint": {"type": "boolean"}}}},
            "jobs": {"lint": {"if": "inputs.lint", "runs-on": "ubuntu-latest", "steps": [{"run": "ruff check ."}]}},
        }
        for value, expected in (
            ("${{ needs.changes.outputs.py == 'true' }}", Status.PASS),
            ("${{ vars.LINT == 'true' }}", Status.ERROR),
        ):
            caller = {"jobs": {"call": {"uses": "./.github/workflows/lint.yml", "with": {"lint": value}}}}
            files = {GITHUB_WORKFLOW: json.dumps(caller), ".github/workflows/lint.yml": json.dumps(called)}
            with self.subTest(value=value):
                self.assertEqual(_run(files).status, expected)

    def test_a_variable_an_earlier_step_may_set_is_the_runs(self) -> None:
        """neovim's: a step sets `have_coverity_token` only when the secret is there; and an action may set any."""
        for earlier in (
            {"run": 'if [ -n "$T" ]; then echo "LINT=yes" >> $GITHUB_ENV; fi'},
            {"uses": "some/action@v1"},
            {"uses": "actions/github-script@v7"},  # GitHub's, but it may export any
        ):
            steps = [earlier, {"if": "env.LINT", "run": "ruff check ."}]
            files = {GITHUB_WORKFLOW: json.dumps({"jobs": {"lint": {"runs-on": "ubuntu-latest", "steps": steps}}})}
            with self.subTest(earlier=earlier):
                self.assertEqual(_run(files).status, Status.PASS)
        steps = [{"uses": "actions/checkout@v4"}, {"if": "env.LINT", "run": "ruff check ."}]
        files = {GITHUB_WORKFLOW: json.dumps({"jobs": {"lint": {"runs-on": "ubuntu-latest", "steps": steps}}})}
        self.assertEqual(_run(files).status, Status.FAIL)  # GitHub's own checkout sets none

    def test_the_command_records_what_it_requires(self) -> None:
        with temp_project({**PYTHON, **_workflow({"if": "secrets.T != ''"}, **{"if": "vars.V"})}) as root:
            commands = make_context(root).facts.of(Command)
        self.assertEqual([command.requires for command in commands], ["vars.V", "vars.V and secrets.T != ''"])


# argo-cd's: the tests measure coverage only when the environment sets COVERAGE_ENABLED.
MAKEFILE = "lint:\nifeq ($(LINT_ENABLED),true)\n\truff check .\nendif\n\tpytest\n"


def _make(*lines: str, env: dict[str, str] | None = None, makefile: str = MAKEFILE) -> dict[str, str]:
    job = {"runs-on": "ubuntu-latest", "steps": [{"run": line} for line in lines], **({"env": env} if env else {})}
    return {"Makefile": makefile, GITHUB_WORKFLOW: json.dumps({"jobs": {"lint": job}})}


class MakeConditionTests(unittest.TestCase):
    def test_a_variable_the_job_does_not_set_is_empty(self) -> None:
        self.assertEqual(_run(_make("make lint")).status, Status.FAIL)

    def test_a_variable_the_job_or_command_line_sets_decides(self) -> None:
        for files in (_make("make lint", env={"LINT_ENABLED": "true"}), _make("LINT_ENABLED=true make lint")):
            with self.subTest(files=files):
                self.assertEqual(_run(files).status, PASSED)

    def test_a_default_the_job_does_not_override_holds(self) -> None:
        """coreutils' `MANPAGES ?= y`, then `ifeq ($(MANPAGES),y)`; and a variable appended to before it is set."""
        for makefile in (
            "LINT ?= y\nlint:\nifeq ($(LINT),y)\n\truff check .\nendif\n",
            "LINT += y\nlint:\nifeq ($(LINT),y)\n\truff check .\nendif\n",
        ):
            with self.subTest(makefile=makefile):
                self.assertEqual(_run(_make("make lint", makefile=makefile)).status, PASSED)
                self.assertEqual(_run(_make("make lint", env={"LINT": "n"}, makefile=makefile)).status, Status.FAIL)

    def test_makes_conditional_functions_are_evaluated(self) -> None:
        """argo-cd's: `ifneq ($(if $(X),,ALL),)`."""
        for test, expected in (
            ("ifneq ($(if $(LINT),,ALL),)", PASSED),
            ("ifeq ($(if $(CI),yes,no),yes)", PASSED),
            ("ifeq ($(if $(LINT),yes),)", PASSED),
            ("ifeq ($(or $(LINT),$(CI)),true)", PASSED),
            ("ifeq ($(and $(CI),$(LINT)),)", PASSED),
            ("ifeq ($(and $(CI),x),x)", PASSED),
        ):
            with self.subTest(test=test):
                makefile = f"lint:\n{test}\n\truff check .\nendif\n"
                self.assertEqual(_run(_make("make lint", makefile=makefile)).status, expected)

    def test_ci_is_set(self) -> None:
        makefile = "lint:\nifdef CI\n\truff check .\nendif\n"
        self.assertEqual(_run(_make("make lint", makefile=makefile)).status, PASSED)

    def test_a_runner_variable_is_required(self) -> None:
        makefile = "lint:\nifeq ($(GITHUB_EVENT_NAME),push)\n\truff check .\nendif\n"
        result = _run(_make("make lint", makefile=makefile))
        self.assertEqual(result.status, Status.ERROR)
        self.assertIn("runs only if $(GITHUB_EVENT_NAME) == push", result.details[0])

    def test_a_recipe_that_runs_somewhere_without_a_requirement_runs(self) -> None:
        """On a self-hosted runner of any platform, a recipe that runs on Windows, or else where a runner variable
        says, runs: on a Windows host."""
        makefile = (
            "ifeq ($(OS),Windows_NT)\nLINT = 1\nendif\nifeq ($(GITHUB_REF_NAME),main)\nLINT = 1\nendif\n"
            "lint:\nifdef LINT\n\truff check .\nendif\n"
        )
        job = {"runs-on": "self-hosted", "steps": [{"run": "make lint"}]}
        files = {"Makefile": makefile, GITHUB_WORKFLOW: json.dumps({"jobs": {"lint": job}})}
        self.assertEqual(_run(files).status, PASSED)

    def test_an_included_makefile_is_read_in_the_jobs_environment_too(self) -> None:
        for includes in ({"lint.mk": MAKEFILE}, {"lint.mk": "include deep.mk\n", "deep.mk": MAKEFILE}):
            with self.subTest(includes=includes):
                files = {**_make("make lint", makefile="include lint.mk\n"), **includes}
                self.assertEqual(_run(files).status, Status.FAIL)

    def test_makes_own_defaults_hold_unless_the_job_sets_them(self) -> None:
        cc = "lint:\nifeq ($(CC),cc)\n\truff check .\nendif\n"
        self.assertEqual(_run(_make("make lint", makefile=cc)).status, PASSED)
        makefile = "lint:\nifeq ($(CC),clang)\n\truff check .\nendif\n"
        self.assertEqual(_run(_make("make lint", makefile=makefile)).status, Status.FAIL)
        self.assertEqual(_run(_make("make lint", env={"CC": "clang"}, makefile=makefile)).status, PASSED)

    def test_a_service_that_adds_its_settings_variables_requires_them(self) -> None:
        """GitLab passes a job the variables its settings define, which the checkout does not show: one the pipeline
        does not set is required, not empty."""
        gitlab = {"Makefile": MAKEFILE, ".gitlab-ci.yml": "lint:\n  script:\n    - make lint\n"}
        result = _run(gitlab)
        self.assertEqual(result.status, Status.ERROR)
        self.assertIn("runs only if $(LINT_ENABLED) == true", result.details[0])


def _gitlab(rules: str, variables: str = "") -> dict[str, str]:
    return {".gitlab-ci.yml": f"{variables}lint:\n  script:\n    - ruff check .\n  rules:\n{rules}"}


class GitlabConditionTests(unittest.TestCase):
    def test_rules_settle_where_the_job_runs(self) -> None:
        for files, expected in (
            (_gitlab("    - if: $CI_PIPELINE_SOURCE == 'merge_request_event'\n"), Status.PASS),
            (_gitlab("    - if: $LINT == 'yes'\n", "variables:\n  LINT: 'yes'\n"), Status.PASS),
            (_gitlab("    - if: $LINT == 'yes'\n", "variables:\n  LINT: 'no'\n"), Status.FAIL),
            (_gitlab("    - when: never\n"), Status.FAIL),
            (_gitlab("    - if: $RUN_LINT\n"), Status.ERROR),  # the project's settings may set it
        ):
            with self.subTest(files=files):
                self.assertEqual(_run(files).status, expected)
