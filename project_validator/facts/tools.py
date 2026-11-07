"""Tools and their runs: every practice's tools (coverage, linters, formatters, analyzers, auditors) in one model.

A `Tool` records its whole upstream capability: the languages it handles, and for each aspect of a project it can
provide (`coverage`, later `lint`, `format`, `audit`), the levels it can provide with how to ask for each. It claims
the commands that run it, and reads nothing but the facts: a claimed command becomes a `ToolRun` fact with the
aspects that run provides, joined with the settings it read (see `project_validator.facts.settings`). A setting
counts only when CI runs the tool that reads it. Questions read the runs of an aspect; none has its own tool type.
"""

from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath

from project_validator.facts import NOTHING, Command, Fact, Facts, Origin, Setting

type Levels = frozenset[str]


@dataclass(frozen=True, slots=True, kw_only=True)
class Run:
    """What one run of a tool provides (aspect -> levels), and the settings files it read to decide. The run covers
    the code of its working directory (see `ToolRun.covers`)."""

    provides: Mapping[str, Levels]
    read: tuple[str, ...] = ()
    # Decided from text that is not parsed (a compiler flag somewhere in a CMake file) rather than read.
    heuristic: bool = False


type Claim = Callable[[Command, Facts], Run | None]


@dataclass(frozen=True, slots=True, kw_only=True)
class Tool:
    """A tool: the languages it handles; `can`, each aspect it can provide with each level and how to ask for it;
    `claims`, which reads a command that runs it (None for a command that does not); and `reads`, the tools whose
    settings it reads, whose unreadable settings make its answers unknown."""

    name: str
    languages: frozenset[str]
    can: Mapping[str, Mapping[str, str]]
    claims: Claim
    reads: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolRun(Fact):
    """A tool CI runs, in one job: what it provides there, for which languages and in which directories."""

    job: str
    tool: str
    languages: frozenset[str]
    provides: Mapping[str, Levels] = NOTHING  # type: ignore[assignment]
    # Directories relative to the project ("." for its root) whose code the run covers.
    scope: tuple[str, ...] = (".",)
    read: tuple[str, ...] = ()
    via: tuple[Origin, ...] = ()
    heuristic: bool = False

    def covers(self, directory: str) -> bool:
        """Whether the run covers code in `directory`: a run in a directory covers it, the directories below it, and
        the unit that contains it (a run in `src/` of the root unit covers the root unit)."""
        return any(within(directory, scope) or within(scope, directory) for scope in self.scope)


def within(path: str, directory: str) -> bool:
    """Whether `path` is `directory` or below it (both relative to the project, "." for its root)."""
    return directory == "." or path == directory or PurePosixPath(path).is_relative_to(directory)


def built_in_tools() -> tuple[Tool, ...]:
    """Every tool defined by a module of the shared build systems, the shared tools or a profile."""
    from project_validator.components import built_in

    return built_in(Tool)


def _scope(command: Command) -> tuple[str, ...]:
    directory = command.directory or "."
    if directory.startswith(("/", "..")):
        return ()  # outside the project: it covers none of the project's code
    return (str(PurePosixPath(directory.removeprefix("./") or ".")),)


def tool_runs(facts: Facts, tools: Iterable[Tool]) -> Iterator[ToolRun]:
    """The run of each tool among `tools` that each command of `facts` is."""
    tools = tuple(tools)
    for command in facts.of(Command):
        for tool in tools:
            run = tool.claims(command, facts)
            if run is not None and any(run.provides.values()):
                yield ToolRun(
                    origin=command.origin,
                    job=command.job,
                    tool=tool.name,
                    languages=tool.languages,
                    provides={aspect: levels for aspect, levels in run.provides.items() if levels},
                    scope=_scope(command),
                    read=run.read,
                    via=command.via,
                    heuristic=run.heuristic,
                )


def provided(aspect: str, *levels: str | None, read: Iterable[Setting | str] = (), heuristic: bool = False) -> Run:
    """A run that provides the `levels` of `aspect` that are not None, from the settings (or files) `read`; it is
    heuristic when one of those settings is."""
    read = tuple(read)
    paths = (found.path if isinstance(found, Setting) else found for found in read)
    guessed = any(isinstance(found, Setting) and found.heuristic for found in read)
    return Run(
        provides={aspect: frozenset(level for level in levels if level is not None)},
        read=tuple(dict.fromkeys(paths)),
        heuristic=heuristic or guessed,
    )


__all__ = ["Claim", "Levels", "Run", "Tool", "ToolRun", "built_in_tools", "provided", "tool_runs", "within"]
