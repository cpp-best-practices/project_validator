"""The documentation-site profile: six generators, each a format recognised by its configuration; the build as its
tests, the strict build as warnings as errors, the prose linters, and the built site as an output."""

from __future__ import annotations

import unittest
from collections.abc import Mapping

from project_validator.checks.committed_artifacts import committed_artifacts
from project_validator.checks.static_analysis import static_analysis
from project_validator.checks.tests_run import tests_run
from project_validator.checks.vcs_ignore import vcs_ignore
from project_validator.checks.warnings_as_errors import warnings_as_errors
from project_validator.core import Check, Result, Status
from project_validator.ecosystems.documentation import DOCUMENTATION, GENERATORS
from tests.layouts.documentation import BOOK, MKDOCS, PAGES
from tests.support import github_action, github_job, make_context, run_in_layout, temp_project, uses

SPHINX = {"docs/conf.py": "project = 'Shop'\nextensions = ['myst_parser']\n", "docs/index.rst": "Shop\n====\n"}
DOCUSAURUS = {"docusaurus.config.js": "module.exports = { title: 'Shop', onBrokenLinks: 'throw' };\n"}
HUGO = {"hugo.toml": 'baseURL = "https://shop.example.com/"\ntitle = "Shop"\n'}
JEKYLL = {"_config.yml": "title: Shop\n", "_posts/2026-01-01-prices.md": "---\ntitle: Prices\n---\n"}


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


def _run_on(selected: Check, files: Mapping[str, str]) -> Result:
    """The result of `selected` for the documentation site in a project of `files`: a generator whose configuration
    is also a language (Sphinx's conf.py, Docusaurus's config) is judged beside that language."""
    with temp_project(files) as root:
        result = selected.run(make_context(root))
    place = next((found for found in result.places if found.ecosystem == DOCUMENTATION.label), None)
    return result if place is None else place.result


class RecognitionTests(unittest.TestCase):
    def test_each_generator_is_told_by_its_configuration(self) -> None:
        cases = (
            ({"mkdocs.yml": MKDOCS, **PAGES}, "MkDocs"),
            (SPHINX, "Sphinx"),
            (DOCUSAURUS, "Docusaurus"),
            ({"book.toml": BOOK}, "mdBook"),
            (HUGO, "Hugo"),
            (JEKYLL, "Jekyll"),
            ({"_config.yml": "remote_theme: just-the-docs/just-the-docs\n"}, "Jekyll"),
        )
        for files, generator in cases:
            with self.subTest(generator=generator), temp_project(files) as root:
                structure = make_context(root).structure
                self.assertIn(generator, structure.formats)
                self.assertEqual(structure.recognised_by["Documentation site"], ("content",))
        # Prose alone, a conf.py that is not Sphinx's, and a _config.yml that is not a site's are no documentation site.
        not_sites = (
            {"README.md": "# Shop\n", "docs/guide.md": "# Guide\n"},
            {"conf.py": "DEBUG = False\n"},
            {"_config.yml": "debug: false\n"},
        )
        for files in not_sites:
            with self.subTest(files=files), temp_project(files) as root:
                self.assertFalse(make_context(root).structure.formats & GENERATORS)
        self.assertEqual((DOCUMENTATION.kind, DOCUMENTATION.toolchain), ("format", None))

    def test_ci_usage(self) -> None:
        for text in (
            "mkdocs build --strict",
            "sphinx-build -W docs out",
            "hugo --minify",
            "uses: peaceiris/actions-hugo@v3",
        ):
            with self.subTest(text=text):
                self.assertTrue(uses(DOCUMENTATION, text))
        self.assertFalse(uses(DOCUMENTATION, "npm test"))


class MkDocsTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_in_layout(self, "MkDocs site", selected, files)

    def test_the_build_is_the_test_and_strict_makes_warnings_errors(self) -> None:
        for line in ("mkdocs build", "mkdocs gh-deploy --force", "pipx run mkdocs build"):
            with self.subTest(line=line):
                self.assertEqual(self._run(tests_run, _ci(line)).status, Status.PASS)
        self.assertEqual(
            self._run(tests_run, github_action("mhausenblas/mkdocs-deploy-gh-pages@master")).status, Status.PASS
        )
        self.assertEqual(self._run(tests_run, _ci("mkdocs serve")).status, Status.WARN)
        for line in ("mkdocs build --strict", "mkdocs build -s"):
            with self.subTest(line=line):
                self.assertEqual(
                    self._run(warnings_as_errors, _ci(line)),
                    Result.passed("warnings are treated as errors with mkdocs build --strict"),
                )
        self.assertEqual(self._run(warnings_as_errors, _ci("mkdocs build")).status, Status.FAIL)

    def test_the_prose_linters_analyse(self) -> None:
        for files, tool in (
            (_ci("markdownlint-cli2 docs/**/*.md"), "markdownlint"),
            (_ci("markdownlint docs"), "markdownlint"),
            (github_action("DavidAnson/markdownlint-cli2-action@v25", globs="docs/**/*.md"), "markdownlint"),
            ({".vale.ini": "MinAlertLevel = suggestion\n", **_ci("vale docs")}, "vale (.vale.ini)"),
            ({".vale.ini": "", **github_action("errata-ai/vale-action@v3", files="docs")}, "vale (.vale.ini)"),
        ):
            with self.subTest(files=files):
                self.assertEqual(self._run(static_analysis, files), Result.passed(f"{tool} runs"))
        configured = {".markdownlint.yaml": "default: true\n", **_ci("markdownlint-cli2 .")}
        self.assertEqual(
            self._run(static_analysis, configured), Result.passed("markdownlint (.markdownlint.yaml) runs")
        )
        # vale needs its .vale.ini; without it, it runs nothing.
        self.assertEqual(self._run(static_analysis, _ci("vale docs")).status, Status.WARN)
        self.assertEqual(self._run(static_analysis, _ci("mkdocs build")).status, Status.FAIL)

    def test_the_built_site_is_ignored_and_never_committed(self) -> None:
        self.assertEqual(self._run(vcs_ignore, {".gitignore": "site/\n"}).status, Status.PASS)
        result = self._run(vcs_ignore, {".gitignore": "*.log\n"})
        self.assertEqual(result.status, Status.WARN)
        self.assertIn("site/", " ".join((result.message, *result.details)))
        self.assertEqual(
            self._run(committed_artifacts, {"site/index.html": "<title>Shop</title>\n"}).status, Status.FAIL
        )


class OtherGeneratorTests(unittest.TestCase):
    def test_each_generators_build_strict_switch_and_output(self) -> None:
        cases = (
            ({"book.toml": BOOK}, "mdbook build", None, "book/"),
            (HUGO, "hugo --minify", "hugo --minify --panicOnWarning", "public/"),
            (JEKYLL, "bundle exec jekyll build", "bundle exec jekyll build --strict_front_matter", "_site/"),
            (SPHINX, "sphinx-build docs docs/_build", "sphinx-build -nW docs docs/_build", "_build/"),
            (DOCUSAURUS, "docusaurus build", None, "build/"),
        )
        for files, build, strict, output in cases:
            with self.subTest(files=files):
                self.assertEqual(_run_on(tests_run, {**files, **_ci(build)}).status, Status.PASS)
                self.assertIn(output, " ".join(_run_on(vcs_ignore, {**files, ".gitignore": "*.log\n"}).details))
                if strict is not None:
                    self.assertEqual(_run_on(warnings_as_errors, {**files, **_ci(strict)}).status, Status.PASS)
                    self.assertEqual(_run_on(warnings_as_errors, {**files, **_ci(build)}).status, Status.FAIL)

    def test_hugo_builds_only_when_it_builds_and_docusaurus_throws_on_broken_links(self) -> None:
        for line, status in (("hugo", Status.PASS), ("hugo build", Status.PASS), ("hugo server -D", Status.WARN)):
            with self.subTest(line=line):
                self.assertEqual(_run_on(tests_run, {**HUGO, **_ci(line)}).status, status)
        self.assertEqual(_run_on(warnings_as_errors, {**DOCUSAURUS, **_ci("docusaurus build")}).status, Status.PASS)
        lax = {"docusaurus.config.js": "module.exports = { title: 'Shop', onBrokenLinks: 'warn' };\n"}
        self.assertEqual(_run_on(warnings_as_errors, {**lax, **_ci("docusaurus build")}).status, Status.FAIL)
        pages = github_action("sphinx-notes/pages@v3", sphinx_build_options="-W --keep-going")
        self.assertEqual(_run_on(tests_run, {**SPHINX, **pages}).status, Status.PASS)
        self.assertEqual(_run_on(warnings_as_errors, {**SPHINX, **pages}).status, Status.PASS)
        # mdBook has no strict switch: the check does not apply to it.
        self.assertEqual(_run_on(warnings_as_errors, {"book.toml": BOOK, **_ci("mdbook build")}).status, Status.SKIP)
