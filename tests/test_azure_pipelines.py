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

    def test_a_template_and_a_matrix_computed_by_an_expression_are_unknown(self) -> None:
        pipeline = {
            "jobs": [
                {"template": "templates/matrix.yml", "parameters": {"targets": ["a"]}},
                {"job": "computed", "strategy": {"matrix": "$[ dependencies.plan.outputs['legs'] ]"}, "steps": []},
                {"job": "steps", "steps": [{"template": "steps/test.yml"}]},
            ]
        }
        unknowns = sorted((unknown.subject, unknown.hides) for unknown in _facts(pipeline).of(Unknown))
        self.assertEqual(
            unknowns,
            [
                ("the matrix of job computed", "jobs"),
                ("the template steps/test.yml", "commands"),
                ("the template templates/matrix.yml", "jobs"),
            ],
        )

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
