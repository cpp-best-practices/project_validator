"""The views of an analysis: plain text, the console, the HTML report, the progress shown while working, and the TUI.
Each says what was detected and how the project was read, every result, and the score."""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import io
import json
import re
import tempfile
import unittest
from collections.abc import AsyncIterator
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

from project_validator.analysis import Analysis, analyse
from project_validator.cli import EXIT_FAILURE, EXIT_USAGE
from project_validator.core import ExtractionError, Progress, Result, Status
from project_validator.plugins import discover
from project_validator.views import common, html, text, tui
from project_validator.views import console as console_view
from project_validator.views.common import LanguageView, language_views
from project_validator.views.progress import ProgressView
from tests.support import FIXTURES, make_context, requires_rich, temp_project
from tests.test_cli import run_cli

requires_textual = unittest.skipUnless(tui.available(), "textual is not installed")

MIXED = {
    "CMakeLists.txt": "project(app CXX)\n",
    "src/main.cpp": "",
    "tests/test_main.cpp": "",
    "scripts/release.py": "",
    "third_party/lib/lib.c": "",
    "README.md": "<script>alert('readme')</script>",
}


def _analysis(files: dict[str, str] | None = None, *, fixture: str | None = None) -> Analysis:
    if fixture is not None:
        return analyse(make_context(FIXTURES / fixture), discover().checks)
    with temp_project(files or MIXED) as root:
        return analyse(make_context(root), discover().checks)


class _Tags(HTMLParser):
    """The tags of an HTML document, and the external resources it loads."""

    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.external: list[str] = []
        self.open: list[str] = []
        self.unbalanced: list[str] = []

    VOID = frozenset({"meta", "link", "br", "input", "img", "circle", "hr"})

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        found = dict(attrs)
        if found.get("id"):
            self.ids.add(str(found["id"]))
        for name in ("src", "href"):
            value = found.get(name) or ""
            if tag in ("script", "link", "img") and value.startswith(("http:", "https:", "//")):
                self.external.append(value)
        if tag not in self.VOID:
            self.open.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in self.VOID:
            return
        if self.open and self.open[-1] == tag:
            self.open.pop()
        else:
            self.unbalanced.append(tag)


class CommonTests(unittest.TestCase):
    def test_a_place_is_named_by_language_unit_and_what_named_it_auxiliary(self) -> None:
        from project_validator.core import Placed

        self.assertEqual(common.place_label(Placed(ecosystem="C++", unit=".", result=Result.passed(""))), "C++")
        place = Placed(ecosystem="Python", unit="tools", result=Result.passed(""), auxiliary=("tooling",))
        self.assertEqual(common.place_label(place), "Python in tools (auxiliary: tooling)")

    def test_the_checks_are_grouped_by_category_worst_first_without_the_skipped(self) -> None:
        groups = common.grouped(_analysis().reports)
        self.assertEqual([group.category for group in groups][:2], ["Build", "Tests"])
        for group in groups:
            statuses = [common.STATUS_ORDER.index(report.result.status) for report in group.reports]
            self.assertEqual(statuses, sorted(statuses))
            self.assertNotIn(Status.SKIP, {report.result.status for report in group.reports})

    def test_extra_credit_is_shown_in_tenths_below_a_point(self) -> None:
        self.assertEqual((common.credit(0.42), common.credit(3.9)), ("0.4", "3"))

    def test_a_detached_checkout_says_so(self) -> None:
        from project_validator.analysis import Git

        self.assertEqual(common.branch_label(Git(branch="HEAD")), "detached")
        self.assertEqual(common.branch_label(Git(branch="main")), "main")

    def test_a_project_that_could_not_be_read_has_no_languages_or_units(self) -> None:
        unread = dataclasses.replace(_analysis(), structure=None)
        self.assertEqual((common.ecosystems(unread), common.units(unread)), ([], []))

    def test_what_git_ignores_is_said_to_be_left_out(self) -> None:
        """#316: the files git ignores are not read; the report says how many paths were left out, when any were."""
        self.assertNotIn("ignore", common.reading(_analysis()))
        left_out = dataclasses.replace(_analysis(), ignored=("generated/", "debug.log"))
        self.assertRegex(common.reading(left_out), r"facts in \d+\.\d\d s; 2 paths git ignores left out$")

    def test_what_was_read_only_in_part_is_said_and_listed(self) -> None:
        """A script the parser follows only in part is noted where the report says what was read, not judged."""
        from project_validator.facts import Facts, Origin, PartlyRead

        noted = PartlyRead(origin=Origin(path="ci.sh"), subject="the command 'echo \"x'", reason="No closing quotation")
        analysis = _analysis()
        analysis = dataclasses.replace(analysis, facts=Facts((*analysis.facts, noted)))
        self.assertRegex(common.reading(analysis), r"facts in \d+\.\d\d s; 1 place read only in part$")
        self.assertIn(
            "  Read in part: the command 'echo \"x': No closing quotation (ci.sh)", text.detected_lines(analysis)
        )

    def test_code_named_auxiliary_is_judged_so(self) -> None:
        from project_validator.analysis import RoleSummary

        found = RoleSummary(role="test", directories=("tests",), files=1, languages=("C++",), auxiliary=True)
        self.assertEqual(common.role_judgement(found), "judged as auxiliary code (--auxiliary)")


