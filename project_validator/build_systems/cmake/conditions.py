"""CMake conditions as the builds they hold in: `if()` arguments, and the boolean generator expressions.

What the build decides by its compiler, platform, configuration or language becomes the values it allows of that
dimension (`if(MSVC)`, `CMAKE_CXX_COMPILER_ID MATCHES "Clang"`, `$<CONFIG:Debug>`). Anything else the project does not
set itself (an option, a compiler check, `EXISTS`) is a requirement that is not understood, as written.
"""

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from itertools import product

from project_validator.build_systems.cmake.values import Item, Lookup, referenced
from project_validator.facts.conditions import ALWAYS, NEVER, OTHER, Condition, both, either, negated, only, requiring

# The identifiers CMake gives each dimension's values, and the value each is; any other identifier is OTHER.
COMPILER_IDS = {"GNU": "gcc", "Clang": "clang", "AppleClang": "appleclang", "MSVC": "msvc", "Intel": "intel"}
COMPILER_IDS |= {"IntelLLVM": "intel"}
_OTHER_COMPILER_IDS = ("ARMClang", "XLClang", "IBMClang", "NVHPC", "PGI", "XL", "SunPro", "Cray", "NVIDIA", "TI")
SYSTEM_NAMES = {"Linux": "linux", "Darwin": "macos", "Windows": "windows", "Emscripten": "emscripten"}
_OTHER_SYSTEM_NAMES = ("FreeBSD", "NetBSD", "OpenBSD", "Android", "iOS", "CYGWIN", "MSYS", "SunOS", "Generic")
BUILD_TYPES = {"Debug": "debug", "Release": "release", "RelWithDebInfo": "relwithdebinfo", "MinSizeRel": "minsizerel"}
LANGUAGE_NAMES = {"C": "C", "CXX": "C++", "CUDA": "CUDA", "OBJC": "Objective-C", "OBJCXX": "Objective-C++"}
LANGUAGE_NAMES |= {"Fortran": "Fortran", "ASM": "Assembly"}


@dataclass(frozen=True, slots=True)
class Dimension:
    """How CMake names the values of a dimension: by identifiers, known and other."""

    name: str
    identifiers: Mapping[str, str]
    others: tuple[str, ...] = ()
    case_sensitive: bool = True

    def named(self, test: Callable[[str], bool]) -> Condition:
        """The builds whose identifier passes `test`."""
        values = [value for identifier, value in self.identifiers.items() if test(identifier)]
        return only(self.name, [*values, *([OTHER] if any(test(other) for other in self.others) else [])])

    def equal_to(self, identifier: str) -> Condition:
        if self.case_sensitive:
            return self.named(lambda known: known == identifier)
        return self.named(lambda known: known.lower() == identifier.lower())

    def listed(self, identifiers: Iterable[str]) -> Condition:
        return either(*(self.equal_to(identifier) for identifier in identifiers))


COMPILER = Dimension("compilers", COMPILER_IDS, _OTHER_COMPILER_IDS)
PLATFORM = Dimension("platforms", SYSTEM_NAMES, _OTHER_SYSTEM_NAMES)
CONFIGURATION = Dimension("configurations", BUILD_TYPES, ("Coverage", "Profile"), case_sensitive=False)
LANGUAGE = Dimension("languages", LANGUAGE_NAMES, ("HIP", "ISPC", "Swift", "CSharp", "Java"))

# The variables that name a dimension's value, compared to identifiers.
DIMENSION_VARIABLES = {
    **{f"CMAKE_{language}_COMPILER_ID": COMPILER for language in LANGUAGE_NAMES},
    "CMAKE_SYSTEM_NAME": PLATFORM,
    "CMAKE_HOST_SYSTEM_NAME": PLATFORM,
    "CMAKE_BUILD_TYPE": CONFIGURATION,
}
_NOT_WINDOWS = ("linux", "macos", "emscripten", OTHER)
# The variables CMake sets true for some compilers or platforms.
FLAG_VARIABLES: Mapping[str, Condition] = {
    "MSVC": only("compilers", ["msvc"]),
    "CMAKE_COMPILER_IS_GNUCC": only("compilers", ["gcc"]),
    "CMAKE_COMPILER_IS_GNUCXX": only("compilers", ["gcc"]),
    "WIN32": only("platforms", ["windows"]),
    "APPLE": only("platforms", ["macos"]),
    "LINUX": only("platforms", ["linux"]),
    "UNIX": only("platforms", _NOT_WINDOWS),
    "EMSCRIPTEN": only("platforms", ["emscripten"]),
    "MINGW": both(only("platforms", ["windows"]), only("compilers", ["gcc"])),
    "CYGWIN": only("platforms", [OTHER]),
    "ANDROID": only("platforms", [OTHER]),
    "IOS": only("platforms", [OTHER]),
}
SYMBOLIC = frozenset(DIMENSION_VARIABLES) | frozenset(FLAG_VARIABLES)

