"""Tools and their runs: every practice's tools (coverage, linters, formatters, analyzers, auditors) in one model.

A `Tool` records its whole upstream capability: the languages it handles, and for each aspect of a project it can
provide (`coverage`, later `lint`, `format`, `audit`), the levels it can provide with how to ask for each. It claims
the commands that run it, and reads nothing but the facts: a claimed command becomes a `ToolRun` fact with the
aspects that run provides, joined with the settings it read (see `project_validator.facts.settings`). A setting
counts only when CI runs the tool that reads it. Questions read the runs of an aspect; none has its own tool type.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import PurePosixPath

from project_validator.components import component_cache, known
from project_validator.facts import NOTHING, Command, ConfigurationFile, Fact, Facts, Origin, Setting, Unknown, resolved
from project_validator.facts.arguments import has_option, program, starts_with
from project_validator.facts.shell import ShellSyntaxError

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
    # What defines it, for findings (`Test functions in *_test.go files`).
    describe: str = ""
    # The kinds of file that define it, when `describe` joins several (a runner's test kinds), so that what several
    # tools share is said once.
    kinds: tuple[str, ...] = ()
    # Whether what a unit of tests (a separate test project, `tests/App.Tests`) defines counts for every unit.
    from_test_units: bool = False


def defined_by(
    *,
    files: Iterable[str] = (),
    named: Iterable[str] = (),
    settings: Iterable[str] = (),
    default: bool = True,
) -> Definition:
    """Defined by the files the settings readers `files` read (a `.clang-format`, whatever it holds), by any read file
    `named` so (`ty.toml`, even empty), or by the files that hold settings of the tools `settings` (`[tool.ruff]` in
    `pyproject.toml`)."""
    readers, names, tools = frozenset(files), frozenset(named), frozenset(settings)

    def found(facts: Facts) -> Iterator[str]:
        for fact in facts.of(ConfigurationFile):
            if fact.reader in readers or PurePosixPath(fact.path).name in names:
                yield fact.path
        yield from (setting.path for setting in facts.of(Setting) if setting.tool in tools)

    return Definition(found=found, default=default)


@dataclass(frozen=True, slots=True, kw_only=True)
class Tool:
    """A tool: the languages it handles; `can`, each aspect it can provide with each level and how to ask for it;
    `claims`, which reads a command that runs it (None for a command that does not); `reads`, the tools whose
    settings it reads, whose unreadable settings make its answers unknown; `definitions`, where the project
    defines how it provides an aspect; and `required`, the aspects it is needed for even when others run."""

    name: str
    languages: frozenset[str]
    can: Mapping[str, Mapping[str, str]]
    claims: Claim
    reads: tuple[str, ...] = ()
    definitions: Mapping[str, Definition] = NOTHING
    # The aspects for which the tool is required alongside the others: it finds what they do not (clang-tidy and
    # cppcheck).
    required: frozenset[str] = frozenset()

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
    provides: Mapping[str, Levels] = NOTHING
    # Directories relative to the project ("." for its root) whose code the run covers.
    scope: tuple[str, ...] = (".",)
    read: tuple[str, ...] = ()
    via: tuple[Origin, ...] = ()
    heuristic: bool = False
    # Why the run cannot fail the pipeline, when it cannot (see `Command.advisory`): it provides nothing as a gate.
    advisory: str = ""
    # The project paths (folders, files, globs) its command names, which it alone reaches; none: all of its scope.
    paths: tuple[str, ...] = ()

    def covers(self, unit: str, units: Iterable[str] = (".",)) -> bool:
        """Whether the run covers the code of `unit`, one of the project's `units`: a run covers the units at or below
        its directory, and the unit its directory belongs to (a run in `src/` of the root unit covers the root unit,
        but a run in a workspace member covers only that member)."""
        units = tuple(units)
        return any(within(unit, scope) or unit == owner(scope, units) for scope in self.scope)


def owner(directory: str, units: Iterable[str]) -> str:
    """The unit (among `units`) that `directory` belongs to: the deepest one that contains it ("." when none does).
    Asked for every run and unit of a monorepo, so the answer is kept per directory and set of units."""
    return _owner(directory, units if isinstance(units, tuple) else tuple(units))


@functools.lru_cache(maxsize=65536)
def _owner(directory: str, units: tuple[str, ...]) -> str:
    return max(
        (unit for unit in units if within(directory, unit)), key=lambda unit: (unit != ".", len(unit)), default="."
    )


def within(path: str, directory: str) -> bool:
    """Whether `path` is `directory` or below it (both relative to the project, "." for its root, as the facts write
    them: normalised, `/`-separated)."""
    return directory == "." or path == directory or path.startswith(directory.rstrip("/") + "/")


type Condition = Callable[[Command], bool]


def starts(*prefixes: tuple[str, ...]) -> Condition:
    """Whether a command, as run, starts with one of `prefixes`: a program (by name, `./vendor/bin/phpunit` is
    `phpunit`) and the subcommands after it (`("cargo", "audit")`)."""
    return lambda command: starts_with(resolved(command), *prefixes) is not None


def with_option(*names: str) -> Condition:
    """Whether a command, as run, gives one of the options `names`, alone or with a value (`--coverage=lcov`)."""
    return lambda command: has_option(resolved(command), *names)


def all_of(*conditions: Condition) -> Condition:
    return lambda command: all(condition(command) for condition in conditions)


def any_of(*conditions: Condition) -> Condition:
    return lambda command: any(condition(command) for condition in conditions)


def when(matches: Condition, run: Callable[[], Run]) -> Claim:
    """A claim of the commands `matches` accepts, each of them `run`."""
    return lambda command, _facts: run() if matches(command) else None


def handling(aspect: str) -> Callable[[], frozenset[str]]:
    """The languages the tools now known handle for `aspect` (plugins add tools, so it is asked when needed)."""
    return component_cache(lambda: frozenset().union(*(tool.languages for tool in tools_for(aspect))))


@component_cache
def tools_for(aspect: str) -> tuple[Tool, ...]:
    """The tools now known that can provide `aspect`."""
    return tuple(tool for tool in known_tools() if aspect in tool.can)


def combined(*tools: Tool) -> Tool:
    """One tool with every aspect of `tools`, which spell the same program for different practices (RuboCop formats
    and lints): a command runs it when one of them claims it, providing what each claims."""

    def claims(command: Command, facts: Facts) -> Run | None:
        runs = [run for tool in tools if (run := tool.claims(command, facts)) is not None]
        if not runs:
            return None
        return Run(
            provides={aspect: levels for run in runs for aspect, levels in run.provides.items()},
            read=tuple(dict.fromkeys(path for run in runs for path in run.read)),
            heuristic=any(run.heuristic for run in runs),
        )

    return Tool(
        name=tools[0].name,
        languages=frozenset().union(*(tool.languages for tool in tools)),
        can={aspect: levels for tool in tools for aspect, levels in tool.can.items()},
        claims=claims,
        reads=tuple(dict.fromkeys(name for tool in tools for name in tool.reads)),
        definitions={aspect: found for tool in tools for aspect, found in tool.definitions.items()},
        required=frozenset().union(*(tool.required for tool in tools)),
    )


def known_tools() -> tuple[Tool, ...]:
    """Every tool defined by a module of the shared build systems, the shared tools or a profile."""
    return known(Tool)


def _scope(command: Command) -> tuple[str, ...]:
    """The directories whose code a run covers: where it runs; the whole project where a variable names the directory
    (its build tree, most often); none outside the project."""
    directory = command.directory or "."
    if directory.startswith("$"):
        return (".",)
    if directory.startswith(("/", "..")):
        return ()  # outside the project: it covers none of the project's code
    return (str(PurePosixPath(directory.removeprefix("./") or ".")),)


# Programs whose first word is a subcommand, never a path (`deno fmt` in deno's std, which has a fmt/ folder).
_SUBCOMMANDS = frozenset(
    {
        "bazel",
        "biome",
        "buf",
        "bun",
        "cargo",
        "deno",
        "dotnet",
        "dprint",
        "dune",
        "go",
        "golangci-lint",
        "gradle",
        "hatch",
        "mix",
        "npm",
        "nox",
        "pdm",
        "pnpm",
        "poetry",
        "ruff",
        "swift",
        "uv",
        "yarn",
    }
)

# The characters that make a path a glob.
_GLOB = re.compile(r"[*?\[]")

# What writes a file in a command line: a redirection, tee or touch.
_WRITES = re.compile(r"(?:>>?|\btee\s+(?:-a\s+)?|\btouch\s+)\s*([^\s;&|<>]+)")


class _Sources:
    """The project's source files, the suffixes of each language's, and the files each job's commands write."""

    def __init__(self, facts: Facts) -> None:
        from project_validator.facts.structure import SourceFile

        found = facts.of(SourceFile)
        self.paths = frozenset(source.path for source in found)
        self.of_path = {source.path: source.language for source in found}
        self.directories = frozenset(str(parent) for path in self.paths for parent in PurePosixPath(path).parents)
        self.languages = {PurePosixPath(source.path).suffix: source.language for source in found if source.language}
        self.written: dict[str, set[str]] = {}
        for command in facts.of(Command):
            self.written.setdefault(command.job, set()).update(_WRITES.findall(command.line))

    def named(self, command: Command, languages: frozenset[str]) -> tuple[str, ...]:
        """The project paths a command names, from where it runs: the folders and files of `languages` it is given
        that the project's sources are in, and the globs that match some (upstream #333). None when one is still a
        variable: what it reaches is not known, so it is taken to reach all of its scope; nor when one is its own
        folder (`.`), nor a file of another language (sblint's `shop.asd` names the system it lints)."""
        directory = command.directory or "."
        found: list[str] = []
        argv = resolved(command)
        words = argv[2:] if program(argv) in _SUBCOMMANDS else argv[1:]
        for word in words:
            if "$" in word:
                return ()
            path = _joined(directory, word.rstrip("/"))
            if path in self.paths and self.of_path.get(path) not in languages:
                return ()
            if path in self.paths or path in self.directories or (_GLOB.search(path) and self.matches(path)):
                found.append(path)
        return tuple(found)

    def matches(self, pattern: str) -> bool:
        return any(fnmatchcase(path, pattern) for path in self.paths)

    def foreign(self, command: Command, languages: frozenset[str]) -> bool:
        """Whether the command names source files of `languages`, all of them written by the job and none the
        project's: a tool run on a file CI wrote (`ormolu -m check test.hs`, to try a release) covers none of the
        project's code."""
        named = [
            word
            for word in resolved(command)[1:]
            if not word.startswith("-") and self.languages.get(PurePosixPath(word).suffix) in languages
        ]
        directory = command.directory or "."
        written = self.written.get(command.job, set())
        return bool(named) and all(word in written and _joined(directory, word) not in self.paths for word in named)


