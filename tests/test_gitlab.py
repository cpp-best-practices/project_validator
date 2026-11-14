from __future__ import annotations

import json
import unittest

from project_validator.build_configurations import BuildConfiguration
from project_validator.ci.gitlab import expand_parallel
from project_validator.facts.jobs import Job
from tests.support import ci_jobs


class ExpandParallelTests(unittest.TestCase):
    def test_without_matrix_runs_once(self) -> None:
        self.assertEqual(expand_parallel(None), [{}])
        self.assertEqual(expand_parallel(3), [{}])

    def test_each_entry_expands_independently(self) -> None:
        parallel = {"matrix": [{"CC": ["gcc", "clang"], "BUILD": "Debug"}, {"CC": "icx"}]}
        self.assertEqual(
            expand_parallel(parallel),
            [{"CC": "gcc", "BUILD": "Debug"}, {"CC": "clang", "BUILD": "Debug"}, {"CC": "icx"}],
        )


def parse_pipeline(pipeline: object) -> tuple[Job, ...]:
    return ci_jobs({".gitlab-ci.yml": json.dumps(pipeline)})


class PipelineJobTests(unittest.TestCase):
    def test_parses_jobs_and_skips_hidden_trigger_and_reserved_keys(self) -> None:
        pipeline = {
            "stages": ["test"],
            "image": "gcc:14",
            ".template": {"script": ["clang"]},
            "downstream": {"trigger": "other/project"},
            "linux": {"script": ["ctest"]},
            "windows": {"tags": ["saas-windows-medium-amd64"], "script": ["cmake -G 'Visual Studio 17 2022'"]},
        }
        linux, windows = parse_pipeline(pipeline)
        self.assertEqual((linux.os, linux.compilers), ("linux", frozenset({"gcc"})))
        self.assertEqual((windows.os, windows.compilers), ("windows", frozenset({"msvc"})))

    def test_matrix_variables_are_substituted(self) -> None:
        pipeline = {
            "build": {
                "image": "$IMAGE",
                "parallel": {"matrix": [{"IMAGE": ["gcc:14", "silkeh/clang:18"]}]},
                "script": ["make"],
            }
        }
        jobs = parse_pipeline(pipeline)
        self.assertEqual([job.compilers for job in jobs], [frozenset({"gcc"}), frozenset({"clang"})])

    def test_untagged_jobs_without_compilers_use_the_linux_default(self) -> None:
        [job] = parse_pipeline({"test": {"script": ["make test"]}})
        self.assertEqual((job.os, job.compilers, job.default_compiler), ("linux", frozenset({"gcc"}), True))

    def test_build_configurations_come_from_matrix_variables(self) -> None:
        pipeline = {
            "build": {
                "parallel": {"matrix": [{"BUILD_TYPE": ["Debug", "Release"], "SANITIZE": ["address", "none"]}]},
                "script": ["cmake -DCMAKE_BUILD_TYPE=$BUILD_TYPE -DSANITIZER=$SANITIZE"],
            }
        }
        self.assertEqual(
            {configuration for job in parse_pipeline(pipeline) for configuration in job.configurations},
            {
                BuildConfiguration(build_type=build_type, sanitizers=sanitizers)
                for build_type in ("debug", "release")
                for sanitizers in (False, True)
            },
        )


class ServiceTests(unittest.TestCase):
    def test_services_are_the_jobs_service_containers(self) -> None:
        pipeline = {
            "default": {"services": ["redis:7"]},
            "test": {
                "image": "python:3.12",
                "services": ["postgres:$PG", {"name": "mysql:8.4", "alias": "db"}, 3],
                "parallel": {"matrix": [{"PG": ["16", "17"]}]},
                "script": ["pytest"],
            },
            "lint": {"script": ["ruff check ."]},
        }
        jobs = {job.name.rpartition(": ")[2]: sorted(job.services) for job in parse_pipeline(pipeline)}
        self.assertEqual(jobs["test (16)"], ["mysql:8.4", "postgres:16"])
        self.assertEqual(jobs["test (17)"], ["mysql:8.4", "postgres:17"])
        self.assertEqual(jobs["lint"], ["redis:7"])
