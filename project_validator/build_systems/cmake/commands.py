"""What evaluated CMake commands set, as facts: compiler and linker options, build settings (variables and target
properties), CTest tests, the dependencies CPM and FetchContent declare, and the commands of custom targets."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from itertools import groupby, takewhile

from project_validator.build_systems.cmake.conditions import CONFIGURATION, LANGUAGE, constant
from project_validator.build_systems.cmake.evaluation import Frame
from project_validator.build_systems.cmake.generator_expressions import generated
from project_validator.build_systems.cmake.syntax import Invocation
from project_validator.build_systems.cmake.values import Item, Value, elements
from project_validator.facts import Fact, Origin, Setting
from project_validator.facts.build import BuildSetting, CompilerOption, disjuncts, implied_options
from project_validator.facts.conditions import ALWAYS, Condition, both
from project_validator.facts.dependencies import Declared
from project_validator.tools.toolchains import WARNINGS_AS_ERRORS_BY_COMPILER

BUILD_SYSTEM = "CMake"
_SCOPES = frozenset({"BEFORE", "INTERFACE", "PUBLIC", "PRIVATE"})
# The variables whose value is a string of compiler (or linker) flags, for one language and configuration.
_FLAGS = re.compile(
    r"CMAKE_(?:(?P<language>C|CXX|CUDA|OBJC|OBJCXX|Fortran)|(?P<linker>EXE|SHARED|MODULE)_LINKER)_FLAGS"
    r"(?:_(?P<configuration>DEBUG|RELEASE|RELWITHDEBINFO|MINSIZEREL))?"
)
_PROPERTY_OPTIONS = {"COMPILE_OPTIONS": "compile", "COMPILE_DEFINITIONS": "definition", "LINK_OPTIONS": "link"}
# The legacy properties that hold options as one command-line string, separated by spaces rather than semicolons.
_PROPERTY_FLAGS = {"COMPILE_FLAGS": "compile", "LINK_FLAGS": "link"}
_TEST_REGISTRATIONS = frozenset(
    {"add_test", "catch_discover_tests", "gtest_discover_tests", "gtest_add_tests", "doctest_discover_tests"}
    | {"boost_discover_tests"}
)
_ADD_TEST_KEYWORDS = frozenset({"CONFIGURATIONS", "WORKING_DIRECTORY", "COMMAND_EXPAND_LISTS"})
_DEPENDENCY_MANAGERS = {
    **dict.fromkeys(("cpmaddpackage", "cpmfindpackage", "cpmdeclarepackage"), "CPM"),
    **dict.fromkeys(("fetchcontent_declare", "fetchcontent_makeavailable", "fetchcontent_populate"), "FetchContent"),
}
_CUSTOM_TARGET_KEYWORDS = frozenset(
    {"COMMAND", "DEPENDS", "BYPRODUCTS", "WORKING_DIRECTORY", "COMMENT", "JOB_POOL", "JOB_SERVER_AWARE", "VERBATIM"}
    | {"USES_TERMINAL", "COMMAND_EXPAND_LISTS", "SOURCES"}
)
_EXECUTE_PROCESS_KEYWORDS = frozenset(
    {"COMMAND", "WORKING_DIRECTORY", "TIMEOUT", "RESULT_VARIABLE", "RESULTS_VARIABLE", "OUTPUT_VARIABLE"}
    | {"ERROR_VARIABLE", "INPUT_FILE", "OUTPUT_FILE", "ERROR_FILE", "OUTPUT_QUIET", "ERROR_QUIET", "COMMAND_ECHO"}
    | {"OUTPUT_STRIP_TRAILING_WHITESPACE", "ERROR_STRIP_TRAILING_WHITESPACE", "ENCODING", "ECHO_OUTPUT_VARIABLE"}
    | {"ECHO_ERROR_VARIABLE", "COMMAND_ERROR_IS_FATAL"}
)
_CUSTOM_COMMAND_KEYWORDS = _CUSTOM_TARGET_KEYWORDS | {
    "OUTPUT",
    "MAIN_DEPENDENCY",
    "IMPLICIT_DEPENDS",
    "DEPFILE",
    "APPEND",
    "DEPENDS_EXPLICIT_ONLY",
    "CODEGEN",
}


@dataclass(frozen=True, slots=True, kw_only=True)
class CustomTarget:
    """A custom target: the commands building it runs (each with where it is written), after its dependencies are
    built; `all` targets are built by every build. Its commands run in its source directory's build directory."""

    name: str
    all: bool
    commands: tuple[tuple[tuple[str, ...], Origin], ...]
    depends: tuple[str, ...]
    directory: str


