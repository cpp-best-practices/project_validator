"""Google Cloud Build: a build config is found where the Cloud Foundation Toolkit keeps them, and read as one job of
steps, each a command in its builder's image (upstream #223)."""

from __future__ import annotations

import unittest

from project_validator.facts import CiConfiguration, CiJob, Command, Facts
from tests.support import config_facts


def _facts(build: object, path: str = "cloudbuild.yaml") -> Facts:
    return config_facts(path, build)


class CloudBuildTests(unittest.TestCase):
    def test_the_toolkits_build_configs_are_found_and_their_steps_read(self) -> None:
        """terraform-google-modules' `build/int.cloudbuild.yaml`: a step runs its `args` with `bash -c`, another its
        builder's tool (the go builder runs go) in its `dir`."""
        build = {
            "steps": [
                {
                    "id": "init",
                    "name": "gcr.io/cloud-foundation-cicd/$_DEVELOPER_TOOLS:$_DEVELOPER_TOOLS_VERSION",
                    "args": ["/bin/bash", "-c", "cft test run all --stage init --verbose"],
                },
                {"name": "gcr.io/cloud-builders/go:1.22", "args": ["test", "./..."], "dir": "test/integration"},
            ],
            "substitutions": {
                "_DEVELOPER_TOOLS": "cft/developer-tools",
                "_DEVELOPER_TOOLS_VERSION": "1.28",
            },
        }
        facts = _facts(build, "build/int.cloudbuild.yaml")
        self.assertEqual([fact.provider for fact in facts.of(CiConfiguration)], ["Google Cloud Build"])
        [job] = facts.of(CiJob)
        self.assertEqual((job.os, job.name), ("linux", "build/int.cloudbuild.yaml"))
        found = [(command.argv, command.directory) for command in facts.of(Command)]
        self.assertIn((("cft", "test", "run", "all", "--stage", "init", "--verbose"), None), found)
        self.assertIn((("go", "test", "./..."), "test/integration"), found)

    def test_an_entrypoint_a_script_substitutions_and_allowed_failures(self) -> None:
        build = {
            "substitutions": {"_TARGET": "//..."},
            "steps": [
                {
                    "name": "gcr.io/bazel-public/bazel",
                    "entrypoint": "bazel",
                    "args": ["test", "$_TARGET", "--config=$$CONFIG"],
                },
                {"name": "python:3.12", "script": "#!/usr/bin/env bash\npip install -r requirements.txt\npytest\n"},
                {"name": "ubuntu", "args": ["./lint.sh"], "allowFailure": True, "env": ["STRICT=1"]},
            ],
        }
        commands = _facts(build).of(Command)
        self.assertEqual(
            [(command.argv, command.advisory) for command in commands],
            [
                (("bazel", "test", "//...", "--config=$CONFIG"), ""),
                # The script has no `set -e`: only its last command's failure fails the step.
                (("pip", "install", "-r", "requirements.txt"), "followed by other commands without set -e"),
                (("pytest",), ""),
                (("./lint.sh",), "allowFailure"),
            ],
        )
        self.assertEqual(commands[-1].env, {"STRICT": "1"})

    def test_configs_elsewhere_are_not_ci(self) -> None:
        self.assertEqual(_facts({"steps": []}, "deploy/x.cloudbuild.yaml").of(CiConfiguration), ())

    def test_a_document_that_is_not_a_mapping_has_no_jobs(self) -> None:
        self.assertEqual(_facts(["a"]).of(CiJob), ())
