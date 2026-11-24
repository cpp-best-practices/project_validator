"""Travis CI: `.travis.yml` is read as jobs (its matrix expanded) and the commands of their phases (upstream #223)."""

from __future__ import annotations

import json
import unittest

from project_validator.facts import CiJob, Command, Facts, Unknown
from tests.support import ci_jobs, config_facts


def _facts(travis: object, **files: str) -> Facts:
    return config_facts(".travis.yml", travis, **files)


def _commands(facts: Facts) -> dict[str, list[tuple[str, ...]]]:
    found: dict[str, list[tuple[str, ...]]] = {}
    for command in facts.of(Command):
        found.setdefault(command.job, []).append(command.argv)
    return found


class TravisJobTests(unittest.TestCase):
    def test_the_matrix_is_every_os_compiler_and_env_combination(self) -> None:
        travis = {
            "language": "cpp",
            "os": ["linux", "osx"],
            "compiler": ["gcc", "clang"],
            "env": ["BUILD=Debug", "BUILD=Release"],
            "script": ["cmake -B build -DCMAKE_BUILD_TYPE=$BUILD", "cmake --build build", "ctest --test-dir build"],
        }
        jobs = ci_jobs({".travis.yml": json.dumps(travis)})
        self.assertEqual(
            sorted((job.os, *job.compilers, *(c.build_type for c in job.configurations)) for job in jobs),
            sorted(
                (os, compiler, build)
                for os in ("linux", "macos")
                for compiler in ("gcc", "clang")
                for build in ("debug", "release")
            ),
        )
        facts = _facts(travis)
        self.assertFalse([unknown for unknown in facts.of(Unknown) if "heuristically" in unknown.reason])
        self.assertEqual(
            next(iter(_commands(facts).values())),
            [
                ("cmake", "-B", "build", "-DCMAKE_BUILD_TYPE=Debug"),
                ("cmake", "--build", "build"),
                ("ctest", "--test-dir", "build"),
            ],
        )

    def test_included_jobs_take_the_first_root_values_and_their_own_keys(self) -> None:
        travis = {
            "language": "python",
            "python": ["3.12", "3.13"],
            "script": "pytest",
            "jobs": {
                "include": [{"name": "lint", "script": "ruff check ."}, {"os": "windows", "language": "shell"}],
                "exclude": [{"python": "3.13"}],
                "allow_failures": [{"name": "lint"}],
            },
        }
        facts = _facts(travis)
        jobs = {job.name: job for job in facts.of(CiJob)}
        self.assertEqual(
            sorted((job.name, job.os, job.matrix.get("python-version")) for job in jobs.values()),
            [("3.12", "linux", "3.12"), ("lint", "linux", "3.12"), ("windows, 3.12", "windows", "3.12")],
        )
        commands = {command.job: command for command in facts.of(Command)}
        lint = next(job.id for job in jobs.values() if job.name == "lint")
        self.assertEqual(commands[lint].argv, ("ruff", "check", "."))
        self.assertEqual(commands[lint].advisory, "allowed to fail (jobs.allow_failures)")
        self.assertEqual(
            sorted(command.argv for command in facts.of(Command) if not command.advisory), [("pytest",), ("pytest",)]
        )

    def test_language_versions_are_the_jobs_toolchains(self) -> None:
        travis = {"language": "python", "python": ["3.12", "3.13"], "script": "pytest"}
        jobs = ci_jobs({".travis.yml": json.dumps(travis), "pyproject.toml": "[project]\nname = 'x'\n"})
        versions = sorted(toolchain.version for job in jobs for toolchain in job.toolchains)
        self.assertEqual(versions, ["3.12", "3.13"])

    def test_what_runs_after_the_script_cannot_fail_the_build(self) -> None:
        travis = {
            "language": "go",
            "install": "go mod download",
            "script": "go test ./...",
            "after_success": "bash <(curl -s https://codecov.io/bash)",
            "after_script": ["make clean"],
        }
        advisories = {command.argv[0]: command.advisory for command in _facts(travis).of(Command)}
        self.assertEqual(advisories["go"], "")
        self.assertEqual(advisories["make"], "in after_script, whose failure Travis CI ignores")

    def test_a_job_with_the_default_script_of_its_language_is_unknown(self) -> None:
        unknowns = _facts({"language": "ruby", "rvm": "3.3"}).of(Unknown)
        self.assertEqual(
            [(unknown.subject, unknown.reason) for unknown in unknowns],
            [("the commands of job 3.3", "it runs the default script of language ruby, which is not read")],
        )
        self.assertEqual(_facts({"language": "generic", "os": "linux"}).of(Unknown), ())

    def test_words_elsewhere_in_the_file_name_no_os_or_ecosystem(self) -> None:
        """golang-migrate's release asset `migrate.windows-amd64.exe.tar.gz` named no Windows job, and its
        `gem install fpm` (the packaging tool) no Fortran."""
        travis = {
            "language": "go",
            "before_install": "gem install --no-document fpm",
            "script": "go test ./...",
            "deploy": {"provider": "releases", "file": ["cli/build/migrate.windows-amd64.exe.tar.gz"]},
        }
        [job] = ci_jobs({".travis.yml": json.dumps(travis), "go.mod": "module x\n"})
        self.assertEqual((job.os, sorted(job.ecosystems)), ("linux", ["Go"]))

    def test_env_lists_with_global_values_are_each_jobs_environment(self) -> None:
        travis = {
            "env": {"global": ["CC=clang", {"secure": "abc"}], "jobs": ["MODE=a", "MODE=b"]},
            "script": "make $MODE",
        }
        facts = _facts(travis)
        self.assertEqual(sorted(job.env.get("MODE", "") for job in facts.of(CiJob)), ["a", "b"])
        self.assertEqual({job.env.get("CC") for job in facts.of(CiJob)}, {"clang"})
        self.assertEqual(sorted(command.argv for command in facts.of(Command)), [("make", "a"), ("make", "b")])

    def test_a_document_that_is_not_a_mapping_has_no_jobs(self) -> None:
        self.assertEqual(_facts(["a"]).of(CiJob), ())
