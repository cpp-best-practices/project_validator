"""just: the recipes `just [recipe ...]` runs, dependencies first (upstream #208)."""

from __future__ import annotations

import unittest

from project_validator.facts import Command, Facts, Unknown
from tests.support import github_job, make_context, temp_project

# cetz's justfile, cut down: a variable, a recipe with a dependency, parameters with defaults and a variadic one, a
# body continued over lines, and the quiet prefix.
JUSTFILE = """\
# The default recipe is the first.
gallery_dir := "./gallery"
export MODE := 'release'

build:
  cd core; \\
  cargo build --release
  @cp core/out.wasm out.wasm

test *filter: build
  tt run {{filter}}

install target="@local": build
  ./scripts/package "{{target}}"

[private]
gallery: build
  typst c "{{gallery_dir}}/a.typ"

lint:
    -typos
    stylua --check {{ gallery_dir }}
"""


def _facts(files: dict[str, str]) -> Facts:
    with temp_project(files) as root:
        return make_context(root).facts


def _run(line: str, files: dict[str, str] | None = None) -> tuple[list[tuple[str, ...]], list[str]]:
    """What `line` runs through the justfile (each command's words), and the subjects of what is unknown."""
    facts = _facts({"justfile": JUSTFILE, **(files or {}), **github_job("ubuntu-latest", line)})
    commands = [command.argv for command in facts.of(Command) if command.via]
    return commands, [unknown.subject for unknown in facts.of(Unknown)]


BUILD = [("cd", "core"), ("cargo", "build", "--release"), ("cp", "core/out.wasm", "out.wasm")]


class JustTests(unittest.TestCase):
    def test_a_recipe_runs_after_its_dependencies(self) -> None:
        self.assertEqual(_run("just test"), ([*BUILD, ("tt", "run")], []))

    def test_arguments_fill_the_parameters(self) -> None:
        self.assertEqual(_run("just test shapes"), ([*BUILD, ("tt", "run", "shapes")], []))
        self.assertEqual(_run("just install"), ([*BUILD, ("./scripts/package", "@local")], []))
        self.assertEqual(_run("just install @preview")[0][-1], ("./scripts/package", "@preview"))

    def test_variables_are_interpolated_and_line_prefixes_dropped(self) -> None:
        self.assertEqual(_run("just lint"), ([("typos",), ("stylua", "--check", "./gallery")], []))
        self.assertEqual(_run("just gallery")[0][-1], ("typst", "c", "./gallery/a.typ"))
        self.assertEqual(_run("just gallery_dir=docs gallery")[0][-1], ("typst", "c", "docs/a.typ"))

    def test_several_recipes_run_in_turn_each_once(self) -> None:
        commands, _ = _run("just lint build test")
        self.assertEqual(commands, [("typos",), ("stylua", "--check", "./gallery"), *BUILD, ("tt", "run")])

    def test_without_a_recipe_just_runs_the_first(self) -> None:
        self.assertEqual(_run("just"), (BUILD, []))

    def test_the_justfile_is_found_where_just_runs_or_named(self) -> None:
        moved = {"justfile": "", "docs/Justfile": "html:\n  mdbook build\n"}
        self.assertEqual(_run("cd docs && just html", moved), ([("mdbook", "build")], []))
        named = {"ci.just": "check:\n  ruff check .\n"}
        self.assertEqual(_run("just --justfile ci.just check", named), ([("ruff", "check", ".")], []))

    def test_listing_runs_nothing(self) -> None:
        self.assertEqual(_run("just --list"), ([], []))

    def test_what_cannot_be_read_is_unknown(self) -> None:
        self.assertEqual(_run("just deploy"), ([], ["the just recipe deploy"]))
        shebang = {"justfile": "bench:\n  #!/usr/bin/env python3\n  print(1)\n"}
        self.assertEqual(_run("just bench", shebang), ([], ["the just recipe bench"]))
        computed = {"justfile": 'tool := env_var("TOOL")\ncheck:\n  {{tool}} check\n'}
        self.assertEqual(_run("just check", computed)[1], ["the just recipe check"])

    def test_a_shell_shebang_recipe_is_a_script(self) -> None:
        shebang = {"justfile": "check:\n  #!/usr/bin/env bash\n  set -euo pipefail\n  ruff check .\n"}
        self.assertEqual(_run("just check", shebang)[0][-1], ("ruff", "check", "."))

    def test_the_justfile_is_found_above_where_just_runs(self) -> None:
        nested = {"justfile": "check:\n  ruff check .\n", "docs/guide.md": ""}
        self.assertEqual(_run("cd docs && just check", nested), ([("ruff", "check", ".")], []))

    def test_without_a_justfile_what_just_runs_is_unknown(self) -> None:
        facts = _facts(github_job("ubuntu-latest", "just test"))
        self.assertEqual([unknown.subject for unknown in facts.of(Unknown)], ["the justfile"])

    def test_set_overrides_a_variable(self) -> None:
        self.assertEqual(_run("just --set gallery_dir docs gallery")[0][-1], ("typst", "c", "docs/a.typ"))

    def test_an_undefined_dependency_and_unread_lines_are_skipped(self) -> None:
        odd = {"justfile": "x = y\ncheck: missing\n  ruff check .\n"}
        self.assertEqual(_run("just check", odd), ([("ruff", "check", ".")], []))

    def test_just_run_outside_the_project_is_not_followed(self) -> None:
        self.assertEqual(_run("cd /tmp && just test"), ([], []))
