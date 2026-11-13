"""Typst: documents (`.typ`), judged by what CI does with them: compiles them (`tests-run`: `typst compile`) and
formats them (`code-formatting`: typstyle, typstfmt). Typst has no lint beyond its compiler, and compiling leaves only
the PDF, so the other checks have nothing to ask."""

from __future__ import annotations

import re

from project_validator.ecosystems.model import Ecosystem, toolchain_patterns
from project_validator.facts.formatting import Enforcement, flagged, format_tool
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import defined_by, starts, when

TYPST = "Typst"
TYPST_ONLY = frozenset({TYPST})

TYPST_ECOSYSTEM = Ecosystem(
    label="Typst",
    languages=TYPST_ONLY,
    source_suffixes={".typ": TYPST},
    toolchain=toolchain_patterns(
        TYPST,
        inputs=("typst-version",),
        programs=("typst", "typstyle", "typstfmt"),
        actions=("setup-typst",),
    ),
)

DOCUMENTS = TestFiles(name="documents (*.typ)", languages=TYPST_ONLY, path=re.compile(r"\.typ$"))
COMPILE = test_runner(
    name="typst compile",
    languages=TYPST_ONLY,
    how="typst compile main.typ",
    runs=when(starts(("typst", "compile"), ("typst", "c")), tested),
    tests=tests_of(DOCUMENTS.name),
)
TYPSTYLE = format_tool(
    name="typstyle",
    languages=TYPST_ONLY,
    can={Enforcement.CHECK: "typstyle --check main.typ", Enforcement.APPLY: "typstyle -i main.typ"},
    formats=flagged(("typstyle",), checks=("--check", "--diff"), applies=("-i", "--inplace")),
    style=defined_by(),
)
TYPSTFMT = format_tool(
    name="typstfmt",
    languages=TYPST_ONLY,
    can={Enforcement.CHECK: "typstfmt --check main.typ", Enforcement.APPLY: "typstfmt main.typ"},
    formats=flagged(("typstfmt",), checks=("--check",)),
    style=defined_by(),
)
