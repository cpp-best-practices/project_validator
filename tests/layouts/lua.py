"""Kinds of Lua project, for tests that run a check in every layout."""

from tests.layouts.model import ProjectLayout

LAYOUTS = (
    ProjectLayout(
        name="LuaRocks package",
        files={"shop-dev-1.rockspec": 'package = "shop"\nversion = "dev-1"\n', "src/shop.lua": "return {}\n"},
        languages=frozenset({"Lua"}),
        build_systems=frozenset({"LuaRocks"}),
    ),
    ProjectLayout(
        name="Lua sources",
        files={"lua/shop/init.lua": "return {}\n"},
        languages=frozenset({"Lua"}),
        build_systems=frozenset(),
    ),
)
