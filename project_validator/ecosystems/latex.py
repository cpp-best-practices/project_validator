"""LaTeX: documents (`.tex` with a `\\documentclass`, or a `.latexmkrc`), judged by what CI does with them: compiles
them (`tests-run`: latexmk, pdflatex, xelatex, lualatex, tectonic, `xu-cheng/latex-action`), lints them
(`compiler-warnings` and `static-analysis`: chktex, lacheck), formats them (`code-formatting`: `latexindent --check`),
and ignores what compiling leaves (`vcs-ignore`: `*.aux`, `*.log`, latexmk's records, SyncTeX data). A stray `.tex`
file makes no LaTeX project: the suffixes count once a document is found."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import PurePosixPath

from project_validator.core import Project
from project_validator.ecosystems.model import Ecosystem, toolchain_patterns
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.expansion import Action
from project_validator.facts.formatting import Enforcement, flagged, format_tool
from project_validator.facts.outputs import BuildOutput
from project_validator.facts.practices import Practice, PracticeName, Requirement, Wording, always
from project_validator.facts.settings import file_reader
from project_validator.facts.shell import ShellCommand, split_script
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import defined_by, starts, when

LATEX = "LaTeX"
LATEX_ONLY = frozenset({LATEX})

_DOCUMENT = re.compile(r"^\s*\\documentclass\b", re.MULTILINE)
_LATEXMKRC = frozenset({".latexmkrc", "latexmkrc"})


def latex_project(project: Project) -> frozenset[str]:
    """Whether the project holds a LaTeX document: a `.tex` that declares its class, or a latexmk configuration."""
    for path in project.files():
        name = PurePosixPath(path).name
        if name in _LATEXMKRC or (name.endswith(".tex") and _DOCUMENT.search(project.read_head(path))):
            return LATEX_ONLY
    return frozenset()


LATEX_ECOSYSTEM = Ecosystem(
    label="LaTeX",
    languages=LATEX_ONLY,
    # The sources count once a document is found: a `.tex` alone may be a fragment another project includes.
    ambiguous_suffixes={".tex": LATEX, ".sty": LATEX, ".cls": LATEX, ".dtx": LATEX, ".ltx": LATEX, ".bib": None},
    detect=latex_project,
    toolchain=toolchain_patterns(
        LATEX,
        inputs=("texlive_version",),
        programs=(
            "latexmk",
            "pdflatex",
            "xelatex",
            "lualatex",
            "tectonic",
            "chktex",
            "lacheck",
            "latexindent",
            "bibtex",
            "biber",
        ),
        actions=("latex-action", "setup-texlive-action"),
    ),
)


# --- The documents compile -------------------------------------------------------------------------------------------

DOCUMENTS = TestFiles(
    name="documents (*.tex with a \\documentclass)",
    languages=LATEX_ONLY,
    path=re.compile(r"\.tex$"),
    contains=_DOCUMENT,
)
COMPILE = test_runner(
    name="latexmk",
    languages=LATEX_ONLY,
    how="latexmk -pdf main.tex (or pdflatex, xelatex, lualatex, tectonic; xu-cheng/latex-action)",
    runs=when(starts(("latexmk",), ("pdflatex",), ("xelatex",), ("lualatex",), ("tectonic",)), tested),
    tests=tests_of(DOCUMENTS.name),
)


def _latex_action(inputs: Mapping[str, str]) -> tuple[tuple[str, ...], ...]:
    """`xu-cheng/latex-action` runs its `pre_compile` script, compiles its `root_file` (one or more) with latexmk,
    then runs its `post_compile` script."""
    before = split_script(inputs.get("pre_compile", ""))
    after = split_script(inputs.get("post_compile", ""))
    compiles = (("latexmk", root) for root in inputs.get("root_file", "main.tex").split())
    return (
        *(found.argv for found in before if isinstance(found, ShellCommand)),
        *compiles,
        *(found.argv for found in after if isinstance(found, ShellCommand)),
    )


LATEX_ACTION = Action(name="xu-cheng/latex-action", runs=_latex_action)


# --- Lints: the warnings LaTeX does not have ------------------------------------------------------------------------

CHKTEX_SETTINGS = file_reader("chktex", (".chktexrc", "chktexrc"))
CHKTEX = analyzer(
    name="chktex",
    languages=LATEX_ONLY,
    how="chktex -q main.tex",
    analyses=when(starts(("chktex",)), analysed),
    rules=defined_by(files=(CHKTEX_SETTINGS.name,)),
)
LACHECK = analyzer(
    name="lacheck", languages=LATEX_ONLY, how="lacheck main.tex", analyses=when(starts(("lacheck",)), analysed)
)
WARNINGS = Practice(
    name=PracticeName.WARNINGS,
    languages=LATEX_ONLY,
    requirements=always(Requirement(name="chktex", tools=("chktex", "lacheck"))),
    words=Wording(
        kind="LaTeX lints",
        searched="CI configuration",
        hint="run chktex (or lacheck) over the documents in CI; .chktexrc holds its settings",
    ),
)


# --- Formatting -----------------------------------------------------------------------------------------------------

LATEXINDENT_SETTINGS = file_reader("latexindent", ("latexindent.yaml", ".latexindent.yaml", "localSettings.yaml"))
LATEXINDENT = format_tool(
    name="latexindent",
    languages=LATEX_ONLY,
    can={Enforcement.CHECK: "latexindent --check main.tex", Enforcement.APPLY: "latexindent -w main.tex"},
    formats=flagged(("latexindent",), checks=("--check", "-k", "--checkv", "-K"), applies=("-w", "--overwrite")),
    style=defined_by(files=(LATEXINDENT_SETTINGS.name,)),
)


# --- What compiling leaves ------------------------------------------------------------------------------------------


def _leftovers(name: str, *suffixes: str) -> BuildOutput:
    globs = "|".join(rf"\*\.{re.escape(suffix)}" for suffix in suffixes)
    return BuildOutput(
        languages=LATEX_ONLY,
        name=name,
        globs=re.compile(rf"(?:\*\*/)?(?:{globs})"),
        paths=tuple(f"main.{suffix}" for suffix in suffixes),
        hint=f"consider ignoring {', '.join(f'*.{suffix}' for suffix in suffixes)}",
        artifacts=tuple(f"*.{suffix}" for suffix in suffixes if suffix != "log"),
    )


AUXILIARY = _leftovers("the compiler's auxiliary files", "aux", "log", "out", "toc")
LATEXMK_RECORDS = _leftovers("latexmk's records", "fls", "fdb_latexmk")
SYNCTEX = _leftovers("SyncTeX data", "synctex.gz")
