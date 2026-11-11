"""Recognising operating systems, compilers and language toolchains in CI configuration text."""

from __future__ import annotations

from project_validator.ecosystems import ToolchainPatterns, registered
from project_validator.facts.jobs import Toolchain
from project_validator.text import matching_names, pattern

OPERATING_SYSTEMS = (
    pattern("linux", r"\b(ubuntu|linux|debian|fedora|alpine|centos|rocky|archlinux)\b"),
    pattern("windows", r"\b(windows|win32|win64|vs20\d\d)\b|visual studio"),
    pattern("macos", r"\b(macos|osx|mac-os)\b"),
)

COMPILERS = (
    pattern("gcc", r"\bgcc\b|\bg\+\+|\bmingw|\bgfortran\b"),
    # setup-cpp names clang `llvm` (`compiler: llvm-19.1.1`, `--compiler llvm`).
    pattern("clang", r"\bclang(?![-_]?(tidy|format|d|-apply-replacements)(?:\b|_))|\bllvm-\d|\bcompiler\W+llvm\b"),
    pattern("appleclang", r"\bapple-?clang\b"),
    pattern("msvc", r"\bmsvc|visual studio|\bvs20\d\d\b|\bcl\.exe\b|\bvcvars"),
    # fortran-lang/setup-fortran names Intel's compilers `intel` and `intel-classic`.
    pattern("intel", r"\bicp?x\b|\bicp?c\b|\bifx\b|\bifort\b|intel-oneapi|\bcompiler\W+intel\b"),
    pattern("flang", r"\b(?:llvm-)?flang(?:-new)?\b"),
)

RUNNER_DEFAULT_COMPILERS = {"linux": "gcc", "macos": "appleclang", "windows": "msvc"}


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


def _language_toolchains(language: str, patterns: ToolchainPatterns, texts: tuple[str, ...]) -> set[Toolchain]:
    """The versions named by the first text that names any, or the runner's default when the language is only used."""
    versions = next((found for text in texts if (found := _named_versions(patterns, text))), set())
    if not versions and any(patterns.usage.search(text) for text in texts):
        versions = {DEFAULT_VERSION}
    return {Toolchain(language=language, version=version) for version in versions}


def detect_ecosystems(*texts: str) -> frozenset[str]:
    """The labels of the registered ecosystems a CI job with `texts` builds with or runs."""
    return frozenset(ecosystem.label for ecosystem in registered() if any(map(ecosystem.used_by, texts)))


def detect_toolchains(*texts: str) -> frozenset[Toolchain]:
    return frozenset(
        toolchain
        for language, patterns in toolchains().items()
        for toolchain in _language_toolchains(language, patterns, texts)
    )