_TRUE = frozenset({"1", "ON", "YES", "TRUE", "Y"})
_FALSE = frozenset({"0", "OFF", "NO", "FALSE", "N", "IGNORE", "NOTFOUND", ""})


def constant(text: str) -> bool | None:
    """Whether `text` is a true or false constant; None when it is neither."""
    upper = text.upper()
    if upper in _TRUE or re.fullmatch(r"[+-]?0*[1-9]\d*(?:\.\d*)?", text):
        return True
    if upper in _FALSE or upper.endswith("-NOTFOUND"):
        return False
    return None


@dataclass(frozen=True, slots=True)
class Operand:
    text: str
    quoted: bool = False


@dataclass(frozen=True, slots=True)
class Variables:
    """What conditions read: variable values, and how to describe a variable the project does not set (a compiler
    check's result is described by the check)."""

    value: Lookup
    describe: Callable[[str], str]
    # Whether configuring decides a variable (an option, a cache variable).
    configured: Callable[[str], bool]

    def defined(self, name: str) -> Condition:
        """The builds in which a variable is defined: where the project sets it, else where configuring does."""
        if self.configured(name):
            return ALWAYS
        items = self.value(name) or ()
        return either(*(item.when for item in items), requiring(f"DEFINED {name}"))


def _named(name: str, variables: Variables) -> Condition:
    """The builds in which a variable the project does not set is true."""
    if name in FLAG_VARIABLES:
        return FLAG_VARIABLES[name]
    return requiring(variables.describe(name))


def _value_truth(item: Item, variables: Variables) -> Condition:
    """`if(VARIABLE)` holds when its value is not a false constant."""
    if (name := referenced(item.text)) is not None:
        return both(item.when, _named(name, variables))
    return item.when if constant(item.text) is not False else NEVER


def truth(operand: Operand, variables: Variables) -> Condition:
    """The builds in which a lone operand is true: a constant, else (unquoted) the variable it names."""
    if (name := referenced(operand.text)) is not None:
        return _named(name, variables)
    if (known := constant(operand.text)) is not None:
        return ALWAYS if known else NEVER
    if operand.quoted:
        return NEVER
    items = variables.value(operand.text)
    if items is None:
        return _named(operand.text, variables)
    return either(*(_value_truth(item, variables) for item in items))


_UNARY = frozenset(
    {"EXISTS", "COMMAND", "DEFINED", "TARGET", "TEST", "POLICY", "IS_DIRECTORY", "IS_SYMLINK", "IS_ABSOLUTE"}
)
_BINARY = frozenset(
    {"EQUAL", "LESS", "LESS_EQUAL", "GREATER", "GREATER_EQUAL", "STREQUAL", "STRLESS", "STRLESS_EQUAL", "STRGREATER"}
    | {"STRGREATER_EQUAL", "VERSION_EQUAL", "VERSION_LESS", "VERSION_LESS_EQUAL", "VERSION_GREATER"}
    | {"VERSION_GREATER_EQUAL", "PATH_EQUAL", "MATCHES", "IN_LIST", "IS_NEWER_THAN"}
)


def _symbol(operand: Operand, variables: Variables) -> Dimension | None:
    """The dimension an operand names the value of (`CMAKE_CXX_COMPILER_ID`, `"${CMAKE_CXX_COMPILER_ID}"`)."""
    name = referenced(operand.text)
    if name is None and not operand.quoted and variables.value(operand.text) is None:
        name = operand.text
    return DIMENSION_VARIABLES.get(name or "")


def _values(operand: Operand, variables: Variables) -> list[Item]:
    """What an operand compares: the value of the variable an unquoted operand names, else its text."""
    items = None if operand.quoted else variables.value(operand.text)
    return list(items) if items is not None else [Item(operand.text)]


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", text))


_COMPARISONS: Mapping[str, Callable[[str, str], bool]] = {
    "STREQUAL": lambda left, right: left == right,
    "STRLESS": lambda left, right: left < right,
    "STRGREATER": lambda left, right: left > right,
    "VERSION_EQUAL": lambda left, right: _version(left) == _version(right),
    "VERSION_LESS": lambda left, right: _version(left) < _version(right),
    "VERSION_GREATER": lambda left, right: _version(left) > _version(right),
    "VERSION_LESS_EQUAL": lambda left, right: _version(left) <= _version(right),
    "VERSION_GREATER_EQUAL": lambda left, right: _version(left) >= _version(right),
    "MATCHES": lambda left, right: re.search(right, left) is not None,
}


