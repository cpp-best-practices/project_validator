"""What the repository holds: the project's files git does not track, and the tracked files that are build outputs.
Read once, from git's list of tracked files."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import PurePosixPath

from project_validator.core import Project
from project_validator.facts import Fact, Origin
from project_validator.facts.outputs import BuildOutput, CommittedOutput
from project_validator.facts.roles import role


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
    judge = _Judge(project, tracked)
    yield from (fact for fact in found if judge.output(fact))


# Roles whose files are kept on purpose: a test's fixtures (an egg-info, a node_modules tree), docs' samples. (Not
# examples: a Java package `com/example/` reads as one.)
_KEPT = frozenset({"test", "docs"})
# Documents a directory of sources may hold beside them (a packaging directory's README).
_DOCUMENTS = frozenset({".md", ".markdown", ".rst", ".txt", ".adoc"})
# Outputs that are binaries: a file of one of these that is text (a shell wrapper named dune.exe, a Java module
# descriptor named module-info.test) is not one.
# The formats tools write into their outputs (package_config.json, project.assets.json, dbt's manifest.json).
_WRITTEN_BY_TOOLS = frozenset({"JSON"})
_SOURCE_ROOTS = frozenset({"src", "lib", "source", "sources"})
_BINARIES = frozenset({".exe", ".test", ".o", ".obj", ".class", ".so", ".dll", ".dylib", ".a", ".lib", ".pyc"})


class _Judge:
    """Whether a tracked path a build output names is one, by what it holds."""

    def __init__(self, project: Project, tracked: list[str]) -> None:
        from project_validator.facts.structure import source_languages  # structure reads the profiles
        from project_validator.project_map import build_files

        self.project, self.tracked, self.language = project, tracked, source_languages()
        known = build_files()
        self.builds = {build for path in tracked for build, _system in known.matches(path)}

    def output(self, fact: CommittedOutput) -> bool:
        path = fact.origin.path
        directory = path.endswith("/")
        if role(path.rstrip("/"), directory=directory) in _KEPT or self._among_sources(path):
            return False
        return self._generated(path, fact.languages) if directory else self._binary(path)

    def _among_sources(self, path: str) -> bool:
        """Whether a directory output is inside a source tree (drift's lib/src/build/), not beside a build file
        (.NET's src/App/obj/ beside App.csproj): builds write theirs where the unit is built."""
        if not path.endswith("/"):
            return False
        parent = PurePosixPath(path.rstrip("/")).parent
        beside = any(PurePosixPath(build.rstrip("/")).parent == parent for build in self.builds)
        return not beside and any(part in _SOURCE_ROOTS for part in parent.parts)

    def _generated(self, directory: str, languages: frozenset[str]) -> bool:
        """A directory is a build output unless it holds only documents and sources of other languages (a bin/ of
        shell scripts beside a Go module, Cloud Build's build/*.yaml, an mdBook's book/)."""
        inside = [path for path in self.tracked if path.startswith(directory)]
        return not inside or any(self._owned(path, languages) for path in inside)

    def _owned(self, path: str, languages: frozenset[str]) -> bool:
        if PurePosixPath(path).suffix.lower() in _DOCUMENTS:
            return False
        language = self.language(path)
        return language is None or language in languages or language in _WRITTEN_BY_TOOLS

    def _binary(self, path: str) -> bool:
        if PurePosixPath(path).suffix.lower() not in _BINARIES:
            return True
        head = self.project.read_bytes(path)[:8192]
        return not head or b"\0" in head
