"""Meson: C/C++ rules that depend on meson.build files, such as test() registration and the cpp_std option."""

from project_validator.build_systems.meson import declared_languages
from project_validator.ecosystems.model import C_FAMILY, BuildSystem
from project_validator.facts import Command, Facts, Setting, resolved
from project_validator.facts.arguments import option_values, program
from project_validator.facts.testing import test_runner, tested
from project_validator.facts.tools import Definition, Run

BUILD_FILE = "meson.build"

# Meson language name -> language, for the languages a project() declaration can enable.
MESON_LANGUAGES = {"c": "C", "cpp": "C++", "rust": "Rust"}


def meson_declared_languages(text: str) -> frozenset[str]:
    """The languages a meson.build's `project()` declares, as `project_validator.build_systems.meson` reads them."""
    return frozenset(MESON_LANGUAGES[name] for name in declared_languages(text) if name in MESON_LANGUAGES)


# --- tests


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
    reads=("Meson",),
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
)
