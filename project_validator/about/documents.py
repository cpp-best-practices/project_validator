"""Documents: the generator the docs are built with, the changelog and its latest entry, CONTRIBUTING, CODEOWNERS,
and issue and pull request templates (upstream #412)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import PurePosixPath

from project_validator.about.detail import Detail
from project_validator.ecosystems.documentation import GENERATORS
from project_validator.facts import Facts
from project_validator.facts.documents import (
    CHANGELOG,
    CODEOWNERS,
    CONTRIBUTING,
    DOXYGEN,
    ISSUE_TEMPLATE,
    PULL_REQUEST_TEMPLATE,
    ProjectDocument,
)
from project_validator.facts.structure import project_formats

# Where a project's own documents are kept: the root, .github/ and docs/ (a subproject's are its own).
_PLACES = frozenset({".", ".github", "docs"})
# The documents said to be missing when a project has none of them.
_EXPECTED = ((CHANGELOG, "CHANGELOG"), (CONTRIBUTING, "CONTRIBUTING"), (CODEOWNERS, "CODEOWNERS"))


def _documents(facts: Facts) -> dict[str, list[ProjectDocument]]:
    found: dict[str, list[ProjectDocument]] = {}
    for document in facts.of(ProjectDocument):
        parent = PurePosixPath(document.origin.path).parent
        place = parent.parent if parent.name.upper() in ("ISSUE_TEMPLATE", "PULL_REQUEST_TEMPLATE") else parent
        if str(place).lower() in _PLACES:
            found.setdefault(document.kind, []).append(document)
    return found


def _changelog(changelogs: list[ProjectDocument]) -> str:
    first = changelogs[0]
    return f"{first.origin.path}, its latest entry {first.latest}" if first.latest else first.origin.path


def documents(facts: Facts) -> Iterator[Detail]:
    """What documents the project keeps; nothing for a project with none of them."""
    found = _documents(facts)
    generators = sorted(GENERATORS & project_formats(facts)) + (["Doxygen"] if DOXYGEN in found else [])
    words = [f"docs built with {', '.join(generators)}"] if generators else []
    if CHANGELOG in found:
        words.append(_changelog(found[CHANGELOG]))
    words += [document.origin.path for document in found.get(CONTRIBUTING, [])[:1]]
    words += [document.origin.path for document in found.get(CODEOWNERS, [])[:1]]
    if templates := len(found.get(ISSUE_TEMPLATE, [])):
        words.append(f"{templates} issue {'template' if templates == 1 else 'templates'}")
    if PULL_REQUEST_TEMPLATE in found:
        words.append("a pull request template")
    if not words:
        return
    if missing := [name for kind, name in _EXPECTED if kind not in found]:
        words.append(f"no {', '.join(missing)}")
    data = {kind: [document.origin.path for document in kept] for kind, kept in found.items()}
    yield Detail(
        group="Documents", subject="the project", text="; ".join(words), data={**data, "generators": generators}
    )


__all__ = ["documents"]
