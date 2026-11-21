"""The mutation job's cache of mutmut's verdicts, carried between CI runs.

    python tests/mutation_cache.py save CACHE         # after mutmut: its verdicts, its stats and the commit
    python tests/mutation_cache.py restore CACHE      # after mutmut created mutants/, before it tests them
    mutmut results | python tests/mutation_cache.py survivors patterns.txt

Only mutmut's results are kept (each source file's `.meta` and `mutmut-stats.json`), never its copy of the tree, so a
deleted test cannot linger in the copy. A restored verdict is kept only while its function's source is unchanged (the
hash mutmut records for it) and no test covering the function changed: mutmut itself resets a verdict only when the
function's own source changes, so a strengthened test would leave its survivors "survived", and a weakened one its
killed mutants "killed".

A changed test module affects its own tests; a changed conftest.py, every test; a changed helper module, every test
module that imports it however indirectly; a changed data file, the test modules that name its folder below `tests/`
(or, outside `tests/`, its name), and every test when no test module names it under `tests/`. A changed data file of the
validator itself affects every test, since the function hashes cannot see it. A change to pyproject.toml or the mutation
requirements restores nothing: the job starts cold, stats pass included.
"""

from __future__ import annotations

import ast
import fnmatch
import json
import shutil
import subprocess
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

PACKAGE = "project_validator/"
STATS = "mutmut-stats.json"
# How the tests run and with what: a change to either makes every verdict and the map of tests to functions stale.
COLD = frozenset({"pyproject.toml", ".github/requirements/mutation.txt"})


