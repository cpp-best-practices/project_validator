"""Kinds of Clojure project, for tests that run a check in every layout."""

from tests.layouts.model import ProjectLayout

SOURCE = "(ns shop.core)\n\n(defn total [prices] (reduce + 0 prices))\n"

LAYOUTS = (
    ProjectLayout(
        name="deps.edn project",
        files={
            "deps.edn": '{:paths ["src"]\n :deps {org.clojure/clojure {:mvn/version "1.12.0"}}}\n',
            "src/shop/core.clj": SOURCE,
        },
        languages=frozenset({"Clojure"}),
        build_systems=frozenset({"Clojure CLI"}),
    ),
    ProjectLayout(
        name="Leiningen project",
        files={
            "project.clj": '(defproject shop "0.1.0"\n  :dependencies [[org.clojure/clojure "1.12.0"]])\n',
            "src/shop/core.clj": SOURCE,
        },
        languages=frozenset({"Clojure"}),
        build_systems=frozenset({"Leiningen"}),
    ),
    ProjectLayout(
        name="Clojure sources",
        files={"src/shop/core.clj": SOURCE},
        languages=frozenset({"Clojure"}),
        build_systems=frozenset(),
    ),
)
