"""The dependency management question: for each language, in each unit of the project that has it, are the
dependencies declared for a package manager, and, where it matters, locked?

A manifest belongs to the unit that owns its directory; a lockfile locks the unit it is in and every unit below it (a
workspace's lockfile at its root locks its members); a lockfile git does not track locks nothing.
"""

from dataclasses import dataclass
from pathlib import PurePosixPath

from project_validator.facts import Command, Facts, Unknown
from project_validator.facts.dependencies import (
    Application,
    Declared,
    Library,
    Lock,
    Locked,
    PackageManager,
    directory_of,
    known_package_managers,
    managers_of,
)
from project_validator.facts.repository import Untracked
from project_validator.facts.roles import AUXILIARY, role
from project_validator.facts.structure import Unit
from project_validator.facts.tools import owner, within
from project_validator.questions import Answer, LanguageAnswers, Question, answer_dict, per_unit


@dataclass(frozen=True, slots=True, kw_only=True)
class DependencyAnswer:
    """Whether the dependencies of `language` in `unit` are managed and, where a lock is asked for, locked.

    `declared`: (manager, manifest) for each manifest that declares dependencies. `locked`: what locks them.
    `lock_required`: whether a lock is asked for. `answer` is yes when nothing is declared, or what is declared is
    locked or need not be; no when a lock is missing; unknown when a manifest could not be read."""

    language: str
    unit: str = "."
    answer: Answer
    declared: tuple[tuple[str, str], ...] = ()
    locked: tuple[str, ...] = ()
    lock_required: bool = False
    lock_hints: tuple[str, ...] = ()
    suggested: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()

    def managers(self) -> tuple[str, ...]:
        return tuple(sorted({manager for manager, _ in self.declared}))

    def manifests(self) -> tuple[str, ...]:
        return tuple(sorted({path for _, path in self.declared}))

    def as_dict(self) -> dict[str, object]:
        return answer_dict(
            self,
            self.answer,
            declared=[{"manager": manager, "manifest": path} for manager, path in self.declared],
            locked=list(self.locked),
            lock_required=self.lock_required,
            unknowns=list(self.unknowns),
        )


class _Unit:
    """Where facts belong among the units of the project."""

    def __init__(self, facts: Facts, unit: str) -> None:
        units = {found.directory: found.role for found in facts.of(Unit)} or {".": "product"}
        self.unit, self.units, self.role = unit, tuple(units), units.get(unit, "product")
        self.untracked = {fact.origin.path for fact in facts.of(Untracked)}

    def owns(self, path: str) -> bool:
        """Whether a manifest is the unit's own: in its directory, outside the units below it, and not auxiliary
        code of a unit of another role."""
        auxiliary = role(path) in AUXILIARY and self.role not in AUXILIARY
        return owner(directory_of(path), self.units) == self.unit and not auxiliary

    def locked_by(self, path: str, *, nested: bool = True) -> bool:
        """Whether a committed lockfile locks the unit: it is in the unit's directory or above it, or (for a manager
        whose lockfiles lock from deeper in the unit: `requirements/*.txt`) the unit's own."""
        return path not in self.untracked and (within(self.unit, directory_of(path)) or (nested and self.owns(path)))


def _lock_required(manager: PackageManager, facts: Facts, place: _Unit) -> bool:
    if manager.lock is not Lock.APPLICATIONS:
        return manager.lock is Lock.ALWAYS
    if any(place.owns(fact.origin.path) for fact in facts.where(Application, manager=manager.name)):
        return True
    library = any(place.owns(fact.origin.path) for fact in facts.where(Library, manager=manager.name))
    return manager.applications_by_default and not library


def _hidden(path: str) -> bool:
    return any(part.startswith(".") for part in PurePosixPath(path).parent.parts)


def _locks(managers: tuple[PackageManager, ...], facts: Facts, place: _Unit) -> tuple[str, ...]:
    """What locks the unit's dependencies: its lockfiles, but those in hidden directories (CI's own, such as an
    action's lockfile or the hash-pinned requirements CI installs) only when no other does; or CI commands that verify
    them."""
    nested = {manager.name: manager.nested_locks for manager in managers}
    found = [
        fact.origin.path
        for fact in facts.of(Locked)
        if fact.manager in nested and place.locked_by(fact.origin.path, nested=nested[fact.manager])
    ]
    files = [path for path in found if not _hidden(path)] or found
    verified = (
        f"CI ({command.origin.path})"
        for command in facts.of(Command)
        if any(manager.verified_by(command) for manager in managers)
    )
    return tuple(dict.fromkeys((*files, *verified)))


def _declared(names: set[str], facts: Facts, place: _Unit) -> tuple[tuple[str, str], ...]:
    found = facts.of(Declared)
    return tuple(
        (fact.manager, fact.origin.path) for fact in found if fact.manager in names and place.owns(fact.origin.path)
    )


def _unknowns(names: set[str], facts: Facts, place: _Unit) -> tuple[str, ...]:
    """What could not be read of the unit's own manifests."""
    return tuple(
        f"{fact.subject}: {fact.reason} ({fact.origin})"
        for fact in facts.of(Unknown)
        if names & set(fact.tools) and place.owns(fact.origin.path)
    )


def _answer(declared: bool, settled: bool, unknown: bool) -> Answer:
    """Unknown when a manifest could not be read and what was read does not settle it."""
    if unknown and not (declared and settled):
        return Answer.UNKNOWN
    return Answer.YES if settled else Answer.NO


def dependency_answer(
    language: str, facts: Facts, managers: tuple[PackageManager, ...], unit: str = "."
) -> DependencyAnswer:
    """Whether `language`'s dependencies in `unit` are managed and locked, by the facts and the known `managers`."""
    known = managers_of(language, managers)
    if not known:
        return DependencyAnswer(language=language, unit=unit, answer=Answer.IMPOSSIBLE)
    place = _Unit(facts, unit)
    names = {manager.name for manager in known}
    declared = _declared(names, facts, place)
    declaring = tuple(manager for manager in known if manager.name in {name for name, _ in declared})
    required = any(_lock_required(manager, facts, place) for manager in declaring)
    locked = _locks(declaring, facts, place) if required else ()
    unknowns = _unknowns(names, facts, place)
    return DependencyAnswer(
        language=language,
        unit=unit,
        answer=_answer(bool(declared), not declared or not required or bool(locked), bool(unknowns)),
        declared=declared,
        locked=locked,
        lock_required=required,
        lock_hints=tuple(dict.fromkeys(manager.lock_hint for manager in declaring if manager.lock_hint)),
        suggested=tuple(manager.name for manager in known if manager.suggested),
        unknowns=unknowns,
    )


def dependency_management(language: str, facts: Facts) -> LanguageAnswers[DependencyAnswer]:
    """For a language: whether its dependencies are managed and locked in each unit that has it."""
    managers = known_package_managers()
    return per_unit(language, facts, lambda unit: dependency_answer(language, facts, managers, unit))


DEPENDENCY_MANAGEMENT_QUESTION = Question(
    name="dependency-management",
    description="Are each language's dependencies in each unit declared for a package manager, and locked?",
    answer=dependency_management,
)

__all__ = ["DEPENDENCY_MANAGEMENT_QUESTION", "DependencyAnswer", "dependency_answer", "dependency_management"]
