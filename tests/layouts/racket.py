"""Kinds of Racket project, for tests that run a check in every layout."""

from __future__ import annotations

from tests.layouts.model import ProjectLayout

SOURCE = "#lang racket/base\n(provide total)\n(define (total prices) (apply + prices))\n"

LAYOUTS = (
    ProjectLayout(
        name="Racket package",
        files={"info.rkt": '#lang info\n(define collection "shop")\n(define deps \'("base"))\n', "main.rkt": SOURCE},
        languages=frozenset({"Racket"}),
        build_systems=frozenset({"raco pkg"}),
    ),
    ProjectLayout(
        name="Racket sources",
        files={"src/shop.rkt": SOURCE},
        languages=frozenset({"Racket"}),
        build_systems=frozenset(),
    ),
)
