"""AppVeyor: `appveyor.yml` is read as its build matrix and the commands of each job's phases (upstream #223)."""

from __future__ import annotations

import json
import unittest

from project_validator.facts import CiJob, Command, Facts, Unknown
from tests.support import argvs, ci_jobs, config_facts

# glfw's: two environment legs, MinGW and Visual Studio, each building with CMake.
GLFW = {
    "image": "Visual Studio 2015",
    "environment": {
        "matrix": [
            {"GENERATOR": "MinGW Makefiles", "BUILD_SHARED_LIBS": "ON", "CFLAGS": "-Werror"},
            {"GENERATOR": "Visual Studio 12 2013", "BUILD_SHARED_LIBS": "OFF", "CFLAGS": "/WX"},
        ]
    },
    "build_script": [
        "set PATH=%PATH:C:\\Program Files\\Git\\usr\\bin;=%",
        'cmake -B build -G "%GENERATOR%" -DBUILD_SHARED_LIBS=%BUILD_SHARED_LIBS%',
        "cmake --build build",
    ],
}


def _facts(config: object, path: str = ".appveyor.yml") -> Facts:
    return config_facts(path, config)


class AppVeyorTests(unittest.TestCase):
    def test_each_environment_leg_is_a_job_running_the_build_script(self) -> None:
        facts = _facts(GLFW)
        jobs = facts.of(CiJob)
        self.assertEqual(
            [(job.os, job.env["GENERATOR"]) for job in jobs],
            [("windows", "MinGW Makefiles"), ("windows", "Visual Studio 12 2013")],
        )
        self.assertIn(("cmake", "-B", "build", "-G", "MinGW Makefiles", "-DBUILD_SHARED_LIBS=ON"), argvs(facts))
        self.assertIn(("cmake", "-B", "build", "-G", "Visual Studio 12 2013", "-DBUILD_SHARED_LIBS=OFF"), argvs(facts))
        self.assertFalse([unknown for unknown in facts.of(Unknown) if "heuristically" in unknown.reason])
        compilers = sorted(
            compiler for job in ci_jobs({".appveyor.yml": json.dumps(GLFW)}) for compiler in job.compilers
        )
        self.assertEqual(compilers, ["gcc", "msvc"])

    def test_the_matrix_is_every_image_platform_and_configuration(self) -> None:
        """AppVeyor sets CONFIGURATION and PLATFORM for each job; `matrix: exclude:` drops a combination and
        `allow_failures` lets one fail."""
        config = {
            "image": ["Visual Studio 2022", "Ubuntu2204"],
            "configuration": ["Debug", "Release"],
            "matrix": {
                "exclude": [{"image": "Ubuntu2204", "configuration": "Debug"}],
                "allow_failures": [{"configuration": "Release", "image": "Ubuntu2204"}],
            },
            "build_script": ["cmake --build build --config %CONFIGURATION%"],
            "test_script": [{"sh": "ctest --test-dir build -C $CONFIGURATION"}],
        }
        facts = _facts(config)
        self.assertEqual(
            sorted((job.os, job.env["CONFIGURATION"]) for job in facts.of(CiJob)),
            [("linux", "Release"), ("windows", "Debug"), ("windows", "Release")],
        )
        linux = next(job.id for job in facts.of(CiJob) if job.os == "linux")
        commands = [(command.argv, command.advisory) for command in facts.of(Command) if command.job == linux]
        self.assertEqual(
            commands,
            [
                (("cmake", "--build", "build", "--config", "Release"), "allowed to fail (matrix.allow_failures)"),
                (("ctest", "--test-dir", "build", "-C", "Release"), "allowed to fail (matrix.allow_failures)"),
            ],
        )

    def test_a_for_section_gives_the_jobs_it_matches_their_own_scripts(self) -> None:
        config = {
            "image": ["Visual Studio 2022", "macos"],
            "build_script": ["build.cmd"],
            "for": [{"matrix": {"only": [{"image": "macos"}]}, "build_script": ["./build.sh"]}],
        }
        facts = _facts(config)
        by_os = {job.os: job.id for job in facts.of(CiJob)}
        scripts = {command.job: command.argv for command in facts.of(Command)}
        self.assertEqual((scripts[by_os["windows"]], scripts[by_os["macos"]]), (("build.cmd",), ("./build.sh",)))

    def test_script_entries_name_their_shell_and_phases_after_the_tests_cannot_fail_the_build(self) -> None:
        config = {
            "install": [{"ps": "Install-Module Pester -Force"}, {"cmd": "pip install -r requirements.txt"}],
            "build": "off",
            "test_script": ["pytest"],
            "on_finish": ["curl -F file=@results.xml https://ci.appveyor.com/api/testresults/junit/x"],
        }
        facts = _facts(config)
        self.assertEqual(
            [(command.argv[0], command.advisory) for command in facts.of(Command)],
            [
                ("Install-Module", ""),
                ("pip", ""),
                ("pytest", ""),
                ("curl", "in on_finish, whose failure AppVeyor ignores"),
            ],
        )

    def test_the_automatic_msbuild_build_is_unknown_unless_it_names_its_project(self) -> None:
        [unknown] = _facts({"image": "Visual Studio 2022", "test_script": ["ctest"]}).of(Unknown)
        self.assertEqual((unknown.subject, unknown.hides), ("the build of job Visual Studio 2022", "commands"))
        named = {"build": {"project": "App.sln"}, "configuration": "Release"}
        self.assertEqual(argvs(_facts(named, "appveyor.yml")), [("msbuild", "App.sln", "/p:Configuration=Release")])

    def test_a_document_that_is_not_a_mapping_has_no_jobs(self) -> None:
        self.assertEqual(_facts(["a"]).of(CiJob), ())
