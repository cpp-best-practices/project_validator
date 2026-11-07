"""Meson: C/C++ rules that depend on meson.build files, such as test() registration and the cpp_std option."""

import re
from pathlib import PurePosixPath

from project_validator.core import Context, Result
from project_validator.ecosystems.c_cpp.compiler_flags import WARNINGS_AS_ERRORS
from project_validator.ecosystems.model import C_FAMILY, BuildSystem
from project_validator.facts import Command, Facts, Setting, resolved
from project_validator.facts.arguments import option_values, program
from project_validator.facts.settings import SettingsReader, matched_settings
from project_validator.facts.testing import test_runner, tested
from project_validator.facts.tools import Definition, Run
from project_validator.rules import CompilerExtensions, WarningsAsErrors
from project_validator.text import Pattern

BUILD_FILE = "meson.build"

# Meson language name -> language, for the languages a project() declaration can enable.
MESON_LANGUAGES = {"c": "C", "cpp": "C++", "rust": "Rust"}

_MESON_PROJECT = re.compile(r"\bproject\s*\(([^)]*)")
_MESON_KEYWORD_ARGUMENT = re.compile(r"\b\w+\s*:")
_MESON_STRING = re.compile(r"'([^']*)'")
_MESON_COMMENT = re.compile(r"#[^\n]*")


def strip_comments(text: str) -> str:
    return _MESON_COMMENT.sub("", text)


def meson_declared_languages(text: str) -> frozenset[str]:
    """The languages after the name in `project('name', 'c', ['cpp'], ...)`, before any keyword argument."""
    declaration = _MESON_PROJECT.search(strip_comments(text))
    if declaration is None:
        return frozenset()
    positional = _MESON_KEYWORD_ARGUMENT.split(declaration.group(1), maxsplit=1)[0]
    declared = _MESON_STRING.findall(positional)[1:]
    return frozenset(MESON_LANGUAGES[name] for name in declared if name in MESON_LANGUAGES)


def meson_texts(context: Context) -> tuple[str, ...]:
    """Every meson.build of the project, without comments."""
    project = context.project
    paths = (path for path in project.files() if PurePosixPath(path).name == BUILD_FILE)
    return tuple(strip_comments(project.read_text(path)) for path in paths)


# --- tests

_REGISTERS_TESTS = re.compile(r"(?<![\w.])test\s*\(")
MESON_TEST_REGISTRATIONS = SettingsReader(
    name="Meson tests",
    files=(BUILD_FILE,),
    read=lambda path, text: matched_settings("Meson", path, strip_comments(text), {"test": (_REGISTERS_TESTS, True)}),
)


def _meson_test(command: Command, _facts: Facts) -> Run | None:
    """`meson test`, or ninja's `test` target in a Meson build directory."""
    argv = resolved(command)
    runs = argv[:2] == ("meson", "test") or (program(argv) == "ninja" and "test" in argv[1:])
    return tested() if runs else None


MESON_TESTS = test_runner(
    name="meson test",
    languages=C_FAMILY,
    how="meson test",
    runs=_meson_test,
    tests=Definition(
        found=lambda facts: (found.path for found in facts.where(Setting, tool="Meson", key="test")),
        default=False,
        from_test_units=True,
        describe=f"tests registered with Meson's test() in {BUILD_FILE}",
    ),
    reads=("Meson tests",),
)

# --- compiler extensions

# The `<lang>_std` option, in default_options or on the command line: c++20 is standard, gnu++20 and vc++20 are not.
_STANDARDS = {"C++": ("cpp_std", r"c\+\+\w+", r"(?:gnu|vc)\+\+\w+"), "C": ("c_std", r"c\w+", r"gnu\w+")}


def _std_option(option: str, value: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![\w-])(?:-D\s*)?{option}\s*=\s*{value}(?![\w+])")


def _checked_language(texts: tuple[str, ...]) -> str:
    declared = frozenset().union(*(meson_declared_languages(text) for text in texts))
    return "C" if "C" in declared and "C++" not in declared else "C++"


def _extensions_disabled(context: Context) -> Result:
    texts = (*meson_texts(context), *context.ci_texts)
    language = _checked_language(texts)
    option, standard, extended = _STANDARDS[language]
    fix = f"set default_options: ['{option}=c++20']" if language == "C++" else f"set default_options: ['{option}=c17']"
    if found := next((match[0] for text in texts if (match := _std_option(option, extended).search(text))), None):
        return Result.failed(f"{language} compiler extensions are enabled with {found}; {fix}")
    if found := next((match[0] for text in texts if (match := _std_option(option, standard).search(text))), None):
        return Result.passed(f"{language} compiler extensions are disabled with {found}")
    return Result.failed(f"{language} compiler extensions are never disabled (the compiler's default is used); {fix}")


# --- warnings as errors

WERROR = Pattern("werror=true", re.compile(r"(?<![\w-])(?:-D\s*)?werror\s*=\s*true\b|(?<![\w-])--werror\b"))


def _warning_texts(context: Context) -> tuple[str, ...]:
    return (*meson_texts(context), *context.ci_texts)


MESON_WARNINGS_AS_ERRORS = WarningsAsErrors(
    flags=(WERROR, *WARNINGS_AS_ERRORS.flags),
    texts=_warning_texts,
    searched="CI configuration or meson.build files",
    hint="set werror=true in default_options (or pass -Dwerror=true or --werror), at least as an option",
)

# Meson builds only the languages its project() declares.
# Meson's build types, by the kind of build each is; `plain` and `custom` say nothing about optimisation.
_MESON_BUILD_TYPES = {"debug": "debug", "debugoptimized": "release", "release": "release", "minsize": "release"}


def meson_build_types(command: Command) -> frozenset[str]:
    """The build type `meson setup` (or `meson configure`) chooses: `--buildtype` or `-Dbuildtype`; `meson setup`
    without one builds Meson's default, debug."""
    argv = resolved(command)
    if argv[:1] != ("meson",) or len(argv) < 2 or argv[1] not in ("setup", "configure"):
        return frozenset()
    chosen = [
        *option_values(argv, "--buildtype"),
        *(word.split("=", 1)[1] for word in argv if word.startswith("-Dbuildtype=")),
    ]
    chosen += [value.split("=", 1)[1] for value in option_values(argv, "-D") if value.startswith("buildtype=")]
    if not chosen and argv[1] == "setup":
        chosen = ["debug"]
    return frozenset(_MESON_BUILD_TYPES[value] for value in chosen if value in _MESON_BUILD_TYPES)


MESON = BuildSystem(
    name="Meson",
    files=(BUILD_FILE, "meson.options"),
    declared_languages=meson_declared_languages,
    build_types=meson_build_types,
    rules=(CompilerExtensions(judge=_extensions_disabled), MESON_WARNINGS_AS_ERRORS),
)
