"""The LaTeX profile: documents compiled, linted and formatted, and what compiling leaves ignored."""

from __future__ import annotations

import unittest

from project_validator.checks.code_formatting import code_formatting
from project_validator.checks.compiler_warnings import compiler_warnings
from project_validator.checks.static_analysis import static_analysis
from project_validator.checks.tests_run import tests_run
from project_validator.checks.vcs_ignore import vcs_ignore
from project_validator.core import Check, Result, Status
from project_validator.ecosystems.latex import LATEX_ECOSYSTEM
from tests.layouts.latex import DOCUMENT
from tests.support import github_action, github_job, make_context, run_as, temp_project, uses

LATEX = frozenset({"LaTeX"})


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


class RecognitionTests(unittest.TestCase):
    def test_a_document_or_latexmkrc_makes_a_latex_project_a_stray_tex_does_not(self) -> None:
        full = {"main.tex": DOCUMENT, "chapters/intro.tex": "\\section{Intro}\n", "refs.bib": "", "shop.sty": ""}
        for files in (full, {".latexmkrc": "$pdf_mode = 1;\n", "notes.tex": "\\section{Notes}\n"}):
            with self.subTest(files=files), temp_project(files) as root:
                structure = make_context(root).structure
                self.assertEqual((structure.languages, structure.build_systems), (LATEX, frozenset()))
                self.assertEqual(structure.unrecognised_suffixes, ())
        with temp_project({"fragment.tex": "\\section{Alone}\n", "src/main.py": ""}) as root:
            self.assertEqual(make_context(root).structure.languages, frozenset({"Python"}))

    def test_an_l3build_package_is_a_latex_project(self) -> None:
        """A `build.lua` naming its `module` is l3build's configuration: the `.dtx` sources beside it are a LaTeX
        package, and its `.lvt` tests and `.tlg` logs are files of it (latex3/l3build); a `build.lua` that names no
        module is only Lua."""
        package = {"build.lua": 'module = "shop"\n', "shop.dtx": "", "testfiles/a.lvt": "", "testfiles/a.tlg": ""}
        with temp_project(package) as root:
            structure = make_context(root).structure
        self.assertIn("LaTeX", structure.languages)
        self.assertEqual(structure.unrecognised_suffixes, ())
        with temp_project({"build.lua": "print(1)\n", "shop.dtx": ""}) as root:
            self.assertNotIn("LaTeX", make_context(root).structure.languages)

    def test_ci_usage(self) -> None:
        for text in (
            "l3build check",
            "latexmk -pdf main.tex",
            "chktex -q main.tex",
            "uses: xu-cheng/latex-action@v4",
            "tectonic main.tex",
        ):
            with self.subTest(text=text):
                self.assertTrue(uses(LATEX_ECOSYSTEM, text))
        self.assertFalse(uses(LATEX_ECOSYSTEM, "make check"))


class L3buildLuaTests(unittest.TestCase):
    def test_l3build_check_tests_the_packages_lua_too(self) -> None:
        """l3build's regression tests run the package in LuaTeX, so they test its Lua as well as its LaTeX: l3build's
        own `l3build-*.lua`, not "Lua: no tests found" (upstream #276)."""
        package = {
            "build.lua": 'module = "shop"\n',
            "shop.dtx": "",
            "shop-tools.lua": "local M = {}\nreturn M\n",
            "testfiles/a.lvt": "\\input{regression-test}\n",
            "testfiles/a.tlg": "",
            **_ci("l3build check"),
        }
        with temp_project(package) as root:
            result = tests_run.run(make_context(root))
        self.assertEqual(result.status, Status.PASS, result)


class LatexTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_as(self, selected, files, LATEX_ECOSYSTEM)

    def test_the_documents_compile(self) -> None:
        for files in (_ci("latexmk -pdf main.tex"), _ci("xelatex main.tex"), _ci("tectonic -X build")):
            with self.subTest(files=files):
                self.assertEqual(
                    self._run(tests_run, files),
                    Result.passed("documents (*.tex with a \\documentclass): 1 file(s), run by latexmk"),
                )
        for files in (
            github_action("xu-cheng/latex-action@v4"),
            github_action("xu-cheng/latex-action@v4", root_file="main.tex thesis.tex"),
        ):
            with self.subTest(files=files):
                self.assertEqual(self._run(tests_run, files).status, Status.PASS)
        self.assertEqual(self._run(tests_run, _ci("chktex main.tex")).status, Status.WARN)

    def test_chktex_is_the_lint_and_latexindent_the_formatter(self) -> None:
        self.assertEqual(
            self._run(compiler_warnings, _ci("chktex -q main.tex")),
            Result.passed("strict LaTeX lints are enabled: chktex"),
        )
        self.assertEqual(self._run(static_analysis, _ci("lacheck main.tex")), Result.passed("lacheck runs"))
        configured = {".chktexrc": "CmdLine { -q }\n", **_ci("chktex main.tex")}
        self.assertEqual(self._run(static_analysis, configured), Result.passed("chktex (.chktexrc) runs"))
        self.assertEqual(self._run(compiler_warnings, _ci("latexmk main.tex")).status, Status.FAIL)
        for line in ("latexindent --check main.tex", "latexindent -k main.tex"):
            with self.subTest(line=line):
                self.assertEqual(
                    self._run(code_formatting, _ci(line)), Result.passed("CI enforces the latexindent style")
                )
        styled = {"latexindent.yaml": "defaultIndent: '  '\n", **_ci("latexindent -k main.tex")}
        self.assertEqual(
            self._run(code_formatting, styled).message, "latexindent.yaml is defined and CI runs latexindent"
        )
        self.assertEqual(self._run(code_formatting, _ci("latexindent -w main.tex")).status, Status.FAIL)

    def test_what_compiling_leaves_is_ignored(self) -> None:
        ignored = {".gitignore": "*.aux\n*.log\n*.fls\n*.fdb_latexmk\n*.synctex.gz\n"}
        self.assertEqual(self._run(vcs_ignore, ignored).status, Status.PASS)
        result = self._run(vcs_ignore, {".gitignore": "*.aux\n*.log\n"})
        self.assertEqual(result.status, Status.WARN)
        self.assertIn("*.fls", " ".join((result.message, *result.details)))
        self.assertIn("*.synctex.gz", " ".join((result.message, *result.details)))
