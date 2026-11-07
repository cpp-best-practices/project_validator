"""Setting facts: what the project's configuration files set, per tool, read once for every question.

A `SettingsReader` reads one tool's settings from the files it reads by default (by name, in any directory) and
from the files a command CI runs names as its configuration (`coverage run --rcfile=ci/coverage.ini`). Tools that
run join their settings by querying the facts (`Facts.settings`), never by reading files themselves. A file that
does not parse is recorded as unknown for its tool.
"""

import configparser
import json
import re
import tomllib
import xml.etree.ElementTree as ElementTree
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import PurePosixPath

from project_validator.core import Project
from project_validator.facts import Command, ConfigurationFile, Fact, Facts, Origin, Setting, Unknown
from project_validator.text import strip_json_comments

type Read = Callable[[str, str], Iterable[Fact]]


@dataclass(frozen=True, slots=True, kw_only=True)
class SettingsReader:
    """`read(path, text)` records the settings of the file `path`. `files` are the names (or globs of names) of the
    files the tool reads in any directory; `named_by` the configuration files a command names, relative to the
    project."""

    name: str
    files: tuple[str, ...]
    read: Read
    named_by: Callable[[Command], Iterable[str]] | None = None


def built_in_settings_readers() -> tuple[SettingsReader, ...]:
    """Every settings reader defined by a module of the shared build systems, the shared tools or a profile."""
    from project_validator.components import built_in

    return built_in(SettingsReader)


def settings_facts(project: Project, readers: Iterable[SettingsReader], commands: Facts) -> Iterator[Fact]:
    """The settings in the files each reader reads by default, then in the files the commands of `commands` name."""
    readers = tuple(readers)
    wanted = [
        (reader, path)
        for path in project.files()
        for reader in readers
        if any(fnmatchcase(PurePosixPath(path).name, pattern) for pattern in reader.files)
    ]
    wanted += [
        (reader, path)
        for command in commands.of(Command)
        for reader in readers
        for path in (reader.named_by(command) if reader.named_by else ())
        if project.exists(path)
    ]
    for reader, path in dict.fromkeys(wanted):
        yield ConfigurationFile(origin=Origin(path=path), reader=reader.name)
        yield from reader.read(path, project.read_text(path))


def plain(value: object) -> object:
    """A setting value as facts hold it: lists become tuples, tables are flattened by `flattened`."""
    if isinstance(value, list):
        return tuple(plain(item) for item in value)
    return value


def flattened(table: Mapping[str, object], prefix: str = "") -> Iterator[tuple[str, object]]:
    """(dotted key, value) for each value in nested tables."""
    for key, value in table.items():
        if isinstance(value, Mapping):
            yield from flattened(value, f"{prefix}{key}.")
        else:
            yield f"{prefix}{key}", plain(value)


def settings(
    tool: str, path: str, found: Iterable[tuple[str, object]], *, heuristic: bool = False
) -> Iterator[Setting]:
    for key, value in found:
        origin = Origin(path=path, at=tuple(key.split(".")))
        yield Setting(origin=origin, tool=tool, key=key, value=value, heuristic=heuristic)


def unreadable(tool: str, path: str, error: Exception) -> Unknown:
    return Unknown(
        origin=Origin(path=path), subject=f"the {tool} settings", reason=f"{error}", hides="settings", tools=(tool,)
    )


def toml_settings(tool: str, path: str, text: str, *table: str) -> Iterator[Fact]:
    """The settings in TOML `table` (`tool`, `coverage`) of the file, flattened under dotted keys."""
    try:
        value: object = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        yield unreadable(tool, path, error)
        return
    for key in table:
        value = value.get(key) if isinstance(value, Mapping) else None
    if isinstance(value, Mapping):
        yield from settings(tool, path, flattened(value))


def ini_settings(tool: str, path: str, text: str, sections: Callable[[str], str | None]) -> Iterator[Fact]:
    """The settings in the INI file's sections that `sections` maps to a key prefix (None for other sections)."""
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(text)
    except configparser.Error as error:
        yield unreadable(tool, path, error)
        return
    for section in parser.sections():
        if (prefix := sections(section)) is not None:
            yield from settings(tool, path, ((f"{prefix}{key}", value) for key, value in parser.items(section)))


def json_settings(tool: str, path: str, text: str, *keys: str, comments: bool = False) -> Iterator[Fact]:
    """The settings in the JSON object at `keys` of the file, flattened under dotted keys."""
    try:
        value: object = json.loads(strip_json_comments(text) if comments else text)
    except json.JSONDecodeError as error:
        yield unreadable(tool, path, error)
        return
    for key in keys:
        value = value.get(key) if isinstance(value, Mapping) else None
    if isinstance(value, Mapping):
        yield from settings(tool, path, flattened(value))


def key_value_settings(tool: str, path: str, text: str) -> Iterator[Setting]:
    """The `key = value` lines of a simple configuration file (gcovr.cfg, .lcovrc); `#` starts a comment."""
    for line in text.splitlines():
        key, equals, value = line.partition("=")
        if equals and not key.lstrip().startswith("#"):
            yield from settings(tool, path, ((key.strip(), value.strip()),))


def xml_root(tool: str, path: str, text: str) -> ElementTree.Element | Unknown:
    """The root element of an XML file, without namespaces; unknown when it does not parse."""
    try:
        root = ElementTree.fromstring(text)  # noqa: S314 - the project's own files, parsed without fetching anything
    except ElementTree.ParseError as error:
        return unreadable(tool, path, error)
    for element in root.iter():
        element.tag = element.tag.rpartition("}")[2]
    return root


def matched_settings(
    tool: str, path: str, text: str, found: Mapping[str, tuple[re.Pattern[str], object]]
) -> Iterator[Setting]:
    """Settings recognised in code by a pattern (key -> (pattern, value)); a value of None takes the first group."""
    for key, (regex, value) in found.items():
        for match in regex.finditer(text):
            yield from settings(tool, path, ((key, match[1] if value is None else value),), heuristic=True)


__all__ = [
    "SettingsReader",
    "built_in_settings_readers",
    "flattened",
    "ini_settings",
    "json_settings",
    "key_value_settings",
    "matched_settings",
    "plain",
    "settings",
    "settings_facts",
    "toml_settings",
    "unreadable",
    "xml_root",
]
