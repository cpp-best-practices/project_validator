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
from project_validator.facts.wellformed import ParseError, Parser, decoded
from project_validator.limits import JSON_NESTING
from project_validator.text import check_json, strip_json_comments

JSON, TOML, XML, YAML = "JSON", "TOML", "XML", "YAML"
DATA_FORMATS = frozenset({JSON, TOML, XML, YAML})

# JSON files that tools read with comments and trailing commas allowed.
# JSON files whose tool reads them with comments and trailing commas (and documents that it does).
JSON_WITH_COMMENTS = (
    *("*.jsonc", "tsconfig*.json", "jsconfig.json", "devcontainer.json", ".vscode/*.json"),
    *("pyrightconfig.json", "turbo.json", ".luarc.json", "asv.conf.json", ".eslintrc.json", "biome.json", "deno.json"),
    # Nerdbank.GitVersioning's version file.
    "version.json",
)


def _allows_comments(path: str) -> bool:
    name = PurePosixPath(path).name
    return any(fnmatchcase(path, glob) or fnmatchcase(name, glob) for glob in JSON_WITH_COMMENTS)


_NESTING = re.compile(r'"(?:[^"\\]|\\.)*"|[\[{]|[\]}]')


def _deep(text: str) -> bool:
    """Whether `text` nests containers deeper than `JSON_NESTING` allows (strings skipped)."""
    if text.count("[") + text.count("{") <= JSON_NESTING.most:
        return False
    depth = 0
    for token in _NESTING.finditer(text):
        depth += {"[": 1, "{": 1, "]": -1, "}": -1}.get(token[0], 0)
        if not JSON_NESTING.allows(depth):
            return True
    return False


def _parse_json(path: str, data: bytes) -> None:
    text = decoded(data)
    text = strip_json_comments(text) if _allows_comments(path) else text
    if _deep(text):
        check_json(text)
        return
    try:
        json.loads(text)
    except json.JSONDecodeError as error:
        raise ParseError(error.msg, error.lineno, error.colno) from error
    except RecursionError:
        check_json(text)


# Where a TOML error is, as tomllib writes it into the message; Python 3.14 also gives `lineno` and `colno`.
_TOML_POSITION = re.compile(r" \(at line (\d+), column (\d+)\)$")


def _parse_toml(_path: str, data: bytes) -> None:
    try:
        tomllib.loads(decoded(data))
    except tomllib.TOMLDecodeError as error:
        message, position = str(error), _TOML_POSITION.search(str(error))
        if position is None:
            raise ParseError(message) from error
        raise ParseError(message[: position.start()], int(position[1]), int(position[2])) from error


def _parse_yaml(_path: str, data: bytes) -> None:
    yaml_support.check_documents(decoded(data))


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
    links={
        "JSON": "https://www.json.org/",
        "TOML": "https://toml.io/",
        "XML": "https://www.w3.org/XML/",
        "YAML": "https://yaml.org/",
    },
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
        ".rng": XML,
        ".sch": XML,
        ".nvdl": XML,
        ".xspec": XML,
    },
)
