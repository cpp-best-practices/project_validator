"""Hatch: the scripts `hatch run <env>:<script>` (or `hatch run <script>`, of the default environment) runs, as
`[tool.hatch.envs.<env>.scripts]` of pyproject.toml or `[envs.<env>.scripts]` of hatch.toml defines them. A script
is a command or a list of commands; one may name another script of its environment, which is not followed."""

from __future__ import annotations

import tomllib
from collections.abc import Iterator, Mapping

from project_validator.core import Context
from project_validator.facts import Command, Origin, Unknown, resolved
from project_validator.facts.arguments import starts_with
from project_validator.facts.expansion import CommandExpander, Expansion, Script, found_at

_FILES = ("hatch.toml", "pyproject.toml")


def _environments(path: str, text: str) -> Mapping[str, object]:
    """The `envs` table of a hatch.toml, or `tool.hatch.envs` of a pyproject.toml; empty when it does not parse."""
    try:
        document: Mapping[str, object] = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return {}
    if path.endswith("pyproject.toml"):
        tool = document.get("tool")
        document = tool.get("hatch", {}) if isinstance(tool, Mapping) else {}
    envs = document.get("envs") if isinstance(document, Mapping) else None
    return envs if isinstance(envs, Mapping) else {}


def _script(envs: Mapping[str, object], env: str, name: str) -> list[str] | None:
    table = envs.get(env)
    scripts = table.get("scripts") if isinstance(table, Mapping) else None
    found = scripts.get(name) if isinstance(scripts, Mapping) else None
    if isinstance(found, str):
        return [found]
    return [line for line in found if isinstance(line, str)] if isinstance(found, list) else None


def _hatch_run(command: Command, context: Context) -> Iterator[Expansion] | None:
    """`hatch run lint:check`, `hatch run +py=3.12 test:cov`, `hatch run test`: the commands of the script."""
    argv = resolved(command)
    if not starts_with(argv, ("hatch", "run")):
        return None
    words = [word for word in argv[2:] if not word.startswith(("-", "+"))]
    if not words:
        return None
    env, _, name = words[0].rpartition(":")
    path = next((found for name_ in _FILES if (found := found_at(context, command.directory, [name_]))), None)
    lines = _script(_environments(path, context.project.read_text(path)), env or "default", name) if path else None
    if lines is None:
        if not env:
            return None  # `hatch run pytest`: a program, which the runner launcher reads
        return iter(
            (
                Unknown(
                    origin=command.origin,
                    subject=f"the hatch script {words[0]}",
                    reason="no hatch configuration defines it",
                ),
            )
        )
    origin = Origin(path=str(path), at=("envs", env or "default", "scripts", name))
    return (Script(text=line, origin=origin) for line in lines)


HATCH_SCRIPTS = CommandExpander(name="hatch scripts", expand=_hatch_run)
