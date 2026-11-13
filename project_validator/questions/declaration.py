"""The schema-declared question: for each format whose schemas declare themselves, in each unit of the project whose
files are in it, which schemas declare their dialect and identifier, which do not, and which declare a superseded
dialect. A test suite's schemas are told apart. A format with no such schemas (YAML) cannot be asked."""

from __future__ import annotations

from dataclasses import dataclass

from project_validator.facts import Facts
from project_validator.facts.declaration import SchemaDeclaration, declared_formats
from project_validator.facts.structure import Unit
from project_validator.facts.tools import owner
from project_validator.questions import FORMATS, Answer, LanguageAnswers, Question, answer_dict, per_unit


@dataclass(frozen=True, slots=True, kw_only=True)
class DeclarationAnswer:
    """Whether the schemas of one format in one unit ("." for the project's root unit) declare themselves: `what` is
    asked of each; `declared`, the judged schemas that declare it all; `problems`, what each judged schema leaves out
    (`path: no $id`); `outdated`, which declare a superseded dialect and why; `test_problems`, the problems of a test
    suite's schemas, which may be undeclared on purpose. `possible` is false for a format no schema of which declares
    anything."""

    language: str
    unit: str = "."
    what: str = ""
    declared: tuple[str, ...] = ()
    problems: tuple[str, ...] = ()
    outdated: tuple[str, ...] = ()
    test_problems: tuple[str, ...] = ()
    possible: bool = True

    @property
    def answer(self) -> Answer:
        if not self.possible:
            return Answer.IMPOSSIBLE
        return Answer.NO if self.problems else Answer.YES

    def as_dict(self) -> dict[str, object]:
        return answer_dict(
            self,
            self.answer,
            what=self.what,
            declared=list(self.declared),
            problems=list(self.problems),
            outdated=list(self.outdated),
            test_problems=list(self.test_problems),
        )


def _schemas(facts: Facts, format_: str, unit: str) -> list[SchemaDeclaration]:
    units = [found.directory for found in facts.of(Unit)] or ["."]
    return [
        schema
        for schema in facts.of(SchemaDeclaration)
        if schema.format == format_ and owner(schema.path, units) == unit
    ]


def _problems(schemas: list[SchemaDeclaration]) -> tuple[str, ...]:
    return tuple(f"{schema.path}: no {name}" for schema in schemas for name in schema.missing)


def declaration_answer(format_: str, facts: Facts, unit: str = ".") -> DeclarationAnswer:
    """How the schemas of `format_` in `unit` declare themselves, by the facts."""
    if format_ not in declared_formats():
        return DeclarationAnswer(language=format_, unit=unit, possible=False)
    schemas = _schemas(facts, format_, unit)
    judged = [schema for schema in schemas if schema.role != "test"]
    return DeclarationAnswer(
        language=format_,
        unit=unit,
        what=next((schema.what for schema in schemas), ""),
        declared=tuple(schema.path for schema in judged if not schema.missing),
        problems=_problems(judged),
        outdated=tuple(f"{schema.path}: {schema.outdated}" for schema in judged if schema.outdated),
        test_problems=_problems([schema for schema in schemas if schema.role == "test"]),
    )


def schema_declarations(language: str, facts: Facts) -> LanguageAnswers[DeclarationAnswer]:
    return per_unit(language, facts, lambda unit, _: declaration_answer(language, facts, unit))


SCHEMA_DECLARED_QUESTION = Question(
    name="schema-declared",
    description="Which schemas of each format in each unit declare their dialect and identifier, and which do not?",
    answer=schema_declarations,
    kinds=FORMATS,
)

__all__ = ["SCHEMA_DECLARED_QUESTION", "DeclarationAnswer", "declaration_answer", "schema_declarations"]
