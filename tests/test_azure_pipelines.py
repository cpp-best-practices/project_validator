"""Azure Pipelines: a pipeline is read as its stages' jobs (each matrix leg a job) and the commands of their steps and
known tasks (upstream #223)."""

from __future__ import annotations

import json
import unittest

from project_validator.facts import CiConfiguration, CiJob, Command, Facts, Unknown
from tests.support import argvs, ci_jobs, config_facts


def _facts(pipeline: object, path: str = "azure-pipelines.yml", **files: str) -> Facts:
    return config_facts(path, pipeline, **files)


# Humanizer's and Newtonsoft's tasks.
TASKS = {
    "pool": {"vmImage": "ubuntu-latest"},
    "steps": [
        {"task": "UseDotNet@2", "inputs": {"version": "10.0.x"}},
        {"task": "UseDotNet@2", "inputs": {"version": "8.0.x"}},
        {
            "task": "DotNetCoreCLI@2",
            "inputs": {
                "command": "custom",
                "custom": "test",
                "arguments": "--coverage --coverage-output-format cobertura",
            },
        },
        {
            "task": "DotNetCoreCLI@2",
            "inputs": {"command": "build", "projects": "src/App.sln", "arguments": "-c Release"},
        },
        {"task": "CmdLine@2", "inputs": {"script": "echo hi"}},
        {"task": "PublishTestResults@2", "inputs": {"testResultsFiles": "**/*.trx"}},
    ],
}


# The ansible collections' matrix.yml, which makes a job of each target, and test.yml, which says what each runs.
ANSIBLE_TEMPLATES = {
    "templates/matrix.yml": """\
parameters:
  - name: targets
    type: object
jobs:
  - template: test.yml
    parameters:
      jobs:
        - ${{ each target in parameters.targets }}:
            - name: ${{ target.name }}
              test: ${{ target.test }}
""",
    "templates/test.yml": """\
parameters:
  - name: jobs
    type: object
jobs:
  - ${{ each job in parameters.jobs }}:
      - job: test_${{ replace(job.test, '/', '_') }}
        displayName: ${{ job.name }}
        steps:
          - script: ansible-test ${{ job.test }}
""",
    "templates/stage.yml": """\
stages:
  - stage: Docs
    jobs:
      - job: docs
        steps:
          - script: make docs
""",
}


