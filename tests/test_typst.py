"""The Typst profile: documents compiled and formatted."""

from __future__ import annotations

import unittest

from project_validator.checks.code_formatting import code_formatting
from project_validator.checks.compiler_warnings import compiler_warnings
from project_validator.checks.tests_run import tests_run
from project_validator.core import Check, Result, Status
from project_validator.ecosystems.typst import TYPST_ECOSYSTEM
from tests.layouts.typst import DOCUMENT
from tests.support import github_job, make_context, run_as, run_in_layout, temp_project, uses


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


class TypstTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_as(self, selected, files, TYPST_ECOSYSTEM)

    def test_typ_sources_are_the_language(self) -> None:
        with temp_project({"main.typ": DOCUMENT, "chapters/prices.typ": "= Prices\n"}) as root:
            structure = make_context(root).structure
        self.assertEqual((structure.languages, structure.build_systems), (frozenset({"Typst"}), frozenset()))
        for text in ("typst compile main.typ", "typstyle --check main.typ", "uses: typst-community/setup-typst@v5"):
            with self.subTest(text=text):
                self.assertTrue(uses(TYPST_ECOSYSTEM, text))
        self.assertFalse(uses(TYPST_ECOSYSTEM, "latexmk main.tex"))

    def test_the_documents_compile_and_are_formatted(self) -> None:
        for line in ("typst compile main.typ", "typst c main.typ main.pdf"):
            with self.subTest(line=line):
                self.assertEqual(self._run(tests_run, _ci(line)), Result.passed("tests found in 1 file(s)"))
        self.assertEqual(self._run(tests_run, _ci("typst watch main.typ")).status, Status.WARN)
        for line, tool in (("typstyle --check main.typ", "typstyle"), ("typstfmt --check main.typ", "typstfmt")):
            with self.subTest(line=line):
                self.assertEqual(self._run(code_formatting, _ci(line)), Result.passed(f"CI enforces the {tool} style"))
        for line in ("typstyle -i main.typ", "typstfmt main.typ"):
            with self.subTest(line=line):
                self.assertEqual(self._run(code_formatting, _ci(line)).status, Status.FAIL)
        # Typst has no lint beyond its compiler.
        skipped = run_in_layout(self, "Typst document", compiler_warnings, _ci("typst compile main.typ"))
        self.assertEqual(skipped.status, Status.SKIP)