class LanguageViewTests(unittest.TestCase):
    """One language's own view (upstream #388): where its files are, and what each check says of it."""

    def test_each_language_has_its_files_and_its_results(self) -> None:
        views = {view.language: view for view in language_views(_analysis())}
        python = views["Python"]
        self.assertEqual(python.anchor, "language-python")
        self.assertEqual([place.directory for place in python.places], ["scripts"])
        checks = {result.check: result for result in python.results}
        self.assertIn("static-analysis", checks)
        self.assertNotIn("compile-commands", checks)  # a C and C++ check says nothing of Python
        self.assertIn("C++", views)

    def test_a_formats_results_come_through_its_ecosystem(self) -> None:
        """YAML's checks speak of it as Data."""
        workflow = "on: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n      - run: cmake .\n"
        views = {
            view.language: view for view in language_views(_analysis({**MIXED, ".github/workflows/ci.yml": workflow}))
        }
        self.assertIn("data-wellformed", {result.check for result in views["YAML"].results})

    def test_a_language_without_files_or_checks_says_so(self) -> None:
        self.assertEqual(tui.language_page(_analysis(), "Rust"), "No Rust files were found.")
        lonely = LanguageView(language="Typst", files="1 file (10%)", places=(), results=())
        with mock.patch.object(tui, "language_views", return_value=[lonely]):
            self.assertIn("no check judges it", tui.language_page(_analysis(), "Typst"))

    def test_the_terminal_page_shows_the_view(self) -> None:
        page = tui.language_page(_analysis(), "Python")
        self.assertIn("Python", page)
        self.assertIn("scripts/", page)
        self.assertIn("static-analysis", page)


class TextTests(unittest.TestCase):
    def test_the_report_says_what_was_detected_before_the_results(self) -> None:
        report = text.render(_analysis())
        detected, _, results = report.partition("\n\n")
        self.assertIn("  C++: build file CMakeLists.txt", detected)
        self.assertIn("  Unit the root (product): built with CMake;", detected)
        self.assertIn("Code of tests: tests/ (1 file, C++): judged as the product; --auxiliary test", detected)
        self.assertIn("Code of vendored code: third_party/ (1 file, C): other projects' code: never judged", detected)
        self.assertIn("  CI: none found", detected)
        self.assertRegex(detected, r"  Read: [\d,]+ facts in \d+\.\d\d s")
        self.assertIn("[FAIL] ci-present:", results)
        self.assertRegex(report, r"\n\d+ checks: \d+ passed")

    def test_the_score_is_appended_when_asked(self) -> None:
        analysis = _analysis()
        self.assertNotIn("Score:", text.render(analysis))
        self.assertIn("Score: ", text.render(analysis, scored=True))
        self.assertIn("Next steps:", text.render(analysis, scored=True))

    def test_repeated_details_are_said_once(self) -> None:
        from project_validator.core import Check
        from project_validator.runner import Report

        report = Report(
            check=Check(name="c", description="", run=lambda _: Result.passed("")),
            result=Result.warned("m", "same", "same", "other"),
        )
        self.assertEqual(text.report_lines([report]), ["[WARN] c: m", "    same", "    other"])

    def test_a_project_that_could_not_be_read_says_why(self) -> None:
        with temp_project(MIXED) as root:
            context = make_context(root)
            context._extracted = ExtractionError("the CI configuration", ValueError("broken"))
            analysis = analyse(context, discover().checks)
        self.assertRegex(text.render(analysis), r"could not be read: .*the CI configuration raised ValueError")


