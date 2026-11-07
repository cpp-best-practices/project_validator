"""What Meson's operators and the methods of its values give, in the builds each result is in (see `values`)."""

from collections.abc import Callable, Iterator

from project_validator.build_systems.meson import syntax
from project_validator.build_systems.meson.values import (
    FALSE,
    TRUE,
    Array,
    Choices,
    Compiler,
    Dictionary,
    Object,
    Symbol,
    Truth,
    Unknown,
    Value,
    array,
    single,
    strings,
    truth,
)
from project_validator.facts.conditions import ALWAYS, NEVER, Condition, Dimension, both, either, negated, requiring

_COMPILER_IDS: dict[str, str | tuple[str, ...]] = {"gcc": "gcc", "clang": ("clang", "appleclang"), "msvc": "msvc"}
_COMPILER_IDS |= dict.fromkeys(("intel", "intel-cl", "intel-llvm", "intel-llvm-cl"), "intel")
_COMPILER_IDS |= dict.fromkeys(("flang", "llvm-flang"), "flang")
COMPILER = Dimension("compilers", _COMPILER_IDS)
ARGUMENT_SYNTAX = Dimension("compilers", {"msvc": "msvc", "gcc": ("gcc", "clang", "appleclang", "intel", "flang")})
PLATFORM = Dimension(
    "platforms", {"linux": "linux", "darwin": "macos", "windows": "windows", "emscripten": "emscripten"}
)
_BUILD_TYPES = {"debug": "debug", "debugoptimized": "relwithdebinfo", "release": "release", "minsize": "minsizerel"}
BUILD_TYPE = Dimension("configurations", _BUILD_TYPES)


def written(expression: syntax.Expression) -> str:
    """An expression as it is written, near enough to name it."""
    match expression:
        case syntax.Literal(value=str() as text):
            return repr(text)
        case syntax.Literal(value=value):
            return str(value).lower()
        case syntax.Name(name=name):
            return name
        case syntax.Call(name=name, arguments=arguments, target=target):
            prefix = f"{written(target)}." if target is not None else ""
            return f"{prefix}{name}({', '.join(written(value) for value in arguments.positional)})"
        case syntax.Operation(left=left, right=right, otherwise=otherwise) if (
            right is not None and otherwise is not None
        ):
            return f"{written(left)} ? {written(right)} : {written(otherwise)}"
        case syntax.Operation(operator=operator, left=left, right=None):
            return f"{operator} {written(left)}"
        case syntax.Operation(operator=operator, left=left, right=right) if right is not None:
            return f"{written(left)} {operator} {written(right)}"
    return "..."


def text_of(value: Value) -> str:
    """A value as a setting or a command word holds it."""
    if isinstance(value, Truth):
        return "true" if value.when == ALWAYS else "false" if value.when == NEVER else "?"
    if isinstance(value, (Unknown, Symbol)):
        return value.text
    if isinstance(value, Array):
        return ",".join(text_of(item) for item, _ in value.items)
    if isinstance(value, Object) and value.kind == "program":
        return value.name
    return str(value)


def within(choices: Choices, when: Condition) -> Choices:
    """The values among `choices` in the builds `when` names."""
    return [(value, held) for value, other in choices if (held := both(other, when))]


def equal(left: Value, right: Value) -> Condition:
    """The builds in which two values are equal; a value that is not known compares as a requirement."""
    for symbol, other in ((left, right), (right, left)):
        if isinstance(symbol, Symbol) and isinstance(other, str):
            return symbol.dimension.equal_to(other)
    if isinstance(left, (Unknown, Symbol)) or isinstance(right, (Unknown, Symbol)):
        return requiring(f"{text_of(left)} == {text_of(right)}")
    if isinstance(left, Truth) or isinstance(right, Truth):
        first, second = truth(left), truth(right)
        return either(both(first, second), both(negated(first), negated(second)))
    return ALWAYS if left == right else NEVER


def added(left: Value, right: Value, when: Condition = ALWAYS) -> Value:
    """`left + right`, or what `left += right` adds in the builds `when` names: an array gains the elements."""
    if isinstance(left, Array):
        more = right.items if isinstance(right, Array) else ((right, ALWAYS),)
        return Array((*left.items, *((value, held) for value, other in more if (held := both(other, when)))))
    if isinstance(left, str) and isinstance(right, str):
        return left + right
    if isinstance(left, int) and isinstance(right, int) and not isinstance(left, bool):
        return left + right
    if isinstance(left, Dictionary) and isinstance(right, Dictionary):
        return Dictionary((*left.items, *right.items))
    return Unknown(f"{text_of(left)} + {text_of(right)}")


_ARITHMETIC: dict[str, Callable[[int, int], int | bool]] = {
    "-": int.__sub__,
    "*": int.__mul__,
    "/": int.__floordiv__,
    "%": int.__mod__,
    "<": int.__lt__,
    ">": int.__gt__,
    "<=": int.__le__,
    ">=": int.__ge__,
}


def binary(operator: str, left: Value, right: Value, text: str) -> Value:
    """A binary operation other than `and` and `or`."""
    if operator in ("==", "!="):
        found = equal(left, right)
        return Truth(found if operator == "==" else negated(found))
    if operator in ("in", "not in") and isinstance(right, Array):
        found = either(*(both(when, equal(left, item)) for item, when in right.items))
        return Truth(found if operator == "in" else negated(found))
    if operator == "+":
        return added(left, right)
    if isinstance(left, int) and isinstance(right, int) and operator in _ARITHMETIC and (right or operator not in "/%"):
        result = _ARITHMETIC[operator](left, right)
        return (TRUE if result else FALSE) if isinstance(result, bool) else result
    return Unknown(text)


