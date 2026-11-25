"""Which of a language's files each tool run reaches (upstream #333): a run covers the paths its command names, or
its whole directory when it names none; a gate whose runs reach only part of the product's code is filled by the
share of its lines they reach, and says which folders they miss."""

from __future__ import annotations

import unittest

from project_validator.checks.code_formatting import code_formatting
from project_validator.checks.static_analysis import static_analysis
from project_validator.checks.tests_run import tests_run
from project_validator.core import Check, Result, Status
from project_validator.facts.structure import SourceFile
from project_validator.facts.tools import ToolRun
from project_validator.judging import labelled
from tests.support import github_job, make_context, temp_project

LINES = "x = 1\n"
PYTHON = {
    "pyproject.toml": "[project]\nname = 'app'\n",
    "app/__init__.py": LINES * 30,
    "plugins/extra.py": LINES * 10,
    "scripts/release.py": LINES * 20,
    "tests/test_app.py": LINES * 50,
}


def _run(*steps: str, files: dict[str, str] | None = None, check: Check = static_analysis) -> Result:
    with temp_project({**(files or PYTHON), **github_job("ubuntu-latest", *steps)}) as root:
        return check.run(make_context(root))


class LinesTests(unittest.TestCase):
    def test_a_source_file_records_its_lines(self) -> None:
        with temp_project({**PYTHON, "app/last.py": "a = 1\nb = 2"}) as root:
            lines = {source.path: source.lines for source in make_context(root).facts.of(SourceFile)}
        self.assertEqual((lines["app/__init__.py"], lines["app/last.py"], lines["plugins/extra.py"]), (30, 2, 10))

    def test_vendored_code_is_not_counted(self) -> None:
        with temp_project({**PYTHON, "vendor/six.py": LINES * 100}) as root:
            lines = {source.path: source.lines for source in make_context(root).facts.of(SourceFile)}
        self.assertEqual(lines["vendor/six.py"], 0)


class PathTests(unittest.TestCase):
    def test_a_run_covers_the_paths_its_command_names(self) -> None:
        for line, expected in (
            ("ruff check app/", ("app",)),
            ("ruff check app plugins/extra.py", ("app", "plugins/extra.py")),
            ("ruff check 'plugins/*.py'", ("plugins/*.py",)),
            ("ruff check .", (".",)),  # its whole directory
            ("ruff check", ()),
            ("ruff check --config ruff.toml", ()),
            ("ruff check pyproject.toml", ()),  # a file of another language: what it names is not told
        ):
            with self.subTest(line=line):
                with temp_project({**PYTHON, **github_job("ubuntu-latest", line)}) as root:
                    [run] = make_context(root).facts.where(ToolRun, tool="ruff check")
                self.assertEqual(run.paths, expected)


class ShareTests(unittest.TestCase):
    def test_a_gate_whose_runs_miss_product_code_is_filled_by_the_share_they_reach(self) -> None:
        result = _run("ruff check app/")
        self.assertEqual((result.status, result.share), (Status.PASS, 0.75))
        self.assertIn("no run reaches plugins/ (10 lines, 25% of the Python lines)", result.details)

    def test_runs_together_cover_what_each_names(self) -> None:
        self.assertEqual(_run("ruff check app/", "pylint plugins").share, 1.0)

    def test_a_run_that_names_no_path_covers_its_whole_directory(self) -> None:
        result = _run("ruff check .")
        self.assertEqual((result.share, result.details), (1.0, ()))

    def test_auxiliary_code_it_skips_takes_nothing_off(self) -> None:
        """tests/ is test code and scripts/ tooling: a run that skips them misses none of the product's."""
        self.assertEqual(_run("ruff check app plugins").share, 1.0)

    def test_paths_that_are_not_known_take_nothing_off(self) -> None:
        result = _run("ruff check $CHANGED_FILES")
        self.assertEqual(result.share, 1.0)

    def test_a_build_file_in_the_language_takes_nothing_off(self) -> None:
        """setup.py is the build's, not the product's code a linter is pointed at."""
        files = {**PYTHON, "setup.py": "from setuptools import setup\nsetup()\n"}
        self.assertEqual(_run("ruff check app plugins", files=files).share, 1.0)

    def test_globs_reach_what_they_match(self) -> None:
        self.assertEqual(_run("ruff check 'app/*.py' 'plugins/*.py'").share, 1.0)

    def test_only_runs_that_enforce_the_gate_reach_code(self) -> None:
        """A formatter that only rewrites plugins/ enforces nothing there."""
        steps = ("ruff format plugins", "ruff format --check app")
        self.assertEqual(_run(*steps, check=code_formatting).share, 0.75)

    def test_a_test_runner_given_paths_is_not_judged_by_what_it_reaches(self) -> None:
        self.assertEqual(_run("pytest tests/test_app.py", check=tests_run).share, 1.0)

    def test_results_folded_together_keep_the_least_share(self) -> None:
        half, most = (Result(status=Status.PASS, message="", share=share) for share in (0.5, 0.75))
        folded = labelled({"a": half, "b": most})
        self.assertEqual(folded.share, 0.5)

    def test_a_subcommand_is_no_path(self) -> None:
        """deno's std has a fmt/ folder; `deno fmt --check` formats all of it."""
        files = {"deno.json": "{}", "fmt/a.ts": LINES * 5, "lib/b.ts": LINES * 5}
        self.assertEqual(_run("deno fmt --check", files=files, check=code_formatting).share, 1.0)

    def test_a_tools_configuration_takes_nothing_off(self) -> None:
        files = {**PYTHON, "noxfile.config.py": LINES, ".pythonrc.py": LINES}
        self.assertEqual(_run("ruff check app plugins", files=files).share, 1.0)
