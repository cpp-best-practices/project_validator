"""The repository's files are sound whatever tools CI runs (upstream #383): no Trojan Source characters, no
merge-conflict markers, no paths that collide by case or that Windows can't check out, no broken symbolic links, and
no Git LFS pointer committed in place of the file. Each is a defect in the files themselves; where only a test's
data holds one (on purpose, as a fixture), it is reported, not failed."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import PurePosixPath

from project_validator.checks.large_files import lfs_patterns
from project_validator.core import Context, Result, check
from project_validator.ecosystems import registered
from project_validator.facts.roles import role
from project_validator.facts.structure import SourceFile

# Unicode's bidirectional embeddings, overrides and isolates, which reorder how source reads (CVE-2021-42574).
_BIDI = re.compile("[\u202a-\u202e\u2066-\u2069]")
# A merge-conflict block: its opening marker, then a separator, then its closing marker, each on a line of its own.
_CONFLICT = re.compile(r"^<{7}(?: [^\n]*)?\n(?:[^\n]*\n)*?={7}\n(?:[^\n]*\n)*?>{7}(?: |$)", re.MULTILINE)
_LFS_POINTER = "version https://git-lfs.github.com/spec/v1\n"
# The names Windows reserves for devices, with any extension, and the characters it does not allow in a name.
_RESERVED = re.compile(r"(?i)^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?$")
_NOT_ALLOWED = re.compile(r'[<>:"|?*\\]')
HINT = "fix the files named: resolve the conflict, remove the control character, rename the path, or `git lfs pull`"
# How many defects are listed.
LISTED = 20


def _text(context: Context, path: str) -> str | None:
    """A file's text, when it is text no larger than the files read; None for a binary or a larger one."""
    project = context.project
    if project.size(path) > context.options.max_file_size:
        return None
    data = project.read_bytes(path)
    if b"\x00" in data:
        return None
    return data.decode("utf-8", errors="replace")


def _in_text(path: str, text: str) -> Iterator[str]:
    """What a file's text holds that it should not."""
    if (bidi := _BIDI.search(text)) is not None:
        line = text.count("\n", 0, bidi.start()) + 1
        yield f"{path}:{line}: a bidirectional control character (U+{ord(bidi[0]):04X})"
    if (conflict := _CONFLICT.search(text)) is not None:
        yield f"{path}:{text.count(chr(10), 0, conflict.start()) + 1}: a merge-conflict marker"


def _in_name(path: str) -> Iterator[str]:
    """What makes a path impossible to check out on Windows."""
    for part in PurePosixPath(path).parts:
        if _RESERVED.match(part):
            yield f"{path}: a name Windows reserves"
        elif found := _NOT_ALLOWED.search(part):
            yield f"{path}: a character Windows does not allow in a name ({found[0]})"
        elif part.endswith((".", " ")):
            yield f"{path}: a name Windows can't end with a dot or a space"


def _collisions(files: tuple[str, ...]) -> Iterator[str]:
    """Paths that differ only by case: one overwrites the other on macOS and Windows."""
    seen: dict[str, str] = {}
    for path in sorted(files):
        if (other := seen.setdefault(path.lower(), path)) != path:
            yield f"{other} and {path} differ only by case"


def _broken_links(context: Context) -> Iterator[str]:
    """Symbolic links whose target does not exist."""
    root = context.project.root
    for directory, names, files in os.walk(root):
        names[:] = [name for name in names if name != ".git"]
        for name in (*names, *files):
            full = os.path.join(directory, name)
            if os.path.islink(full) and not os.path.exists(full):
                relative = PurePosixPath(os.path.relpath(full, root)).as_posix()
                yield f"{relative}: a symbolic link to {os.readlink(full)}, which does not exist"


def _code(context: Context) -> frozenset[str]:
    """The source files of the project's programming languages: where a conflict marker or a bidirectional control
    character changes how code reads. Prose and data are not searched: a translation writes right-to-left text with
    them, and a guide to merging shows a conflict."""
    languages = {
        language for ecosystem in registered() if ecosystem.kind == "language" for language in ecosystem.languages
    }
    return frozenset(source.path for source in context.facts.of(SourceFile) if source.language in languages)


def _defects(context: Context) -> Iterator[tuple[str, str]]:
    """Each defect, with the path it is in."""
    files = context.tracked_files
    stored = lfs_patterns(context, files)
    code = _code(context)
    for path in files:
        yield from ((path, found) for found in _in_name(path))
        if (text := _text(context, path)) is None:
            continue
        if path in code:
            yield from ((path, found) for found in _in_text(path, text))
        if text.startswith(_LFS_POINTER) and not any(lfs.matches(path) for lfs in stored):
            yield path, f"{path}: a Git LFS pointer, not the file"
    yield from ((found.split(" and ")[0], found) for found in _collisions(files))
    yield from ((found.split(":")[0], found) for found in _broken_links(context))


@check(
    name="repository-hygiene",
    description="No Trojan Source characters, conflict markers, unportable paths, broken links or stray LFS pointers",
)
def repository_hygiene(context: Context) -> Result:
    found = list(_defects(context))
    if not found:
        return Result.passed("no conflict markers, control characters, unportable paths or broken links")
    product = [defect for path, defect in found if role(path) != "test"]
    tests = [f"{defect} (test code)" for path, defect in found if role(path) == "test"]
    listed = [*product, *tests]
    details = [*listed[:LISTED], *((f"and {len(listed) - LISTED} more",) if len(listed) > LISTED else ()), HINT]
    if product:
        return Result.failed(f"{len(product)} defect(s) in the repository's files", *details)
    return Result.warned(f"{len(tests)} defect(s), in test code only (fixtures kept on purpose?)", *details)
