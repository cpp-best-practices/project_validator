"""Kinds of OCaml project, for tests that run a check in every layout."""

from __future__ import annotations

from tests.layouts.model import ProjectLayout

LAYOUTS = (
    ProjectLayout(
        name="dune project",
        files={
            "dune-project": "(lang dune 3.0)\n",
            "bin/dune": "(executable\n (name main))\n",
            "bin/main.ml": "let () = print_endline (string_of_int (Shop.total [ 1; 2 ]))\n",
            "lib/dune": "(library\n (name shop))\n",
            "lib/shop.ml": "let total prices = List.fold_left ( + ) 0 prices\n",
        },
        languages=frozenset({"OCaml"}),
        build_systems=frozenset({"dune"}),
    ),
    ProjectLayout(
        name="OCaml sources",
        files={
            "src/shop.ml": "let total prices = List.fold_left ( + ) 0 prices\n",
            "src/shop.mli": "val total : int list -> int\n",
        },
        languages=frozenset({"OCaml"}),
        build_systems=frozenset(),
    ),
)