def _definition(text: str) -> str:
    return text if text.startswith(("-D", "/D")) else f"-D{text}"


def _registered_test(words: list[str]) -> tuple[str, ...]:
    """What `add_test` registers: the test's name and its command's words (`NAME n COMMAND c args...`, or the old
    `add_test(n c args...)`); one without a name (empty, or `NAME` alone) registers nothing."""
    if words[:1] == ["NAME"]:
        name = words[1] if len(words) > 1 else ""
        command = words[words.index("COMMAND") + 1 :] if "COMMAND" in words else []
        stops = [at for at, word in enumerate(command) if word in _ADD_TEST_KEYWORDS]
        return (name, *command[: stops[0] if stops else len(command)])
    return tuple(words)


@dataclass(slots=True)
class Collector:
    """An `Observer` that records what each command sets."""

    facts: list[Fact] = field(default_factory=list)
    targets: dict[str, list[CustomTarget]] = field(default_factory=dict)
    dependencies: dict[str, list[str]] = field(default_factory=dict)
    # The variables a path was resolved into (`file(REAL_PATH)`, `get_filename_component(REALPATH)`), and the path as
    # written: a guard comparing the variable compares the path.
    resolved: dict[str, str] = field(default_factory=dict)
    # The commands `execute_process()` runs (a script run with `cmake -P` runs them).
    processes: list[tuple[tuple[str, ...], Origin]] = field(default_factory=list)

    def invoked(self, frame: Frame, invocation: Invocation, words: list[Value]) -> None:
        if (handler := _COMMANDS.get(invocation.name)) is not None:
            handler(self, frame, invocation, words)
        elif invocation.name in _TEST_REGISTRATIONS:
            self.ctest(frame, invocation, "registers", invocation.name)
            registered = _registered_test([word.text for word in words])
            if invocation.name == "add_test" and registered[:1] not in ((), ("",)):
                self.ctest(frame, invocation, "test", registered)
        elif invocation.name in _DEPENDENCY_MANAGERS:
            manager = _DEPENDENCY_MANAGERS[invocation.name]
            self.facts.append(Declared(origin=frame.origin(invocation), manager=manager))

    def finished(self, frame: Frame) -> None:
        """The CMake variables a directory set last, as settings; those that hold flags, as options too."""
        for name, items in frame.scope.variables.items():
            if items is None or not name.startswith("CMAKE_"):
                continue
            for item in items:
                if item.origin is not None:
                    self._variable(frame, name, item, item.origin)

    def _variable(self, frame: Frame, name: str, item: Item, origin: Origin) -> None:
        self.facts += variable_facts(origin, name, item.text, both(frame.condition, item.when))

    def _add(self, origin: Origin, builds: Condition, options: Iterable[str], kind: str, target: str | None) -> None:
        for option in options:
            for applies in disjuncts(builds):
                self.facts.append(
                    CompilerOption(
                        origin=origin,
                        build_system=BUILD_SYSTEM,
                        option=option,
                        linking=kind == "link",
                        applies=applies,
                        target=target,
                    )
                )

    def options(
        self, frame: Frame, invocation: Invocation, words: Iterable[Value], kind: str, target: str | None = None
    ) -> None:
        """Options as `add_compile_options()` takes them: each word one option (or, from a generator expression, a
        list of them), in the builds the word and the expression name."""
        for word in words:
            for value in generated(word.text):
                options = [_definition(option) if kind == "definition" else option for option in elements(value.text)]
                builds = both(frame.condition, word.when, value.when)
                self._add(word.origin or frame.origin(invocation), builds, options, kind, target)

    def ctest(self, frame: Frame, invocation: Invocation, key: str, value: object) -> None:
        self.facts.append(Setting(origin=frame.origin(invocation), tool="CTest", key=key, value=value))

    def guard(self, frame: Frame, invocation: Invocation, text: str) -> None:
        self.facts.append(Setting(origin=frame.origin(invocation), tool=BUILD_SYSTEM, key="guard", value=text))

    def setting(
        self,
        frame: Frame,
        invocation: Invocation,
        name: str,
        value: Value,
        target: str | None,
        *,
        default: bool = False,
    ) -> None:
        self.facts += warnings_as_errors(
            frame.origin(invocation), name, value.text, both(frame.condition, value.when), target
        )
        for applies in disjuncts(both(frame.condition, value.when)):
            origin = frame.origin(invocation)
            self.facts.append(
                BuildSetting(
                    origin=origin,
                    build_system=BUILD_SYSTEM,
                    name=name,
                    value=value.text,
                    applies=applies,
                    target=target,
                    default=default,
                )
            )


