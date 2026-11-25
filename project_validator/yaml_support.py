"""PyYAML support; it is required, but imported here so a missing install is reported cleanly instead of crashing."""

from __future__ import annotations

import importlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import cache
from types import ModuleType
from typing import Any

from project_validator.parsing import ParseError, Span

MISSING_MESSAGE = "PyYAML >= 6.0 is required (python3 -m pip install PyYAML, or the distro's python3-yaml package)"
NESTED_MESSAGE = "nested too deeply to read"


class YamlError(ParseError):
    pass


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
def _escape_safe() -> type:
    """The safe loader, where an escape past the last character (`"\\U99999999"`, which PyYAML hands to chr()) is a
    scanner error at its scalar, not the ValueError chr() raises (an OverflowError before Python 3.13)."""
    yaml: Any = _yaml

    class Loader(yaml.SafeLoader):  # type: ignore[misc]
        def scan_flow_scalar_non_spaces(self, double: bool, start_mark: Any) -> list[str]:
            try:
                return list(super().scan_flow_scalar_non_spaces(double, start_mark))
            except (ValueError, OverflowError) as error:
                problem = "found an escape that names no character"
                raise yaml.scanner.ScannerError("while scanning a quoted scalar", start_mark, problem) from error

    return Loader


@cache
def _yaml_1_2() -> type:
    """The safe loader (see `_escape_safe`), reading a plain scalar that starts with `:` in a flow collection (`[:a,
    :b]`) as YAML 1.2 does: `:` starts a scalar when what follows it is not a space or a flow indicator."""

    class Loader(_escape_safe()):  # type: ignore[misc]
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


def _position(error: Exception) -> tuple[int, int] | tuple[()]:
    """Where PyYAML says the error is (line and column, from 1): the problem's mark, else its context's."""
    mark = getattr(error, "problem_mark", None) or getattr(error, "context_mark", None)
    return () if mark is None else (mark.line + 1, mark.column + 1)


def load(text: str) -> object:
    """The YAML document of `text`; a value with a local tag is a `Tagged`."""
    if _yaml is None:
        raise YamlError(MISSING_MESSAGE)
    try:
        return _yaml.load(text, Loader=_loader())
    except _yaml.YAMLError as error:
        raise YamlError(str(error).replace("\n", " "), *_position(error)) from error
    except RecursionError as error:
        raise YamlError(NESTED_MESSAGE) from error


def load_pairs(text: str) -> object:
    """The YAML document of `text`, its top-level mapping as a list of (key, value) pairs in order, each key kept as
    often as it is written (Cirrus CI's repeated `task:`); a document that is no mapping is as `load` gives it."""
    if _yaml is None:
        raise YamlError(MISSING_MESSAGE)
    loader = _loader()(text)
    try:
        root = loader.get_single_node()
        if not isinstance(root, _yaml.MappingNode):
            return None if root is None else loader.construct_document(root)
        loader.flatten_mapping(root)
        return [
            (loader.construct_object(key, deep=True), loader.construct_object(value, deep=True))
            for key, value in root.value
        ]
    except _yaml.YAMLError as error:
        raise YamlError(str(error).replace("\n", " "), *_position(error)) from error
    except RecursionError as error:
        raise YamlError(NESTED_MESSAGE) from error
    finally:
        loader.dispose()


type Place = tuple[str | int, ...]
# At most this deep, and this many places, are recorded of one document.
_DEEPEST_PLACE = 64
_MOST_PLACES = 100_000


def places(text: str) -> Callable[[Place], Span | None]:
    """Where each place of the YAML document of `text` is (`("jobs", "test", "steps", 3, "run")`, as the readers name
    the place of what they find): a key from itself through its value, a sequence's item from its start to its end.
    A key a mapping merges in (`<<: *defaults`) is placed where it is written, unless the mapping has its own. A place
    the document does not have, or a document that does not parse, has no span."""
    found: dict[Place, Span] = {}
    if _yaml is not None:
        try:
            root = _yaml.compose(text, Loader=_yaml_1_2())
        except (_yaml.YAMLError, RecursionError):
            root = None
        pending: list[tuple[Place, Any]] = [((), root)] if root is not None else []
        while pending and len(found) < _MOST_PLACES:
            place, node = pending.pop()
            for at, start, child in _children(node, place) if len(place) < _DEEPEST_PLACE else ():
                if at not in found:
                    found[at] = Span(
                        start.line + 1, start.column + 1, child.end_mark.line + 1, child.end_mark.column + 1
                    )
                    pending.append((at, child))
    return found.get


def _children(node: Any, place: Place) -> Iterator[tuple[Place, Any, Any]]:
    """Each place under `node`, with where it starts and its node: a mapping's own keys before those it merges in."""
    yaml: Any = _yaml
    if isinstance(node, yaml.SequenceNode):
        yield from (((*place, index), item.start_mark, item) for index, item in enumerate(node.value))
    elif isinstance(node, yaml.MappingNode):
        for key, value in _pairs(node):
            if isinstance(key, yaml.ScalarNode):
                yield (*place, key.value), key.start_mark, value


def _pairs(node: Any) -> list[tuple[Any, Any]]:
    """A mapping's (key, value) nodes: its own, then those of the mappings it merges in (`<<: *a`, `<<: [*a, *b]`)."""
    yaml: Any = _yaml
    merged = [pair for pair in node.value if isinstance(pair[0], yaml.ScalarNode) and pair[0].value == "<<"]
    sources = [value.value if isinstance(value, yaml.SequenceNode) else [value] for _, value in merged]
    mappings = [source for found in sources for source in found if isinstance(source, yaml.MappingNode)]
    return [
        *(pair for pair in node.value if pair not in merged),
        *(pair for source in mappings for pair in source.value),
    ]


def check_documents(text: str) -> None:
    """Parse every document of `text` without constructing values, so any tag (`!reference`, `!Ref`) is accepted:
    only whether the text is well-formed YAML is judged."""
    if _yaml is None:
        raise YamlError(MISSING_MESSAGE)
    try:
        for _ in _yaml.compose_all(text, Loader=_yaml_1_2()):
            pass
    except _yaml.MarkedYAMLError as error:
        raise YamlError(error.problem or error.context or "invalid YAML", *_position(error)) from error
    except _yaml.YAMLError as error:
        raise YamlError(str(error).replace("\n", " ")) from error
    except RecursionError as error:
        raise YamlError(NESTED_MESSAGE) from error