@requires_rich
class ConsoleTests(unittest.TestCase):
    def _render(self, analysis: Analysis, **options: bool) -> str:
        stream = io.StringIO()
        console_view.render(analysis, stream, width=120, **options)
        return re.sub(r"\x1b\[[0-9;]*m", "", stream.getvalue())

    def test_the_report_has_a_header_detection_results_and_score(self) -> None:
        output = self._render(_analysis())
        for expected in ("project_validator", "What was detected", "Recognised by", "Code: tests", "Build", "Score"):
            with self.subTest(expected=expected):
                self.assertIn(expected, output)
        self.assertRegex(output, r"\d+% +Level \d")

    def test_the_skipped_checks_are_counted_unless_verbose(self) -> None:
        analysis = _analysis()
        self.assertIn("checks do not apply here", self._render(analysis))
        verbose = self._render(analysis, verbose=True)
        self.assertIn("Not applicable", verbose)
        self.assertIn("the project's structure:", verbose)

    def test_a_result_of_several_places_has_a_line_for_each(self) -> None:
        output = self._render(_analysis())
        self.assertRegex(output, r"✘ +C\+\+ +no static analyzer runs")
        self.assertRegex(output, r"▲ +Python \(auxiliary: only in tooling code\) +no static analyzer runs")

    def test_long_details_are_cut_unless_verbose(self) -> None:
        analysis = _analysis(fixture="well_configured_cpp")
        self.assertIn("more (--verbose shows them)", self._render(analysis))
        self.assertNotIn("more (--verbose shows them)", self._render(analysis, verbose=True))

    def test_a_project_that_could_not_be_read_says_why(self) -> None:
        with temp_project(MIXED) as root:
            context = make_context(root)
            context._extracted = ExtractionError("the CI configuration", ValueError("broken"))
            output = self._render(analyse(context, discover().checks))
        self.assertIn("could not be read", output)

    def test_the_score_is_coloured_by_how_much_is_in_place(self) -> None:
        styles = [console_view.score_style(percent) for percent in (100, 80, 60, 10)]
        self.assertEqual(styles, ["bold green", "green", "yellow", "red"])

    def test_a_checkout_shows_its_branch_and_commit_and_unknown_suffixes_are_listed(self) -> None:
        from project_validator.analysis import Git

        analysis = _analysis({**MIXED, "data/a.zyx": "", "data/b.zyx": ""})
        output = self._render(dataclasses.replace(analysis, git=Git(commit="c" * 40, branch="main")))
        self.assertIn(f"main @ {'c' * 10}", output)
        self.assertRegex(output, r"Not recognised +\.zyx \(2\)")

    def test_without_rich_installed_nothing_is_imported(self) -> None:
        with mock.patch("importlib.import_module", side_effect=ImportError("rich")):
            self.assertIsNone(console_view._import_rich())

    def test_without_rich_it_is_an_error(self) -> None:
        with mock.patch.object(console_view, "_rich", None):
            self.assertFalse(console_view.available())
            with self.assertRaisesRegex(console_view.ConsoleError, "rich is not available"):
                console_view.render(_analysis(), io.StringIO())


