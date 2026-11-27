"""Binary and asset files are checked for soundness (upstream #383, part B): where a project holds images, PDFs, fonts,
audio or video, archives or 3D models, CI (or a pre-commit hook) runs a tool that checks them. ClamAV or YARA check
every kind; the others decode their kind (a truncated PNG, a broken PDF cross-reference table, a font that won't
load). A project with no such files skips the check."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import PurePosixPath

from project_validator.core import Context, Result, check
from project_validator.facts.practices import named
from project_validator.facts.roles import role
from project_validator.text import Pattern, pattern

# The kinds of binary file, by suffix.
KINDS: Mapping[str, frozenset[str]] = {
    "image": frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".tif", ".tiff"}),
    "PDF document": frozenset({".pdf"}),
    "font": frozenset({".ttf", ".otf", ".woff", ".woff2"}),
    "audio or video": frozenset({".mp3", ".wav", ".ogg", ".flac", ".mp4", ".webm", ".mov", ".mkv"}),
    "archive": frozenset({".zip", ".tar", ".tgz", ".gz", ".bz2", ".xz", ".7z"}),
    "3D model": frozenset({".gltf", ".glb"}),
}
# The tools that check every kind: a virus scanner and pattern rules.
EVERY_KIND = (pattern("ClamAV", r"\bclam(?:d)?scan\b"), pattern("YARA", r"\byara\b"))
# The tools that decode one kind, by the kind they check.
TOOLS: Mapping[str, tuple[Pattern, ...]] = {
    "image": (
        pattern("ImageMagick", r"\b(?:magick\s+)?identify\s+(?:[^\n]*\s)?-regard-warnings\b|\bmagick\s+identify\b"),
        pattern("pngcheck", r"\bpngcheck\b"),
        pattern("jpeginfo", r"\bjpeginfo\b"),
    ),
    "PDF document": (pattern("qpdf", r"\bqpdf\s+(?:[^\n]*\s)?--check\b"), pattern("veraPDF", r"\bverapdf\b")),
    "font": (pattern("fontbakery", r"\bfontbakery\b"),),
    "audio or video": (pattern("ffprobe", r"\bffprobe\b"),),
    "archive": (),
    "3D model": (pattern("glTF Validator", r"\bgltf[_-]validator\b"),),
}
HINT = (
    "run ClamAV (clamscan -r .) over the repository, or a tool that decodes each kind of file (magick identify "
    "-regard-warnings, pngcheck, qpdf --check, fontbakery, ffprobe -v error, gltf_validator)"
)
# How many files of a kind no tool checks are named.
LISTED = 3


def _files_of_kinds(context: Context) -> dict[str, list[str]]:
    """The project's own files of each kind (not vendored code's)."""
    found: dict[str, list[str]] = {}
    for path in context.tracked_files:
        suffix = PurePosixPath(path).suffix.lower()
        kind = next((kind for kind, suffixes in KINDS.items() if suffix in suffixes), None)
        if kind is not None and role(path) != "vendored":
            found.setdefault(kind, []).append(path)
    return found


def _named(files: list[str]) -> str:
    return ", ".join(files[:LISTED]) + (f" and {len(files) - LISTED} more" if len(files) > LISTED else "")


@check(name="file-soundness", description="CI checks the project's binary and asset files (e.g. ClamAV, magick, qpdf)")
def file_soundness(context: Context) -> Result:
    kinds = _files_of_kinds(context)
    if not kinds:
        return Result.skipped("the project holds no binary or asset files (images, PDFs, fonts, media, archives)")
    every = named(context.facts, EVERY_KIND)
    run = {kind: named(context.facts, TOOLS[kind]) for kind in kinds}
    unchecked = [kind for kind in KINDS if kind in kinds and not every and not run[kind]]
    if unchecked:
        message = "; ".join(f"no tool checks the {kind} files ({_named(kinds[kind])})" for kind in unchecked)
        return Result.warned(message, HINT)
    tools = list(dict.fromkeys([*every, *(tool for kind in kinds for tool in run[kind])]))
    return Result.passed(f"CI checks the binary files with {', '.join(tools)}")