def _compared(left: str, operator: str, right: str) -> bool | None:
    """The comparison of two known strings; None when it cannot be made (a number that is not one)."""
    try:
        if operator in _COMPARISONS:
            return _COMPARISONS[operator](left, right)
        if operator in ("EQUAL", "LESS", "GREATER", "LESS_EQUAL", "GREATER_EQUAL"):
            difference = int(left) - int(right)
            return {"EQUAL": difference == 0, "LESS": difference < 0, "GREATER": difference > 0}.get(
                operator, difference <= 0 if operator == "LESS_EQUAL" else difference >= 0
            )
    except ValueError, re.error:
        return None
    return None


def _symbolic(dimension: Dimension, operator: str, other: str) -> Condition | None:
    if operator == "STREQUAL":
        return dimension.equal_to(other)
    if operator == "MATCHES":
        try:
            pattern = re.compile(other)
        except re.error:
            return None
        return dimension.named(lambda identifier: pattern.search(identifier) is not None)
    return None


@dataclass(slots=True)
class _Parser:
    """`if()` arguments, by CMake's precedence: parentheses, unary tests, binary tests, NOT, AND, then OR."""

    operands: list[Operand]
    variables: Variables
    position: int = 0

    def _peek(self, offset: int = 0) -> Operand | None:
        index = self.position + offset
        return self.operands[index] if index < len(self.operands) else None

    def _keyword(self, *keywords: str) -> bool:
        operand = self._peek()
        if operand is not None and not operand.quoted and operand.text in keywords:
            self.position += 1
            return True
        return False

    def disjunction(self) -> Condition:
        found = self.conjunction()
        while self._keyword("OR"):
            found = either(found, self.conjunction())
        return found

    def conjunction(self) -> Condition:
        found = self.negation()
        while self._keyword("AND"):
            found = both(found, self.negation())
        return found

    def negation(self) -> Condition:
        return negated(self.negation()) if self._keyword("NOT") else self.test()

    def test(self) -> Condition:
        if self._keyword("("):
            found = self.disjunction()
            self._keyword(")")
            return found
        if (operand := self._peek()) is not None and not operand.quoted and operand.text in _UNARY:
            return self._unary(operand.text)
        return self._binary_or_truth()

    def _next(self) -> Operand:
        operand = self._peek() or Operand("")
        self.position += 1
        return operand

    def _unary(self, operator: str) -> Condition:
        self.position += 1
        operand = self._next()
        if operator == "DEFINED":
            return self.variables.defined(operand.text)
        return requiring(f"{operator} {operand.text}")

    def _binary_or_truth(self) -> Condition:
        left = self._next()
        following = self._peek()
        if following is None or following.quoted or following.text not in _BINARY:
            return truth(left, self.variables)
        self.position += 1
        return self._comparison(left, following.text, self._next())

    def _comparison(self, left: Operand, operator: str, right: Operand) -> Condition:
        written = f"{left.text} {operator} {right.text}"
        for symbol, other in ((left, right), (right, left)):
            if (dimension := _symbol(symbol, self.variables)) is not None:
                found = _symbolic(dimension, operator, other.text) if referenced(other.text) is None else None
                return requiring(written) if found is None else found
        pairs = product(_values(left, self.variables), _values(right, self.variables))
        return either(*(self._known(first, operator, second, written) for first, second in pairs))

    def _known(self, left: Item, operator: str, right: Item, written: str) -> Condition:
        when = both(left.when, right.when)
        if "${" in left.text or "${" in right.text:
            return both(when, requiring(written))
        result = _compared(left.text, operator, right.text)
        if result is None:
            return both(when, requiring(written))
        return when if result else NEVER


def condition(operands: list[Operand], variables: Variables) -> Condition:
    """The builds in which the `if()` (or `elseif()`, `while()`) with these arguments holds."""
    return _Parser(operands, variables).disjunction() if operands else NEVER


__all__ = [
    "COMPILER",
    "CONFIGURATION",
    "DIMENSION_VARIABLES",
    "FLAG_VARIABLES",
    "LANGUAGE",
    "PLATFORM",
    "SYMBOLIC",
    "Operand",
    "Variables",
    "condition",
    "constant",
    "truth",
]
