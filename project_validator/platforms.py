"""Recognising operating systems, compilers and language toolchains in CI configuration text."""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from project_validator.text import matching_names, pattern

OPERATING_SYSTEMS = (
    pattern("linux", r"\b(ubuntu|linux|debian|fedora|alpine|centos|rocky|archlinux)\b"),
    pattern("windows", r"\b(windows|win32|win64|vs20\d\d)\b|visual studio"),
    pattern("macos", r"\b(macos|osx|mac-os)\b"),
)

COMPILERS = (
    pattern("gcc", r"\bgcc\b|\bg\+\+|\bmingw"),
    pattern("clang", r"\bclang(?![-_]?(tidy|format|d|-apply-replacements)\b)"),
    pattern("appleclang", r"\bapple-?clang\b"),
    pattern("msvc", r"\bmsvc|visual studio|\bvs20\d\d\b|\bcl\.exe\b|\bvcvars"),
    pattern("intel", r"\bicp?x\b|\bicp?c\b|intel-oneapi"),
)

RUNNER_DEFAULT_COMPILERS = {"linux": "gcc", "macos": "appleclang", "windows": "msvc"}


def detect_operating_systems(text: str) -> list[str]:
    return matching_names((text,), OPERATING_SYSTEMS)


def detect_compilers(text: str) -> list[str]:
    return matching_names((text,), COMPILERS)


@dataclass(frozen=True, slots=True, order=True, kw_only=True)
class Toolchain:
    """A language toolchain a CI job runs with, e.g. Python 3.14 or Rust nightly."""

    language: str
    version: str

    def __str__(self) -> str:
        return f"{self.language} {self.version}"


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolchainPatterns:
    versions: tuple[re.Pattern[str], ...]
    usage: re.Pattern[str]


DEFAULT_VERSION = "default"

_RUST_VERSION = r"(stable|beta|nightly|\d+\.\d+(?:\.\d+)?)"

# Language -> how a job names the versions it runs, and how a job that names none shows that it uses the language.
TOOLCHAINS = {
    "Python": ToolchainPatterns(
        versions=(
            re.compile(r"\bpython-version\W+(\d+(?:\.(?:\d+|x))*|pypy[\d.]*)"),
            re.compile(r"\bpython:(\d+(?:\.\d+)*)"),
            re.compile(r"\bpython(\d\.\d+)\b"),
        ),
        usage=re.compile(
            r"\bpython[\d.]*\s+(?:-|\S+\.py\b)|\bpip\d*\s+install\b|\bpytest\b|\btox\b|\bnox\b|\bsetup-python\b"
        ),
    ),
    "Rust": ToolchainPatterns(
        versions=(
            re.compile(rf"\brust-toolchain@{_RUST_VERSION}"),
            re.compile(rf"\btoolchain\W+{_RUST_VERSION}"),
            re.compile(rf"\bcargo\s+\+{_RUST_VERSION}"),
            re.compile(rf"\brustup\s+(?:default|toolchain\s+install|install)\s+{_RUST_VERSION}"),
            re.compile(r"\brust:(\d+\.\d+(?:\.\d+)?)"),
        ),
        usage=re.compile(r"\bcargo\b|\brustup\b|\brustc\b"),
    ),
}


def _named_versions(patterns: ToolchainPatterns, text: str) -> set[str]:
    return {match[1] for regex in patterns.versions for match in regex.finditer(text)}


def _language_toolchains(language: str, patterns: ToolchainPatterns, texts: tuple[str, ...]) -> set[Toolchain]:
    """The versions named by the first text that names any, or the runner's default when the language is only used."""
    versions = next((found for text in texts if (found := _named_versions(patterns, text))), set())
    if not versions and any(patterns.usage.search(text) for text in texts):
        versions = {DEFAULT_VERSION}
    return {Toolchain(language=language, version=version) for version in versions}


def detect_toolchains(*texts: str) -> frozenset[Toolchain]:
    return frozenset(
        toolchain
        for language, patterns in TOOLCHAINS.items()
        for toolchain in _language_toolchains(language, patterns, texts)
    )


def toolchain_versions(toolchains: Iterable[Toolchain], language: str) -> frozenset[str]:
    return frozenset(toolchain.version for toolchain in toolchains if toolchain.language == language)
