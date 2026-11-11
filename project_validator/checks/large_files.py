"""Large files are kept out of git's history: Git LFS or DVC stores them instead."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import PurePosixPath

from project_validator.core import Context, Result, check

GITATTRIBUTES = ".gitattributes"
# How many of the largest files are listed.
LISTED = 5
HINT = "track large files with Git LFS (git lfs track '*.bin') or DVC (dvc add), or keep them out of the repository"


@dataclass(frozen=True, slots=True)
class _LfsPattern:
    """A `.gitattributes` pattern that stores files in Git LFS, and the directory of that `.gitattributes`."""

    directory: PurePosixPath
    pattern: str

    def matches(self, path: str) -> bool:
        """A pattern without a slash matches a file name at any depth; one with a slash, a path from its directory."""
        relative = PurePosixPath(path)
        if self.directory.parts and not relative.is_relative_to(self.directory):
            return False
        relative = relative.relative_to(self.directory)
        if "/" in self.pattern:
            return fnmatchcase(str(relative), self.pattern.lstrip("/"))
        return fnmatchcase(relative.name, self.pattern)


def _lfs_patterns(context: Context, files: tuple[str, ...]) -> list[_LfsPattern]:
    patterns = []
    for path in files:
        if PurePosixPath(path).name == GITATTRIBUTES:
            for line in context.project.read_text(path).splitlines():
                fields = line.split()
                if len(fields) > 1 and not fields[0].startswith("#") and "filter=lfs" in fields[1:]:
                    patterns.append(_LfsPattern(PurePosixPath(path).parent, fields[0]))
    return patterns


def _size(size: int) -> str:
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KiB"
    return f"{size / (1024 * 1024):.3g} MiB"


@check(name="large-files", description="Large files are stored with Git LFS or DVC rather than committed directly")
def large_files(context: Context) -> Result:
    project = context.project
    files = context.tracked_files
    limit = context.options.max_file_size
    patterns = _lfs_patterns(context, files)
    large = [
        (project.size(path), path)
        for path in files
        if project.size(path) > limit
        and not any(lfs.matches(path) for lfs in patterns)
        and not project.exists(f"{path}.dvc")
    ]
    if not large:
        return Result.passed(f"no committed file is larger than {_size(limit)}")
    largest = sorted(large, key=lambda entry: (-entry[0], entry[1]))
    count = len(large)
    return Result.warned(
        f"{count} committed file{'s are' if count != 1 else ' is'} larger than {_size(limit)}",
        *(f"{path} ({_size(size)})" for size, path in largest[:LISTED]),
        *((f"and {count - LISTED} more",) if count > LISTED else ()),
        HINT,
    )