def _joined(directory: str, path: str) -> str:
    return str(PurePosixPath(directory) / path.removeprefix("./")).removeprefix("./")


def _claimed(tool: Tool, command: Command, facts: Facts) -> Run | Unknown | None:
    """The run of `tool` that `command` is, if any; unknown when a command line it reads does not split into words."""
    try:
        return tool.claims(command, facts)
    except ShellSyntaxError as error:
        reason = f"a command line it reads does not split into words: {error}"
        return Unknown(
            origin=command.origin, subject=f"the {tool.name} run", reason=reason, hides="settings", tools=(tool.name,)
        )


def _required(tool: Tool, command: Command) -> Unknown:
    """Whether a command runs `tool`, when it runs only under a requirement the checkout does not settle."""
    reason = f"{command.line!r} runs only if {command.requires}"
    return Unknown(
        origin=command.origin, subject=f"the {tool.name} run", reason=reason, hides="settings", tools=(tool.name,)
    )


def tool_runs(facts: Facts, tools: Iterable[Tool]) -> Iterator[ToolRun | Unknown]:
    """The run of each tool among `tools` that each command of `facts` is; unknown when a command line the tool reads
    (in its settings) does not split into words."""
    tools = tuple(tools)
    sources = _Sources(facts)
    for command in facts.of(Command):
        for tool in tools:
            run = _claimed(tool, command, facts)
            if isinstance(run, Unknown):
                yield run
            elif run is not None and any(run.provides.values()) and command.requires:
                yield _required(tool, command)
            elif run is not None and any(run.provides.values()):
                yield ToolRun(
                    origin=command.origin,
                    job=command.job,
                    tool=tool.name,
                    languages=tool.languages,
                    provides={aspect: levels for aspect, levels in run.provides.items() if levels},
                    scope=() if sources.foreign(command, tool.languages) else _scope(command),
                    read=run.read,
                    via=command.via,
                    heuristic=run.heuristic or (command.directory or "").startswith("$"),
                    advisory=command.advisory,
                    paths=sources.named(command, tool.languages),
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
    "Condition",
    "Definition",
    "Levels",
    "Run",
    "Tool",
    "ToolRun",
    "all_of",
    "any_of",
    "combined",
    "defined_by",
    "either",
    "handling",
    "known_tools",
    "owner",
    "provided",
    "starts",
    "tool_runs",
    "tools_for",
    "when",
    "with_option",
    "within",
]
