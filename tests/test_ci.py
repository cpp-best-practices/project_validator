from __future__ import annotations

import unittest
from functools import partial
from unittest import mock

from project_validator import yaml_support
from project_validator.ci import CiAnalysis, _matrix_text, find_ci_files
from project_validator.core import Project
from project_validator.plugins import discover
from tests.support import CI_FILES, PROJECT_LAYOUTS, ci_jobs, layout_project, make_context, temp_project


class FindCiFilesTests(unittest.TestCase):
    def test_finds_files_for_every_provider(self) -> None:
        files = {
            ".github/workflows/a.yml": "",
            ".github/workflows/b.yaml": "",
            ".github/workflows/readme.md": "",
            ".gitlab-ci.yml": "",
            "Jenkinsfile": "",
        }
        with temp_project(files) as root:
            found = find_ci_files(Project(root), discover().providers)
        self.assertEqual(
            sorted((f.provider.name, f.path) for f in found),
            [
                ("GitHub Actions", ".github/workflows/a.yml"),
                ("GitHub Actions", ".github/workflows/b.yaml"),
                ("GitLab CI", ".gitlab-ci.yml"),
                ("Jenkins", "Jenkinsfile"),
            ],
        )

    def test_finds_every_provider_in_every_layout(self) -> None:
        for layout in PROJECT_LAYOUTS:
            for provider, path in CI_FILES.items():
                with layout_project(self, layout, {path: ""}, ci=provider) as root:
                    found = find_ci_files(Project(root), discover().providers)
                    self.assertEqual([(f.provider.name, f.path) for f in found], [(provider, path)])


class HeuristicJobsTests(unittest.TestCase):
    """Configuration that is not parsed: one job per OS it names, judged by the whole file."""

    def test_one_job_per_operating_system(self) -> None:
        jobs = ci_jobs({".travis.yml": "os: [ubuntu-latest, windows-latest]\ncxx: [g++, clang++]\n"})
        self.assertEqual([job.os for job in jobs], ["linux", "windows"])
        self.assertTrue(all(job.compilers == {"gcc", "clang"} and job.heuristic for job in jobs))

    def test_the_operating_systems_are_those_the_runners_are_configured_with(self) -> None:
        """A description, a comment or a command that names an OS (docker-code-server's image label: "VS Code … on
        your Mac, Windows") names no runner; the keys that configure one do, whatever the provider calls them."""
        for path, text, expected in (
            (
                "Jenkinsfile",
                "environment {\n  DIST_IMAGE = 'ubuntu'\n}\nsh 'docker build --label \"desc=on Windows\"'\n",
                ["linux"],
            ),
            ("azure-pipelines.yml", "pool:\n  vmImage: 'windows-latest'\nsteps:\n- script: echo linux\n", ["windows"]),
            (".circleci/config.yml", "jobs:\n  b:\n    macos:\n      xcode: 15.0\n    steps: [run: make]\n", ["macos"]),
            ("appveyor.yml", "image: Visual Studio 2022  # ported from linux\n# os: linux\n", ["windows"]),
            ("Jenkinsfile", "pipeline {\n  agent { label 'windows' }\n}\n", ["windows"]),
            (".travis.yml", "matrix:\n  include:\n    - os: osx\n    - os: linux\n", ["macos", "linux"]),
            # A sequence written at its key's indentation (scalafmt's AppVeyor), and an image behind an anchor (envoy).
            ("appveyor.yml", "image:\n- Visual Studio 2017\nbuild: off\n", ["windows"]),
            (".circleci/config.yml", "build-image: &image\n  envoyproxy/build-ubuntu:f4a8\njobs: {}\n", ["linux"]),
        ):
            with self.subTest(path=path, text=text.splitlines()[0]):
                self.assertEqual(sorted(job.os for job in ci_jobs({path: text})), sorted(expected))

    def test_runner_default_when_no_compiler_is_named(self) -> None:
        [job] = ci_jobs({".travis.yml": "os: osx\n"})
        self.assertEqual((job.compilers, job.default_compiler), (frozenset({"appleclang"}), True))

    def test_unknown_operating_system(self) -> None:
        [job] = ci_jobs({".travis.yml": "script: make\n"})
        self.assertEqual((job.os, job.compilers), ("unknown", frozenset()))

    def test_build_types_come_from_the_lines_that_could_be_commands(self) -> None:
        [job] = ci_jobs(
            {".travis.yml": "os: linux\nscript:\n  - cmake -S . -DCMAKE_BUILD_TYPE=Debug\n  - 'cargo test --release'\n"}
        )
        self.assertEqual({configuration.build_type for configuration in job.configurations}, {"debug", "release"})


WORKFLOW = {".github/workflows/ci.yml": "jobs:\n  a:\n    runs-on: ubuntu-latest\n    steps: []\n"}


class ParseJobsTests(unittest.TestCase):
    def _parse(self, files: dict[str, str]) -> CiAnalysis:
        with temp_project(files) as root:
            return make_context(root).ci_analysis

    def test_structured_parsing_has_no_notes(self) -> None:
        analysis = self._parse(WORKFLOW)
        self.assertEqual(analysis.notes, ())
        self.assertEqual([job.name for job in analysis.jobs], [".github/workflows/ci.yml: a"])

    def test_missing_pyyaml_is_reported(self) -> None:
        with mock.patch.object(yaml_support, "_yaml", None):
            analysis = self._parse(WORKFLOW)
        self.assertIn(yaml_support.MISSING_MESSAGE, analysis.notes[0])

    def test_invalid_yaml_is_scanned_heuristically(self) -> None:
        analysis = self._parse({".gitlab-ci.yml": "a: [unclosed\n"})
        self.assertIn("invalid YAML", analysis.notes[0])

    def test_unstructured_providers_are_noted(self) -> None:
        analysis = self._parse({".travis.yml": "os: linux\ncompiler: gcc\n"})
        self.assertEqual(analysis.notes, (".travis.yml: Travis CI is scanned heuristically",))


class MatrixToolchainTests(unittest.TestCase):
    def test_matrix_values_that_are_objects_are_read_as_written(self) -> None:
        self.assertEqual(
            _matrix_text({"versions": '{"ghc": "9.6"}', "os": "ubuntu"}), '{"versions": {"ghc": "9.6"}, "os": "ubuntu"}'
        )
        self.assertEqual(_matrix_text({"odd": "{not json"}), '{"odd": "{not json"}')


class CargoProfileTests(unittest.TestCase):
    def test_a_custom_profile_builds_what_it_inherits(self) -> None:
        from project_validator.ecosystems.rust import cargo_profile_build_types
        from tests.support import command

        manifest = (
            '[profile.fast]\ninherits = "release"\n[profile.slow]\ninherits = "dev"\n'
            '[profile.loop]\ninherits = "loop"\n[profile.none]\nlto = true\n'
        )
        cases = {
            "cargo build --profile fast": manifest,
            "cargo test --profile slow": manifest,
            "cargo build --profile loop": manifest,
            "cargo build --profile none": manifest,
            "cargo build --profile fast ": "[profile",
            "cargo build": manifest,
            "cargo fmt --profile fast": manifest,
        }
        expected = [{"release"}, {"debug"}, set(), set(), set(), set(), set()]
        for (line, text), wanted in zip(cases.items(), expected, strict=True):
            with self.subTest(line=line):
                found = cargo_profile_build_types(command(line), partial(_same, text))
                self.assertEqual(found, frozenset(wanted))
        self.assertEqual(
            cargo_profile_build_types(command("cargo build --profile fast"), lambda _path: None), frozenset()
        )


def _same(text: str, _path: str) -> str | None:
    return text
