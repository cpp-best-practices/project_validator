"""What every question about an aspect of the shared tool model asks, for one language in one unit: which known tools
provide the aspect, which of them CI runs and at which levels, where the project defines how they provide it, and what
could not be read. A practice's question is a declaration over this (see `aspect_answers`); its policy reads the
answer.

Coverage, whose levels are granularities with a ranking of their own, has its own answer
(`project_validator.questions.coverage`).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import PurePosixPath

from project_validator.facts import Facts
from project_validator.facts.auxiliary import selectors
from project_validator.facts.roles import role
from project_validator.facts.structure import Unit, tests_unit
from project_validator.facts.testing import TEST
from project_validator.facts.tools import Tool, known_tools, owner, within
from project_validator.questions import Answer, LanguageAnswers, answer_dict, per_unit, runs_of, unknowns_for
from project_validator.questions.reach import PATHED, Reach, reach


@dataclass(frozen=True, slots=True, kw_only=True)
class KnownTool:
    """A known tool of the aspect: how it provides each level, whether it needs the project to define how (a style,
    its rules) because it has no default worth running, and whether it is required alongside the others (it finds
    what they do not)."""

    name: str
    can: Mapping[str, str]
    needs_definition: bool = False
    required: bool = False
    # What defines how it provides the aspect (`Test functions in *_test.go files`), and the kinds it joins.
    describe: str = ""
    kinds: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class Ran:
    """A tool CI runs: the levels its runs provide, and the settings files they read to decide."""

    name: str
    levels: frozenset[str]
    read: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolAnswer:
    """Whether CI provides `aspect` at `level` for one language in one unit ("." for the project's root unit).

    `runs`: the tools CI runs, with the levels each provides there. `defined`: the files that define how a known tool
    provides the aspect (tool -> files), CI running it or not. `known`: every known tool of the aspect for the
    language. `auxiliary`: the roles of the code the answer is about when only auxiliary code of the unit (helper
    scripts, docs, examples, benchmarks) is in the language; empty when it is about the unit's product code."""

    aspect: str
    language: str
    unit: str = "."
    level: str
    answer: Answer
    auxiliary: tuple[str, ...] = ()
    runs: tuple[Ran, ...] = ()
    defined: tuple[tuple[str, tuple[str, ...]], ...] = ()
    known: tuple[KnownTool, ...] = ()
    unknowns: tuple[str, ...] = ()
    # The unknowns that may hide where a known tool is defined (settings that could not be read).
    unknown_definitions: tuple[str, ...] = ()
    # The tools CI runs for the aspect only where they cannot fail the pipeline, each with why (see `advised`).
    advisory: tuple[tuple[str, str], ...] = ()
    # When every file that defines the aspect here is a unit of tests' (tokio's benches have no test of their own;
    # tests-integration's count for them), those units.
    lent_by: tuple[str, ...] = ()
    # How much of the unit's product code of the language the runs that provide the level reach, when not all of it.
    reach: Reach | None = None

    def providing(self, level: str | None = None) -> tuple[str, ...]:
        """The tools CI runs that provide `level` (by default, the answer's)."""
        wanted = self.level if level is None else level
        return tuple(ran.name for ran in self.runs if wanted in ran.levels)

    def tools_ran(self) -> tuple[str, ...]:
        """The names of every tool CI ran for the aspect, each once, in order."""
        return tuple(dict.fromkeys(ran.name for ran in self.runs))

    def advised(self) -> tuple[tuple[str, str], ...]:
        """The tools CI runs for the aspect only where they cannot fail the pipeline, each with why."""
        return self.advisory

    def others(self) -> tuple[str, ...]:
        """The tools CI runs that do not provide the answer's level (a formatter that only rewrites files)."""
        return tuple(ran.name for ran in self.runs if self.level not in ran.levels)

    def read_by(self, tool: str) -> tuple[str, ...]:
        """The settings files CI's runs of `tool` read to decide what they provide."""
        return next((ran.read for ran in self.runs if ran.name == tool), ())

    def definitions(self, tools: Iterable[str] | None = None) -> tuple[str, ...]:
        """The files that define the aspect for `tools` (by default, every known tool)."""
        names = None if tools is None else set(tools)
        found = (path for name, paths in self.defined if names is None or name in names for path in paths)
        return tuple(dict.fromkeys(found))

    def undefined(self) -> tuple[str, ...]:
        """The tools CI runs at the answer's level that need a definition the project lacks."""
        needing = {tool.name for tool in self.known if tool.needs_definition} - {name for name, _ in self.defined}
        return tuple(name for name in self.providing() if name in needing)

    def required_idle(self) -> tuple[str, ...]:
        """The required tools CI does not run at the answer's level, when one is required."""
        providing = set(self.providing())
        return tuple(tool.name for tool in self.known if tool.required and tool.name not in providing)

    def how(self, level: str | None = None) -> tuple[str, ...]:
        """How each known tool provides `level` (by default, the answer's); a tool with no way to give is never
        suggested (it only provides the level as part of something else, molecule's testinfra verifier, or is
        recognised where a project uses it but another is recommended: uncrustify beside clang-format)."""
        wanted = self.level if level is None else level
        return tuple(tool.can[wanted] for tool in self.known if tool.can.get(wanted))

    def names(self) -> tuple[str, ...]:
        """The known tools to name: those suggested (see `how`), and those the project defines."""
        defined = {name for name, _ in self.defined}
        return tuple(tool.name for tool in self.known if any(tool.can.values()) or tool.name in defined)

    def as_dict(self) -> dict[str, object]:
        return answer_dict(
            self,
            self.answer,
            level=self.level,
            runs={ran.name: {"levels": sorted(ran.levels), "read": list(ran.read)} for ran in self.runs},
            defined={name: list(paths) for name, paths in self.defined},
            known={
                tool.name: {"can": dict(tool.can), "needs_definition": tool.needs_definition, "required": tool.required}
                for tool in self.known
            },
            unknowns=list(self.unknowns),
            unknown_definitions=list(self.unknown_definitions),
            advisory=dict(self.advisory),
        )


def _relevant(path: str, unit: str, facts: Facts, auxiliary: tuple[str, ...], *, configuration: bool) -> bool:
    """Whether a definition file applies to code in `unit`: tools look for theirs in a file's directory and the
    directories above it, so one at or above the unit applies to all of it, and one inside it (not in a unit of its
    own) to part of it, unless that part is vendored or auxiliary code (a test fixture's, and when the file is
    `configuration` rather than a test, an example's: see `Selectors.apart`) the answer is not about (`auxiliary`:
    what named the code it is about)."""
    directory = str(PurePosixPath(path).parent)
    if within(unit, directory):
        return True
    named = selectors(facts).apart(path, unit if configuration else None)
    inside = within(directory, unit) and _owner(path, facts) == unit
    return inside and role(path) != "vendored" and (not named or named in auxiliary)


def _owner(path: str, facts: Facts) -> str:
    """The unit a file inside units is part of: the innermost (a nested package's tests are its own)."""
    return owner(path, [found.directory for found in facts.of(Unit)] or ["."])


def _runs(aspect: str, language: str, unit: str, facts: Facts, auxiliary: tuple[str, ...]) -> tuple[Ran, ...]:
    levels: dict[str, set[str]] = {}
    read: dict[str, dict[str, None]] = {}
    for run in runs_of(aspect, language, unit, facts, auxiliary=auxiliary):
        levels.setdefault(run.tool, set()).update(run.provides[aspect])
        read.setdefault(run.tool, {}).update(dict.fromkeys(run.read))
    return tuple(Ran(name=name, levels=frozenset(found), read=tuple(read[name])) for name, found in levels.items())


def _advisory(
    aspect: str, language: str, unit: str, facts: Facts, auxiliary: tuple[str, ...], ran: Iterable[Ran]
) -> tuple[tuple[str, str], ...]:
    """The tools whose runs of the aspect cannot fail the pipeline and that no run that can provides, with why."""
    gating = {found.name for found in ran}
    found = runs_of(aspect, language, unit, facts, auxiliary=auxiliary, advisory=True)
    return tuple(dict.fromkeys((run.tool, run.advisory) for run in found if run.tool not in gating))


def _known(tool: Tool, aspect: str) -> KnownTool:
    definition = tool.definitions.get(aspect)
    return KnownTool(
        name=tool.name,
        can=tool.can[aspect],
        needs_definition=tool.needs_definition(aspect),
        required=aspect in tool.required,
        describe=definition.describe if definition is not None else "",
        kinds=definition.kinds if definition is not None else (),
    )


type _Defined = tuple[tuple[str, tuple[str, ...]], ...]


def _defined(aspect: str, known: tuple[Tool, ...], facts: Facts, unit: str, auxiliary: tuple[str, ...]) -> _Defined:
    """Each known tool whose definition a file that applies to `unit` (or to the auxiliary code the answer is about)
    holds, with those files."""
    in_test_unit = tests_unit(facts)

    def applies(tool: Tool, path: str) -> bool:
        definition = tool.definitions.get(aspect)
        relevant = _relevant(path, unit, facts, auxiliary, configuration=aspect != TEST)
        return relevant or (definition is not None and definition.from_test_units and in_test_unit(path, unit))

    found = ((tool.name, tuple(path for path in tool.defined(aspect, facts) if applies(tool, path))) for tool in known)
    return tuple((name, paths) for name, paths in found if paths)


def _lent_by(defined: _Defined, facts: Facts, unit: str) -> tuple[str, ...]:
    """The units of tests whose files are every file in `defined`, when none is `unit`'s own; not for the root, which
    such a unit tests as a matter of course (an OCaml project's test/)."""
    units = {found.directory: found.role for found in facts.of(Unit)}
    owners = {owner(path, units) for _, paths in defined for path in paths}
    if unit == "." or not owners or unit in owners or any(units.get(found) != "test" for found in owners):
        return ()
    return tuple(sorted(owners))


def _verdict(level: str, runs: tuple[Ran, ...], unknowns: tuple[str, ...]) -> Answer:
    return Answer.YES if any(level in ran.levels for ran in runs) else Answer.UNKNOWN if unknowns else Answer.NO


def tool_answer(
    aspect: str,
    level: str,
    language: str,
    facts: Facts,
    tools: Iterable[Tool],
    unit: str = ".",
    *,
    auxiliary: tuple[str, ...] = (),
) -> ToolAnswer:
    """Whether CI provides `aspect` at `level` for `language` in `unit` (or its `auxiliary` code); what `tools` can."""
    known = tuple(tool for tool in tools if aspect in tool.can and language in tool.languages)
    answer = ToolAnswer(
        aspect=aspect, language=language, unit=unit, level=level, answer=Answer.IMPOSSIBLE, auxiliary=auxiliary
    )
    if not known:
        return answer
    runs = _runs(aspect, language, unit, facts, auxiliary)
    return replace(
        answer,
        answer=_verdict(level, runs, unknowns := unknowns_for(known, facts)),
        reach=_reach(aspect, level, language, unit, facts),
        runs=runs,
        defined=(defined := _defined(aspect, known, facts, unit, auxiliary)),
        lent_by=_lent_by(defined, facts, unit),
        known=tuple(_known(tool, aspect) for tool in known),
        unknowns=unknowns,
        unknown_definitions=unknowns_for(known, facts, hiding=("settings",)),
        advisory=_advisory(aspect, language, unit, facts, auxiliary, runs),
    )


def _reach(aspect: str, level: str, language: str, unit: str, facts: Facts) -> Reach | None:
    """What the runs that provide `level` reach of the unit's product code, for an aspect a run provides for the paths
    it is given (an answer about auxiliary code has no product code to miss)."""
    if aspect not in PATHED:
        return None
    found = runs_of(aspect, language, unit, facts)
    return reach(language, unit, facts, (run for run in found if level in run.provides[aspect]))


type LanguageToolAnswers = LanguageAnswers[ToolAnswer]


def aspect_answers(aspect: str, level: str) -> Callable[[str, Facts], LanguageToolAnswers]:
    """For a language: whether CI provides `aspect` at `level` in each unit that has the language (see `per_unit`)."""

    def answer(language: str, facts: Facts) -> LanguageToolAnswers:
        tools = known_tools()
        return per_unit(
            language,
            facts,
            lambda unit, roles: tool_answer(aspect, level, language, facts, tools, unit, auxiliary=roles),
        )

    return answer


__all__ = ["KnownTool", "LanguageToolAnswers", "Ran", "ToolAnswer", "aspect_answers", "tool_answer"]