def variable_facts(origin: Origin, name: str, value: str, builds: Condition) -> Iterator[Fact]:
    """A CMake variable's value, in `builds`, as a setting; the flags of one that holds flags, as options too."""
    for applies in disjuncts(builds):
        yield BuildSetting(origin=origin, build_system=BUILD_SYSTEM, name=name, value=value, applies=applies)
    yield from warnings_as_errors(origin, name, value, builds)
    if flags := _FLAGS.fullmatch(name):
        kind = "link" if flags["linker"] else "compile"
        for applies in disjuncts(both(builds, _flags_builds(flags))):
            for option in value.split():
                yield CompilerOption(
                    origin=origin, build_system=BUILD_SYSTEM, option=option, applies=applies, linking=kind == "link"
                )


_WARNINGS_AS_ERRORS = frozenset({"CMAKE_COMPILE_WARNING_AS_ERROR", "COMPILE_WARNING_AS_ERROR"})


def warnings_as_errors(
    origin: Origin, name: str, value: str, builds: Condition, target: str | None = None
) -> Iterator[CompilerOption]:
    """`CMAKE_COMPILE_WARNING_AS_ERROR` (or a target's `COMPILE_WARNING_AS_ERROR`) on passes each compiler its flag."""
    if name in _WARNINGS_AS_ERRORS and constant(value):
        yield from implied_options(origin, BUILD_SYSTEM, WARNINGS_AS_ERRORS_BY_COMPILER, builds, target)


def _flags_builds(flags: re.Match[str]) -> Condition:
    language = LANGUAGE.equal_to(flags["language"]) if flags["language"] else ALWAYS
    configuration = CONFIGURATION.equal_to(flags["configuration"]) if flags["configuration"] else ALWAYS
    return both(language, configuration)


def _global_options(kind: str) -> Callable[[Collector, Frame, Invocation, list[Value]], None]:
    def record(collector: Collector, frame: Frame, invocation: Invocation, words: list[Value]) -> None:
        collector.options(frame, invocation, words, kind)

    return record


def _target_options(kind: str) -> Callable[[Collector, Frame, Invocation, list[Value]], None]:
    def record(collector: Collector, frame: Frame, invocation: Invocation, words: list[Value]) -> None:
        if words:
            options = (word for word in words[1:] if word.text not in _SCOPES)
            collector.options(frame, invocation, options, kind, words[0].text)

    return record


def _link_libraries(collector: Collector, frame: Frame, invocation: Invocation, words: list[Value]) -> None:
    """Flags among the libraries a target links (`-fsanitize=address`) are link options."""
    if words:
        flags = (word for word in words[1:] if word.text.startswith("-"))
        collector.options(frame, invocation, flags, "link", words[0].text)


def _add_definitions(collector: Collector, frame: Frame, invocation: Invocation, words: list[Value]) -> None:
    flags = (Value(flag, word.when, word.origin) for word in words for flag in word.text.split())
    collector.options(frame, invocation, flags, "compile")


def _property(
    collector: Collector, frame: Frame, invocation: Invocation, target: str | None, name: str, values: list[Value]
) -> None:
    """A property that holds options sets those options; a target's other properties are settings, those of a
    directory or the whole build are not asked about."""
    if name in _PROPERTY_OPTIONS:
        collector.options(frame, invocation, values, _PROPERTY_OPTIONS[name], target)
    elif name in _PROPERTY_FLAGS:
        listed = [replace(value, text=";".join(value.text.split())) for value in values]
        collector.options(frame, invocation, listed, _PROPERTY_FLAGS[name], target)
    elif target is not None:
        for when, group in groupby(values, key=lambda value: value.when):
            collector.setting(frame, invocation, name, Value(";".join(value.text for value in group), when), target)


def _set_target_properties(collector: Collector, frame: Frame, invocation: Invocation, words: list[Value]) -> None:
    texts = [word.text for word in words]
    if "PROPERTIES" not in texts:
        return
    split = texts.index("PROPERTIES")
    pairs = _arguments(words[split + 1 :])
    for target in texts[:split]:
        for name, values in zip(pairs[::2], pairs[1::2], strict=False):
            _property(collector, frame, invocation, target, name[0].text, values)


