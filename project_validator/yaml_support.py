"""PyYAML support; it is required, but imported here so a missing install is reported cleanly instead of crashing."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from functools import cache
from types import ModuleType
from typing import Any

MISSING_MESSAGE = "PyYAML >= 6.0 is required (python3 -m pip install PyYAML, or the distro's python3-yaml package)"
NESTED_MESSAGE = "nested too deeply to read"


class YamlError(Exception):
    def __init__(self, message: str, line: int | None = None, column: int | None = None) -> None:
        super().__init__(message)
        # 1-based, when the parser knows where the problem is.
        self.line = line
        self.column = column


def _import_yaml() -> ModuleType | None:
    try:
        return importlib.import_module("yaml")
    except ImportError:
        return None


_yaml = _import_yaml()


def available() -> bool:
    return _yaml is not None


@dataclass(frozen=True, slots=True)
class Tagged:
    """A value with a local tag a tool defines (GitLab's `!reference [.setup, script]`, CloudFormation's `!Ref`)."""

    tag: str
    value: object


@cache
def _yaml_1_2() -> type:
    """The safe loader, reading a plain scalar that starts with `:` in a flow collection (`[:a, :b]`) as YAML 1.2
    does: `:` starts a scalar when what follows it is not a space or a flow indicator."""
    yaml: Any = _yaml

    class Loader(yaml.SafeLoader):  # type: ignore[misc]
        def colon_scalar(self) -> bool:
            """Whether the `:` here starts a plain scalar: in a flow collection, at the start of an entry (after `[`,
            `{` or `,`, so not the value of a JSON-like key, `{"a":1}`), and followed by a safe character."""
            if not self.flow_level or self.peek() != ":" or self.peek(1) in _NOT_PLAIN_SAFE:
                return False
            at = self.pointer - 1
            while at >= 0 and self.buffer[at] in " \t\r\n":
                at -= 1
            return at >= 0 and self.buffer[at] in "[{,"

        def check_value(self) -> bool:
            return not self.colon_scalar() and bool(super().check_value())

        def check_plain(self) -> bool:
            return self.colon_scalar() or bool(super().check_plain())

    return Loader


_NOT_PLAIN_SAFE = "\0 \t\r\n\x85\u2028\u2029,[]{}"


@cache
def _loader() -> type:
    """A safe loader that keeps values with local tags as `Tagged` instead of rejecting them."""
    yaml: Any = _yaml

    class Loader(_yaml_1_2()):  # type: ignore[misc]
        def construct_mapping(self, node: Any, deep: bool = False) -> dict[object, object]:
            """A mapping, where a key that is a tagged collection (`? !t {a: 1}`) is unhashable, as an untagged one
            is: a `Tagged` passes the loader's own check for a hashable key, and hashing its value fails."""
            try:
                return super().construct_mapping(node, deep=deep)  # type: ignore[no-any-return]
            except TypeError as error:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping", node.start_mark, "found unhashable key", node.start_mark
                ) from error

    def tagged(loader: Any, suffix: str, node: Any) -> Tagged:
        if isinstance(node, yaml.SequenceNode):
            return Tagged(tag=f"!{suffix}", value=loader.construct_sequence(node))
        if isinstance(node, yaml.MappingNode):
            return Tagged(tag=f"!{suffix}", value=loader.construct_mapping(node))
        return Tagged(tag=f"!{suffix}", value=loader.construct_scalar(node))

    Loader.add_multi_constructor("!", tagged)
    return Loader


def load(text: str) -> object:
    """The YAML document of `text`; a value with a local tag is a `Tagged`."""
    if _yaml is None:
        raise YamlError(MISSING_MESSAGE)
    try:
        return _yaml.load(text, Loader=_loader())
    except _yaml.YAMLError as error:
        raise YamlError(str(error).replace("\n", " ")) from error
    except RecursionError as error:
        raise YamlError(NESTED_MESSAGE) from error


def check_documents(text: str) -> None:
    """Parse every document of `text` without constructing values, so any tag (`!reference`, `!Ref`) is accepted:
    only whether the text is well-formed YAML is judged."""
    if _yaml is None:
        raise YamlError(MISSING_MESSAGE)
    try:
        for _ in _yaml.compose_all(text, Loader=_yaml_1_2()):
            pass
    except _yaml.MarkedYAMLError as error:
        mark = error.problem_mark or error.context_mark
        problem = error.problem or error.context or "invalid YAML"
        raise YamlError(problem, mark.line + 1, mark.column + 1) if mark else YamlError(problem) from error
    except _yaml.YAMLError as error:
        raise YamlError(str(error).replace("\n", " ")) from error
    except RecursionError as error:
        raise YamlError(NESTED_MESSAGE) from error
