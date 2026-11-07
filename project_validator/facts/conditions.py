"""Conditions: the builds something applies to, as a multi-valued decision diagram.

A build is described by its value of each dimension (compiler, platform, configuration, language; see `DIMENSIONS`)
and by whether each requirement the build system cannot decide holds (`ENABLE_WARNINGS`, a compiler check). A
`Condition` is a set of builds, kept as a reduced, shared decision diagram over those variables: the dimensions first,
each with one branch per value, then the requirements, true or false. Two conditions are equal exactly when they hold
in the same builds, and negating, joining and intersecting them stays cheap however many branches a build file has.
`disjuncts` writes a condition out as the `Applies` facts hold.
"""

from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from itertools import groupby

from project_validator.build_configurations import BUILD_TYPE_KINDS

# The values each dimension can take; "other" stands for those a build system names but none of these is.
OTHER = "other"
COMPILERS = ("gcc", "clang", "appleclang", "msvc", "intel", OTHER)
PLATFORMS = ("linux", "macos", "windows", "emscripten", OTHER)
CONFIGURATIONS = (*BUILD_TYPE_KINDS, OTHER)
LANGUAGES = ("C", "C++", "CUDA", "Objective-C", "Objective-C++", "Fortran", "Assembly", OTHER)
DIMENSIONS: Mapping[str, tuple[str, ...]] = {
    "compilers": COMPILERS,
    "platforms": PLATFORMS,
    "configurations": CONFIGURATIONS,
    "languages": LANGUAGES,
}
NOT = "NOT "
# At most this many disjuncts are written out for one condition.
MOST_DISJUNCTS = 64

_FALSE, _TRUE = 0, 1
_DIMENSION_NAMES = tuple(DIMENSIONS)
_BOOLEAN = (False, True)


class _Diagram:
    """The shared nodes: each is (variable, children), one child per value of the variable, reduced and unique."""

    def __init__(self) -> None:
        self.nodes: list[tuple[int, tuple[int, ...]]] = [(-1, ()), (-1, ())]
        self.unique: dict[tuple[int, tuple[int, ...]], int] = {}
        self.requirements: dict[str, int] = {}
        self.names: list[str] = []
        self.memo: dict[tuple[str, int, int], int] = {}

    def values(self, variable: int) -> tuple[object, ...]:
        return DIMENSIONS[_DIMENSION_NAMES[variable]] if variable < len(_DIMENSION_NAMES) else _BOOLEAN

    def node(self, variable: int, children: tuple[int, ...]) -> int:
        if all(child == children[0] for child in children):
            return children[0]
        key = (variable, children)
        if key not in self.unique:
            self.unique[key] = len(self.nodes)
            self.nodes.append(key)
        return self.unique[key]

    def requirement(self, name: str) -> int:
        if name not in self.requirements:
            self.requirements[name] = len(_DIMENSION_NAMES) + len(self.names)
            self.names.append(name)
        return self.requirements[name]

    def variable(self, node: int) -> int:
        return self.nodes[node][0] if node > _TRUE else 1 << 30

    def child(self, node: int, variable: int, index: int) -> int:
        """`node`'s branch for the `index`th value of `variable` (itself, when it does not branch on `variable`)."""
        found, children = self.nodes[node]
        return children[index] if found == variable else node

    def apply(self, operation: str, first: int, second: int) -> int:
        terminal = _terminal(operation, first, second)
        if terminal is not None:
            return terminal
        key = (operation, *sorted((first, second)))
        if key not in self.memo:
            variable = min(self.variable(first), self.variable(second))
            children = tuple(
                self.apply(operation, self.child(first, variable, index), self.child(second, variable, index))
                for index in range(len(self.values(variable)))
            )
            self.memo[key] = self.node(variable, children)  # type: ignore[index]
        return self.memo[key]  # type: ignore[index]

    def negate(self, node: int) -> int:
        if node <= _TRUE:
            return _TRUE - node
        key = ("not", node, node)
        if key not in self.memo:
            variable, children = self.nodes[node]
            self.memo[key] = self.node(variable, tuple(self.negate(child) for child in children))
        return self.memo[key]


def _terminal(operation: str, first: int, second: int) -> int | None:
    """The result of `operation` when one side decides it alone."""
    absorbing, neutral = (_FALSE, _TRUE) if operation == "and" else (_TRUE, _FALSE)
    if absorbing in (first, second):
        return absorbing
    if first in (neutral, second):
        return second
    return first if second == neutral else None


_DIAGRAM = _Diagram()


@dataclass(frozen=True, slots=True)
class Condition:
    """A set of builds (see the module's documentation); true when it holds in some build."""

    node: int

    def __bool__(self) -> bool:
        return self.node != _FALSE


