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

from project_validator.facts import NOTHING, Command, ConfigurationFile, Fact, Facts, Origin, Setting

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


def either(*claims: Claim) -> Claim:
    """The run the first of `claims` that claims a command says it is."""

    def claims_any(command: Command, facts: Facts) -> Run | None:
        return next((run for claim in claims if (run := claim(command, facts)) is not None), None)

    return claims_any


@dataclass(frozen=True, slots=True, kw_only=True)
class Definition:
    """Where a project defines how a tool provides an aspect (its formatting style, its rules): `found` returns the
    files that define it. A tool with a `default` provides the aspect without one."""

    found: Callable[[Facts], Iterable[str]]
    default: bool = True


def defined_by(*, files: Iterable[str] = (), settings: Iterable[str] = (), default: bool = True) -> Definition:
    """Defined by the files the settings readers `files` read (a `.clang-format`, whatever it holds), or by the files
    that hold settings of the tools `settings` (`[tool.ruff]` in `pyproject.toml`)."""
    readers, tools = frozenset(files), frozenset(settings)

    def found(facts: Facts) -> Iterator[str]:
        yield from (fact.path for fact in facts.of(ConfigurationFile) if fact.reader in readers)
        yield from (setting.path for setting in facts.of(Setting) if setting.tool in tools)

    return Definition(found=found, default=default)


@dataclass(frozen=True, slots=True, kw_only=True)
class Tool:
    """A tool: the languages it handles; `can`, each aspect it can provide with each level and how to ask for it;
    `claims`, which reads a command that runs it (None for a command that does not); `reads`, the tools whose
    settings it reads, whose unreadable settings make its answers unknown; and `definitions`, where the project
    defines how it provides an aspect."""

    name: str
    languages: frozenset[str]
    can: Mapping[str, Mapping[str, str]]
    claims: Claim
    reads: tuple[str, ...] = ()
    definitions: Mapping[str, Definition] = NOTHING  # type: ignore[assignment]

    def defined(self, aspect: str, facts: Facts) -> tuple[str, ...]:
        """The files that define how the tool provides `aspect`."""
        definition = self.definitions.get(aspect)
        return () if definition is None else tuple(dict.fromkeys(definition.found(facts)))

    def needs_definition(self, aspect: str) -> bool:
        definition = self.definitions.get(aspect)
        return definition is not None and not definition.default


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

    def covers(self, unit: str, units: Iterable[str] = (".",)) -> bool:
        """Whether the run covers the code of `unit`, one of the project's `units`: a run covers the units at or below
        its directory, and the unit its directory belongs to (a run in `src/` of the root unit covers the root unit,
        but a run in a workspace member covers only that member)."""
        units = tuple(units)
        return any(within(unit, scope) or unit == owner(scope, units) for scope in self.scope)


def owner(directory: str, units: Iterable[str]) -> str:
    """The unit (among `units`) that `directory` belongs to: the deepest one that contains it ("." when none does)."""
    return max(
        (unit for unit in units if within(directory, unit)), key=lambda unit: (unit != ".", len(unit)), default="."
    )


def within(path: str, directory: str) -> bool:
    """Whether `path` is `directory` or below it (both relative to the project, "." for its root)."""
    return directory == "." or path == directory or PurePosixPath(path).is_relative_to(directory)


def known_tools() -> tuple[Tool, ...]:
    """Every tool defined by a module of the shared build systems, the shared tools or a profile."""
    from project_validator.components import known

    return known(Tool)


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


__all__ = [
    "Claim",
    "Definition",
    "Levels",
    "Run",
    "Tool",
    "ToolRun",
    "defined_by",
    "either",
    "known_tools",
    "owner",
    "provided",
    "tool_runs",
    "within",
]
