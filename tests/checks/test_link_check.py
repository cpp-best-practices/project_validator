"""The link-check check: CI checks each documentation site's links and fails on a broken one, or warns; a project
with no documentation site is not asked."""

from __future__ import annotations

import unittest

from project_validator.checks.link_check import link_check
from project_validator.core import Result, Status
from project_validator.facts.links import LINKS
from project_validator.runner import run_check
from tests.layouts.documentation import BOOK, MKDOCS, PAGES
from tests.support import github_action, github_job, make_context, run_in_layout, temp_project

CHECKED = "CI checks the documentation's links with {}"
NOT_CHECKED = (Status.WARN, "no link check found in CI configuration")
SPHINX = {"docs/conf.py": 'project = "Shop"\nextensions = []\n', "docs/index.rst": "Shop\n====\n"}


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


class LinkCheckTests(unittest.TestCase):
    def test_applies_to_the_documentation_sites(self) -> None:
        self.assertEqual(link_check.aspect, LINKS)
        self.assertEqual(
            link_check.languages, frozenset({"MkDocs", "Sphinx", "Docusaurus", "mdBook", "Hugo", "Jekyll"})
        )

    def test_a_link_checker_run_on_the_site_passes_and_none_warns(self) -> None:
        for line, tool in (
            ("lychee --no-progress 'docs/**/*.md'", "lychee"),
            ("npx --yes markdown-link-check docs/index.md", "markdown-link-check"),
            ("linkinator site --recurse", "linkinator"),
            ("muffet http://localhost:8000", "muffet"),
            ("htmltest site", "htmltest"),
            ("bundle exec htmlproofer ./site", "HTMLProofer"),
            ("linkchecker site/index.html", "LinkChecker"),
        ):
            with self.subTest(line=line):
                result = run_in_layout(self, "MkDocs site", link_check, _ci("mkdocs build --strict", line))
                self.assertEqual(result, Result.passed(CHECKED.format(tool)))
        result = run_in_layout(self, "MkDocs site", link_check, _ci("mkdocs build --strict"))
        self.assertEqual((result.status, result.message), NOT_CHECKED)
        self.assertIn("lychee --no-progress", result.details[0])
        # `lychee --dump` lists the links without checking them.
        result = run_in_layout(self, "MkDocs site", link_check, _ci("lychee --dump 'docs/**/*.md'"))
        self.assertEqual(result.status, Status.WARN)

    def test_the_lychee_action_fails_the_job_unless_told_not_to(self) -> None:
        action = github_action("lycheeverse/lychee-action@v2", args="--no-progress 'docs/**/*.md'")
        self.assertEqual(
            run_in_layout(self, "MkDocs site", link_check, action), Result.passed(CHECKED.format("lychee"))
        )
        by_default = github_action("lycheeverse/lychee-action@v2")
        self.assertEqual(run_in_layout(self, "MkDocs site", link_check, by_default).status, Status.PASS)
        reporting = github_action("lycheeverse/lychee-action@v2", fail="false")
        self.assertEqual(run_in_layout(self, "MkDocs site", link_check, reporting).status, Status.WARN)

    def test_the_markdown_link_check_actions(self) -> None:
        for name in (
            "gaurav-nelson/github-action-markdown-link-check@v1",
            "tcort/github-action-markdown-link-check@v1",
        ):
            with self.subTest(action=name):
                result = run_in_layout(self, "MkDocs site", link_check, github_action(name, **{"folder-path": "docs"}))
                self.assertEqual(result, Result.passed(CHECKED.format("markdown-link-check")))

    def test_sphinx_checks_links_with_its_linkcheck_builder(self) -> None:
        for line in (
            "sphinx-build -b linkcheck docs docs/_build/linkcheck",
            "sphinx-build -M linkcheck docs docs/_build",
            "python -m sphinx --builder linkcheck docs docs/_build",
            "make -C docs linkcheck",
        ):
            with self.subTest(line=line):
                with temp_project({**SPHINX, **_ci(line)}) as root:
                    result = run_check(link_check, make_context(root))
                self.assertEqual(result, Result.passed(CHECKED.format("sphinx linkcheck")))
        with temp_project({**SPHINX, **_ci("sphinx-build -W docs docs/_build")}) as root:
            result = run_check(link_check, make_context(root))
        self.assertEqual((result.status, result.message), NOT_CHECKED)
        self.assertIn("sphinx-build -b linkcheck", result.details[0])

    def test_mdbook_checks_links_through_its_backend(self) -> None:
        with_backend = {"book.toml": BOOK + "\n[output.html]\n\n[output.linkcheck]\nfollow-web-links = true\n"}
        result = run_in_layout(self, "mdBook", link_check, {**with_backend, **_ci("mdbook build")})
        self.assertEqual(result, Result.passed(CHECKED.format("mdbook-linkcheck")))
        result = run_in_layout(self, "mdBook", link_check, _ci("mdbook build", "mdbook-linkcheck"))
        self.assertEqual(result.status, Status.PASS)
        result = run_in_layout(self, "mdBook", link_check, _ci("mdbook build"))
        self.assertEqual((result.status, result.message), NOT_CHECKED)
        self.assertIn("[output.linkcheck]", result.details[0])

    def test_mkdocs_checks_links_with_the_htmlproofer_plugin(self) -> None:
        with_plugin = {"mkdocs.yml": MKDOCS + "plugins:\n  - search\n  - htmlproofer\n"}
        result = run_in_layout(self, "MkDocs site", link_check, {**with_plugin, **_ci("mkdocs build --strict")})
        self.assertEqual(result, Result.passed(CHECKED.format("mkdocs-htmlproofer-plugin")))
        configured = {"mkdocs.yml": MKDOCS + "plugins:\n  - search\n  - htmlproofer:\n      raise_error: true\n"}
        result = run_in_layout(self, "MkDocs site", link_check, {**configured, **_ci("mkdocs build --strict")})
        self.assertEqual(result.status, Status.PASS)
        result = run_in_layout(self, "MkDocs site", link_check, {**with_plugin, **_ci("mkdocs serve")})
        self.assertEqual(result.status, Status.WARN)

    def test_a_scheduled_job_counts(self) -> None:
        workflow = (
            "on:\n  schedule:\n    - cron: '0 6 * * 1'\njobs:\n  links:\n    runs-on: ubuntu-latest\n"
            "    steps:\n      - run: lychee --no-progress 'docs/**/*.md'\n"
        )
        files = {"mkdocs.yml": MKDOCS, **PAGES, ".github/workflows/links.yml": workflow}
        with temp_project(files) as root:
            self.assertEqual(run_check(link_check, make_context(root)), Result.passed(CHECKED.format("lychee")))

    def test_does_not_apply_without_a_documentation_site(self) -> None:
        with temp_project({"README.md": "# Shop\n", "src/main.py": "", **_ci("lychee README.md")}) as root:
            result = run_check(link_check, make_context(root))
        self.assertEqual(result, Result.skipped("not applicable to Python"))
