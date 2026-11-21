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
# Files that only keep a directory in git (an output directory a tool expects to exist).
_PLACEHOLDERS = frozenset({".keep", ".gitkeep", ".gitignore", ".keepme", ".placeholder", ".empty"})
# Documents a directory of sources may hold beside them (a packaging directory's README).
_DOCUMENTS = frozenset({".md", ".markdown", ".rst", ".txt", ".adoc"})
# Outputs that are binaries: a file of one of these that is text (a shell wrapper named dune.exe, a Java module
# descriptor named module-info.test) is not one.
# The formats tools write into their outputs (package_config.json, project.assets.json, dbt's manifest.json).
_WRITTEN_BY_TOOLS = frozenset({"JSON"})
_SOURCE_ROOTS = frozenset({"src", "lib", "source", "sources"})
# Settings a tool keeps in its own directory, committed on purpose (Bundler's `.bundle/config`, Homebrew's).
_SETTINGS = ("/.bundle/config",)
# What a build writes into an output directory where that is not the language's sources: `python -m build` writes
# wheels and sdists into dist/, never a `.py` (ghostty's dist/ of packaging scripts).
_WRITTEN = {("Python", "dist"): (".whl", ".gz", ".zip", ".egg", ".tar")}
_OWNED, _FOREIGN, _UNKNOWN = "owned", "foreign", "unknown"
# Media a source directory holds (a book's images, a site's favicon): binary, but no build's output.
_MEDIA = frozenset({".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".bmp", ".pdf", ".mp4", ".ogv"})
_MEDIA |= {".woff", ".woff2", ".ttf", ".otf"}
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
        """A directory is a build output unless it holds documents or sources of other languages (a bin/ of shell
        scripts beside a Go module, Cloud Build's build/*.yaml, an mdBook's book/ with its images) and nothing its
        build writes, or only the placeholders and settings kept in git (cmake_template's out/coverage/.keep,
        Bundler's .bundle/config). Files of no known language (images, binaries) say neither."""
        inside = [path for path in self.tracked if path.startswith(directory)]
        kept = [
            path
            for path in inside
            if PurePosixPath(path).name not in _PLACEHOLDERS and not f"/{path}".endswith(_SETTINGS)
        ]
        if not kept:
            return not inside
        written = next(
            (
                suffixes
                for (language, name), suffixes in _WRITTEN.items()
                if language in languages and directory.rstrip("/").endswith(name)
            ),
            None,
        )
        found = {self._kind(path, languages, written) for path in kept}
        return _OWNED in found or _FOREIGN not in found

    def _kind(self, path: str, languages: frozenset[str], written: tuple[str, ...] | None) -> str:
        """Whether a file is what the output's build writes, a document or source of another language, or unknown."""
        file = PurePosixPath(path)
        if written is not None and file.name.lower().endswith(written):
            return _OWNED
        if file.suffix.lower() in _DOCUMENTS:
            return _FOREIGN
        language = self.language(path) or self._script(path)
        if language is None:
            return _OWNED if file.suffix.lower() not in _MEDIA and self._holds_binary(path) else _UNKNOWN
        if written is None and (language in languages or language in _WRITTEN_BY_TOOLS):
            return _OWNED
        return _FOREIGN

    def _script(self, path: str) -> str | None:
        """The language of a script without a suffix, by its shebang (fzf's bin/fzf-tmux)."""
        if PurePosixPath(path).suffix:
            return None
        from project_validator.tools.shell_scripts import SHELLS, interpreter

        return "Shell" if interpreter(self.project.read_head(path, 160)) in SHELLS else None

    def _binary(self, path: str) -> bool:
        if PurePosixPath(path).suffix.lower() not in _BINARIES:
            return True
        return not self.project.read_bytes(path)[:1] or self._holds_binary(path)

    def _holds_binary(self, path: str) -> bool:
        return b"\0" in self.project.read_bytes(path)[:8192]
