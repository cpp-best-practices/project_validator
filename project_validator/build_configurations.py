"""Recognising the CMake build types and sanitizer settings a CI job builds with."""

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


def detect_build_types(*texts: str) -> set[str]:
    values = (value for text in texts for match in _BUILD_TYPE_SOURCES.finditer(text) for value in match.groups())
    return {BUILD_TYPE_KINDS[value.lower()] for value in values if value and value.lower() in BUILD_TYPE_KINDS}


def sanitizers_enabled(texts: Iterable[str]) -> bool:
    """Sanitizer flags or options, or cmake_template's packaging maintainer mode being off (which enables them)."""
    return any(_SANITIZERS_ENABLED.search(text) for text in texts)


def detect_configurations(*texts: str) -> set[BuildConfiguration]:
    sanitizers = sanitizers_enabled(texts)
    return {
        BuildConfiguration(build_type=build_type, sanitizers=sanitizers) for build_type in detect_build_types(*texts)
    }
