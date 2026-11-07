"""The formatting question: for each language, in each unit of the project that has it, does CI enforce the
formatting, and where is it defined?"""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath

from project_validator.facts import Facts
from project_validator.facts.formatting import FORMAT, Enforcement
from project_validator.facts.tools import Tool, ToolRun, known_tools, within
from project_validator.questions import Answer, LanguageAnswers, Question, per_unit, runs_of, unknowns_for


@dataclass(frozen=True, slots=True, kw_only=True)
class FormattingAnswer:
    """Whether CI enforces the formatting of one language in one unit ("." for the project's root unit).

    `enforced`: by the tools in `tools`. `applied`: tools CI runs that rewrite files where nothing fails or commits
    the changes. `defined`: the files that define the formatting of a known tool (tool -> files), including tools CI
    does not run. `undefined`: tools CI runs whose formatting needs a definition the project lacks. `known`: how each
    known tool checks the formatting."""

    language: str
    unit: str = "."
    enforced: Answer
    tools: tuple[str, ...] = ()
    applied: tuple[str, ...] = ()
    defined: tuple[tuple[str, tuple[str, ...]], ...] = ()
    undefined: tuple[str, ...] = ()
    known: tuple[tuple[str, str], ...] = ()
    default_style: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "language": self.language,
            "unit": self.unit,
            "enforced": str(self.enforced),
            "tools": list(self.tools),
            "applied": list(self.applied),
            "defined": {tool: list(files) for tool, files in self.defined},
            "undefined": list(self.undefined),
            "known": dict(self.known),
            "default_style": list(self.default_style),
            "unknowns": list(self.unknowns),
        }


def formats(tool: Tool) -> bool:
    return FORMAT in tool.can


def _relevant(path: str, unit: str) -> bool:
    """Whether a definition file applies to code in `unit`: formatters look for theirs in a file's directory and the
    directories above it, so one at or above the unit applies to all of it, and one inside it to part of it."""
    directory = str(PurePosixPath(path).parent)
    return within(unit, directory) or within(directory, unit)


def _defined(known: tuple[Tool, ...], facts: Facts, unit: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Each known tool whose formatting a file that applies to `unit` defines, with those files."""
    found = (
        (tool.name, tuple(path for path in tool.defined(FORMAT, facts) if _relevant(path, unit))) for tool in known
    )
    return tuple((name, files) for name, files in found if files)


def _enforcement(runs: tuple[ToolRun, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The tools whose runs enforce the formatting, and the others, which only rewrite files."""
    enforcing = tuple(dict.fromkeys(run.tool for run in runs if Enforcement.CHECK in run.provides[FORMAT]))
    return enforcing, tuple(dict.fromkeys(run.tool for run in runs if run.tool not in enforcing))


def formatting_answer(language: str, facts: Facts, tools: Iterable[Tool], unit: str = ".") -> FormattingAnswer:
    """Whether CI enforces the formatting of `language` in `unit`, by the facts, and what the known `tools` could."""
    known = tuple(tool for tool in tools if formats(tool) and language in tool.languages)
    if not known:
        return FormattingAnswer(language=language, unit=unit, enforced=Answer.IMPOSSIBLE)
    enforcing, applied = _enforcement(runs_of(FORMAT, language, unit, facts))
    defined = _defined(known, facts, unit)
    unknowns = unknowns_for(known, facts)
    styled = {tool.name for tool in known if not tool.needs_definition(FORMAT)} | {name for name, _ in defined}
    return FormattingAnswer(
        language=language,
        unit=unit,
        enforced=Answer.YES if enforcing else Answer.UNKNOWN if unknowns else Answer.NO,
        tools=enforcing,
        applied=applied,
        defined=defined,
        undefined=tuple(name for name in enforcing if name not in styled),
        known=tuple((tool.name, tool.can[FORMAT][Enforcement.CHECK]) for tool in known),
        default_style=tuple(tool.name for tool in known if not tool.needs_definition(FORMAT)),
        unknowns=unknowns,
    )


type LanguageFormatting = LanguageAnswers[FormattingAnswer]


def language_formatting(language: str, facts: Facts) -> LanguageFormatting:
    tools = known_tools()
    return per_unit(language, facts, lambda unit: formatting_answer(language, facts, tools, unit))


FORMATTING_QUESTION = Question(
    name="formatting",
    description="Does CI enforce the formatting of each language in each unit, and where is the formatting defined?",
    answer=language_formatting,
)

__all__ = [
    "FORMATTING_QUESTION",
    "FormattingAnswer",
    "LanguageFormatting",
    "formats",
    "formatting_answer",
    "language_formatting",
]
