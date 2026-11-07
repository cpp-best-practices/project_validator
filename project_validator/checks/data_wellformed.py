"""Every JSON, TOML, YAML and XML file parses: real validation, since a broken data file is a bug."""

import json
import re
import tomllib
from collections import Counter
from collections.abc import Callable, Mapping
from fnmatch import fnmatchcase
from pathlib import PurePosixPath
from xml.parsers import expat

from project_validator import yaml_support
from project_validator.core import Context, Result, check
from project_validator.text import strip_json_comments

# Hidden directories that hold configuration worth parsing (CI, editors, dev containers).
CONFIGURATION_DIRECTORIES = frozenset({".github", ".gitlab", ".circleci", ".buildkite", ".devcontainer", ".vscode"})
# Files larger than this are not parsed, and are reported as skipped.
MAX_SIZE = 5 * 1024 * 1024
# JSON files that tools read with comments and trailing commas allowed.
JSON_WITH_COMMENTS = ("*.jsonc", "tsconfig*.json", "jsconfig.json", "devcontainer.json", ".vscode/*.json")


class _ParseError(Exception):
    def __init__(self, message: str, line: int | None = None, column: int | None = None) -> None:
        super().__init__(message)
        self.where = f":{line}:{column}" if line is not None and column is not None else ""


def _decoded(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise _ParseError(f"not UTF-8 ({error.reason} at byte {error.start})") from error


def _parse_json(data: bytes, *, comments: bool = False) -> None:
    text = _decoded(data)
    text = strip_json_comments(text) if comments else text
    try:
        json.loads(text)
    except json.JSONDecodeError as error:
        raise _ParseError(error.msg, error.lineno, error.colno) from error
    except RecursionError:
        _check_deep_json(text)  # nested deeper than Python's parser recurses (test data of JSON parsers)


_JSON_TOKEN = re.compile(
    r"""\s*(?:(?P<open>[\[{])|(?P<close>[\]}])|(?P<colon>:)|(?P<comma>,)"""
    r"""|(?P<value>"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"|true|false|null"""
    r"""|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?))"""
)


# An open container and what may come next in it: "value", "key", "colon", "comma or close" (or "value or close" and
# "key or close" right after it opens).
type _Stack = list[list[str]]


def _value(stack: _Stack, match: re.Match[str]) -> bool:
    """A value or an opening bracket: where a value (or, as a key, a string) may come."""
    expecting = (stack[-1][1] if stack else "value").removesuffix(" or close")
    if expecting not in ("value", "key") or (expecting == "key" and not str(match["value"] or "").startswith('"')):
        return False
    if stack:
        stack[-1][1] = "colon" if expecting == "key" else "comma or close"
    if match["open"]:
        stack.append([match["open"], "key or close" if match["open"] == "{" else "value or close"])
    return True


def _close(stack: _Stack, match: re.Match[str]) -> bool:
    if not stack or stack[-1][1] == "value" or stack[-1][1] in ("key", "colon"):
        return False
    return stack.pop()[0] == {"]": "[", "}": "{"}[match["close"]]


def _colon(stack: _Stack, _match: re.Match[str]) -> bool:
    if not stack or stack[-1][1] != "colon":
        return False
    stack[-1][1] = "value"
    return True


def _comma(stack: _Stack, _match: re.Match[str]) -> bool:
    if not stack or stack[-1][1] != "comma or close":
        return False
    stack[-1][1] = "key" if stack[-1][0] == "{" else "value"
    return True


_READ = {"open": _value, "value": _value, "close": _close, "colon": _colon, "comma": _comma}


def _check_deep_json(text: str) -> None:
    """Whether `text` is one JSON value, read without recursion: each container on a stack, with what may come next
    in it. An error is reported where the token that breaks it starts."""
    stack: _Stack = []
    position, done = 0, False
    while not done and (match := _JSON_TOKEN.match(text, position)) is not None:
        kind = match.lastgroup or ""
        position = match.start(kind)
        if not _READ[kind](stack, match):
            break
        position, done = match.end(), not stack and kind != "colon" and kind != "comma"
    if not done or text[position:].strip():
        line = text.count("\n", 0, position) + 1
        raise _ParseError("malformed JSON", line, position - text.rfind("\n", 0, position))


def _parse_toml(data: bytes) -> None:
    try:
        tomllib.loads(_decoded(data))
    except tomllib.TOMLDecodeError as error:
        raise _ParseError(error.msg, error.lineno, error.colno) from error


def _parse_yaml(data: bytes) -> None:
    try:
        yaml_support.check_documents(_decoded(data))
    except yaml_support.YamlError as error:
        raise _ParseError(str(error), error.line, error.column) from error


def _parse_xml(data: bytes) -> None:
    parser = expat.ParserCreate()
    # Never read external entities or an external DTD.
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    try:
        parser.Parse(data, True)
    except expat.ExpatError as error:
        raise _ParseError(expat.ErrorString(error.code), error.lineno, error.offset + 1) from error


type Parser = Callable[[bytes], None]

PARSERS: Mapping[str, tuple[str, Parser]] = {
    ".json": ("JSON", _parse_json),
    ".toml": ("TOML", _parse_toml),
    ".yaml": ("YAML", _parse_yaml),
    ".yml": ("YAML", _parse_yaml),
    ".xml": ("XML", _parse_xml),
    ".xsd": ("XML", _parse_xml),
    ".xsl": ("XML", _parse_xml),
    ".xslt": ("XML", _parse_xml),
}


def _parser(path: str) -> tuple[str, Parser] | None:
    """(the format of `path`, its parser), or None when it is not a data file."""
    if any(fnmatchcase(path, glob) or fnmatchcase(PurePosixPath(path).name, glob) for glob in JSON_WITH_COMMENTS):
        return "JSON", lambda data: _parse_json(data, comments=True)
    return PARSERS.get(PurePosixPath(path).suffix.lower())


def _problem(context: Context, path: str, parser: Parser) -> str | None:
    """Why `path` does not parse, or None when it does."""
    try:
        parser((context.project.root / path).read_bytes())
    except _ParseError as error:
        return f"{path}{error.where}: {error}"
    return None


def _files(count: int) -> str:
    return f"{count} data file{'s' * (count != 1)}"


@check(name="data-wellformed", description="Every JSON, TOML, YAML and XML file in the project parses")
def data_wellformed(context: Context) -> Result:
    project = context.project
    found = {path: parser for path in project.files(hidden=CONFIGURATION_DIRECTORIES) if (parser := _parser(path))}
    skipped = tuple(
        f"{path}: not parsed, larger than {MAX_SIZE >> 20} MiB" for path in found if project.size(path) > MAX_SIZE
    )
    files = {path: parser for path, parser in found.items() if project.size(path) <= MAX_SIZE}
    if problems := [problem for path, (_, parser) in files.items() if (problem := _problem(context, path, parser))]:
        verb = "does" if len(problems) == 1 else "do"
        return Result.failed(f"{_files(len(problems))} {verb} not parse", *problems, *skipped)
    if not files:
        return Result.passed("no JSON, TOML, YAML or XML files to parse", *skipped)
    formats = Counter(format_ for format_, _ in files.values())
    counts = ", ".join(f"{format_}: {count}" for format_, count in sorted(formats.items()))
    verb = "parses" if len(files) == 1 else "parse"
    return Result.passed(f"{_files(len(files))} {verb} ({counts})", *skipped)
