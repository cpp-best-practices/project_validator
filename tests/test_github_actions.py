from __future__ import annotations

import json
import unittest
from collections.abc import Mapping

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

    def test_service_containers_are_the_jobs_services(self) -> None:
        workflow = {
            "jobs": {
                "test": {
                    "runs-on": "ubuntu-latest",
                    "strategy": {"matrix": {"pg": ["16", "17"]}},
                    "services": {
                        "postgres": {"image": "postgres:${{ matrix.pg }}", "ports": ["5432:5432"]},
                        "cache": "redis:7",
                        "odd": 3,
                    },
                    "steps": [{"run": "pytest"}],
                }
            }
        }
        jobs = self._jobs(workflow)
        self.assertEqual(
            sorted(sorted(job.services) for job in jobs), [["postgres:16", "redis:7"], ["postgres:17", "redis:7"]]
        )
        self.assertEqual(
            self._jobs({"jobs": {"a": {"runs-on": "ubuntu-latest", "steps": []}}})[0].services, frozenset()
        )

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


class ConditionalExportTests(unittest.TestCase):
    def test_an_export_that_runs_only_sometimes_is_not_known(self) -> None:
        from project_validator.ci.github_actions import _exported

        always = 'echo "A=1" >> $GITHUB_ENV\nx; echo "B=2" >> "$GITHUB_ENV"'
        sometimes = (
            'if x; then\n  echo "C=1" >> $GITHUB_ENV\nfi\n'
            '[ y ] && echo "D=1" >> $GITHUB_ENV\nz || echo "E=1" >> $GITHUB_ENV'
        )
        self.assertEqual(_exported(always), {"A": "1", "B": "2"})
        self.assertEqual(_exported(sometimes), {})


class AdvisoryStepTests(unittest.TestCase):
    """A step that cannot fail the job (`continue-on-error`) runs, but only advises: its commands say why."""

    def _commands(self, job: Mapping[str, object]) -> list[Command]:
        workflow = {"jobs": {"check": {"runs-on": "ubuntu-latest", **job}}}
        with temp_project({GITHUB_WORKFLOW: json.dumps(workflow)}) as root:
            return [command for command in make_context(root).facts.of(Command) if not command.via]

    def test_a_step_that_continues_on_error_is_advisory(self) -> None:
        commands = self._commands(
            {"steps": [{"run": "make linkcheck", "continue-on-error": True}, {"run": "make html"}]}
        )
        self.assertEqual(
            [(command.argv, command.advisory) for command in commands],
            [(("make", "linkcheck"), "continue-on-error"), (("make", "html"), "")],
        )

    def test_a_job_that_continues_on_error_makes_every_step_advisory(self) -> None:
        commands = self._commands({"continue-on-error": True, "steps": [{"run": "ruff check ."}]})
        self.assertEqual([command.advisory for command in commands], ["continue-on-error"])

    def test_continue_on_error_is_evaluated_per_combination(self) -> None:
        job = {
            "strategy": {"matrix": {"python": ["3.13", "3.14-dev"], "include": [{"python": "3.14-dev", "dev": True}]}},
            "continue-on-error": "${{ matrix.dev == true }}",
            "steps": [{"run": "pytest"}],
        }
        self.assertEqual([command.advisory for command in self._commands(job)], ["", "continue-on-error"])

    def test_continue_on_error_false_is_a_gate(self) -> None:
        commands = self._commands({"steps": [{"run": "pytest", "continue-on-error": False}]})
        self.assertEqual([command.advisory for command in commands], [""])

    def test_an_unknown_continue_on_error_is_advisory_and_unknown(self) -> None:
        workflow = {
            "jobs": {
                "check": {
                    "runs-on": "ubuntu-latest",
                    "steps": [{"run": "pytest", "continue-on-error": "${{ needs.plan.outputs.optional }}"}],
                }
            }
        }
        with temp_project({GITHUB_WORKFLOW: json.dumps(workflow)}) as root:
            facts = make_context(root).facts
        self.assertEqual([command.advisory for command in facts.of(Command)], ["continue-on-error"])
        self.assertEqual(
            [(unknown.subject, unknown.hides) for unknown in facts.of(Unknown)],
            [("whether a step of job check can fail it", "commands")],
        )


class CalledWorkflowInputTests(unittest.TestCase):
    """A called workflow's `inputs.*` are what the caller passes, where that is known (#211)."""

    def _commands(self, passed: str, default: str = "18") -> list[tuple[str, ...]]:
        caller = {"jobs": {"call": {"uses": "./.github/workflows/w.yml", "with": {"node-version": passed}}}}
        called = {
            "on": {"workflow_call": {"inputs": {"node-version": {"type": "string", "default": default}}}},
            "jobs": {"t": {"runs-on": "ubuntu-latest", "steps": [{"run": "echo ${{ inputs.node-version }}"}]}},
        }
        files = {GITHUB_WORKFLOW: json.dumps(caller), ".github/workflows/w.yml": json.dumps(called)}
        with temp_project(files) as root:
            return [command.argv for command in make_context(root).facts.of(Command)]

    def test_a_known_value_is_the_input(self) -> None:
        self.assertEqual(self._commands("24"), [("echo", "24")])

    def test_a_value_that_is_not_known_leaves_the_input_unknown_not_its_default(self) -> None:
        passed = "${{ github.event_name == 'workflow_dispatch' && inputs.node-version || '24' }}"
        self.assertEqual(self._commands(passed), [("echo", "${{ inputs.node-version }}")])


class ContainerImageInputTests(unittest.TestCase):
    def test_an_image_input_that_is_empty_off_linux_is_no_container(self) -> None:
        """googletest's cmake.yml: `container: image: ${{ inputs.container_image }}`, passed `''` for macOS and
        Windows, so those jobs run on their runners, not in a Linux container."""
        caller = {
            "jobs": {
                "cmake": {
                    "strategy": {
                        "matrix": {"config": [{"os": "ubuntu-24.04", "image": "gcc:14"}, {"os": "windows-2022"}]}
                    },
                    "uses": "./.github/workflows/w.yml",
                    "with": {"os": "${{ matrix.config.os }}", "container_image": "${{ matrix.config.image || '' }}"},
                }
            }
        }
        called = {
            "on": {"workflow_call": {"inputs": {"os": {"type": "string"}, "container_image": {"type": "string"}}}},
            "jobs": {"t": {"runs-on": "${{ inputs.os }}", "container": {"image": "${{ inputs.container_image }}"}}},
        }
        files = {GITHUB_WORKFLOW: json.dumps(caller), ".github/workflows/w.yml": json.dumps(called)}
        self.assertEqual(sorted(job.os for job in ci_jobs(files)), ["linux", "windows"])
