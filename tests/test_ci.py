import unittest
from unittest import mock

from project_validator import yaml_support
from project_validator.ci import CiAnalysis, find_ci_files
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
