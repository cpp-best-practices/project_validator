"""One analysis of a project, which every view renders: what was detected and how it was read, the results, the score,
and progress while it works."""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from project_validator.analysis import Analysis, Progress, RoleSummary, analyse, file_url
from project_validator.core import Options
from project_validator.plugins import discover
from tests.support import FIXTURES, make_context, temp_project

MIXED = {
    "CMakeLists.txt": "project(app CXX)\n",
    "src/main.cpp": "",
    "tests/test_main.cpp": "",
    "examples/demo.cpp": "",
    "scripts/release.py": "",
    "third_party/lib/lib.c": "",
}


def _analysis(files: dict[str, str], **options: object) -> Analysis:
    with temp_project(files) as root:
        return analyse(make_context(root), discover().checks, **options)  # type: ignore[arg-type]


class AnalysisTests(unittest.TestCase):
    def test_it_holds_the_structure_facts_reports_and_score(self) -> None:
        analysis = _analysis(MIXED)
        if analysis.structure is None:
            self.fail("not read")
        self.assertEqual(sorted(analysis.structure.languages), ["C++", "Python"])
        self.assertTrue(analysis.facts.all)
        self.assertEqual({report.check.name for report in analysis.reports}, {c.name for c in discover().checks})
        self.assertIsNotNone(analysis.score)
        self.assertGreater(analysis.seconds, 0)

    def test_the_score_can_be_left_out(self) -> None:
        self.assertIsNone(_analysis(MIXED, scored=False).score)

    def test_each_extraction_stage_is_timed_with_what_it_found(self) -> None:
        stages = {stage.name: stage for stage in _analysis(MIXED).stages}
        self.assertIn("the project's structure", stages)
        self.assertIn("the tool runs", stages)
        self.assertGreater(stages["the project's structure"].found, 0)
        self.assertTrue(all(stage.seconds >= 0 for stage in stages.values()))

    def test_the_code_in_each_detected_role_is_summarised(self) -> None:
        roles = {summary.role: summary for summary in _analysis(MIXED).roles}
        self.assertEqual(set(roles), {"product", "test", "example", "tooling", "vendored"})
        self.assertEqual(roles["test"], RoleSummary(role="test", directories=("tests",), files=1, languages=("C++",)))
        self.assertEqual(roles["tooling"].languages, ("Python",))
        self.assertEqual(roles["vendored"].directories, ("third_party",))

    def test_a_role_suggests_the_option_that_judges_it_as_auxiliary(self) -> None:
        roles = {summary.role: summary for summary in _analysis(MIXED).roles}
        self.assertEqual(roles["example"].suggestion, "--auxiliary example")
        self.assertIsNone(roles["product"].suggestion)
        self.assertIsNone(roles["vendored"].suggestion)

    def test_a_role_already_named_auxiliary_suggests_nothing(self) -> None:
        with temp_project(MIXED) as root:
            analysis = analyse(make_context(root, auxiliary=("example",)), discover().checks)
        roles = {summary.role: summary for summary in analysis.roles}
        self.assertTrue(roles["example"].auxiliary)
        self.assertIsNone(roles["example"].suggestion)

    def test_the_options_and_validator_version_are_recorded(self) -> None:
        analysis = _analysis(MIXED)
        self.assertEqual(analysis.options["allow_unknown"], False)
        self.assertRegex(analysis.validator, r"^\d+\.\d+")

    def test_an_extraction_failure_is_kept(self) -> None:
        with temp_project({"CMakeLists.txt": ""}) as root:
            context = make_context(root)
            context._extracted = None
            from project_validator.core import ExtractionError

            context._extracted = ExtractionError("the CI configuration", ValueError("broken"))
            analysis = analyse(context, discover().checks)
        self.assertIn("the CI configuration", str(analysis.error))
        self.assertIsNone(analysis.score)

    def test_as_json(self) -> None:
        data = _analysis(MIXED).as_dict()
        self.assertEqual(
            set(data),
            {"project", "validator", "options", "seconds", "stages", "structure", "roles", "results", "score", "git"},
        )
        json.dumps(data)


class ProgressTests(unittest.TestCase):
    def test_the_stages_and_checks_are_reported_as_they_start_and_end(self) -> None:
        events: list[Progress] = []
        with temp_project(MIXED) as root:
            analyse(make_context(root), discover().checks[:3], progress=events.append)
        kinds = [(event.kind, event.done) for event in events]
        self.assertEqual(kinds[0], ("stage", False))
        self.assertIn(("stage", True), kinds)
        self.assertEqual(
            [event.name for event in events if event.kind == "check" and event.done],
            [check.name for check in discover().checks[:3]],
        )
        finished = [event for event in events if event.kind == "check" and event.done]
        self.assertEqual([event.total for event in finished], [3, 3, 3])
        self.assertEqual([event.index for event in finished], [1, 2, 3])

    def test_progress_of_the_fixture_extraction_is_reported_once(self) -> None:
        events: list[Progress] = []
        with temp_project(MIXED) as root:
            context = make_context(root)
            context.observe(events.append)
            _ = context.facts
            _ = context.facts
        self.assertEqual(sum(1 for event in events if event.kind == "stage" and not event.done), 9)


def _git(root: Path, *arguments: str) -> None:
    subprocess.run([shutil.which("git") or "git", *arguments], cwd=root, check=True)  # noqa: S603 - tests


class GitTests(unittest.TestCase):
    def test_a_checkout_gives_its_commit_and_its_github_files(self) -> None:
        with temp_project({"main.py": ""}) as root:
            _git(root, "init", "-q")
            _git(root, "remote", "add", "origin", "git@github.com:o/r.git")
            _git(root, "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-q", "--allow-empty", "-m", "m")
            analysis = analyse(make_context(root), ())
        self.assertRegex(analysis.git.commit or "", r"^[0-9a-f]{40}$")
        self.assertEqual(analysis.git.web, "https://github.com/o/r")
        self.assertEqual(
            file_url(analysis.git, "src/a.py:3"), f"https://github.com/o/r/blob/{analysis.git.commit}/src/a.py#L3"
        )

    def test_without_git_there_is_no_commit_and_no_links(self) -> None:
        with temp_project({"main.py": ""}) as root:
            analysis = analyse(make_context(root), ())
        self.assertIsNone(analysis.git.commit)
        self.assertIsNone(file_url(analysis.git, "main.py"))

    def test_https_remotes_and_the_fixture_name(self) -> None:
        from project_validator.analysis import web_url

        self.assertEqual(web_url("https://github.com/o/r.git"), "https://github.com/o/r")
        self.assertEqual(web_url("https://gitlab.com/g/p"), "https://gitlab.com/g/p")
        self.assertIsNone(web_url("/local/path"))
        analysis = analyse(make_context(FIXTURES / "well_configured_python", Options()), ())
        self.assertEqual(analysis.name, "well_configured_python")


if __name__ == "__main__":
    unittest.main()
