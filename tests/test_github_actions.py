from __future__ import annotations

import json
import unittest

from project_validator.ci.github_actions import (
    Combination,
    action_references,
    expand_matrix,
    substitute_matrix,
)
from project_validator.facts import Command, Unknown
from project_validator.facts.jobs import Job
from tests.support import GITHUB_WORKFLOW, ci_jobs, make_context, temp_project


class ExpandMatrixTests(unittest.TestCase):
    def test_without_matrix_runs_once(self) -> None:
        self.assertEqual(expand_matrix(None), [{}])

    def test_expression_matrix_cannot_be_expanded(self) -> None:
        self.assertIsNone(expand_matrix("${{ fromJSON(needs.setup.outputs.matrix) }}"))
        self.assertIsNone(expand_matrix({"os": "${{ fromJSON(inputs.os) }}"}))

    def test_cartesian_product(self) -> None:
        self.assertEqual(
            expand_matrix({"os": ["a", "b"], "cc": ["x", "y"]}),
            [{"os": "a", "cc": "x"}, {"os": "a", "cc": "y"}, {"os": "b", "cc": "x"}, {"os": "b", "cc": "y"}],
        )

    def test_exclude_removes_partially_matching_combinations(self) -> None:
        matrix = {"os": ["a", "b"], "cc": ["x", "y"], "exclude": [{"os": "b"}]}
        self.assertEqual(expand_matrix(matrix), [{"os": "a", "cc": "x"}, {"os": "a", "cc": "y"}])

    def test_include_extends_matching_combinations(self) -> None:
        matrix = {"cc": ["gcc", "clang"], "include": [{"cc": "gcc", "cxx": "g++"}, {"extra": "all"}]}
        self.assertEqual(
            expand_matrix(matrix),
            [{"cc": "gcc", "cxx": "g++", "extra": "all"}, {"cc": "clang", "extra": "all"}],
        )

    def test_include_that_would_overwrite_original_values_adds_a_combination(self) -> None:
        matrix = {"cc": ["gcc"], "include": [{"cc": "msvc", "os": "windows"}]}
        self.assertEqual(expand_matrix(matrix), [{"cc": "gcc"}, {"cc": "msvc", "os": "windows"}])

    def test_include_only_matrix(self) -> None:
        self.assertEqual(expand_matrix({"include": [{"os": "a"}, {"os": "b"}]}), [{"os": "a"}, {"os": "b"}])


class SubstituteMatrixTests(unittest.TestCase):
    def test_substitutes_nested_values_and_keeps_unknown_ones(self) -> None:
        combination: Combination = {"config": {"os": "windows-latest"}, "cc": "gcc"}
        self.assertEqual(
            substitute_matrix("${{ matrix.config.os }} ${{matrix.cc}} ${{ matrix.nope }}", combination),
            "windows-latest gcc ${{ matrix.nope }}",
        )