class AzurePipelinesTests(unittest.TestCase):
    def test_a_pipeline_of_steps_is_one_job_on_its_pool(self) -> None:
        """hledger's: `script:` steps run in bash on Linux and in cmd on Windows; `bash:` and `pwsh:` name their
        shell."""
        pipeline = {
            "pool": {"vmImage": "windows-2022"},
            "steps": [
                {"script": "curl -skL -ostack.zip http://www.stackage.org/stack/windows-x86_64"},
                {"script": "stack build --copy-bins --local-bin-path=.", "displayName": "build"},
                {"pwsh": "./build.ps1 -Configuration Release"},
                {"checkout": "self"},
            ],
        }
        facts = _facts(pipeline)
        [job] = facts.of(CiJob)
        self.assertEqual((job.os, job.provider), ("windows", "Azure Pipelines"))
        self.assertEqual(
            argvs(facts)[1:],
            [("stack", "build", "--copy-bins", "--local-bin-path=."), ("./build.ps1", "-Configuration", "Release")],
        )
        self.assertFalse([unknown for unknown in facts.of(Unknown) if "heuristically" in unknown.reason])

    def test_each_matrix_leg_of_each_job_of_each_stage_is_a_job(self) -> None:
        pipeline = {
            "variables": {"CONFIG": "Release"},
            "stages": [
                {
                    "stage": "test",
                    "jobs": [
                        {
                            "job": "unit",
                            "strategy": {
                                "matrix": {
                                    "linux": {"imageName": "ubuntu-latest", "CC": "gcc"},
                                    "mac": {"imageName": "macOS-latest", "CC": "clang"},
                                }
                            },
                            "pool": {"vmImage": "$(imageName)"},
                            "steps": [{"bash": "cmake -B b -DCMAKE_BUILD_TYPE=$(CONFIG) -DCMAKE_C_COMPILER=$(CC)"}],
                        },
                        {"job": "lint", "pool": "self-hosted", "steps": [{"script": "ruff check ."}]},
                    ],
                }
            ],
        }
        facts = _facts(pipeline)
        self.assertEqual(
            sorted((job.name, job.os) for job in facts.of(CiJob)),
            [("lint", "unknown"), ("unit (linux)", "linux"), ("unit (mac)", "macos")],
        )
        self.assertIn(("cmake", "-B", "b", "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_C_COMPILER=clang"), argvs(facts))

    def test_known_tasks_run_their_commands_and_set_up_their_toolchains(self) -> None:
        """Humanizer's `DotNetCoreCLI@2` with `custom: test` and `--coverage` is `dotnet test --coverage`; Newtonsoft's
        `UseDotNet@2` version is its .NET SDK."""
        facts = _facts(TASKS)
        self.assertEqual(
            argvs(facts),
            [
                ("dotnet", "test", "--coverage", "--coverage-output-format", "cobertura"),
                ("dotnet", "build", "src/App.sln", "-c", "Release"),
                ("echo", "hi"),
            ],
        )
        files = {"azure-pipelines.yml": json.dumps(TASKS), "App.csproj": '<Project Sdk="Microsoft.NET.Sdk" />'}
        self.assertEqual(
            sorted(str(toolchain) for job in ci_jobs(files) for toolchain in job.toolchains),
            [".NET SDK 10.0.x", ".NET SDK 8.0.x"],
        )

    def test_a_matrix_computed_by_an_expression_and_a_missing_template_are_unknown(self) -> None:
        pipeline = {
            "jobs": [
                {"template": "templates/matrix.yml", "parameters": {"targets": ["a"]}},
                {"job": "computed", "strategy": {"matrix": "$[ dependencies.plan.outputs['legs'] ]"}, "steps": []},
                {"job": "steps", "steps": [{"template": "steps/test.yml@tools"}]},
            ]
        }
        unknowns = sorted((unknown.subject, unknown.hides, unknown.reason) for unknown in _facts(pipeline).of(Unknown))
        self.assertEqual(
            unknowns,
            [
                ("the matrix of job computed", "jobs", "it is computed by an expression"),
                ("the template steps/test.yml@tools", "commands", "it is in another repository"),
                ("the template templates/matrix.yml", "jobs", "templates/matrix.yml is not in the project"),
            ],
        )

    def test_a_local_steps_template_runs_its_steps_with_the_parameters_passed(self) -> None:
        """command-line-api's `eng/pipelines` templates: a template's path is relative to the file that names it, or
        to the repository's root after `/`; its parameters' defaults hold where the caller passes none."""
        template = {
            "parameters": [{"name": "configuration", "default": "Debug"}, {"name": "tests", "default": True}],
            "steps": [
                {"script": "dotnet build -c ${{ parameters.configuration }}"},
                {"${{ if parameters.tests }}": [{"script": "dotnet test"}]},
            ],
        }
        pipeline = {
            "steps": [
                {"template": "eng/build.yml", "parameters": {"configuration": "Release"}},
                {"template": "/eng/build.yml", "parameters": {"tests": False}},
            ]
        }
        facts = _facts(pipeline, **{"eng/build.yml": json.dumps(template)})
        self.assertEqual(
            argvs(facts),
            [("dotnet", "build", "-c", "Release"), ("dotnet", "test"), ("dotnet", "build", "-c", "Debug")],
        )
        self.assertEqual([command.origin.path for command in facts.of(Command)], ["eng/build.yml"] * 3)
        self.assertEqual(list(facts.of(Unknown)), [])

    def test_jobs_and_stages_templates_make_jobs_and_templates_nest(self) -> None:
        """The ansible collections' matrix.yml makes a job of each target and passes them to test.yml, which says
        what each job runs."""
        targets = [{"name": "Sanity", "test": "sanity"}, {"name": "Units", "test": "units/3.12"}]
        sanity = {"stage": "Sanity", "jobs": [{"template": "templates/matrix.yml", "parameters": {"targets": targets}}]}
        pipeline = {"stages": [sanity, {"template": "templates/stage.yml"}]}
        facts = _facts(pipeline, **ANSIBLE_TEMPLATES)
        self.assertEqual(
            [(job.name, job.id) for job in facts.of(CiJob)],
            [
                ("Sanity", "azure-pipelines.yml:Sanity.test_sanity"),
                ("Units", "azure-pipelines.yml:Sanity.test_units_3.12"),
                ("docs", "azure-pipelines.yml:Docs.docs"),
            ],
        )
        self.assertEqual(argvs(facts), [("ansible-test", "sanity"), ("ansible-test", "units/3.12"), ("make", "docs")])

    def test_the_parameters_a_pipeline_passes_are_expanded_where_it_passes_them(self) -> None:
        """command-line-api passes jobs whose matrix holds a conditional leg to Arcade's jobs.yml."""
        template = {
            "parameters": [{"name": "jobs", "type": "object"}],
            "jobs": [{"${{ each job in parameters.jobs }}": ["${{ job }}"]}],
        }
        legs = {
            "${{ if in(variables['Build.Reason'], 'PullRequest') }}": {"Debug": {"C": "Debug"}},
            "Release": {"C": "Release"},
        }
        job = {"job": "Windows", "strategy": {"matrix": legs}, "steps": [{"script": "build $(C)"}]}
        pipeline = {"jobs": [{"template": "jobs.yml", "parameters": {"jobs": [job]}}]}
        facts = _facts(pipeline, **{"jobs.yml": json.dumps(template)})
        self.assertEqual([found.name for found in facts.of(CiJob)], ["Windows (Debug)", "Windows (Release)"])

    def test_a_pipeline_extends_a_template(self) -> None:
        template = {
            "parameters": {"cmd": "pytest"},
            "jobs": [{"job": "t", "steps": [{"script": "${{ parameters.cmd }}"}]}],
        }
        for passed, expected in (({"cmd": "tox"}, [("tox",)]), ({}, [("pytest",)])):
            with self.subTest(passed=passed):
                pipeline = {"extends": {"template": "base.yml", "parameters": passed}}
                self.assertEqual(argvs(_facts(pipeline, **{"base.yml": json.dumps(template)})), expected)

    def test_a_template_whose_expressions_cannot_be_evaluated_is_unknown(self) -> None:
        template = {"steps": [{"script": "${{ counter('x', 1) }}"}]}
        facts = _facts({"steps": [{"template": "t.yml"}]}, **{"t.yml": json.dumps(template)})
        reasons = [(unknown.subject, unknown.reason) for unknown in facts.of(Unknown)]
        self.assertEqual(reasons, [("the template t.yml", "the function counter is not evaluated")])
        self.assertEqual(argvs(facts), [])

    def test_a_step_that_continues_on_error_cannot_fail_the_job(self) -> None:
        pipeline = {"steps": [{"script": "flaky-check", "continueOnError": True}, {"script": "pytest"}]}
        advisories = {command.argv[0]: command.advisory for command in _facts(pipeline).of(Command)}
        self.assertEqual(advisories, {"flaky-check": "continueOnError", "pytest": ""})

    def test_pipelines_are_found_where_azure_devops_looks_for_them(self) -> None:
        """command-line-api's `.vsts-ci.yml` and the ansible collections' `.azure-pipelines/azure-pipelines.yml`."""
        for path in (
            "azure-pipelines.yml",
            ".azure-pipelines.yml",
            ".azure-pipelines/azure-pipelines.yml",
            ".vsts-ci.yml",
        ):
            with self.subTest(path=path):
                facts = _facts(
                    {
                        "jobs": [
                            {
                                "job": "Windows",
                                "pool": {"vmImage": "windows-latest"},
                                "steps": [{"script": "eng\\common\\cibuild.cmd"}],
                            }
                        ]
                    },
                    path,
                )
                self.assertEqual([fact.provider for fact in facts.of(CiConfiguration)], ["Azure Pipelines"])
                self.assertEqual([job.os for job in facts.of(CiJob)], ["windows"])

    def test_a_document_that_is_not_a_mapping_has_no_jobs(self) -> None:
        self.assertEqual(_facts(["a"]).of(CiJob), ())
