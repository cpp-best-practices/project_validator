"""The files of other repositories a CI configuration uses, fetched when asked (`--fetch-remote`, upstream #248): a
reusable workflow (`owner/repo/.github/workflows/lint.yml@ref`) or a composite action (`owner/repo/path@ref`), read
from GitHub at the ref it is pinned to. A file pinned to a full commit cannot change, so it is cached (under
`$XDG_CACHE_HOME/project_validator/remote`); one pinned to a tag or a branch is fetched each time. Without the option,
or offline (`--offline`, `PROJECT_VALIDATOR_OFFLINE`), nothing is fetched and the file is not read, as before.

A remote file is named, where the CI reader asks for a path, by `reference`: `remote:<ref>/<owner>/<repo>/<path>`, so
that a path below it (an action's `action.yml`) is still a path."""

from __future__ import annotations

import os
import re
import urllib.error
import urllib.request
from pathlib import Path

PREFIX = "remote:"
_RAW = "https://raw.githubusercontent.com/"
_COMMIT = re.compile(r"[0-9a-f]{40}")
_SEGMENT = re.compile(r"^[\w.-]+$")
# How long a fetch may take.
TIMEOUT = 20


def reference(repository: str, path: str, ref: str) -> str:
    """The name of the file `path` of `repository` (`owner/repo`) at `ref`."""
    return f"{PREFIX}{ref}/{repository}/{path}".rstrip("/")


def is_remote(path: str) -> bool:
    return path.startswith(PREFIX)


def _cache() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base, "project_validator", "remote")


def _get(url: str) -> str | None:
    """The text at `url`; None when there is none (404) or it cannot be fetched."""
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as response:  # noqa: S310 - a fixed https origin
            return str(response.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def fetched(name: str) -> str | None:
    """The text of the remote file `name` (see `reference`): from the cache when it is pinned to a commit and was
    fetched before; None when it is not a well-formed name, or has no such file."""
    ref, _, rest = name.removeprefix(PREFIX).partition("/")
    parts = rest.split("/")
    if len(parts) < 3 or not all(_SEGMENT.match(part) for part in (ref, *parts)) or ".." in parts:
        return None
    cached = _cache().joinpath(ref, *parts)
    if _COMMIT.fullmatch(ref) and cached.is_file():
        return cached.read_text(encoding="utf-8")
    text = _get(f"{_RAW}{'/'.join(parts[:2])}/{ref}/{'/'.join(parts[2:])}")
    if text is not None and _COMMIT.fullmatch(ref):
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(text, encoding="utf-8")
    return text


__all__ = ["PREFIX", "fetched", "is_remote", "reference"]
