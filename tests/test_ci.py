import unittest
from unittest import mock

from project_validator import yaml_support
from project_validator.ci import find_ci_files, heuristic_jobs, parse_jobs
from project_validator.core import Project
from project_validator.plugins import discover
from tests.support import CI_FILES, PROJECT_LAYOUTS, layout_project, temp_project


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
    def test_one_job_per_operating_system(self) -> None:
        jobs = heuristic_jobs("f", "os: [ubuntu-latest, windows-latest]\ncxx: [g++, clang++]")
        self.assertEqual([job.os for job in jobs], ["linux", "windows"])
        self.assertTrue(all(job.compilers == {"gcc", "clang"} and job.heuristic for job in jobs))

    def test_runner_default_when_no_compiler_is_named(self) -> None:
        [job] = heuristic_jobs("f", "os: osx")
        self.assertEqual((job.compilers, job.default_compiler), (frozenset({"appleclang"}), True))

    def test_unknown_operating_system(self) -> None:
        [job] = heuristic_jobs("f", "script: make")
        self.assertEqual((job.os, job.compilers), ("unknown", frozenset()))


WORKFLOW = {".github/workflows/ci.yml": "jobs:\n  a:\n    runs-on: ubuntu-latest\n    steps: []\n"}


class ParseJobsTests(unittest.TestCase):
    def _parse(self, files: dict[str, str]):
        with temp_project(files) as root:
            project = Project(root)
            return parse_jobs(project, find_ci_files(project, discover().providers))

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
