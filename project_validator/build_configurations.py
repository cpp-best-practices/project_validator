"""Build configurations: the build types a CI job builds (each build system reads its own commands), and whether
sanitizers are on."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

BUILD_TYPE_KINDS = {"debug": "debug", "release": "release", "relwithdebinfo": "release", "minsizerel": "release"}

_DISABLED = r"(?!(?:off|false|no|none|0)\b)"
_SANITIZERS_ENABLED = re.compile(
    r"[-/]fsanitize[=-]\w"
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


def build_type_kinds(*values: str) -> frozenset[str]:
    """The kinds (`debug`, `release`) of the build types named by `values`; other build types count as neither."""
    return frozenset(BUILD_TYPE_KINDS[value.lower()] for value in values if value.lower() in BUILD_TYPE_KINDS)


def sanitizers_enabled(texts: Iterable[str]) -> bool:
    """Sanitizer flags (`-fsanitize=address`; Zig's `-fsanitize-thread`) or options, or cmake_template's packaging
    maintainer mode being off (which enables them)."""
    return any(_SANITIZERS_ENABLED.search(text) for text in texts)
