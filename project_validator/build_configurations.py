"""Recognising the CMake build types, Cargo profiles and sanitizer settings a CI job builds with."""

import re
from collections.abc import Iterable
from dataclasses import dataclass

BUILD_TYPE_KINDS = {"debug": "debug", "release": "release", "relwithdebinfo": "release", "minsizerel": "release"}

_VALUE = r"""["']?\s*[=:]\s*["']?(\w+)"""
_BUILD_TYPE_SOURCES = re.compile(
    rf"(?:\b|_)build[_-]?type(?::string)?{_VALUE}"
    r"""|--config(?:\s+|=)["']?(\w+)"""
    r"""|\s(?-i:-C)\s+["']?(\w+)"""
    rf"|\bconfiguration{_VALUE}",
    re.IGNORECASE,
)

# A Cargo command up to the end of its shell command; the job text is JSON, so line breaks appear as `\n`.
_CARGO_COMMANDS = re.compile(r"\bcargo\s+(?:\+\S+\s+)?(?:build|test|run|nextest\s+run)\b([^\\\n\"&;|]*)")
_CARGO_RELEASE = re.compile(r"--release\b|--profile[=\s]+release\b")
_CARGO_OTHER_PROFILE = re.compile(r"--profile\b")

_DISABLED = r"(?!(?:off|false|no|none|0)\b)"
_SANITIZERS_ENABLED = re.compile(
    r"[-/]fsanitize=\w"
    rf"|sanitiz\w*(?::bool)?[\"']?\s*[=:]\s*[\"']?{_DISABLED}\w"
    r"""|packaging_maintainer_mode(?::bool)?["']?\s*[=:]\s*["']?(?:off|false|no|0)\b""",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True, order=True, kw_only=True)
class BuildConfiguration:
    build_type: str
    sanitizers: bool

    def __str__(self) -> str:
        build_type = self.build_type.capitalize()
        return f"{build_type} + sanitizers" if self.sanitizers else build_type


def _cargo_profile(arguments: str) -> str | None:
    if _CARGO_RELEASE.search(arguments):
        return "release"
    return None if _CARGO_OTHER_PROFILE.search(arguments) else "debug"


def _cargo_build_types(texts: Iterable[str]) -> set[str]:
    profiles = (_cargo_profile(match[1]) for text in texts for match in _CARGO_COMMANDS.finditer(text))
    return {profile for profile in profiles if profile is not None}


def detect_build_types(*texts: str) -> set[str]:
    values = (value for text in texts for match in _BUILD_TYPE_SOURCES.finditer(text) for value in match.groups())
    cmake = {BUILD_TYPE_KINDS[value.lower()] for value in values if value and value.lower() in BUILD_TYPE_KINDS}
    return cmake | _cargo_build_types(texts)


def sanitizers_enabled(texts: Iterable[str]) -> bool:
    """Sanitizer flags or options, or cmake_template's packaging maintainer mode being off (which enables them)."""
    return any(_SANITIZERS_ENABLED.search(text) for text in texts)


def detect_configurations(*texts: str) -> set[BuildConfiguration]:
    sanitizers = sanitizers_enabled(texts)
    return {
        BuildConfiguration(build_type=build_type, sanitizers=sanitizers) for build_type in detect_build_types(*texts)
    }
