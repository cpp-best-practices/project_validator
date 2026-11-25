"""`.bazelrc`: the options a bazel command picks up from its workspace's rc files, written out (upstream #207).

Bazel reads the `.bazelrc` at the top of the workspace (the directory of its `MODULE.bazel` or `WORKSPACE`), and one a
`--bazelrc=` startup option names, before its command line. Each line names a command and options for it (`build
--copt=-Wall`), or, after `:name`, options a `--config=name` brings (`build:linux --copt=-Werror`); a line ending in
`\\` goes on. A command takes the options of `common` and `always`, then of the commands it inherits (`test`, `run`
and `coverage` inherit `build`; `coverage` inherits `test`), then its own. `--config=name`, on the command line or in
the rc files, brings each such command's `:name` options in its place, a config bringing itself once. With
`--enable_platform_specific_config`, the config named for the host's OS (`linux`, `macos`, `windows`) is brought after
the rc files' options, in the builds on that OS. `import` and `try-import` of a file in the workspace
(`%workspace%/ci.bazelrc`) are followed; no other file is read, and `startup` options are not a command's.

A bazel command is expanded into itself with those options written out, and `--ignore_all_rc_files`, with which
bazel reads none: the same command, whose compiler options (`--copt=-Werror`), compilation mode and tests are then
read as its own. A command with no option from the rc files is not expanded.
"""

from __future__ import annotations

import posixpath
from collections.abc import Iterator, Mapping
from pathlib import PurePosixPath

from project_validator.build_systems.bazel.build import WORKSPACE_FILES, bazel_command
from project_validator.core import Context
from project_validator.facts import Command, Origin, resolved
from project_validator.facts.arguments import option_values
from project_validator.facts.conditions import only
from project_validator.facts.expansion import CommandExpander, Expansion, Invocation, Only
from project_validator.facts.shell import ShellSyntaxError, command_line, split_words
from project_validator.includes import Chain, Refused, follow
from project_validator.limits import BAZELRC_IMPORTS

IGNORE_RC_FILES = "--ignore_all_rc_files"
_PARENTS = {"test": "build", "run": "build", "coverage": "test", "cquery": "build", "aquery": "build"}
# The configs `--enable_platform_specific_config` brings, by the platform each is for.
_PLATFORM_CONFIGS = {"linux": "linux", "macos": "macos", "windows": "windows"}
_PLATFORM_SPECIFIC = "--enable_platform_specific_config"
_NO_PLATFORM_SPECIFIC = "--noenable_platform_specific_config"

type _Sections = dict[str, list[str]]


def _workspace(context: Context, directory: str | None) -> str:
    """The workspace a command in `directory` runs in: the nearest directory up from it with a MODULE.bazel or
    WORKSPACE file, else the directory itself."""
    current = PurePosixPath((directory or ".").strip("/") or ".")
    for candidate in (current, *current.parents):
        if any(context.project.exists(str(candidate / name)) for name in WORKSPACE_FILES):
            return str(candidate)
    return str(current)


def _lines(text: str) -> Iterator[str]:
    """The logical lines of an rc file: a line ending in `\\` goes on to the next."""
    pending = ""
    for line in text.splitlines():
        if line.endswith("\\"):
            pending += line[:-1] + " "
            continue
        yield pending + line
        pending = ""
    if pending:
        yield pending


def _read(context: Context, path: str, workspace: str, sections: _Sections, chain: Chain) -> None:
    """The sections of the rc file `path`, and of those it imports, added to `sections` as bazel reads them."""
    for line in _lines(context.project.read_text(path)):
        try:
            words = split_words(line, comments=True)
        except ShellSyntaxError:
            continue
        if not words:
            continue
        if words[0] in ("import", "try-import") and len(words) == 2:
            imported = posixpath.normpath(words[1].replace("%workspace%", workspace).removeprefix("./"))
            reached = follow(chain, imported, BAZELRC_IMPORTS, context.project.exists)
            if not isinstance(reached, Refused):
                _read(context, imported, workspace, sections, reached)
        else:
            sections.setdefault(words[0], []).extend(words[1:])


