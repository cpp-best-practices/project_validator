"""Kinds of Common Lisp project, for tests that run a check in every layout."""

from tests.layouts.model import ProjectLayout

SOURCE = (
    "(defpackage #:shop (:use #:cl) (:export #:total))\n(in-package #:shop)\n\n"
    "(defun total (prices) (reduce #'+ prices))\n"
)

LAYOUTS = (
    ProjectLayout(
        name="ASDF system",
        files={
            "shop.asd": '(defsystem "shop"\n  :pathname "src"\n  :components ((:file "shop")))\n',
            "src/shop.lisp": SOURCE,
        },
        languages=frozenset({"Common Lisp"}),
        build_systems=frozenset({"ASDF"}),
    ),
    ProjectLayout(
        name="Lisp sources",
        files={"src/shop.lisp": SOURCE},
        languages=frozenset({"Common Lisp"}),
        build_systems=frozenset(),
    ),
)
