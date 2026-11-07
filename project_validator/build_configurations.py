"""Build configurations: the build types a CI job builds (each build system reads its own commands), and whether
sanitizers are on."""

import re
from collections.abc import Iterable
from dataclasses import dataclass

BUILD_TYPE_KINDS = {"debug": "debug", "release": "release", "relwithdebinfo": "release", "minsizerel": "release"}

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


def build_type_kinds(*values: str) -> frozenset[str]:
    """The kinds (`debug`, `release`) of the build types named by `values`; other build types count as neither."""
    return frozenset(BUILD_TYPE_KINDS[value.lower()] for value in values if value.lower() in BUILD_TYPE_KINDS)


def _value(word: str, following: str | None, name: str) -> str | None:
    if word == name:
        return following
    if word.startswith(f"{name}="):
        return word[len(name) + 1 :]
    if len(name) == 2 and word.startswith(name) and len(word) > 2:
        return word[2:]  # -Cvalue
    return None


def option_values(argv: tuple[str, ...], *names: str) -> list[str]:
    """The values of options `names` in `argv`, written `--name value`, `--name=value` or (one letter) `-Cvalue`."""
    following = [*argv[1:], None]
    return [
        value
        for word, after in zip(argv, following, strict=True)
        for name in names
        if (value := _value(word, after, name)) is not None
    ]


def sanitizers_enabled(texts: Iterable[str]) -> bool:
    """Sanitizer flags or options, or cmake_template's packaging maintainer mode being off (which enables them)."""
    return any(_SANITIZERS_ENABLED.search(text) for text in texts)
