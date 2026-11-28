"""Dependencies: each package manager's manifests and whether a lockfile pins what they declare, and how much of
other projects' code is vendored into the repository (upstream #412)."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import PurePosixPath

from project_validator.about.detail import Detail, and_more, in_product
from project_validator.facts import Fact, Facts
from project_validator.facts.dependencies import Declared, Locked
from project_validator.facts.roles import VENDOR_DIRECTORIES
from project_validator.facts.structure import SourceFile
from project_validator.words import counted, folder

# Manifests named before the rest are counted.
SHOWN = 3


def _named(paths: Iterable[str]) -> str:
    """`Cargo.toml, crates/a/Cargo.toml and 4 more`."""
    paths = list(dict.fromkeys(paths))
    rest = len(paths) - SHOWN
    return ", ".join(paths[:SHOWN]) + and_more(rest)


def _products(facts: Iterable[Fact]) -> list[str]:
    """The paths of the product's own facts: not those of its tests' fixtures."""
    return [fact.origin.path for fact in in_product(facts)]


def _vendor_folder(path: str) -> str:
    """The folder vendored code is kept in: its vendor directory (`third_party/`), else the file's own folder (a
    minified bundle)."""
    parts = PurePosixPath(path).parts
    index = next((at for at, part in enumerate(parts[:-1]) if part.lower() in VENDOR_DIRECTORIES), len(parts) - 2)
    return folder("/".join(parts[: index + 1]) if index >= 0 else ".")


def _vendored(facts: Facts) -> Detail | None:
    paths = [source.path for source in facts.of(SourceFile) if source.vendored]
    if not paths:
        return None
    folders = sorted(set(map(_vendor_folder, paths)))
    return Detail(
        group="Dependencies",
        subject="vendored code",
        text=f"{counted(len(paths), 'file')} in {_named(folders)}",
        data={"files": len(paths), "folders": folders},
    )


def _counts(declared: list[Declared]) -> tuple[str, dict[str, list[str]]]:
    """How many direct dependencies the manifests declare, each named once (`12 direct dependencies and 3 for
    development, `), and which: none said unless every manifest's are read. One used both ways counts as direct."""
    if not declared or any(fact.direct is None for fact in declared):
        return "", {}
    direct = sorted({name for fact in declared for name in fact.direct or ()})
    development = sorted({name for fact in declared for name in fact.development} - set(direct))
    words = counted(len(direct), "direct dependency", "direct dependencies")
    if development:
        words += f" and {len(development)} for development"
    return f"{words}, ", {"direct": direct, "development": development}


def dependencies(facts: Facts) -> Iterator[Detail]:
    """Each package manager's manifests and lockfiles, then the vendored code."""
    managers = sorted({fact.manager for fact in facts.of(Declared)})
    for manager in managers:
        manifests = list(in_product(facts.where(Declared, manager=manager)))
        declared = [fact.origin.path for fact in manifests]
        if not declared:
            continue
        locked = _products(facts.where(Locked, manager=manager))
        lock = f"locked by {_named(locked)}" if locked else "no lockfile"
        count, names = _counts(manifests)
        yield Detail(
            group="Dependencies",
            subject=manager,
            text=f"{count}declared in {_named(declared)}; {lock}",
            data={"declared": list(dict.fromkeys(declared)), "locked": list(dict.fromkeys(locked)), **names},
        )
    if vendored := _vendored(facts):
        yield vendored


__all__ = ["dependencies"]