def _arguments(words: list[Value]) -> list[list[Value]]:
    """`words` by the argument each is a value of: a value the argument takes in other builds (a variable set in both
    branches of an `if()`) follows the first, and is the same argument."""
    arguments: list[list[Value]] = []
    for word in words:
        if word.choice == 0 or not arguments:
            arguments.append([word])
        else:
            arguments[-1].append(word)
    return arguments


def _set_property(collector: Collector, frame: Frame, invocation: Invocation, words: list[Value]) -> None:
    """`set_property(TARGET t... PROPERTY name values...)`, or of a DIRECTORY (or GLOBAL), which every target in it
    has."""
    texts = [word.text for word in words]
    if "PROPERTY" not in texts or texts[0] not in ("TARGET", "DIRECTORY", "GLOBAL"):
        return
    split = texts.index("PROPERTY")
    if split + 1 >= len(words):
        return
    targets = (
        [text for text in texts[1:split] if text not in ("APPEND", "APPEND_STRING")] if texts[0] == "TARGET" else [None]
    )
    for target in targets:
        _property(collector, frame, invocation, target, texts[split + 1], words[split + 2 :])


def _option(collector: Collector, frame: Frame, invocation: Invocation, words: list[Value]) -> None:
    """An option's default: `option(NAME "help" ON)`, `cmake_dependent_option(NAME "help" ON ...)`; the condition a
    dependent option depends on is a guard."""
    arguments = _arguments(words)
    if len(arguments) >= 2:
        for value in arguments[2] if len(arguments) > 2 else [Value("OFF")]:
            collector.setting(frame, invocation, words[0].text, value, None, default=True)
    if invocation.name == "cmake_dependent_option" and len(arguments) >= 4:
        collector.guard(frame, invocation, arguments[3][0].text)


def _guard(collector: Collector, frame: Frame, invocation: Invocation, words: list[Value]) -> None:
    """What an `if()` (or `elseif()`) tests, as written: the evaluator decides where it holds; the text says what the
    project guards on (`PROJECT_IS_TOP_LEVEL`, a comparison of the source and binary directories). A variable a path
    was resolved into reads as the path."""
    texts = (collector.resolved.get(word.text.removeprefix("${").removesuffix("}"), word.text) for word in words)
    collector.guard(frame, invocation, " ".join(texts))


def _resolve(collector: Collector, _frame: Frame, invocation: Invocation, _words: list[Value]) -> None:
    """`file(REAL_PATH path var)` and `get_filename_component(var path REALPATH|ABSOLUTE)`: the path as written, before
    the evaluator expands it, is what `var` holds."""
    raw = [argument.text for argument in invocation.arguments]
    if invocation.name == "file" and raw[:1] == ["REAL_PATH"] and len(raw) >= 3:
        collector.resolved[raw[2]] = raw[1]
    elif invocation.name == "get_filename_component" and len(raw) >= 3 and raw[2] in ("REALPATH", "ABSOLUTE"):
        collector.resolved[raw[0]] = raw[1]


def _string(collector: Collector, frame: Frame, invocation: Invocation, _words: list[Value]) -> None:
    """`string(COMPARE EQUAL a b var)` computes a flag the project then guards on: it tests what an
    `if(a STREQUAL b)` would, so the comparison, as written, is a guard."""
    raw = [argument.text for argument in invocation.arguments]
    if raw[:2] == ["COMPARE", "EQUAL"] and len(raw) >= 5:
        collector.guard(frame, invocation, f"{raw[2]} STREQUAL {raw[3]}")


def _set(collector: Collector, frame: Frame, invocation: Invocation, words: list[Value]) -> None:
    """A cache variable's default: `set(NAME value CACHE type "help")`."""
    texts = [word.text for word in words]
    if "CACHE" in texts and texts.index("CACHE") >= 1:
        value = ";".join(texts[1 : texts.index("CACHE")])
        collector.setting(frame, invocation, texts[0], Value(value, words[0].when), None, default=True)


def _enable_testing(collector: Collector, frame: Frame, invocation: Invocation, _words: list[Value]) -> None:
    collector.ctest(frame, invocation, "enables", True)


