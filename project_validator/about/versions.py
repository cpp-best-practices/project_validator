"""Versions: the versions each language declares beside those CI tests it with (upstream #412)."""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator

from project_validator.about.detail import Detail, and_more, in_product, own_code
from project_validator.facts import Facts
from project_validator.facts.axes import ToolchainAxis, axis_of
from project_validator.facts.versions import DeclaredVersion, declared_versions

_NUMBER = re.compile(r"v?\d+(?:\.\d+)*")
# The oldest version a declaration supports, when it names one first: `>=3.10`, `^18`, `~=3.9`, `1.70`, `node >=18`.
_OLDEST = re.compile(r"(?:[a-z]+\s+)?(?:>=|\^|~=?|==)?\s*v?(?P<version>\d+(?:\.\d+)*)", re.IGNORECASE)


def _version_key(version: str) -> tuple[tuple[int, str], ...]:
    """Versions in their order (3.9 before 3.10), the parts that are not numbers by their text."""
    return tuple((int(part), "") if part.isdigit() else (-1, part) for part in re.split(r"[.\s-]+", version))


def _oldest(declared: Iterable[DeclaredVersion]) -> str | None:
    """The oldest version the project supports, from the first declaration that names one."""
    found = (_OLDEST.match(version.version) for version in declared if not version.pinned)
    return next((match["version"] for match in found if match), None)


def _same_line(one: str, other: str) -> bool:
    """Whether two versions are releases of one line: their first two parts agree (Go 1.22.0 and 1.22), or as many as
    the shorter has (Node.js 24 and 24.18.0)."""
    parts, others = one.split("."), other.split(".")
    shared = min(len(parts), len(others), 2)
    return parts[:shared] == others[:shared]


def _untested(oldest: str | None, tested: Iterable[str]) -> str | None:
    """The oldest version supported when CI tests no release of its line; None when that cannot be told: nothing is
    tested, or a version tested is not a number (`3.x`, `stable`)."""
    tested = [version.removeprefix("v") for version in tested]
    if oldest is None or not tested or not all(_NUMBER.fullmatch(version) for version in tested):
        return None
    covered = any(_same_line(version, oldest) for version in tested)
    return None if covered else oldest


def _tested(languages: Iterable[str], axis: ToolchainAxis, facts: Facts) -> frozenset[str]:
    """The toolchains (versions, compilers) CI runs `languages` with."""
    from project_validator.questions.platforms import platform_answer

    found: set[str] = set()
    for language in languages:
        if answer := platform_answer(language, facts):
            found |= {toolchain for (_os, toolchain), _configurations in answer.platforms}
    return frozenset(found)


def _product_languages(facts: Facts) -> set[str]:
    """The languages the product is written in, not its tests' (fixtures in other languages) nor its formats; those
    of its own code when it has no product code (its only code is tests)."""
    own = own_code(facts)
    product = {str(source.language) for source in own if source.role == "product"}
    return product or {str(source.language) for source in own}


def _subjects(facts: Facts, declared: Iterable[DeclaredVersion]) -> dict[tuple[str, ...], ToolchainAxis | None]:
    """The languages shown together, with the axis CI varies them on: those that share an axis (C and C++, on their
    compilers) are one subject."""
    languages = sorted(_product_languages(facts) | {version.language for version in declared})
    by_axis: dict[ToolchainAxis | str, list[str]] = {}
    for language in languages:
        by_axis.setdefault(axis_of(language, facts) or language, []).append(language)
    return {tuple(found): key if isinstance(key, ToolchainAxis) else None for key, found in by_axis.items()}


def _declared_words(declared: Iterable[DeclaredVersion]) -> list[str]:
    """What is declared, each version said once with where (`supports node >=18 (package.json and 3 more)`)."""
    origins: dict[tuple[bool, str], list[str]] = {}
    for version in declared:
        origins.setdefault((version.pinned, version.version), []).append(version.origin.path)
    found = [
        f"{'pins' if pinned else 'supports'} {version} ({paths[0]}{and_more(len(paths) - 1)})"
        for (pinned, version), paths in origins.items()
    ]
    return found or ["declares no version"]


def _declaration(version: DeclaredVersion) -> dict[str, object]:
    return {"version": version.version, "pinned": version.pinned, "origin": str(version.origin)}


def _versions_of(
    languages: tuple[str, ...], axis: ToolchainAxis | None, declared: Iterable[DeclaredVersion], facts: Facts
) -> Detail | None:
    """What `languages` declare beside what CI tests them with; None when neither is known."""
    own = sorted(
        (version for version in declared if version.language in languages),
        key=lambda version: (version.pinned, version.origin.path),
    )
    tested = sorted(_tested(languages, axis, facts), key=_version_key) if axis is not None else []
    if not own and not tested:
        return None
    words = _declared_words(own)
    if axis is not None:
        words.append(f"CI tests {axis.plural()} {', '.join(tested)}" if tested else f"CI names no {axis.noun}")
    untested = _untested(_oldest(own), tested)
    if untested is not None:
        words.append(f"the oldest supported, {untested}, is not tested")
    return Detail(
        group="Versions",
        subject=", ".join(languages),
        text="; ".join(words),
        data={
            "languages": list(languages),
            "declared": [_declaration(version) for version in own],
            "axis": axis.noun if axis is not None else None,
            "tested": tested,
            "untested_minimum": untested,
        },
    )


def versions(facts: Facts) -> Iterator[Detail]:
    """The versions each language declares beside those CI tests it with: `supports >=3.10 (pyproject.toml); CI tests
    Python versions 3.10, 3.12`, and the oldest supported when CI does not test it."""
    declared = in_product(declared_versions(facts))
    for languages, axis in _subjects(facts, declared).items():
        if detail := _versions_of(languages, axis, declared, facts):
            yield detail


__all__ = ["versions"]
