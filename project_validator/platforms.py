"""Recognising operating systems, compilers and language toolchains in CI configuration text."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING

from project_validator.ecosystems import ToolchainPatterns, registered
from project_validator.facts import ActionStep
from project_validator.facts.jobs import Toolchain
from project_validator.text import matching_names, pattern

if TYPE_CHECKING:
    from project_validator.core import Project

OPERATING_SYSTEMS = (
    pattern("linux", r"\b(ubuntu|linux|debian|fedora|alpine|centos|rocky|archlinux)\b"),
    pattern("windows", r"\b(windows|win32|win64|vs20\d\d)\b|visual studio"),
    pattern("macos", r"\b(macos|osx|mac-os)\b"),
)

COMPILERS = (
    # Not a cross compiler's name (`arm-linux-gnueabihf-gcc`, a linker variable's value).
    # Nor the 32-bit libraries a clang job installs (`gcc-multilib`).
    # MSYS2's MINGW64, MINGW32 and UCRT64 environments build with gcc (its CLANG64 with clang).
    pattern("gcc", r"(?<![\w-])gcc\b(?!-multilib)|(?<![\w-])g\+\+(?!-multilib)|\bmingw|\bucrt64\b|\bgfortran\b"),
    # setup-cpp names clang `llvm` (`compiler: llvm-19.1.1`, `--compiler llvm`). Emscripten's emcc is clang.
    pattern(
        "clang",
        r"\bclang(?![-_]?(tidy|format|d|-apply-replacements)(?:\b|_))|\bllvm-\d|\bcompiler\W+llvm\b"
        r"|\bemsdk\b|\bemcmake\b|\bemcc\b|(?<![\w-])em\+\+",
    ),
    pattern("appleclang", r"\bapple-?clang\b"),
    pattern("msvc", r"\bmsvc|visual studio|\bvs20\d\d\b|\bcl\.exe\b|\bvcvars"),
    # fortran-lang/setup-fortran names Intel's compilers `intel` and `intel-classic`.
    pattern("intel", r"\bicp?x\b|\bicp?c\b|\bifx\b|\bifort\b|intel-oneapi|\bcompiler\W+intel\b"),
    pattern("flang", r"\b(?:llvm-)?flang(?:-new)?\b"),
)

RUNNER_DEFAULT_COMPILERS = {"linux": "gcc", "macos": "appleclang", "windows": "msvc"}
# The ecosystems whose jobs compile with the runner's default compiler when they name none.
COMPILING_ECOSYSTEMS = frozenset({"C", "C++", "Fortran"})


def detect_operating_systems(text: str) -> list[str]:
    return matching_names((text,), OPERATING_SYSTEMS)


def detect_compilers(text: str) -> list[str]:
    return matching_names((text,), COMPILERS)


DEFAULT_VERSION = "default"


def toolchains() -> dict[str, ToolchainPatterns]:
    """Language -> how a job names the versions it runs, and how a job that names none shows it uses the language."""
    return {ecosystem.toolchain.language: ecosystem.toolchain for ecosystem in registered() if ecosystem.toolchain}


def _named_versions(patterns: ToolchainPatterns, text: str) -> set[str]:
    versions = {match[1] for regex in patterns.versions for match in regex.finditer(text)}
    return versions | {label.format(match[1]) for regex, label in patterns.labelled for match in regex.finditer(text)}


def _step_versions(patterns: ToolchainPatterns, steps: Iterable[ActionStep]) -> set[str]:
    """The versions the setup actions' inputs name, read by the patterns' readers of each action; a reader may name
    several, one per line (setup-dotnet installs every version of a `dotnet-version: |` block)."""
    readers = dict(patterns.steps)
    found = (read(step.inputs) for step in steps if (read := readers.get(step.uses.partition("@")[0])) is not None)
    return {
        line.strip() for versions in found if versions is not None for line in versions.splitlines() if line.strip()
    }


def pinned_versions(project: Project) -> dict[str, str]:
    """Language -> the version the project's files pin for a job that names none (`rust-toolchain.toml`'s channel)."""
    pinned: dict[str, str] = {}
    for language, patterns in toolchains().items():
        for name, version in patterns.pinned_by:
            if project.exists(name) and (found := version.search(project.read_text(name))) is not None:
                pinned[language] = found[1]
                break
    return pinned


def _language_toolchains(
    language: str,
    patterns: ToolchainPatterns,
    texts: tuple[str, ...],
    commands: Commands,
    steps: Iterable[ActionStep] = (),
    pinned: str | None = None,
) -> set[Toolchain]:
    """The versions named by the first text that names any and by the setup actions' inputs, or, when the language
    is only used, the version the project pins, else the runner's default."""
    versions = next((found for text in texts if (found := _named_versions(patterns, text))), set())
    versions |= _step_versions(patterns, steps)
    if not versions and patterns.used_by(texts, commands):
        versions = {pinned or DEFAULT_VERSION}
    return {Toolchain(language=language, version=version) for version in versions}


# The commands a job runs, each its words.
type Commands = tuple[tuple[str, ...], ...]


def detect_ecosystems(texts: Iterable[str], commands: Commands) -> frozenset[str]:
    """The labels of the registered ecosystems a CI job with `texts` (its matrix values, its evidence) that runs
    `commands` builds with or runs."""
    texts = tuple(texts)
    return frozenset(ecosystem.label for ecosystem in registered() if ecosystem.used_by(texts, commands))


def detect_toolchains(
    texts: Iterable[str], commands: Commands, steps: Iterable[ActionStep] = (), pinned: Mapping[str, str] | None = None
) -> frozenset[Toolchain]:
    """The toolchains a CI job with `texts` that runs `commands` and uses the actions `steps` names, or uses without
    naming a version (then the version `pinned` names for the language, if any; see `pinned_versions`)."""
    texts, steps, pinned = tuple(texts), tuple(steps), pinned or {}
    return frozenset(
        toolchain
        for language, patterns in toolchains().items()
        for toolchain in _language_toolchains(language, patterns, texts, commands, steps, pinned.get(language))
    )
