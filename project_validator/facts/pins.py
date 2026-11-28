"""The versions a project pins its tools at (upstream #412): exactly, not as a range. Shown beside each tool CI runs;
never judged.

A pin is read from what the project commits (`PinnedTool`, by the readers in `tools/pins.py`: pre-commit's `rev:`, an
exact requirement, an exact package.json dependency) and from what CI does (`pins`): an install command naming an
exact version (`pip install black==24.8.0`, `npm i -g eslint@9.1.0`, `go install ...@v1.59.1`, `cargo install
cargo-audit --version 0.20.0`), or an action's `version` input (`golangci/golangci-lint-action` with `version:
v1.59.1`)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

from project_validator.facts import ActionStep, Command, Fact, Facts
from project_validator.facts.arguments import program

# An exact version, as a pin writes it: `1.2.3`, `v0.6.9`, `24.8.0`, `1.0.0-rc.1`. Not a range, nor a major alone.
EXACT = re.compile(r"v?(?P<version>\d+(?:\.\d+)+(?:[-+][\w.]+)?)")


@dataclass(frozen=True, slots=True, kw_only=True)
class PinnedTool(Fact):
    """A package (a tool's, or a pre-commit hook's id) pinned at an exact `version`."""

    package: str
    version: str


def exact(text: str) -> str:
    """The version `text` pins exactly, without a leading `v`; "" for a range or anything else."""
    found = EXACT.fullmatch(text.strip())
    return found["version"] if found else ""


_PYTHON_PIN = re.compile(r"(?P<package>[A-Za-z0-9][\w.-]*)(?:\[[^\]]*\])?==(?P<version>[^\s;,]+)")
_NODE_PIN = re.compile(r"(?P<package>@?[\w.-]+(?:/[\w.-]+)?)@(?P<version>[^\s@]+)")
_PYTHON_INSTALLERS = frozenset({"pip", "pip3", "pipx", "uv", "python", "python3", "py"})
_NODE_INSTALLERS = frozenset({"npm", "pnpm", "yarn", "bun", "npx", "pnpx", "bunx"})


def _go(argv: tuple[str, ...]) -> Iterator[tuple[str, str]]:
    """`go install github.com/golangci/golangci-lint/cmd/golangci-lint@v1.59.1`: the last part of the path that is no
    major version (`/v2`)."""
    for word in argv[2:]:
        path, at, version = word.rpartition("@")
        if at and (parts := [part for part in path.split("/") if not re.fullmatch(r"v\d+", part)]):
            yield parts[-1], version


def _cargo(argv: tuple[str, ...]) -> Iterator[tuple[str, str]]:
    """`cargo install cargo-audit --version 0.20.0` (or `--version=0.20.0`, `cargo-audit@0.20.0`)."""
    words, crates, version = iter(argv[2:]), [], ""
    for word in words:
        if word == "--version":
            version = next(words, "")
        elif word.startswith("--version="):
            version = word.partition("=")[2]
        elif not word.startswith("-"):
            crates.append(word)
    for crate in crates:
        name, at, pinned = crate.partition("@")
        if at or version:
            yield name, pinned or version


def _command(argv: tuple[str, ...]) -> Iterator[tuple[str, str]]:
    name = program(argv)
    if name in _PYTHON_INSTALLERS and "install" in argv:
        yield from ((found["package"], found["version"]) for word in argv if (found := _PYTHON_PIN.fullmatch(word)))
    elif name in _NODE_INSTALLERS:
        words = argv[1:] if name.endswith("x") else argv[2:] if len(argv) > 1 else ()
        yield from ((found["package"], found["version"]) for word in words if (found := _NODE_PIN.fullmatch(word)))
    elif argv[:2] == ("go", "install"):
        yield from _go(argv)
    elif argv[:2] == ("cargo", "install"):
        yield from _cargo(argv)


def _action(step: ActionStep) -> Iterator[tuple[str, str]]:
    """An action's `version` input, for the tool the action is named after (`golangci-lint-action`, `setup-ruff`)."""
    name = step.uses.partition("@")[0].rsplit("/", 1)[-1]
    if version := step.inputs.get("version"):
        yield name.removesuffix("-action").removeprefix("setup-"), version


def normal(package: str) -> str:
    """A package's name as pins and tools are compared: lower case, `_` and spaces as `-`."""
    return re.sub(r"[_\s]+", "-", package.strip().lower())


def pins(facts: Facts) -> dict[str, set[str]]:
    """Each package (`normal`) and the exact versions it is pinned at, in the project's files or in CI."""
    found: dict[str, set[str]] = {}
    pairs = [
        *((pin.package, pin.version) for pin in facts.of(PinnedTool)),
        *(pair for command in facts.of(Command) for pair in _command(command.argv)),
        *(pair for step in facts.of(ActionStep) for pair in _action(step)),
    ]
    for package, version in pairs:
        if pinned := exact(version):
            found.setdefault(normal(package), set()).add(pinned)
    return found


__all__ = ["EXACT", "PinnedTool", "exact", "normal", "pins"]