class HtmlTests(unittest.TestCase):
    analysis: ClassVar[Analysis]
    document: ClassVar[str]
    tags: ClassVar[_Tags]

    @classmethod
    def setUpClass(cls) -> None:
        cls.analysis = _analysis()
        cls.document = html.render(cls.analysis)
        cls.tags = _Tags()
        cls.tags.feed(cls.document)

    def test_it_is_one_self_contained_document(self) -> None:
        self.assertTrue(self.document.startswith("<!DOCTYPE html>"))
        self.assertEqual(self.tags.external, [])
        self.assertIn("<style>", self.document)
        self.assertEqual(self.tags.unbalanced, [])

    def test_it_has_every_section(self) -> None:
        for anchor, _ in html.SECTIONS:
            with self.subTest(section=anchor):
                self.assertIn(anchor, self.tags.ids)

    def test_every_check_has_a_result_to_link_to(self) -> None:
        for report in self.analysis.reports:
            self.assertIn(html._anchor(report.check.name), self.tags.ids)

    def test_each_language_links_to_its_own_view(self) -> None:
        self.assertIn("language-python", self.tags.ids)
        self.assertIn('href="#language-python"', self.document)
        self.assertIn(".language-view:target", self.document)  # shown when its link is followed

    def test_arrow_keys_open_and_close_the_trees(self) -> None:
        self.assertIn("ArrowRight", self.document)
        self.assertIn("ArrowLeft", self.document)

    def test_what_the_project_supplies_is_escaped(self) -> None:
        # A job's name, not a file's: Windows forbids "<" in a file name.
        workflow = "on: push\njobs:\n  evil:\n    name: evil<script>alert(1)</script>\n    runs-on: ubuntu-latest\n"
        workflow += "    steps:\n      - run: pytest\n"
        with temp_project({**MIXED, ".github/workflows/ci.yml": workflow}) as root:
            document = html.render(analyse(make_context(root), discover().checks))
        self.assertNotIn("<script>alert", document)
        self.assertIn("evil&lt;script&gt;alert(1)", document)  # in the page
        self.assertIn("evil\\u003cscript>alert(1)\\u003c/script>", document)  # in the facts' JSON, no "<" to end it

    def test_the_facts_travel_as_json_with_each_kind_described(self) -> None:
        payload = self.document.split('<script type="application/json" id="facts-data">', 1)[1]
        data = json.loads(payload.split("</script>", 1)[0])
        self.assertEqual(len(data["facts"]), len(self.analysis.facts.all))
        kinds = {kind: doc for kind, _, doc in data["kinds"]}
        self.assertIn("SourceFile", kinds)
        self.assertTrue(kinds["SourceFile"].startswith("A source file"))

    def test_the_score_and_the_roles_are_explained(self) -> None:
        self.assertIn("100% means every quality gate", self.document)
        self.assertIn("--auxiliary test would judge it as auxiliary", self.document)

    def test_a_checkout_links_its_files_and_commit(self) -> None:
        from project_validator.analysis import Git

        git = Git(commit="a" * 40, branch="main", web="https://github.com/o/r")
        analysis = dataclasses.replace(self.analysis, git=git)
        document = html.render(analysis)
        self.assertIn(f"https://github.com/o/r/commit/{'a' * 40}", document)
        self.assertIn(f"https://github.com/o/r/blob/{'a' * 40}/src/main.cpp", document)

    def test_many_ci_jobs_are_folded(self) -> None:
        document = html.render(_analysis(fixture="well_configured_cpp"))
        self.assertIn("more jobs</summary>", document)

    def test_a_project_that_could_not_be_read_says_why(self) -> None:
        with temp_project(MIXED) as root:
            context = make_context(root)
            context._extracted = ExtractionError("the CI configuration", ValueError("broken"))
            document = html.render(analyse(context, discover().checks))
        self.assertRegex(document, r"could not be read: .*the CI configuration raised ValueError")
        self.assertNotIn('id="next"', document)


class ProgressViewTests(unittest.TestCase):
    @requires_rich
    def test_the_stages_are_listed_as_they_finish(self) -> None:
        stream = io.StringIO()
        with ProgressView(stream) as view:
            view(Progress(kind="stage", name="the CI jobs", done=False))
            view(Progress(kind="stage", name="the CI jobs", done=True, seconds=0.25, found=12))
            view(Progress(kind="check", name="coverage", done=False, index=3, total=40))
            view(Progress(kind="check", name="coverage", done=True, index=3, total=40))
        output = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", stream.getvalue())
        self.assertIn("Working out what each CI job builds, and on what 12 facts, 0.25 s", output)

    def test_without_rich_it_shows_nothing(self) -> None:
        stream = io.StringIO()
        with mock.patch("project_validator.views.progress.available", return_value=False), ProgressView(stream) as view:
            view(Progress(kind="stage", name="x", done=True))
        self.assertEqual(stream.getvalue(), "")