class WorkflowJobTests(unittest.TestCase):
    def _jobs(self, workflow: object) -> tuple[Job, ...]:
        return ci_jobs({GITHUB_WORKFLOW: json.dumps(workflow)})

    def test_compilers_come_from_matrix_values(self) -> None:
        workflow = {
            "jobs": {
                "build": {
                    "runs-on": "${{ matrix.config.os }}",
                    "strategy": {"matrix": {"config": [{"os": "ubuntu-latest", "cxx": "clang++"}]}},
                    "steps": [{"run": "install gcc"}],
                }
            }
        }
        [job] = self._jobs(workflow)
        self.assertEqual((job.os, job.compilers, job.default_compiler), ("linux", frozenset({"clang"}), False))

    def test_compilers_fall_back_to_what_the_job_runs_then_runner_default(self) -> None:
        workflow = {
            "jobs": {
                "named": {"runs-on": "macos-latest", "steps": [{"run": "brew install gcc"}]},
                "unnamed": {"runs-on": "windows-latest", "steps": [{"run": "cmake --build build"}]},
            }
        }
        named, unnamed = self._jobs(workflow)
        self.assertEqual(named.compilers, frozenset({"gcc"}))
        self.assertEqual((unnamed.compilers, unnamed.default_compiler), (frozenset({"msvc"}), True))

    def test_step_names_conditions_and_unevaluated_inputs_name_no_compiler(self) -> None:
        workflow = {
            "jobs": {
                "build": {
                    "runs-on": "ubuntu-latest",
                    "steps": [
                        {"name": "Build with clang", "if": "github.ref == 'msvc'", "run": "cmake --build build"},
                        {"uses": "aminya/setup-cpp@v1", "with": {"vcvarsall": "${{ contains(github.ref, 'x') }}"}},
                        {"uses": "ilammy/msvc-dev-cmd@v1", "if": "runner.os == 'Windows'"},
                        {"uses": "aminya/setup-cpp@v1", "with": {"vcvarsall": "${{ runner.os == 'Windows' }}"}},
                        {"if": "runner.os == 'Windows'", "run": "cl.exe /W4 main.cpp"},
                    ],
                }
            }
        }
        [job] = self._jobs(workflow)
        self.assertEqual((job.compilers, job.default_compiler), (frozenset({"gcc"}), True))

    def test_container_jobs_run_on_linux(self) -> None:
        workflow = {"jobs": {"c": {"runs-on": "self-hosted", "container": "gcc:14", "steps": []}}}
        self.assertEqual(self._jobs(workflow)[0].os, "linux")

    def test_reusable_workflow_calls_are_not_jobs_here(self) -> None:
        self.assertEqual(self._jobs({"jobs": {"call": {"uses": "org/repo/.github/workflows/x.yml@v1"}}}), ())

    def test_expression_matrix_is_reported_as_unknown(self) -> None:
        workflow = {"jobs": {"j": {"runs-on": "ubuntu-latest", "strategy": {"matrix": "${{ fromJSON(x) }}"}}}}
        [job] = self._jobs(workflow)
        self.assertEqual(job.os, "linux")
        self.assertIn("expression", job.name)

    def test_steps_conditioned_on_a_computed_matrix_still_run(self) -> None:
        """When the matrix is computed by an expression, a step `if: matrix.x` may run in some combination: it is
        kept, with its condition as written, beside the unknown that says the matrix was not read."""
        workflow = {
            "jobs": {
                "test": {
                    "runs-on": "ubuntu-latest",
                    "strategy": {"matrix": "${{ fromJSON(needs.plan.outputs.matrix) }}"},
                    "steps": [
                        {"run": "pytest"},
                        {"if": "matrix.coverage == 'true'", "run": "coverage run --branch -m pytest"},
                        {"if": "matrix.lint", "run": "ruff check ."},
                    ],
                }
            }
        }
        with temp_project({GITHUB_WORKFLOW: json.dumps(workflow)}) as root:
            facts = make_context(root).facts
        commands = [command for command in facts.of(Command) if not command.via]  # not what they run in turn
        self.assertEqual(
            [command.argv for command in commands],
            [("pytest",), ("coverage", "run", "--branch", "-m", "pytest"), ("ruff", "check", ".")],
        )
        self.assertEqual([command.condition for command in commands][1:], ["matrix.coverage == 'true'", "matrix.lint"])
        self.assertEqual([unknown.hides for unknown in facts.of(Unknown)], ["matrix"])

    def test_a_job_whose_condition_is_false_does_not_run(self) -> None:
        workflow = {
            "jobs": {
                "windows-only": {
                    "if": "matrix.os == 'windows-latest'",
                    "strategy": {"matrix": {"os": ["ubuntu-latest", "windows-latest"]}},
                    "runs-on": "${{ matrix.os }}",
                    "steps": [],
                }
            }
        }
        self.assertEqual([job.os for job in self._jobs(workflow)], ["windows"])

    def test_documents_without_jobs_have_none(self) -> None:
        self.assertEqual(ci_jobs({GITHUB_WORKFLOW: "name: x\n"}), ())


class ActionReferencesTests(unittest.TestCase):
    def test_lists_the_actions_and_reusable_workflows_a_workflow_uses(self) -> None:
        workflow = {
            "jobs": {
                "build": {"steps": [{"uses": "actions/checkout@v4"}, {"run": "make"}, {"uses": "./.github/actions/x"}]},
                "release": {"uses": "octo/workflows/.github/workflows/release.yml@main"},
                "odd": {"steps": "not a list"},
                "broken": "not a job",
            }
        }
        self.assertEqual(
            action_references(workflow),
            ["octo/workflows/.github/workflows/release.yml@main", "actions/checkout@v4", "./.github/actions/x"],
        )

    def test_a_document_that_is_not_a_workflow_uses_nothing(self) -> None:
        documents: tuple[object, ...] = (None, [], {"jobs": []}, {"on": "push"})
        for document in documents:
            with self.subTest(document=document):
                self.assertEqual(action_references(document), [])