def _is_test_module(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return parts[0] == "tests" and parts[-1].startswith("test_") and parts[-1].endswith(".py")


def _test_modules(root: Path) -> dict[str, str]:
    """Each test module under `tests/` (the fixture projects' own aside), by path, with its text."""
    found = {}
    for path in sorted((root / "tests").rglob("test_*.py")):
        relative = path.relative_to(root).as_posix()
        if "fixtures" not in PurePosixPath(relative).parts:
            found[relative] = path.read_text(encoding="utf-8")
    return found


def _imported(root: Path, path: str) -> set[str]:
    """The repository's own files, the validator's aside, that the module at `path` imports."""
    names: set[str] = set()
    for node in ast.walk(ast.parse((root / path).read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.update({node.module, *(f"{node.module}.{alias.name}" for alias in node.names)})
    files = (f"{name.replace('.', '/')}{suffix}" for name in names for suffix in (".py", "/__init__.py"))
    return {file for file in files if not file.startswith(PACKAGE) and (root / file).is_file()}


def _importers(root: Path, modules: Iterable[str]) -> dict[str, set[str]]:
    """For each file the test modules import, however indirectly, the test modules that do."""
    importers: dict[str, set[str]] = {}
    for module in modules:
        seen: set[str] = set()
        pending = [module]
        while pending:
            for file in _imported(root, pending.pop()) - seen:
                seen.add(file)
                pending.append(file)
                importers.setdefault(file, set()).add(module)
    return importers


def _naming(path: str, modules: Mapping[str, str]) -> set[str] | None:
    """The test modules a changed data file affects: those that name its folder below `tests/`, else its name."""
    parts = PurePosixPath(path).parts
    names = {parts[1]} if parts[0] == "tests" else {parts[0], parts[-1]}
    owners = {module for module, text in modules.items() if any(name in text for name in names)}
    return None if parts[0] == "tests" and not owners else owners


def affected_tests(changed: Iterable[str], root: Path) -> set[str] | None:
    """The test modules whose tests the `changed` paths affect; None for all of them."""
    modules = _test_modules(root)
    importers: dict[str, set[str]] | None = None
    affected: set[str] = set()
    for path in changed:
        if path.startswith(PACKAGE):
            if not path.endswith(".py"):
                return None
        elif PurePosixPath(path).name == "conftest.py":
            return None  # pytest loads it for every test beneath it
        elif _is_test_module(path):
            affected |= {path} & modules.keys()
        elif path.endswith(".py"):
            importers = _importers(root, modules) if importers is None else importers
            affected |= importers.get(path, set())
        elif (owners := _naming(path, modules)) is None:
            return None
        else:
            affected |= owners
    return affected


def reset_functions(tests: set[str] | None, tests_by_function: Mapping[str, Iterable[str]]) -> set[str] | None:
    """The functions (mutmut's mangled names) covered by a test in the `tests` modules; None for all of them."""
    if tests is None:
        return None
    return {function for function, ids in tests_by_function.items() if any(i.split("::")[0] in tests for i in ids)}


def merged_verdicts(fresh: Mapping[str, Any], cached: Mapping[str, Any], reset: set[str] | None) -> dict[str, Any]:
    """`fresh` (the `.meta` mutmut just wrote) with the `cached` verdicts of the functions whose source is unchanged
    and that are not `reset`."""
    fresh_hashes, cached_hashes = fresh["hash_by_function_name"], cached["hash_by_function_name"]
    verdicts, durations = {}, {}
    for key in fresh["exit_code_by_key"]:
        function = key.rpartition("__mutmut_")[0]
        name = function.rpartition(".")[2]
        unchanged = name in fresh_hashes and cached_hashes.get(name) == fresh_hashes[name]
        kept = reset is not None and function not in reset and unchanged
        verdicts[key] = cached["exit_code_by_key"].get(key) if kept else None
        if verdicts[key] is not None and key in cached["durations_by_key"]:
            durations[key] = cached["durations_by_key"][key]
    return {**fresh, "exit_code_by_key": verdicts, "durations_by_key": durations}


def save(mutants: Path, cache: Path, commit: str) -> None:
    """Keep mutmut's verdicts and stats in `cache`, with the commit they were made at."""
    shutil.rmtree(cache, ignore_errors=True)
    for meta in mutants.rglob("*.meta"):
        target = cache / "meta" / meta.relative_to(mutants)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(meta, target)
    if (mutants / STATS).is_file():
        shutil.copyfile(mutants / STATS, cache / STATS)
    (cache / "commit").write_text(f"{commit}\n", encoding="utf-8")


def restore(cache: Path, mutants: Path, changed: list[str] | None, root: Path) -> int | None:
    """Merge the cached verdicts into the `.meta` files mutmut just wrote, and put back its stats; how many functions
    were reset (None for all), or nothing when the cache is empty. `changed` is None when the paths changed since the
    cached commit are unknown. A change to how the tests run (`COLD`) restores nothing, not even the stats."""
    if not (cache / STATS).is_file():
        return 0
    if changed is not None and COLD.intersection(changed):
        return None
    stats = json.loads((cache / STATS).read_text(encoding="utf-8"))
    tests = None if changed is None else affected_tests(changed, root)
    reset = reset_functions(tests, stats["tests_by_mangled_function_name"])
    for meta in mutants.rglob("*.meta"):
        cached = cache / "meta" / meta.relative_to(mutants)
        if cached.is_file():
            fresh = json.loads(meta.read_text(encoding="utf-8"))
            merged = merged_verdicts(fresh, json.loads(cached.read_text(encoding="utf-8")), reset)
            meta.write_text(json.dumps(merged, indent=4), encoding="utf-8")
    shutil.copyfile(cache / STATS, mutants / STATS)
    return None if reset is None else len(reset)


def survivors(results: Iterable[str], patterns: Iterable[str]) -> list[str]:
    """The lines of `mutmut results` whose mutant one of `patterns` names: the cache holds other functions' too."""
    patterns = list(patterns)
    keys = ((line, line.strip().rpartition(":")[0]) for line in results)
    return [line for line, key in keys if any(fnmatch.fnmatchcase(key, pattern) for pattern in patterns)]


def _git(*arguments: str) -> str | None:
    completed = subprocess.run(  # noqa: S603 - argv list, no shell
        ["git", *arguments],  # noqa: S607 - git from PATH, as the suite does
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout if completed.returncode == 0 else None


def _restore_command(cache: Path) -> None:
    if not (cache / STATS).is_file():
        print("No cached verdicts: every mutant is tested")
        return
    commit = (cache / "commit").read_text(encoding="utf-8").strip() if (cache / "commit").is_file() else ""
    diff = _git("diff", "--name-only", commit, "HEAD") if commit else None
    changed = None if diff is None else diff.split()
    reset = restore(cache, Path("mutants"), changed, Path.cwd())
    if reset is None:
        print(f"Restored the verdicts of {commit or 'no commit'}: testing every mutant again")
    else:
        print(f"Restored the verdicts of {commit}: the tests of {reset} function(s) changed")


def main(argv: list[str]) -> int:
    command, argument = argv
    if command == "save":
        save(Path("mutants"), Path(argument), commit=(_git("rev-parse", "HEAD") or "").strip())
    elif command == "restore":
        _restore_command(Path(argument))
    else:
        patterns = Path(argument).read_text(encoding="utf-8").split()
        print("".join(survivors(sys.stdin, patterns)), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
