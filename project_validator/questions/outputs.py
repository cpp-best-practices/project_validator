"""The build output questions, for each language: does every version control system the project is set up for
ignore the language's build outputs, and are none of them committed?

Both are answered for the project as a whole (unit "."): its ignore files are at its root, and an output committed
anywhere is committed. A language's build outputs are those of the build systems the project uses, or the language's
own (see `project_validator.facts.outputs.outputs_of`).
"""

from dataclasses import dataclass

from project_validator.facts import ConfigurationFile, Facts
from project_validator.facts.outputs import BuildOutput, CommittedOutput, IgnoreEntry, known_build_outputs, outputs_of
from project_validator.facts.structure import BuildFile
from project_validator.questions import Answer, LanguageAnswers, Question
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
        return {
            "language": self.language,
            "unit": self.unit,
            "answer": str(self.answer),
            "outputs": {output.name: dict(output.entries) for output in self.outputs},
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class CommittedAnswer:
    """Whether no build output of `language` is committed (`committed` lists those that are)."""

    language: str
    unit: str = "."
    answer: Answer
    committed: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "language": self.language,
            "unit": self.unit,
            "answer": str(self.answer),
            "committed": list(self.committed),
        }


def ignore_files(facts: Facts) -> tuple[str, ...]:
    """The ignore files at the root of the project."""
    read = {fact.path for fact in facts.of(ConfigurationFile)}
    return tuple(path for path in IGNORE_FILES if path in read)


def _outputs(language: str, facts: Facts) -> tuple[BuildOutput, ...]:
    build_systems = frozenset(fact.build_system for fact in facts.of(BuildFile))
    return outputs_of(language, build_systems, known_build_outputs())


def _ignored(output: BuildOutput, facts: Facts, files: tuple[str, ...]) -> OutputIgnored:
    def entry(path: str) -> str | None:
        found = (fact for fact in facts.of(IgnoreEntry) if fact.origin.path == path and output.ignored_by(fact))
        return next((fact.written for fact in found), None)

    return OutputIgnored(name=output.name, hint=output.hint, entries=tuple((path, entry(path)) for path in files))


def ignored_outputs(language: str, facts: Facts) -> LanguageAnswers[IgnoreAnswer]:
    """For a language: whether the project's ignore files ignore its build outputs."""
    outputs = _outputs(language, facts)
    if not outputs:
        answer = IgnoreAnswer(language=language, answer=Answer.IMPOSSIBLE)
    else:
        files = ignore_files(facts)
        found = tuple(_ignored(output, facts, files) for output in outputs)
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
)
COMMITTED_ARTIFACTS_QUESTION = Question(
    name="committed-artifacts",
    description="Is no build output of each language committed?",
    answer=committed_outputs,
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
