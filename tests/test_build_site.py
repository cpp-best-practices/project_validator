"""Tests of tests/build_site.py: the documentation site CI publishes."""

from __future__ import annotations

import contextlib
import io
import os
import posixpath
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock

from leaderboard import entries
from leaderboard.evaluation import write
from leaderboard.history import record
from project_validator.ecosystems import PROFILES
from tests import build_site
from tests.build_site import ROOT, Site, build, pages, render_page, rewrite_links, title_of

SITE = Site(repository="owner/name", ref="main", revision="0123456789abcdef0123456789abcdef01234567")
PAGES = {"index.html", "docs/architecture.html", "docs/ecosystems/index.html", "docs/ecosystems/zig.html"}


class _Links(HTMLParser):
    """The hrefs and ids of a page."""

    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name == "href" and value:
                self.hrefs.append(value)
            elif name == "id" and value:
                self.ids.add(value)


def _parse(path: Path) -> _Links:
    links = _Links()
    links.feed(path.read_text(encoding="utf-8"))
    return links


class TitleTests(unittest.TestCase):
    def test_the_first_heading_is_the_title_without_code_marks(self) -> None:
        self.assertEqual(title_of("intro\n\n# The `coverage` check\n\n## not this\n"), "The coverage check")

    def test_a_page_without_a_heading_is_named_after_the_project(self) -> None:
        self.assertEqual(title_of("just text\n"), "project_validator")


class RewriteLinksTests(unittest.TestCase):
    def rewrite(self, source: str, page: str = "index.html") -> str:
        return rewrite_links(source, page, PAGES, SITE, ROOT)

    def test_a_markdown_page_becomes_its_html_page(self) -> None:
        self.assertEqual(self.rewrite("[a](docs/architecture.md)"), "[a](docs/architecture.html)")

    def test_a_directory_with_an_index_becomes_the_index(self) -> None:
        self.assertEqual(self.rewrite("[e](docs/ecosystems)"), "[e](docs/ecosystems/index.html)")

    def test_links_are_relative_to_the_linking_page(self) -> None:
        source = "[a](../architecture.md) [r](../../README.md#usage) [z](zig.md)"
        self.assertEqual(
            self.rewrite(source, page="docs/ecosystems/go.html"),
            "[a](../architecture.html) [r](../../index.html#usage) [z](zig.html)",
        )

    def test_a_fragment_and_a_title_survive(self) -> None:
        self.assertEqual(
            self.rewrite('[a](docs/architecture.md#facts "The facts")'), '[a](docs/architecture.html#facts "The facts")'
        )

    def test_anything_else_in_the_repository_points_at_github_at_the_revision(self) -> None:
        self.assertEqual(
            self.rewrite("[l](LICENSE.txt) [t](tests/fixtures)"),
            f"[l]({SITE.file_url('LICENSE.txt', directory=False)}) "
            f"[t]({SITE.file_url('tests/fixtures', directory=True)})",
        )
        self.assertEqual(
            self.rewrite("[p](../project_validator/cli.py)", page="docs/architecture.html"),
            f"[p]({SITE.file_url('project_validator/cli.py', directory=False)})",
        )

    def test_absolute_and_anchor_links_are_left_alone(self) -> None:
        source = "[u](https://example.com/a.md) [m](mailto:x@y.z) [a](#adding-an-ecosystem)"
        self.assertEqual(self.rewrite(source), source)


class RenderPageTests(unittest.TestCase):
    def test_a_page_says_which_branch_and_commit_it_was_built_from(self) -> None:
        page = render_page("# T\n\nbody\n", "index.html", SITE, "2026-11-10")
        self.assertIn("Built from <code>main</code> at ", page)
        self.assertIn(f'<a href="https://github.com/owner/name/commit/{SITE.revision}">0123456</a> on 2026-11-10', page)
        self.assertIn("<title>T - project_validator</title>", page)
        self.assertIn("<p>body</p>", page)

    def test_the_navigation_is_relative_and_marks_the_current_section(self) -> None:
        page = render_page("# E\n", "docs/ecosystems/index.html", SITE, "2026-11-10")
        self.assertIn('<a href="../../index.html">Overview</a>', page)
        self.assertIn('<a href="../../docs/support-matrix.html">Support matrix</a>', page)
        self.assertIn('<a href="../../docs/ecosystems/index.html" class="active">Ecosystems</a>', page)
        board = render_page("# P\n", "leaderboard/projects/o--r.html", SITE, "2026-11-10")
        self.assertIn('<a href="../../leaderboard/index.html" class="active">Leaderboard</a>', board)
        self.assertIn('class="page wrap wide"', board)
        self.assertIn('<link rel="stylesheet" href="../../style.css">', page)

    def test_headings_get_the_ids_github_gives_them_and_tables_render(self) -> None:
        source = "# T\n\n## Adding an ecosystem\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
        page = render_page(source, "index.html", SITE, "d")
        self.assertIn('<h2 id="adding-an-ecosystem">', page)
        self.assertIn("<td>1</td>", page)

    def test_a_placeholder_in_code_is_shown_not_parsed_as_a_tag(self) -> None:
        page = render_page("# T\n\n`docs/ecosystems/<name>.md`\n", "index.html", SITE, "d")
        self.assertIn("&lt;name&gt;", page)


