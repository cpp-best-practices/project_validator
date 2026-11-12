"""Data: the formats a project's data and configuration are written in (JSON, TOML, YAML, XML). A format, not a
language: nothing about toolchains, tests or coverage applies; its files are judged for hygiene, first that every one
parses (`data-wellformed`). They are recognised in the configuration directories (`.github`, `.vscode`) too, where a
language's files are not, so a CI workflow is judged as the YAML it is.
"""

from __future__ import annotations

import json
import re
import tomllib
from fnmatch import fnmatchcase
from pathlib import PurePosixPath
from xml.parsers import expat

from project_validator import yaml_support
from project_validator.ecosystems.model import Ecosystem
from project_validator.facts.wellformed import ParseError, Parser
from project_validator.text import JsonSyntaxError, check_json, strip_json_comments

JSON, TOML, XML, YAML = "JSON", "TOML", "XML", "YAML"
DATA_FORMATS = frozenset({JSON, TOML, XML, YAML})

# JSON files that tools read with comments and trailing commas allowed.
JSON_WITH_COMMENTS = ("*.jsonc", "tsconfig*.json", "jsconfig.json", "devcontainer.json", ".vscode/*.json")


def _decoded(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ParseError(f"not UTF-8 ({error.reason} at byte {error.start})") from error


def _allows_comments(path: str) -> bool:
    name = PurePosixPath(path).name
    return any(fnmatchcase(path, glob) or fnmatchcase(name, glob) for glob in JSON_WITH_COMMENTS)


def _check_deep_json(text: str) -> None:
    """JSON nested deeper than Python's parser recurses (a JSON parser's test data), read without recursion."""
    try:
        check_json(text)
    except JsonSyntaxError as error:
        raise ParseError(str(error), error.line, error.column) from error


def _parse_json(path: str, data: bytes) -> None:
    text = _decoded(data)
    text = strip_json_comments(text) if _allows_comments(path) else text
    try:
        json.loads(text)
    except json.JSONDecodeError as error:
        raise ParseError(error.msg, error.lineno, error.colno) from error
    except RecursionError:
        _check_deep_json(text)


# Where a TOML error is, as tomllib writes it into the message; Python 3.14 also gives `lineno` and `colno`.
_TOML_POSITION = re.compile(r" \(at line (\d+), column (\d+)\)$")


def _parse_toml(_path: str, data: bytes) -> None:
    try:
        tomllib.loads(_decoded(data))
    except tomllib.TOMLDecodeError as error:
        message, position = str(error), _TOML_POSITION.search(str(error))
        if position is None:
            raise ParseError(message) from error
        raise ParseError(message[: position.start()], int(position[1]), int(position[2])) from error


def _parse_yaml(_path: str, data: bytes) -> None:
    try:
        yaml_support.check_documents(_decoded(data))
    except yaml_support.YamlError as error:
        raise ParseError(str(error), error.line, error.column) from error


def _parse_xml(_path: str, data: bytes) -> None:
    parser = expat.ParserCreate()
    # Never read external entities or an external DTD.
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    try:
        parser.Parse(data, True)
    except expat.ExpatError as error:
        raise ParseError(expat.ErrorString(error.code), error.lineno, error.offset + 1) from error


JSON_PARSER = Parser(format=JSON, parse=_parse_json)
TOML_PARSER = Parser(format=TOML, parse=_parse_toml)
YAML_PARSER = Parser(format=YAML, parse=_parse_yaml)
XML_PARSER = Parser(format=XML, parse=_parse_xml)

DATA = Ecosystem(
    label="Data",
    kind="format",
    languages=DATA_FORMATS,
    source_suffixes={
        ".json": JSON,
        ".jsonc": JSON,
        ".toml": TOML,
        ".yaml": YAML,
        ".yml": YAML,
        ".xml": XML,
        ".xsd": XML,
        ".xsl": XML,
        ".xslt": XML,
    },
)