def _known_element(container: Array, key: int) -> bool:
    """Whether the array is the same in every build, and has an element at `key`."""
    return all(when == ALWAYS for _, when in container.items) and -len(container.items) <= key < len(container.items)


def indexed(container: Value, key: Value, target: str) -> Value:
    """`container[key]`: an array's element (when the array is the same in every build), or a dictionary's value."""
    if isinstance(container, Array) and isinstance(key, int) and _known_element(container, key):
        return container.items[key][0]
    if isinstance(container, Dictionary) and isinstance(key, str):
        return next((value for name, value in container.items if name == key), Unknown(f"{target}[{key!r}]"))
    return Unknown(f"{target}[...]")


def pairs(value: Value) -> list[tuple[str, Value]]:
    """The options a `default_options` element sets: `'key=value'`, or a dictionary's."""
    if isinstance(value, Dictionary):
        return list(value.items)
    if isinstance(value, str) and "=" in value:
        key, setting = value.split("=", 1)
        return [(key, setting)]
    return []


def looped(value: Value, when: Condition) -> Iterator[tuple[tuple[Value, ...], Condition]]:
    """What `foreach` runs for: an array's elements, a dictionary's keys and values."""
    if isinstance(value, Dictionary):
        yield from (((key, item), when) for key, item in value.items)
    elif isinstance(value, Array):
        yield from (((item,), held) for item, other in value.items if (held := both(when, other)))
    else:
        yield (value,), when


# --- methods


def _accepts(arguments: list[str]) -> Condition:
    return requiring(f"the compiler accepts {' '.join(arguments)}")


def _supported(arguments: list[str], *, first: bool) -> Array:
    """`get_supported_arguments()`: each argument where the compiler accepts it; `first_supported_argument()`: the
    first such one."""
    found, earlier = [], ALWAYS
    for argument in arguments:
        accepted = _accepts([argument])
        found.append((argument, both(earlier, accepted) if first else accepted))
        earlier = both(earlier, negated(accepted))
    return array(found)


_CHECKS = frozenset({"has_argument", "has_multi_arguments", "has_link_argument", "has_multi_link_arguments"})
_SUPPORTED = frozenset({"get_supported_arguments", "get_supported_link_arguments", "first_supported_argument"})


def compiler_method(call: syntax.Call, arguments: list[str]) -> Value:
    """A method of `meson.get_compiler()`."""
    if call.name == "get_id":
        return Symbol(COMPILER, written(call))
    if call.name == "get_argument_syntax":
        return Symbol(ARGUMENT_SYNTAX, written(call))
    if call.name in _CHECKS:
        return Truth(_accepts(arguments))
    if call.name in _SUPPORTED:
        return _supported(arguments, first=call.name.startswith("first"))
    return Unknown(written(call))


def object_method(target: Object, call: syntax.Call, arguments: list[str]) -> Value:
    """A method of `meson`, of a machine, or of another object."""
    if target.kind == "meson" and call.name == "get_compiler" and arguments:
        return Compiler(arguments[0])
    if target.kind == "meson" and call.name == "is_subproject":
        return FALSE
    if target.kind == "machine" and call.name == "system":
        return Symbol(PLATFORM, written(call))
    return Unknown(written(call))


_TESTS: dict[str, Callable[[str, str], bool]] = {
    "startswith": str.startswith,
    "endswith": str.endswith,
    "contains": str.__contains__,
}
_SIMPLE: dict[str, Callable[[str], str]] = {"strip": str.strip, "to_lower": str.lower, "to_upper": str.upper}


def string_method(target: str, name: str, values: Choices) -> Value:
    """A method of a string."""
    arguments = [text for text, _ in strings(values)]
    if name == "format":
        found = target
        for index, (value, _) in enumerate(values):
            found = found.replace(f"@{index}@", text_of(value))
        return found
    if name in _TESTS and arguments:
        return TRUE if _TESTS[name](target, arguments[0]) else FALSE
    if name == "join":
        return target.join(arguments)
    if name in _SIMPLE:
        return _SIMPLE[name](target)
    if name == "split":
        return array((part, ALWAYS) for part in (target.split(arguments[0]) if arguments else target.split()))
    return Unknown(f"{target!r}.{name}()")


def method(target: Value, call: syntax.Call, values: Choices) -> Choices:
    """A method call on `target`, with the values of its positional arguments."""
    arguments = [text for text, _ in strings(values)]
    if isinstance(target, Compiler):
        return single(compiler_method(call, arguments))
    if isinstance(target, Object):
        return single(object_method(target, call, arguments))
    if isinstance(target, str):
        return single(string_method(target, call.name, values))
    if isinstance(target, Array) and call.name == "contains":
        return single(Truth(either(*(equal(item, text) for item, _ in target.items for text in arguments))))
    return single(Unknown(written(call)))


__all__ = [
    "ARGUMENT_SYNTAX",
    "BUILD_TYPE",
    "COMPILER",
    "PLATFORM",
    "added",
    "binary",
    "equal",
    "indexed",
    "looped",
    "method",
    "pairs",
    "text_of",
    "within",
    "written",
]