class PagesTests(unittest.TestCase):
    def test_the_pages_are_the_readme_the_docs_their_index_and_the_generated_matrix(self) -> None:
        found = pages(ROOT)
        self.assertIn("index.html", found)
        self.assertIn("docs/architecture.html", found)
        self.assertIn("docs/ecosystems/index.html", found)
        self.assertTrue(found["docs/support-matrix.html"].startswith("# Support matrix\n"))
        for profile in PROFILES:
            self.assertIn(f"docs/ecosystems/{profile}.html", found)

    def test_the_ecosystems_index_links_every_ecosystem_page_by_its_title(self) -> None:
        index = pages(ROOT)["docs/ecosystems/index.html"]
        self.assertIn("- [Fortran](fortran.md)", index)
        self.assertIn("- [C](c.md)", index)
        self.assertIn("- [C++](cpp.md)", index)
        self.assertEqual(index.count("\n- ["), len(PROFILES))


def _nightly(name: str, language: str) -> dict[str, object]:
    """A night's result for a project, as `leaderboard evaluate` writes it."""
    return {
        "name": name,
        "language": language,
        "commit": "c" * 40,
        "validator": "v" * 40,
        "evaluated": "2026-11-18T03:17:00Z",
        "score": {
            "version": "1",
            "percent": 50.0,
            "level": 1,
            "level_name": "Foundations",
            "filled": 1,
            "slots": 2,
            "summary": "50% · Level 1 Foundations · 1 of 2 gates in place",
            "cells": [],
            "next_steps": [],
        },
    }


class BuildTests(unittest.TestCase):
    def test_the_site_builds_from_the_repository_and_every_link_and_anchor_resolves(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            written = build(ROOT, output, SITE)
            self.assert_links_resolve(output, written)
            self.assertIn("leaderboard/index.html", written)

    def test_the_leaderboard_is_built_from_the_nightly_results(self) -> None:
        listed = entries(ROOT / "leaderboard" / "projects.toml")
        result = _nightly(listed[0].name, listed[0].language)
        with tempfile.TemporaryDirectory() as tmp:
            results, data, output = Path(tmp) / "results", Path(tmp) / "data", Path(tmp) / "site"
            write(result, results)
            record(results, data, "2026-11-18")
            written = build(ROOT, output, SITE, data)
            self.assert_links_resolve(output, written)
            slug = listed[0].slug
            self.assertIn(f"leaderboard/projects/{slug}.html", written)
            self.assertIn(f"leaderboard/badges/{slug}.json", written)
            page = (output / "leaderboard" / "projects" / f"{slug}.html").read_text(encoding="utf-8")
        self.assertIn(f"https://owner.github.io/name/leaderboard/badges/{slug}.json", page)
        self.assertEqual(Site(repository="Owner/Name", ref="", revision="").pages_url, "https://owner.github.io/Name/")

    def assert_links_resolve(self, output: Path, written: list[str]) -> None:
        files = sorted(path.relative_to(output).as_posix() for path in output.rglob("*.*"))
        self.assertEqual(sorted(written), files)
        parsed = {page: _parse(output / page) for page in written if page.endswith(".html")}
        for page, links in parsed.items():
            for href in links.hrefs:
                if "://" in href:
                    continue
                path, _, fragment = href.partition("#")
                target = posixpath.normpath(posixpath.join(posixpath.dirname(page), path)) if path else page
                self.assertIn(target, written, f"{page} links to {href}")
                if fragment:
                    self.assertIn(fragment, parsed[target].ids, f"{page} links to {href}")

    def test_the_readme_links_the_site(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("https://cpp-best-practices.github.io/project_validator/", readme)


class MainTests(unittest.TestCase):
    def test_runs_as_a_script_and_lists_what_it_wrote(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            done = subprocess.run(  # noqa: S603 - tests
                [sys.executable, build_site.__file__, tmp, "--ref", "main", "--revision", "abc1234"],
                capture_output=True,
                encoding="utf-8",
                check=False,
                env={**os.environ, "PYTHONPATH": str(ROOT)},
            )
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn("docs/support-matrix.html\n", done.stdout)
            self.assertIn("leaderboard/index.html\n", done.stdout)
            self.assertIn("Built from <code>main</code> at ", (Path(tmp) / "index.html").read_text(encoding="utf-8"))

    def test_defaults_to_the_checked_out_branch_and_commit(self) -> None:
        answers = {("branch", "--show-current"): "topic", ("rev-parse", "HEAD"): "f" * 40}
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(build_site, "_git", side_effect=lambda *arguments: answers[arguments]),
            contextlib.redirect_stdout(io.StringIO()) as printed,
        ):
            self.assertEqual(build_site.main(["build_site.py", tmp]), 0)
            page = (Path(tmp) / "index.html").read_text(encoding="utf-8")
        self.assertIn("index.html\n", printed.getvalue())
        self.assertIn("Built from <code>topic</code> at ", page)
        self.assertIn(f'/commit/{"f" * 40}">fffffff</a>', page)

    def test_a_detached_head_is_named_so(self) -> None:
        answers = {("branch", "--show-current"): "", ("rev-parse", "HEAD"): "f" * 40}
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(build_site, "_git", side_effect=lambda *arguments: answers[arguments]),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(build_site.main(["build_site.py", tmp]), 0)
            self.assertIn("Built from <code>HEAD</code> at ", (Path(tmp) / "index.html").read_text(encoding="utf-8"))
