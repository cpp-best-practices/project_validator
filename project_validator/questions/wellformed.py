"""The wellformed question: for each format, in each unit of the project whose files are in it, which data files parse
and which do not, where and why. A test suite's malformed data and files too large to read are told apart."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from project_validator.facts import Facts
from project_validator.facts.structure import Unit
from project_validator.facts.tools import owner
from project_validator.facts.wellformed import DataFile
from project_validator.questions import FORMATS, Answer, LanguageAnswers, Question, answer_dict, per_unit


@dataclass(frozen=True, slots=True, kw_only=True)
class WellformedAnswer:
    """Whether the data files of one format in one unit ("." for the project's root unit) parse: `parsed`, the judged
    files that do; `problems`, where and why each judged file does not (`path:line:column: why`); `test_problems`,
    the same for a test suite's data files, which may be malformed on purpose; `unread`, why each file that was not
    parsed was not (path -> why)."""

    language: str
    unit: str = "."
    parsed: tuple[str, ...] = ()
    problems: tuple[str, ...] = ()
    test_problems: tuple[str, ...] = ()
    unread: Mapping[str, str]

    @property
    def answer(self) -> Answer:
        return Answer.NO if self.problems else Answer.YES

    def as_dict(self) -> dict[str, object]:
        return answer_dict(
            self,
            self.answer,
            parsed=list(self.parsed),
            problems=list(self.problems),
            test_problems=list(self.test_problems),
            unread=dict(self.unread),
        )


def located(file: DataFile) -> str:
    """Where and why a file does not parse, as compilers write it: `path:line:column: why`."""
    where = f":{file.line}:{file.column}" if file.line is not None and file.column is not None else ""
    return f"{file.path}{where}: {file.problem}"


def _data_files(facts: Facts, format_: str, unit: str) -> list[DataFile]:
    units = [found.directory for found in facts.of(Unit)] or ["."]
    return [file for file in facts.of(DataFile) if file.format == format_ and owner(file.path, units) == unit]


def _problems(files: Iterable[DataFile]) -> tuple[str, ...]:
    return tuple(located(file) for file in files if file.problem is not None)


def wellformed_answer(format_: str, facts: Facts, unit: str = ".") -> WellformedAnswer:
    """How the files of `format_` in `unit` parse, by the facts."""
    files = _data_files(facts, format_, unit)
    judged = [file for file in files if file.role != "test" and file.unread is None]
    return WellformedAnswer(
        language=format_,
        unit=unit,
        parsed=tuple(file.path for file in judged if file.problem is None),
        problems=_problems(judged),
        test_problems=_problems(file for file in files if file.role == "test"),
        unread={file.path: file.unread for file in files if file.unread is not None},
    )


def wellformed_files(language: str, facts: Facts) -> LanguageAnswers[WellformedAnswer]:
    return per_unit(language, facts, lambda unit, _: wellformed_answer(language, facts, unit))


WELLFORMED_QUESTION = Question(
    name="wellformed",
    description="Which data files of each format in each unit parse, and where do the others break?",
    answer=wellformed_files,
    kinds=FORMATS,
)

__all__ = ["WELLFORMED_QUESTION", "WellformedAnswer", "located", "wellformed_answer", "wellformed_files"]
