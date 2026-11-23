"""Generator expressions (see cmake-generator-expressions(7)), which CMake evaluates per build: `$<$<CONFIG:Debug>:-O0>`
is `-O0` in Debug builds and nothing in the others. Each value an argument takes is found with the builds it is in,
by walking its tree (`project_validator.build_systems.cmake.generator_syntax`)."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping

from project_validator.build_systems.cmake.conditions import COMPILER, CONFIGURATION, LANGUAGE, PLATFORM, constant
from project_validator.build_systems.cmake.generator_syntax import START, Expression, Template, parse, split, written
from project_validator.build_systems.cmake.values import MOST_VALUES, Value, referenced
from project_validator.facts.conditions import ALWAYS, NEVER, Condition, both, either, negated, requiring


def _listed(evaluate: Callable[[list[str]], Condition]) -> Callable[[list[str]], Condition]:
    return lambda arguments: evaluate([name for argument in arguments for name in argument.split(",") if name])


def _lang_and_id(arguments: list[str]) -> Condition:
    language, *compilers = arguments
    return both(LANGUAGE.equal_to(language), COMPILER.listed(compilers))


def _bool(arguments: list[str]) -> Condition:
    text = ",".join(arguments)
    if (name := referenced(text)) is not None:
        return requiring(name)
    return NEVER if constant(text) is False else ALWAYS


def _streq(arguments: list[str]) -> Condition | None:
    if len(arguments) != 2 or any("${" in argument or START in argument for argument in arguments):
        return None
    return ALWAYS if arguments[0] == arguments[1] else NEVER


_COMPILER_ID = re.compile(r"(?:C|CXX|CUDA|OBJC|OBJCXX|Fortran|HIP|ASM\w*)_COMPILER_ID")
_TESTS: Mapping[str, Callable[[list[str]], Condition | None]] = {
    "CONFIG": _listed(CONFIGURATION.listed),
    "PLATFORM_ID": _listed(PLATFORM.listed),
    "COMPILE_LANGUAGE": _listed(LANGUAGE.listed),
    "LINK_LANGUAGE": _listed(LANGUAGE.listed),
    "COMPILE_LANG_AND_ID": _lang_and_id,
    "LINK_LANG_AND_ID": _lang_and_id,
    "BOOL": _bool,
    "STREQUAL": _streq,
}


def test(text: str) -> Condition:
    """The builds in which `text`, a boolean expression or a constant, is 1."""
    return _holds(parse(text))


def _holds(template: Template) -> Condition:
    """The builds in which a parsed boolean expression or constant is 1; one not understood is a requirement."""
    text = written(template)
    if (known := constant(text)) is not None:
        return ALWAYS if known else NEVER
    if len(template) != 1 or not isinstance(expression := template[0], Expression):
        return requiring(text)
    found = _test(written(expression.name), expression.rest or ())
    return requiring(text) if found is None else found


def _test(name: str, rest: Template) -> Condition | None:
    found: Condition | None
    arguments = [written(argument) for argument in split(rest, ",")]
    if name == "NOT":
        found = negated(_holds(rest))
    elif name in ("AND", "OR"):
        found = (both if name == "AND" else either)(*map(_holds, split(rest, ",")))
    elif _COMPILER_ID.fullmatch(name):
        found = _listed(COMPILER.listed)(arguments)
    else:
        found = _TESTS[name](arguments) if name in _TESTS else None
    return found


_PASSED = frozenset({"BUILD_INTERFACE", "BUILD_LOCAL_INTERFACE", "HOST_LINK", "DEVICE_LINK", "LINK_ONLY"})
_CHARACTERS = {"SEMICOLON": ";", "COMMA": ",", "ANGLE-R": ">", "INSTALL_INTERFACE": ""}


def _in(when: Condition, value: Template) -> list[Value]:
    """The values `value` takes in the builds `when` names."""
    return [Value(part.text, held) for part in _generated(value) if (held := both(when, part.when))]


def _conditional(when: Condition, value: Template) -> list[Value]:
    """`$<condition:value>`: the value where the condition holds, nothing elsewhere."""
    found = _in(when, value)
    return [*found, Value("", rest)] if (rest := negated(when)) else found


def _expression(expression: Expression) -> list[Value]:
    """The values one expression takes."""
    name, rest = written(expression.name), expression.rest or ()
    if name in ("0", "1") or (expression.name and isinstance(expression.name[0], Expression)):
        return _conditional(_holds(expression.name), rest)
    if name == "IF" and len(arguments := split(rest, ",")) == 3:
        when = _holds(arguments[0])
        return [*_in(when, arguments[1]), *_in(negated(when), arguments[2])]
    if name in _PASSED:
        return _generated(rest)
    if name in _CHARACTERS:
        return [Value(_CHARACTERS[name])]
    tested = (expression.rest is not None and name in _TESTS) or name in ("NOT", "AND", "OR")
    if tested or _COMPILER_ID.fullmatch(name):
        when = _holds((expression,))
        return [Value("1", when), Value("0", negated(when))]
    return [Value(expression.written)]


def _generated(template: Template) -> list[Value]:
    values = [Value("")]
    for part in template:
        found = _expression(part) if isinstance(part, Expression) else [Value(part)]
        values = [
            Value(value.text + more.text, when)
            for value in values
            for more in found
            if (when := both(value.when, more.when))
        ][:MOST_VALUES]
    return [value for value in values if value.when]


def generated(text: str) -> list[Value]:
    """The values `text` takes, with the builds it takes each in; expressions that are not understood (or are nested
    too deeply) are kept."""
    try:
        return _generated(parse(text))
    except RecursionError:
        return [Value(text)]


__all__ = ["generated", "test"]
