"""The license question: which licenses do the project's license files hold, and does each manifest (of a language)
declare the license of the license files nearest to it?

The project's own license files are those at its root, and REUSE's `LICENSES/`. A manifest is compared with the
license files of its directory, or of the nearest directory above it that has any: a member of a monorepo may hold
its own. Only the product's manifests count, not those of the docs, examples, tooling or tests.
"""

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from project_validator.facts import Facts
from project_validator.facts.licenses import DeclaredLicense, LicenseFile
from project_validator.facts.roles import role
from project_validator.facts.structure import Unit
from project_validator.questions import Answer, LanguageAnswers, Question, answer_dict
from project_validator.tools.licenses import REUSE_DIRECTORY, identifiers_in


@dataclass(frozen=True, slots=True, kw_only=True)
class Mismatch:
    """A manifest that declares `declared`, which is not the license of the license files `files` hold."""

    manifest: str
    declared: str
    licenses: frozenset[str]


@dataclass(frozen=True, slots=True, kw_only=True)
class LicenseAnswer:
    """The project's license files with the licenses each holds (none when unrecognised), and the manifests whose
    declared license does not match theirs. Yes when there are license files, all recognised and matched."""

    language: str
    unit: str = "."
    answer: Answer
    files: tuple[tuple[str, frozenset[str]], ...] = ()
    mismatches: tuple[Mismatch, ...] = ()
    # Where there is no license file at the root: those of the project's units (the packages of a monorepo).
    packages: tuple[tuple[str, frozenset[str]], ...] = ()

    def licenses(self) -> frozenset[str]:
        return frozenset().union(*(licenses for _, licenses in self.files))

    def packages_licenses(self) -> frozenset[str]:
        return frozenset().union(*(licenses for _, licenses in self.packages))

    def unrecognised(self) -> tuple[str, ...]:
        return tuple(path for path, licenses in self.files if not licenses)

    def as_dict(self) -> dict[str, object]:
        return answer_dict(
            self,
            self.answer,
            files={path: sorted(licenses) for path, licenses in self.files},
            mismatches=[
                {"manifest": found.manifest, "declared": found.declared, "licenses": sorted(found.licenses)}
                for found in self.mismatches
            ],
        )


def _comparable(identifiers: frozenset[str]) -> frozenset[str]:
    """A license text says nothing of `-only` or `-or-later`, so those are compared as the license itself."""
    return frozenset(re.sub(r"(?:-only|-or-later|\+)$", "", spdx) for spdx in identifiers)


def _directory(file: LicenseFile) -> str:
    """The directory a license file licenses: REUSE's `LICENSES/` licenses the directory that holds it."""
    parent = PurePosixPath(file.origin.path).parent
    return str(parent.parent if parent.name == REUSE_DIRECTORY else parent)


def _nearest(path: str, files: tuple[LicenseFile, ...]) -> frozenset[str]:
    """The licenses of the license files nearest to `path`: in its directory, or the nearest above it."""
    by_directory: dict[str, set[str]] = {}
    for file in files:
        by_directory.setdefault(_directory(file), set()).update(file.licenses)
    for directory in PurePosixPath(path).parents:
        if (found := by_directory.get(str(directory))) is not None:
            return frozenset(found)
    return frozenset()


def license_answer(facts: Facts, language: str | None = None) -> LicenseAnswer:
    """The answer for the project, comparing the manifests of `language` (every language's, by default)."""
    files = tuple(facts.of(LicenseFile))
    own = tuple((file.origin.path, file.licenses) for file in files if _directory(file) == ".")
    declared = (
        fact
        for fact in facts.of(DeclaredLicense)
        if (language is None or language in fact.languages) and role(fact.origin.path) == "product"
    )
    mismatches = tuple(
        Mismatch(manifest=fact.origin.path, declared=fact.expression, licenses=licenses)
        for fact in declared
        if (licenses := _nearest(fact.origin.path, files))
        and _comparable(identifiers_in(fact.expression)) != _comparable(licenses)
    )
    licensed = bool(own) and all(licenses for _, licenses in own) and not mismatches
    return LicenseAnswer(
        language=language or "",
        answer=Answer.YES if licensed else Answer.NO,
        files=own,
        mismatches=mismatches,
        packages=_packages(facts, files, own),
    )


def _packages(
    facts: Facts, files: tuple[LicenseFile, ...], own: tuple[tuple[str, frozenset[str]], ...]
) -> tuple[tuple[str, frozenset[str]], ...]:
    """Where there is no license file at the root (`own`), those of the project's units (a monorepo's packages)."""
    if own:
        return ()
    units = {unit.directory for unit in facts.of(Unit) if unit.role == "product"} - {"."}
    return tuple((file.origin.path, file.licenses) for file in files if _directory(file) in units)


def licenses(language: str, facts: Facts) -> LanguageAnswers[LicenseAnswer]:
    return LanguageAnswers(language=language, units=(license_answer(facts, language),))


LICENSE_QUESTION = Question(
    name="license",
    description="Which licenses do the license files hold, and does each manifest of the language declare them?",
    answer=licenses,
)

__all__ = ["LICENSE_QUESTION", "LicenseAnswer", "Mismatch", "license_answer", "licenses"]
