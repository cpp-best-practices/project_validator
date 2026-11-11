"""Kinds of BEAM project, for tests that run a check in every layout."""

from tests.layouts.model import ProjectLayout

LAYOUTS = (
    ProjectLayout(
        name="Mix Elixir",
        files={
            "mix.exs": "defmodule Shop.MixProject do\n  use Mix.Project\nend\n",
            "lib/shop.ex": "defmodule Shop do\nend\n",
        },
        languages=frozenset({"Elixir"}),
        build_systems=frozenset({"Mix"}),
    ),
    ProjectLayout(
        name="rebar3 Erlang",
        files={"rebar.config": "{erl_opts, [debug_info]}.\n", "src/shop.erl": "-module(shop).\n"},
        languages=frozenset({"Erlang"}),
        build_systems=frozenset({"rebar3"}),
    ),
)