class TuiPageTests(unittest.TestCase):
    def test_the_pages_say_what_the_other_views_say(self) -> None:
        analysis = _analysis()
        self.assertRegex(tui.overview(analysis), r"\d+%")
        self.assertIn("Languages and formats", tui.detected(analysis))
        self.assertIn("Next steps", tui.next_steps(analysis))
        report = next(report for report in analysis.reports if report.check.name == "static-analysis")
        self.assertIn("static-analysis", tui.report_page(report))
        self.assertIn("Static analysers find", tui.report_page(report))

    def test_the_facts_are_listed_by_kind_and_searched(self) -> None:
        analysis = _analysis()
        self.assertIn("SourceFile", tui.facts_page(analysis, "SourceFile"))
        self.assertIn("matching", tui.facts_page(analysis, None, "release.py"))
        self.assertIn("1 of", tui.facts_page(analysis, None, "release.py"))

    def test_a_project_that_could_not_be_read_says_why(self) -> None:
        error = ExtractionError("the CI configuration", ValueError("broken"))
        unread = dataclasses.replace(_analysis(), structure=None, error=error)
        self.assertIn(f"could not be read:[/] {tui.markup(error)}", tui.detected(unread))

    def test_the_ci_jobs_are_listed_with_their_os(self) -> None:
        workflow = "on: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n      - run: cmake --build b\n"
        detected = tui.detected(_analysis({**MIXED, ".github/workflows/ci.yml": workflow}))
        self.assertRegex(detected, r"build \[dim\]linux")

    def test_a_result_of_the_whole_project_lists_its_details(self) -> None:
        report = next(report for report in _analysis().reports if report.check.name == "ci-present")
        page = tui.report_page(dataclasses.replace(report, result=Result.failed("none", "detail one")))
        self.assertIn("[dim]detail one[/]", page)

    def test_with_nothing_left_to_do_the_next_steps_say_so(self) -> None:
        analysis = _analysis()
        score = analysis.score
        self.assertIsNotNone(score)
        done = dataclasses.replace(analysis, score=dataclasses.replace(score, next_steps=()))  # type: ignore[type-var]
        self.assertEqual(tui.next_steps(done), "Every quality gate that applies is in place.")

    def test_only_the_first_facts_are_listed(self) -> None:
        with mock.patch.object(tui, "FACTS_SHOWN", 2):
            page = tui.facts_page(_analysis(), None)
        self.assertIn("more; search to narrow them", page)
        self.assertEqual(page.count("\n  [dim]"), 2)

    def test_markup_in_the_project_s_text_is_escaped(self) -> None:
        self.assertEqual(tui.markup("[bold]x"), r"\[bold]x")

    def test_without_textual_the_option_says_how_to_get_it(self) -> None:
        with mock.patch.object(tui, "available", return_value=False):
            code, _, errors = run_cli("--tui", str(FIXTURES / "bare_python"))
        self.assertEqual(code, EXIT_USAGE)
        self.assertIn("pip install project_validator[tui]", errors)


@contextlib.asynccontextmanager
async def _analysed_tui() -> AsyncIterator[tuple[Any, Any]]:
    """The TUI on MIXED, and its pilot, once the analysis is read."""
    with temp_project(MIXED) as root:
        app = tui.build_app(make_context(root), discover().checks, [c.name for c in discover().checks])
        async with app.run_test() as pilot:
            for _ in range(100):
                await pilot.pause(0.05)
                if app.analysis is not None:  # type: ignore[attr-defined]
                    break
            yield app, pilot


async def _drive_tui() -> list[str]:
    """Run the TUI on MIXED: wait for the analysis, search the facts, open what was detected, then three pages."""
    async with _analysed_tui() as (app, pilot):
        seen = [str(app.sub_title)]
        await pilot.press("slash", *"release")
        await pilot.pause(0.1)
        seen.append(str(app.query_one("#pane").render()))
        await pilot.press("escape", "down", "down", "enter")
        await pilot.pause(0.1)
        seen.append(str(app.query_one("#pane").render()))
        analysis = app.analysis
        report = next(report for report in analysis.reports if report.check.name == "static-analysis")
        for page, value in (("facts", "SourceFile"), ("next", None), ("report", report)):
            app._page(page, value)
            seen.append(str(app.query_one("#pane").render()))
        await pilot.press("q")
        return seen


