"""Whether the project's data files parse. A format's profile defines a `Parser` for each of its formats; each of the
project's own files in a format with a parser is a `DataFile` fact, parsed once at extraction, with where and why it
does not parse. Nothing here judges: the `wellformed` question counts, and its policy decides."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, replace

from project_validator.components import known
from project_validator.core import Project
from project_validator.facts import Fact, Facts

# Files larger than this are not parsed, and recorded as unread.
MAX_SIZE = 5 * 1024 * 1024
NESTED_MESSAGE = "nested too deeply to read"


class ParseError(Exception):
    """Why a file does not parse, and where (a line and a column, counted from 1) when the parser says."""

    def __init__(self, message: str, line: int | None = None, column: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.line = line
        self.column = column


type Parse = Callable[[str, bytes], None]


@dataclass(frozen=True, slots=True, kw_only=True)
class Parser:
    """How the files of one format are read for well-formedness: `parse(path, data)` returns when `data`, the bytes of
    the file at `path`, is well formed, and raises `ParseError` where it is not (the path may say how to read the
    data: a `tsconfig.json` allows comments). A profile defines one per format; they are found, not listed."""

    format: str
    parse: Parse


@dataclass(frozen=True, slots=True, kw_only=True)
class DataFile(Fact):
    """A file in a format with a parser, and whether it parses: `problem` says why it does not (None when it does),
    at `line`:`column` when the parser says; `unread` says why it was not parsed (too large). `role` is the file's
    (see `project_validator.facts.roles`): a test suite's data may be malformed on purpose."""

    format: str
    role: str = "product"
    problem: str | None = None
    line: int | None = None
    column: int | None = None
    unread: str | None = None

    @property
    def path(self) -> str:
        return self.origin.path


def known_parsers() -> tuple[Parser, ...]:
    """Every parser a profile or a plugin defines."""
    return known(Parser)


def parsed_formats() -> frozenset[str]:
    """The formats the known parsers read (plugins add parsers, so it is asked when needed)."""
    return frozenset(parser.format for parser in known_parsers())


def _parsed(project: Project, parser: Parser, found: DataFile) -> DataFile:
    """`found`, the data file at its path, with how it parses."""
    if project.size(found.path) > MAX_SIZE:
        return replace(found, unread=f"larger than {MAX_SIZE >> 20} MiB")
    try:
        parser.parse(found.path, project.read_bytes(found.path))
    except ParseError as error:
        return replace(found, problem=error.message, line=error.line, column=error.column)
    except RecursionError:
        return replace(found, problem=NESTED_MESSAGE)
    return found


def data_file_facts(project: Project, facts: Facts, parsers: Iterable[Parser]) -> Iterator[DataFile]:
    """Each of the project's own files (vendored ones apart) in a format one of `parsers` reads, parsed."""
    from project_validator.facts.structure import SourceFile  # structure reads the profiles, which define parsers

    by_format = {parser.format: parser for parser in parsers}
    for source in facts.of(SourceFile):
        parser = by_format.get(source.language or "")
        if parser is not None and not source.vendored:
            yield _parsed(project, parser, DataFile(origin=source.origin, format=parser.format, role=source.role))


__all__ = [
    "MAX_SIZE",
    "NESTED_MESSAGE",
    "DataFile",
    "Parse",
    "ParseError",
    "Parser",
    "data_file_facts",
    "known_parsers",
    "parsed_formats",
]