def _include(collector: Collector, frame: Frame, invocation: Invocation, words: list[Value]) -> None:
    if not words:
        return
    if words[0].text == "CTest":
        _enable_testing(collector, frame, invocation, words)
    elif words[0].text.endswith("CPM.cmake"):
        collector.facts.append(Declared(origin=frame.origin(invocation), manager="CPM"))


def _commands(
    words: Iterable[Value], origin: Origin, keywords: frozenset[str] = _CUSTOM_TARGET_KEYWORDS
) -> Iterator[tuple[tuple[str, ...], Origin]]:
    """The commands of a custom target: the words after its name (and ALL), then after each COMMAND; of an argument
    whose value depends on the build, its first value."""
    current: list[str] | None = []
    for word in (word for word in words if word.choice == 0):
        if word.text in keywords:
            if current:
                yield tuple(current), origin
            current = [] if word.text == "COMMAND" else None
        elif current is not None:
            current.append(word.text)
    if current:
        yield tuple(current), origin


def _add_custom_target(collector: Collector, frame: Frame, invocation: Invocation, words: list[Value]) -> None:
    if not words:
        return
    texts = [word.text for word in words]
    built_by_all = texts[1:2] == ["ALL"]
    rest = words[2 if built_by_all else 1 :]
    depends = texts[texts.index("DEPENDS") + 1 :] if "DEPENDS" in texts else []
    target = CustomTarget(
        name=texts[0],
        all=built_by_all,
        commands=tuple(_commands(rest, frame.origin(invocation))),
        depends=tuple(name for name in depends if name not in _CUSTOM_TARGET_KEYWORDS),
        directory=frame.directory,
    )
    collector.targets.setdefault(target.name, []).append(target)


def _add_custom_command(collector: Collector, frame: Frame, invocation: Invocation, words: list[Value]) -> None:
    """`add_custom_command(OUTPUT files... COMMAND ...)`: a target depending on one of the files runs its commands
    first, so each file is a custom target of its own that builds by running them."""
    texts = [word.text for word in words]
    if texts[:1] != ["OUTPUT"]:
        return
    ends = [at for at, text in enumerate(texts[1:], 1) if text in _CUSTOM_COMMAND_KEYWORDS] or [len(texts)]
    depends = _following(texts, "DEPENDS")
    commands = tuple(_commands(words[ends[0] :], frame.origin(invocation), _CUSTOM_COMMAND_KEYWORDS))
    for output in texts[1 : ends[0]]:
        target = CustomTarget(name=output, all=False, commands=commands, depends=depends, directory=frame.directory)
        collector.targets.setdefault(output, []).append(target)


def _following(texts: list[str], keyword: str) -> tuple[str, ...]:
    """The words after `keyword`, up to the next keyword of `add_custom_command`."""
    rest = texts[texts.index(keyword) + 1 :] if keyword in texts else []
    return tuple(takewhile(lambda text: text not in _CUSTOM_COMMAND_KEYWORDS, rest))


def _execute_process(collector: Collector, frame: Frame, invocation: Invocation, words: list[Value]) -> None:
    collector.processes += _commands(words, frame.origin(invocation), _EXECUTE_PROCESS_KEYWORDS)


def _add_dependencies(collector: Collector, _frame: Frame, _invocation: Invocation, words: list[Value]) -> None:
    if words:
        collector.dependencies.setdefault(words[0].text, []).extend(word.text for word in words[1:])


_COMMANDS: Mapping[str, Callable[[Collector, Frame, Invocation, list[Value]], None]] = {
    "add_compile_options": _global_options("compile"),
    "add_compile_definitions": _global_options("definition"),
    "add_link_options": _global_options("link"),
    "add_definitions": _add_definitions,
    "target_compile_options": _target_options("compile"),
    "target_compile_definitions": _target_options("definition"),
    "target_link_options": _target_options("link"),
    "target_link_libraries": _link_libraries,
    "set_target_properties": _set_target_properties,
    "set_property": _set_property,
    "option": _option,
    "cmake_dependent_option": _option,
    "if": _guard,
    "elseif": _guard,
    "set": _set,
    "string": _string,
    "file": _resolve,
    "get_filename_component": _resolve,
    "enable_testing": _enable_testing,
    "include": _include,
    "add_custom_target": _add_custom_target,
    "add_custom_command": _add_custom_command,
    "execute_process": _execute_process,
    "add_dependencies": _add_dependencies,
}


__all__ = ["BUILD_SYSTEM", "Collector", "CustomTarget", "variable_facts"]