async def _arrow_keys() -> list[bool]:
    """Run the TUI on MIXED and walk its tree with the arrow keys: Left collapses a node, Right expands it, and Right
    again moves to its first child; Left on a leaf moves to its parent."""
    async with _analysed_tui() as (app, pilot):
        tree = app.query_one("#nav")
        seen = [tree.root.is_expanded]
        await pilot.press("left")
        seen.append(tree.root.is_expanded)
        await pilot.press("right")
        seen.append(tree.root.is_expanded)
        await pilot.press("right")
        seen.append(tree.cursor_node is tree.root.children[0])
        await pilot.press("right")  # a leaf: nowhere further to go
        seen.append(tree.cursor_node is tree.root.children[0])
        await pilot.press("left")
        seen.append(tree.cursor_node is tree.root)
        await pilot.press("q")
        return seen


async def _empty_branch() -> bool:
    """Right on an expanded branch with no children stays where it is."""
    from textual.app import App, ComposeResult

    from project_validator.views.tui_app import NavTree

    class _One(App[None]):
        def compose(self) -> ComposeResult:
            tree: NavTree = NavTree("root", id="nav")
            tree.root.expand()
            yield tree

    app = _One()
    async with app.run_test() as pilot:
        tree = app.query_one("#nav", NavTree)
        tree.focus()
        await pilot.press("right")
        return tree.cursor_node is tree.root


@requires_textual
class TuiAppTests(unittest.TestCase):
    def test_right_on_an_empty_branch_stays(self) -> None:
        self.assertTrue(asyncio.run(_empty_branch()))

    def test_arrow_keys_collapse_expand_and_move(self) -> None:
        self.assertEqual(asyncio.run(_arrow_keys()), [True, False, True, True, True, True])

    def test_it_reads_the_project_then_browses_it(self) -> None:
        title, facts, detected, kind, steps, report = asyncio.run(_drive_tui())
        self.assertRegex(title, r"\d+% · Level")
        self.assertIn("release", facts)
        self.assertIn("Languages and formats", detected)
        self.assertIn("SourceFile", kind)
        self.assertIn("Next steps", steps)
        self.assertIn("Static analysers find", report)

    def test_its_exit_code_is_the_app_s_or_0(self) -> None:
        app = mock.Mock()
        app.run.return_value = None
        with mock.patch.object(tui, "build_app", return_value=app):
            self.assertEqual(tui.run(make_context(FIXTURES / "bare_python"), (), ()), 0)


class CliTests(unittest.TestCase):
    def test_html_writes_the_report_beside_any_format(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.html"
            code, output, _ = run_cli("--html", str(path), "--format", "json", str(FIXTURES / "bare_python"))
            self.assertEqual(code, EXIT_FAILURE)
            self.assertIsInstance(json.loads(output), list)
            self.assertTrue(path.read_text(encoding="utf-8").startswith("<!DOCTYPE html>"))

    def test_markdown_ends_with_the_score_when_asked(self) -> None:
        _, output, _ = run_cli("--format", "markdown", "--score", str(FIXTURES / "bare_python"))
        self.assertRegex(output, r"\*\*Score:\*\* \d+% · Level \d")

    def test_format_html_prints_the_report(self) -> None:
        _, output, _ = run_cli("--format", "html", str(FIXTURES / "bare_python"))
        self.assertTrue(output.startswith("<!DOCTYPE html>"))

    @requires_rich
    def test_verbose_shows_every_detail_in_the_console(self) -> None:
        _, output, _ = run_cli("--color", "always", "--verbose", str(FIXTURES / "well_configured_cpp"))
        self.assertIn("Not applicable", output)

    @requires_rich
    def test_progress_is_shown_on_a_terminal_s_stderr_only(self) -> None:
        from argparse import Namespace

        from project_validator.cli import _progress

        shown = Namespace(tui=False, color="auto")
        with mock.patch("sys.stderr") as stderr:
            stderr.isatty.return_value = True
            self.assertIsInstance(_progress(shown), ProgressView)
            self.assertNotIsInstance(_progress(Namespace(tui=False, color="never")), ProgressView)
            self.assertNotIsInstance(_progress(Namespace(tui=True, color="auto")), ProgressView)
            stderr.isatty.return_value = False
            self.assertNotIsInstance(_progress(shown), ProgressView)


if __name__ == "__main__":
    unittest.main()
