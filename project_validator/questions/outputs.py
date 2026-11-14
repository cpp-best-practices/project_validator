"""The build output questions, for each language: does every version control system the project is set up for
ignore the language's build outputs, and are none of them committed?

Both are answered for the project as a whole (unit "."): its ignore files are at its root, and an output committed
anywhere is committed. A language's build outputs are those of the build systems the project uses and the language's
own (see `project_validator.facts.outputs.outputs_of`).
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass

from project_validator.facts import ConfigurationFile, Facts
from project_validator.facts.outputs import BuildOutput, CommittedOutput, IgnoreEntry, known_build_outputs, outputs_of
from project_validator.facts.structure import BuildFile, SourceFile, Unit
from project_validator.facts.testing import TestFile
from project_validator.facts.tools import within
from project_validator.questions import EVERY_KIND, Answer, LanguageAnswers, Question, answer_dict
from project_validator.tools.version_control import IGNORE_FILES


@dataclass(frozen=True, slots=True, kw_only=True)
class OutputIgnored:
    """For the build output `name`: the entry of each ignore file that ignores it, or None where none does."""

    name: str
    hint: str
    entries: tuple[tuple[str, str | None], ...]

    def unignored(self) -> tuple[str, ...]:
        return tuple(path for path, entry in self.entries if entry is None)


@dataclass(frozen=True, slots=True, kw_only=True)
class IgnoreAnswer:
    """Whether every ignore file ignores every build output of `language`: impossible when it has none."""

    language: str
    unit: str = "."
    answer: Answer
    outputs: tuple[OutputIgnored, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return answer_dict(self, self.answer, outputs={output.name: dict(output.entries) for output in self.outputs})


@dataclass(frozen=True, slots=True, kw_only=True)
class CommittedAnswer:
    """Whether no build output of `language` is committed (`committed` lists those that are)."""

    language: str
    unit: str = "."
    answer: Answer
    committed: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return answer_dict(self, self.answer, committed=list(self.committed))


def ignore_files(facts: Facts) -> tuple[str, ...]:
    """The ignore files at the root of the project."""
    read = {fact.path for fact in facts.of(ConfigurationFile)}
    return tuple(path for path in IGNORE_FILES if path in read)


def _outputs(language: str, facts: Facts) -> tuple[BuildOutput, ...]:
    build_systems = frozenset(fact.build_system for fact in facts.of(BuildFile))
    return outputs_of(language, build_systems, known_build_outputs())


def _units_writing(output: BuildOutput, language: str, facts: Facts) -> tuple[str, ...]:
    """The directories of the units that write `output`: those built with one of its build systems (Gradle's build/
    is not written beside a Maven project), else those with `language` among their languages or formats."""
    units = facts.of(Unit)
    if output.build_systems:
        built = [unit.directory for unit in units if output.build_systems & set(unit.build_systems)]
    else:
        built = [unit.directory for unit in units if language in unit.languages or language in unit.formats]
    return tuple(built) or (".",)


def _own_directories(language: str, facts: Facts) -> tuple[str, ...]:
    """The directories of `language`'s sources and, for a format, of the files its tools are recognised by (a
    site's conf.py)."""
    files = (
        *(source.path for source in facts.of(SourceFile) if source.language == language),
        *(test.origin.path for test in facts.of(TestFile) if test.language == language),
    )
    return tuple(sorted({posixpath.dirname(path) or "." for path in files}))


def _written_at(language: str, facts: Facts, output: BuildOutput) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Where `output` is written: in the units that write it, and beside `language`'s own files (for a format, as
    a unit would: Sphinx's _build next to its conf.py)."""
    units, own = _units_writing(output, language, facts), _own_directories(language, facts)
    if any(language in unit.formats for unit in facts.of(Unit)):
        units = tuple(dict.fromkeys((*units, *own)))
    return units, own


def _below(paths: tuple[str, ...], directory: str) -> tuple[str, ...]:
    """`paths` that are `directory` or below it, relative to it."""
    if directory == ".":
        return paths
    return tuple(posixpath.relpath(path, directory) for path in paths if within(path, directory))


def _ignored(output: BuildOutput, facts: Facts, files: tuple[str, ...], language: str = "") -> OutputIgnored:
    """For each ignore file at the root, the entry that ignores `output`: its own, or that of an ignore file of the
    same name in a directory the output is written below (a unit's own .gitignore), which applies there."""
    units, sources = _written_at(language, facts, output)

    def ignores(fact: IgnoreEntry, name: str) -> bool:
        # The root file applies at the root wherever it is kept (`.fossil-settings/ignore-glob`); a nested one, named
        # as a root-level file is (`docs/.gitignore`), applies in its directory.
        if fact.origin.path == name:
            directory = "."
        elif "/" not in name and posixpath.basename(fact.origin.path) == name:
            directory = posixpath.dirname(fact.origin.path)
        else:
            return False
        return output.ignored_by(fact, _below(units, directory), _below(sources, directory)) and (
            directory == "." or bool(_below(units, directory) or _below(sources, directory))
        )

    def entry(path: str) -> str | None:
        found = next((fact for fact in facts.of(IgnoreEntry) if ignores(fact, path)), None)
        if found is None:
            return None
        return found.written if found.origin.path == path else f"{found.written} ({found.origin.path})"

    return OutputIgnored(name=output.name, hint=output.hint, entries=tuple((path, entry(path)) for path in files))


def ignored_outputs(language: str, facts: Facts) -> LanguageAnswers[IgnoreAnswer]:
    """For a language: whether the project's ignore files ignore its build outputs."""
    outputs = _outputs(language, facts)
    if not outputs:
        answer = IgnoreAnswer(language=language, answer=Answer.IMPOSSIBLE)
    else:
        files = ignore_files(facts)
        found = tuple(_ignored(output, facts, files, language) for output in outputs)
        ignored = all(not output.unignored() for output in found)
        answer = IgnoreAnswer(language=language, answer=Answer.YES if ignored else Answer.NO, outputs=found)
    return LanguageAnswers(language=language, units=(answer,))


def committed_outputs(language: str, facts: Facts) -> LanguageAnswers[CommittedAnswer]:
    """For a language: whether any of its build outputs is committed."""
    outputs = _outputs(language, facts)
    if not outputs:
        answer = CommittedAnswer(language=language, answer=Answer.IMPOSSIBLE)
    else:
        names = {output.name for output in outputs}
        committed = tuple(
            dict.fromkeys(
                fact.origin.path
                for fact in facts.of(CommittedOutput)
                if fact.output in names and language in fact.languages
            )
        )
        answer = CommittedAnswer(language=language, answer=Answer.NO if committed else Answer.YES, committed=committed)
    return LanguageAnswers(language=language, units=(answer,))


VCS_IGNORE_QUESTION = Question(
    name="vcs-ignore",
    description="Do the project's ignore files keep each language's build outputs out of version control?",
    answer=ignored_outputs,
    kinds=EVERY_KIND,
)
COMMITTED_ARTIFACTS_QUESTION = Question(
    name="committed-artifacts",
    description="Is no build output of each language committed?",
    answer=committed_outputs,
    kinds=EVERY_KIND,
)

__all__ = [
    "COMMITTED_ARTIFACTS_QUESTION",
    "VCS_IGNORE_QUESTION",
    "CommittedAnswer",
    "IgnoreAnswer",
    "OutputIgnored",
    "committed_outputs",
    "ignore_files",
    "ignored_outputs",
]
