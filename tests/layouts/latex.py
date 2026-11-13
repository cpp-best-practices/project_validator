"""Kinds of LaTeX project, for tests that run a check in every layout: a document."""

from __future__ import annotations

from tests.layouts.model import ProjectLayout

DOCUMENT = """\
\\documentclass{article}
\\usepackage{booktabs}
\\title{Prices of the shop}
\\begin{document}
\\maketitle
A total is the sum of the prices; a discount takes a percentage off.
\\end{document}
"""

LAYOUTS = (
    ProjectLayout(
        name="LaTeX document",
        files={"main.tex": DOCUMENT},
        languages=frozenset({"LaTeX"}),
        build_systems=frozenset(),
    ),
)
