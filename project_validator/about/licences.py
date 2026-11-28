"""Licences: what the license files hold beside what the manifests declare, how many sources carry an SPDX header,
and the licenses of vendored code (upstream #412)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator, Mapping

from project_validator.about.detail import Detail, and_more, in_product, own_code
from project_validator.facts import Facts
from project_validator.facts.licenses import DeclaredLicense, LicenseFile, VendoredLicenseFile


def _said(by_path: Mapping[str, str], verb: str, verbs: str) -> list[str]:
    """Each thing said once, by the first path that says it: `LICENSE and 2 more hold MIT`."""
    paths: dict[str, list[str]] = {}
    for path, said in by_path.items():
        paths.setdefault(said, []).append(path)
    return [
        f"{found[0]}{and_more(len(found) - 1)} {verbs if len(found) > 1 else verb} {said}"
        for said, found in paths.items()
    ]


def _held(licenses: Iterable[str]) -> str:
    return ", ".join(sorted(licenses)) or "a license that is not recognised"


def _licenses(found: LicenseFile) -> frozenset[str]:
    return found.licenses | found.named


def _project(facts: Facts) -> Detail | None:
    files = [found for found in in_product(facts.of(LicenseFile)) if not found.note]
    declared = in_product(facts.of(DeclaredLicense))
    sources = [source for source in own_code(facts) if source.lines]
    headers = Counter(source.license for source in sources if source.license)
    words = _said({found.origin.path: _held(_licenses(found)) for found in files}, "holds", "hold")
    words += _said({found.origin.path: found.expression for found in declared}, "declares", "declare")
    if headers:
        carried = sum(headers.values())
        words.append(
            f"{carried} of {len(sources)} source files {'carries' if carried == 1 else 'carry'} an SPDX header"
        )
    if not words:
        return None
    return Detail(
        group="Licences",
        subject="the project",
        text="; ".join(words),
        data={
            "files": {found.origin.path: sorted(_licenses(found)) for found in files},
            "declared": {found.origin.path: found.expression for found in declared},
            "headers": dict(headers),
            "sources": len(sources),
        },
    )


def _vendored(facts: Facts) -> Detail | None:
    files = facts.of(VendoredLicenseFile)
    if not files:
        return None
    return Detail(
        group="Licences",
        subject="vendored code",
        text="; ".join(_said({found.origin.path: _held(found.licenses) for found in files}, "holds", "hold")),
        data={"files": {found.origin.path: sorted(found.licenses) for found in files}},
    )


def licences(facts: Facts) -> Iterator[Detail]:
    """The project's licenses, then those of its vendored code."""
    yield from (detail for detail in (_project(facts), _vendored(facts)) if detail is not None)


__all__ = ["licences"]