ALWAYS = Condition(_TRUE)
NEVER = Condition(_FALSE)


def both(*conditions: Condition) -> Condition:
    """The builds every one of `conditions` holds in."""
    node = _TRUE
    for condition in conditions:
        node = _DIAGRAM.apply("and", node, condition.node)
    return Condition(node)


def either(*conditions: Condition) -> Condition:
    """The builds one of `conditions` holds in."""
    node = _FALSE
    for condition in conditions:
        node = _DIAGRAM.apply("or", node, condition.node)
    return Condition(node)


def negated(condition: Condition) -> Condition:
    """The builds `condition` does not hold in."""
    return Condition(_DIAGRAM.negate(condition.node))


def only(dimension: str, values: Iterable[str]) -> Condition:
    """The builds whose `dimension` takes one of `values`."""
    allowed = frozenset(values)
    variable = _DIMENSION_NAMES.index(dimension)
    return Condition(_DIAGRAM.node(variable, tuple(int(value in allowed) for value in DIMENSIONS[dimension])))


def requiring(requirement: str) -> Condition:
    """The builds in which `requirement`, a condition the build system cannot decide, holds."""
    return Condition(_DIAGRAM.node(_DIAGRAM.requirement(requirement), (_FALSE, _TRUE)))


type Path = tuple[tuple[str, frozenset[str]], ...]
"""A path to the builds a condition holds in: the values allowed of each dimension, and the requirements that hold
(`"X"`) or do not (`"NOT X"`), written as dimension "requires"."""


def _branches(node: int) -> Iterator[tuple[tuple[str, frozenset[str]], int]]:
    """Each distinct branch of `node`: what it allows (a dimension's values, or a requirement), and where it leads."""
    variable, children = _DIAGRAM.nodes[node]
    if variable < len(_DIMENSION_NAMES):
        dimension = _DIMENSION_NAMES[variable]
        values = DIMENSIONS[dimension]
        ordered = sorted(range(len(children)), key=children.__getitem__)
        for child, indexes in groupby(ordered, key=children.__getitem__):
            yield (dimension, frozenset(values[index] for index in indexes)), child
        return
    name = _DIAGRAM.names[variable - len(_DIMENSION_NAMES)]
    yield ("requires", frozenset({f"{NOT}{name}"})), children[0]
    yield ("requires", frozenset({name})), children[1]


def paths(condition: Condition) -> list[Path]:
    """The paths to the builds `condition` holds in, at most `MOST_DISJUNCTS` of them."""
    found: list[Path] = []
    pending: list[tuple[int, Path]] = [(condition.node, ())]
    while pending and len(found) < MOST_DISJUNCTS:
        node, path = pending.pop()
        if node == _TRUE:
            found.append(path)
        elif node != _FALSE:
            pending += ((child, (*path, step)) for step, child in _branches(node))
    return found


@dataclass(frozen=True, slots=True)
class Dimension:
    """How a build system names the values of a dimension (CMake's `GNU`, Meson's `gcc`): by identifiers, each
    known one standing for one value or several (Meson's `clang` is Clang or Apple Clang); any other identifier, such
    as those in `others`, stands for OTHER."""

    name: str
    identifiers: Mapping[str, str | tuple[str, ...]]
    others: tuple[str, ...] = ()
    case_sensitive: bool = True

    def named(self, test: Callable[[str], bool]) -> Condition:
        """The builds whose identifier passes `test`."""
        values = [
            value for identifier, found in self.identifiers.items() if test(identifier) for value in _values(found)
        ]
        return only(self.name, [*values, *([OTHER] if any(test(other) for other in self.others) else [])])

    def _same(self, known: str, identifier: str) -> bool:
        return known == identifier if self.case_sensitive else known.lower() == identifier.lower()

    def equal_to(self, identifier: str) -> Condition:
        if not any(self._same(known, identifier) for known in self.identifiers):
            return only(self.name, [OTHER])
        return self.named(lambda known: self._same(known, identifier))

    def listed(self, identifiers: Iterable[str]) -> Condition:
        return either(*(self.equal_to(identifier) for identifier in identifiers))


def _values(found: str | tuple[str, ...]) -> tuple[str, ...]:
    return (found,) if isinstance(found, str) else found


__all__ = [
    "ALWAYS",
    "COMPILERS",
    "CONFIGURATIONS",
    "DIMENSIONS",
    "LANGUAGES",
    "NEVER",
    "NOT",
    "OTHER",
    "PLATFORMS",
    "Condition",
    "Dimension",
    "both",
    "either",
    "negated",
    "only",
    "paths",
    "requiring",
]
