"""CircleCI: `.circleci/config.yml` is read as the jobs its workflows run and the commands of their steps (upstream
#223)."""

from __future__ import annotations

import json
import unittest

from project_validator.facts import CiJob, Command, Facts, Unknown
from tests.support import argvs, ci_jobs, config_facts

CONFIG = ".circleci/config.yml"


def _facts(config: object, **files: str) -> Facts:
    return config_facts(CONFIG, config, **files)


# xmlunit's: `matrix: parameters: version: [...]` with the version in the job's image.
JDK_MATRIX = {
    "version": 2.1,
    "jobs": {
        "build": {
            "parameters": {"version": {"type": "string", "default": "17.0"}},
            "docker": [{"image": "cimg/openjdk:<<parameters.version>>"}],
            "steps": [{"run": "mvn verify -Djdk=<< parameters.version >>"}],
        }
    },
    "workflows": {
        "ci": {
            "jobs": [
                {"build": {"matrix": {"parameters": {"version": ["8.0", "11.0", "21.0"]}}}},
                {"build": {"name": "default-jdk"}},
            ]
        }
    },
}


class CircleCiJobTests(unittest.TestCase):
    def test_the_jobs_workflows_run_and_the_commands_of_their_run_steps(self) -> None:
        """pandoc's and envoy's: `run:` as a command line or as a mapping with `command:`; `checkout` and the other
        built-in steps run nothing of the project's; a job no workflow runs does not run."""
        config = {
            "version": 2.1,
            "jobs": {
                "test": {
                    "docker": [{"image": "haskell:9.10"}],
                    "environment": {"MODE": "ci"},
                    "steps": [
                        "checkout",
                        {"run": "cabal build all"},
                        {"run": {"name": "Test", "command": "cabal test all\nscript/analysis-test"}},
                        {"store_test_results": {"path": "out"}},
                    ],
                },
                "unused": {"docker": [{"image": "x"}], "steps": [{"run": "make never"}]},
            },
            "workflows": {"ci": {"jobs": ["test"]}},
        }
        facts = _facts(config)
        [job] = facts.of(CiJob)
        self.assertEqual((job.name, job.os, job.image, job.env), ("test", "linux", "haskell:9.10", {"MODE": "ci"}))
        self.assertEqual(argvs(facts), [("cabal", "build", "all"), ("cabal", "test", "all"), ("script/analysis-test",)])
        self.assertFalse([unknown for unknown in facts.of(Unknown) if "heuristically" in unknown.reason])

    def test_a_config_without_workflows_runs_each_job(self) -> None:
        config = {"version": 2, "jobs": {"build": {"docker": [{"image": "gcc:14"}], "steps": [{"run": "make"}]}}}
        self.assertEqual(argvs(_facts(config)), [("make",)])

    def test_the_images_after_the_first_are_the_jobs_services(self) -> None:
        """dbt-utils: `cimg/python` runs the steps, `cimg/postgres:17.5` is the database beside it."""
        config = {
            "jobs": {
                "integration": {
                    "docker": [{"image": "cimg/python:3.13.7"}, {"image": "cimg/postgres:17.5"}],
                    "steps": [{"run": "./run_test.sh postgres"}],
                }
            }
        }
        [job] = _facts(config).of(CiJob)
        self.assertEqual((job.image, job.services), ("cimg/python:3.13.7", ("cimg/postgres:17.5",)))

    def test_a_matrix_makes_a_job_of_each_combination_of_its_parameters(self) -> None:
        """xmlunit's (see JDK_MATRIX)."""
        facts = _facts(JDK_MATRIX)
        self.assertEqual(
            sorted((job.name, job.image) for job in facts.of(CiJob)),
            [
                ("build-11.0", "cimg/openjdk:11.0"),
                ("build-21.0", "cimg/openjdk:21.0"),
                ("build-8.0", "cimg/openjdk:8.0"),
                ("default-jdk", "cimg/openjdk:17.0"),
            ],
        )
        self.assertIn(("mvn", "verify", "-Djdk=21.0"), argvs(facts))
        files = {CONFIG: json.dumps(JDK_MATRIX), "pom.xml": "<project/>\n"}
        versions = sorted(toolchain.version for job in ci_jobs(files) for toolchain in job.toolchains)
        self.assertEqual(versions, ["11.0", "17.0", "21.0", "8.0"])

    def test_the_runner_is_the_docker_machine_or_macos_executor(self) -> None:
        config = {
            "executors": {"win": {"machine": {"image": "windows-server-2022-gui:current"}}},
            "jobs": {
                "linux": {"machine": {"image": "ubuntu-2204:current"}, "steps": [{"run": "make"}]},
                "mac": {"macos": {"xcode": "15.4.0"}, "steps": [{"run": "make"}]},
                "windows": {"executor": "win", "steps": [{"run": "make"}]},
                "named": {"executor": {"name": "win"}, "steps": [{"run": "make"}]},
                "orb": {"executor": "other/default", "steps": [{"run": "make"}]},
            },
        }
        self.assertEqual(
            {job.name: job.os for job in _facts(config).of(CiJob)},
            {"linux": "linux", "mac": "macos", "windows": "windows", "named": "windows", "orb": "unknown"},
        )

    def test_an_executor_takes_the_parameters_a_job_gives_it(self) -> None:
        """xmlunit's: `executor: {name: openjdk, version: <<parameters.version>>}`, its image `cimg/openjdk` of that
        version."""
        config = {
            "executors": {
                "openjdk": {
                    "parameters": {"version": {"type": "string", "default": "17.0"}},
                    "docker": [{"image": "cimg/openjdk:<<parameters.version>>"}],
                }
            },
            "jobs": {
                "test-only": {
                    "parameters": {"version": {"type": "string", "default": "17.0"}},
                    "executor": {"name": "openjdk", "version": "<<parameters.version>>"},
                    "steps": [{"run": "mvn test"}],
                },
                "default": {"executor": "openjdk", "steps": [{"run": "mvn test"}]},
            },
            "workflows": {
                "w": {"jobs": [{"test-only": {"matrix": {"parameters": {"version": ["8.0", "21.0"]}}}}, "default"]}
            },
        }
        images = sorted(job.image or "" for job in _facts(config).of(CiJob))
        self.assertEqual(images, ["cimg/openjdk:17.0", "cimg/openjdk:21.0", "cimg/openjdk:8.0"])

    def test_the_configs_commands_are_expanded_and_an_orbs_are_unknown(self) -> None:
        config = {
            "version": 2.1,
            "orbs": {"node": "circleci/node@5.2"},
            "commands": {
                "lint": {
                    "parameters": {"strict": {"type": "boolean", "default": False}},
                    "steps": [{"run": "ruff check . --strict=<< parameters.strict >>"}, "deeper"],
                },
                "deeper": {"steps": [{"run": "mypy ."}]},
            },
            "jobs": {
                "check": {
                    "docker": [{"image": "cimg/python:3.13"}],
                    "steps": [
                        {"lint": {"strict": True}},
                        "node/install-packages",
                        {"when": {"condition": True, "steps": [{"run": "pytest"}]}},
                    ],
                }
            },
        }
        facts = _facts(config)
        self.assertEqual(argvs(facts), [("ruff", "check", ".", "--strict=true"), ("mypy", "."), ("pytest",)])
        [unknown] = facts.of(Unknown)
        self.assertEqual(
            (unknown.subject, unknown.reason, unknown.hides),
            ("the step node/install-packages", "it is a command of the orb node, which is not read", "commands"),
        )

    def test_a_command_that_runs_itself_is_followed_once(self) -> None:
        config = {
            "commands": {"loop": {"steps": [{"run": "pytest"}, "loop"]}},
            "jobs": {"j": {"docker": [{"image": "x"}], "steps": ["loop"]}},
        }
        facts = _facts(config)
        self.assertEqual(argvs(facts), [("pytest",)])
        self.assertEqual([unknown.reason for unknown in facts.of(Unknown)], ["it runs itself"])

    def test_a_background_step_cannot_fail_the_job(self) -> None:
        config = {
            "jobs": {
                "j": {
                    "docker": [{"image": "x"}],
                    "steps": [{"run": {"command": "./server", "background": True}}, {"run": "pytest"}],
                }
            }
        }
        advisories = {command.argv[0]: command.advisory for command in _facts(config).of(Command)}
        self.assertEqual(advisories, {"./server": "runs in the background", "pytest": ""})

    def test_an_orb_job_in_a_workflow_is_unknown(self) -> None:
        config = {"orbs": {"py": "circleci/python@2"}, "workflows": {"w": {"jobs": ["py/test"]}}}
        [unknown] = _facts(config).of(Unknown)
        self.assertEqual((unknown.subject, unknown.hides), ("the job py/test", "jobs"))
        self.assertEqual(unknown.reason, "it is a job of the orb py, which is not read")

    def test_a_document_that_is_not_a_mapping_has_no_jobs(self) -> None:
        self.assertEqual(_facts(["a"]).of(CiJob), ())
