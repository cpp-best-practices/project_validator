"""What the repository holds: the project's files git does not track, and the tracked files that are build outputs.
Read once, from git's list of tracked files."""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from project_validator.core import Project
from project_validator.facts import Fact, Origin
from project_validator.facts.outputs import BuildOutput, CommittedOutput


@dataclass(frozen=True, slots=True, kw_only=True)
class Untracked(Fact):
    """A file of the project that git does not track (ignored, or never added), so it is not part of the project
    others check out; outside a git checkout every file counts as tracked."""


def repository_facts(project: Project, outputs: Iterable[BuildOutput]) -> Iterator[Fact]:
    """The files git does not track, and each build output that is tracked, once for every output that names it."""
    tracked = project.tracked_files()
    tracked_set = set(tracked)
    yield from (Untracked(origin=Origin(path=path)) for path in project.files() if path not in tracked_set)
    outputs = tuple(outputs)
    found = dict.fromkeys(
        CommittedOutput(origin=Origin(path=artifact), output=output.name, languages=output.languages)
        for path in tracked
        for output in outputs
        if (artifact := output.artifact(path))
    )
    yield from found


__all__ = ["Untracked", "repository_facts"]