def _sections(context: Context, workspace: str, named: list[str]) -> tuple[_Sections, str] | None:
    """The sections of the workspace's rc files (and those the command names), and the first file read; None
    without one."""
    paths = [
        path
        for path in (posixpath.join(workspace, ".bazelrc").removeprefix("./"), *named)
        if context.project.exists(path)
    ]
    if not paths:
        return None
    sections: _Sections = {}
    for path in paths:
        _read(context, path, workspace, sections, Chain.start(path))
    return sections, paths[0]


def _commands(subcommand: str) -> list[str]:
    """The commands whose options a command takes, in the order it takes them."""
    inherited = [subcommand]
    while inherited[-1] in _PARENTS:
        inherited.append(_PARENTS[inherited[-1]])
    return ["always", "common", *reversed(inherited)]


def _expanded(
    words: list[str], commands: list[str], sections: Mapping[str, list[str]], brought: frozenset[str]
) -> list[str]:
    """`words` with each `--config=name` replaced by the options it brings (those of each of `commands`' `:name`)."""
    found: list[str] = []
    following = iter(words)
    for word in following:
        if word == "--config":
            word = f"--config={next(following, '')}"
        if not word.startswith("--config="):
            found.append(word)
            continue
        name = word.removeprefix("--config=")
        if name not in brought:
            options = [option for command in commands for option in sections.get(f"{command}:{name}", [])]
            found += _expanded(options, commands, sections, brought | {name})
    return found


def _platform_specific(options: list[str]) -> bool:
    """Whether the options leave `--enable_platform_specific_config` on: the last of it (`=false`) or its `--no` form
    decides."""
    enabled = False
    for word in options:
        name, _, value = word.partition("=")
        if name == _PLATFORM_SPECIFIC:
            enabled = value.lower() not in ("false", "0", "no")
        elif name == _NO_PLATFORM_SPECIFIC:
            enabled = False
    return enabled


def _rc_files(command: Command, context: Context, startup: list[str]) -> tuple[_Sections, str] | None:
    """The sections of the rc files a command reads: its workspace's, and those its `--bazelrc=` names."""
    named = option_values(("bazel", *startup), "--bazelrc")
    paths = [posixpath.join(command.directory or ".", path).removeprefix("./") for path in named]
    return _sections(context, _workspace(context, command.directory), paths)


def _written(start: list[str], rest: tuple[str, ...], sections: _Sections, origin: Origin) -> list[Expansion] | None:
    """The command `start` (up to its subcommand) then `rest`, with its rc files' options written out: once, or once
    per platform with the config for that OS; None when the rc files give it nothing."""
    commands = _commands(start[-1])
    options = _expanded(
        [option for name in commands for option in sections.get(name, [])], commands, sections, frozenset()
    )
    given = _expanded(list(rest), commands, sections, frozenset())

    def invocation(brought: list[str]) -> Invocation:
        words = (*start, *options, *brought, *given)
        return Invocation(argv=words, line=command_line(words), origin=origin)

    if _platform_specific(options):
        return [
            Only(
                invocation(_expanded([f"--config={config}"], commands, sections, frozenset())),
                only("platforms", [platform]),
            )
            for platform, config in _PLATFORM_CONFIGS.items()
        ]
    if not options and given == list(rest):
        return None
    return [invocation([])]


def _bazelrc(command: Command, context: Context) -> list[Expansion] | None:
    """A bazel command with the options of its rc files written out (see the module)."""
    argv = resolved(command)
    found = bazel_command(argv)
    if found is None:
        return None
    subcommand, rest = found
    startup = list(argv[1 : len(argv) - len(rest) - 1])
    read = None if IGNORE_RC_FILES in startup else _rc_files(command, context, startup)
    if read is None:
        return None
    sections, path = read
    return _written([argv[0], *startup, IGNORE_RC_FILES, subcommand], rest, sections, Origin(path=path))


BAZELRC = CommandExpander(name=".bazelrc options", expand=_bazelrc)


__all__ = ["BAZELRC", "IGNORE_RC_FILES"]
