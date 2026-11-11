"""JavaScript and TypeScript: packaged with package.json (npm, pnpm, yarn, bun) or deno.json, judged by the Node.js,
Deno and Bun versions CI runs.

Much of a JavaScript project's tooling runs through the scripts of its package.json (`npm run lint`), so the scripts
CI runs count as CI configuration wherever a rule reads more than CI configuration.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import PurePosixPath

from project_validator import yaml_support
from project_validator.core import Context
from project_validator.ecosystems.model import BuildSystem, Ecosystem, toolchain_patterns
from project_validator.evidence import json_value
from project_validator.facts import Command, Fact, Facts, Origin, Unknown, resolved
from project_validator.facts.arguments import option_values, positional, program, starts_with
from project_validator.facts.audit import audited, auditor
from project_validator.facts.axes import versions_axis
from project_validator.facts.coverage import Granularity, coverage_tool, measured
from project_validator.facts.dependencies import PackageManager, lockfile_reader, manifest_reader
from project_validator.facts.expansion import CommandExpander, Expansion, Script, found_at, joined, launcher
from project_validator.facts.formatting import Enforcement, flagged, format_tool
from project_validator.facts.licenses import declared_license_reader
from project_validator.facts.outputs import BuildOutput, directories, ignored_at_top_level
from project_validator.facts.practices import Practice, PracticeName, Requirement, Wording, always, met, required
from project_validator.facts.settings import (
    Read,
    SettingsReader,
    file_reader,
    json_settings,
    matched_settings,
    plain,
    settings,
    unreadable,
)
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import Claim, Run, Tool, all_of, defined_by, starts, when, with_option
from project_validator.text import pattern, strip_json_comments
from project_validator.tools.audits import multi_ecosystem_audits

JAVASCRIPT = "JavaScript"
TYPESCRIPT = "TypeScript"
PACKAGE_JSON = "package.json"
DENO_CONFIG_FILES = ("deno.json", "deno.jsonc")
# A package.json that names what it provides is a JavaScript package, even before any source is found.
ENTRY_POINTS = ("main", "module", "exports", "bin")


def _declared_by_package(_path: str, text: str) -> frozenset[str]:
    """package.json is everywhere, as the tooling of projects in other languages; only a package's entry points (or
    JavaScript sources, recognised by their suffixes) make a project a JavaScript one."""
    try:
        manifest = json.loads(text)
    except json.JSONDecodeError:
        return frozenset()
    is_package = isinstance(manifest, dict) and any(key in manifest for key in ENTRY_POINTS)
    return frozenset({JAVASCRIPT}) if is_package else frozenset()


def _workspaces(text: str) -> tuple[str, ...]:
    """The workspaces a package.json declares (npm, yarn and bun: `workspaces`, as a list or under `packages`)."""
    try:
        manifest = json.loads(text)
    except json.JSONDecodeError:
        return ()
    found = manifest.get("workspaces") if isinstance(manifest, dict) else None
    if isinstance(found, dict):
        found = found.get("packages")
    return tuple(str(member) for member in found) if isinstance(found, list) else ()


NPM = BuildSystem(name="npm", files=(PACKAGE_JSON,), declared_languages=_declared_by_package, members=_workspaces)
DENO = BuildSystem(name="Deno", files=DENO_CONFIG_FILES, languages=frozenset({TYPESCRIPT}))


def _json_strings(value: object) -> dict[str, str]:
    return {key: item for key, item in value.items() if isinstance(item, str)} if isinstance(value, dict) else {}


# `npm test`, `npm run lint`, `pnpm lint`, `yarn run lint`, `bun run lint`, `deno task lint`.
RUNS_SCRIPT = re.compile(
    r"\bnpm\s+(?:run(?:-script)?\s+(?P<npm>[\w:.-]+)|(?P<npm_lifecycle>test|t|start)\b)"
    r"|\b(?:pnpm|yarn)\s+(?:run\s+)?(?P<pnpm>[\w:.-]+)"
    r"|\bbun\s+run\s+(?P<bun>[\w:.-]+)"
    r"|\bdeno\s+task\s+(?P<deno>[\w:.-]+)"
)
NPM_LIFECYCLE_ALIASES = {"t": "test"}


# How a command names the package script it runs: the scripts npm runs by name, and the commands each package
# manager has besides `run` (which it does not take for script names).
_NPM_SCRIPT_COMMANDS = {
    "test": "test",
    "t": "test",
    "tst": "test",
    "start": "start",
    "stop": "stop",
    "restart": "restart",
}
_NPM_RUN = frozenset({"run", "run-script", "rum", "urn"})
_OWN_COMMANDS = {
    "pnpm": frozenset({"install", "i", "add", "remove", "update", "exec", "dlx", "audit", "outdated", "list", "why"}),
    "yarn": frozenset({"install", "add", "remove", "upgrade", "up", "exec", "dlx", "audit", "npm", "workspaces"}),
    "bun": frozenset({"install", "i", "add", "remove", "update", "x", "test", "build", "pm", "audit", "outdated"}),
}
_DIRECTORY_OPTIONS = frozenset({"--prefix", "--cwd", "-C", "--dir"})


@dataclass(frozen=True, slots=True)
class _ScriptRun:
    name: str
    directory: str | None
    # Named with `run` (or npm's own `test`), so it must exist; pnpm, yarn and bun run a binary of a name that is not
    # a script.
    explicit: bool


# Options that select workspace packages, with the value they take.
_SELECTION_OPTIONS = frozenset({"--filter", "-F", "--workspace", "-w"})


def _script_named(argv: tuple[str, ...]) -> _ScriptRun | None:
    words, options = positional(argv, _DIRECTORY_OPTIONS | _SELECTION_OPTIONS)
    if not words:
        return None
    directory = next((value for name, value in options.items() if value and name in _DIRECTORY_OPTIONS), None)
    program, first = argv[0], words[0]
    if first in _NPM_RUN:
        return _ScriptRun(words[1], directory, explicit=True) if len(words) > 1 else None
    if program == "npm":
        return (
            _ScriptRun(_NPM_SCRIPT_COMMANDS[first], directory, explicit=True) if first in _NPM_SCRIPT_COMMANDS else None
        )
    return None if first in _OWN_COMMANDS[program] else _ScriptRun(first, directory, explicit=False)


def workspace_members(context: Context, directory: str | None) -> list[str]:
    """The directories of the workspace packages the package.json (or pnpm-workspace.yaml) in `directory` declares."""
    patterns = (
        list(_workspaces(context.project.read_text(path)))
        if context.project.exists(path := joined(directory, PACKAGE_JSON))
        else []
    )
    if context.project.exists(pnpm := joined(directory, "pnpm-workspace.yaml")):
        try:
            declared = yaml_support.load(context.project.read_text(pnpm))
        except yaml_support.YamlError:
            declared = None
        packages = declared.get("packages") if isinstance(declared, dict) else None
        patterns += [str(pattern) for pattern in packages] if isinstance(packages, list) else []
    globs = [
        joined(directory, pattern.removeprefix("./").rstrip("/")) for pattern in patterns if not pattern.startswith("!")
    ]
    manifests = (path for path in context.project.files() if path.endswith(f"/{PACKAGE_JSON}"))
    members = (str(PurePosixPath(path).parent) for path in manifests)
    return sorted({member for member in members if any(fnmatchcase(member, glob) for glob in globs)})


# Options that run a script in every workspace package (or the ones a filter names, all of which are taken).
_WORKSPACE_FLAGS = frozenset({"-r", "--recursive", "--filter", "-F", "--workspaces", "-ws", "--workspace", "-w"})


def _in_workspaces(command: Command, context: Context, name: str) -> list[Expansion]:
    """The script `name` of each workspace package that has it."""
    found: list[Expansion] = []
    for member in workspace_members(context, command.directory):
        path = joined(member, PACKAGE_JSON)
        if (script := _json_strings(json_value(context, path, "scripts")).get(name)) is not None:
            found.append(Script(text=script, origin=Origin(path=path, at=("scripts", name)), directory=member))
    return found


def _package_scripts(command: Command, context: Context) -> Iterator[Expansion] | None:
    """`npm test`, `npm run lint`, `pnpm lint`, `yarn run lint`, `bun run lint`: the package.json scripts they run,
    with npm's and yarn's pre and post scripts around them; with `-r`, `--filter` or `--workspaces`, the scripts of
    the workspace packages."""
    if not command.argv or command.argv[0] not in ("npm", *_OWN_COMMANDS) or not (run := _script_named(command.argv)):
        return None
    if any(word.partition("=")[0] in _WORKSPACE_FLAGS for word in command.argv[1:]):
        return iter(_in_workspaces(command, context, run.name))
    path = joined(run.directory or command.directory, PACKAGE_JSON)
    scripts = _json_strings(json_value(context, path, "scripts"))
    if run.name not in scripts:
        if not run.explicit:
            return None
        return iter((Unknown(origin=command.origin, subject=f"the script {run.name}", reason=f"{path} has none"),))
    names = [f"{prefix}{run.name}" for prefix in (("pre", "", "post") if command.argv[0] in ("npm", "yarn") else ("",))]
    return (
        Script(text=scripts[name], origin=Origin(path=path, at=("scripts", name)), directory=run.directory)
        for name in names
        if name in scripts
    )


PACKAGE_SCRIPTS = CommandExpander(name="package.json scripts", expand=_package_scripts)
# Monorepo task runners, which run a script in each workspace package that has it.
_TASK_RUNNERS = frozenset({"turbo", "lerna", "nx"})
_TASK_OPTIONS = frozenset({"-t", "--target", "--targets", "--filter", "--scope", "--projects", "-p", "--parallel"})


def _tasks(runner: str, words: list[str], options: dict[str, str]) -> list[str]:
    """The tasks a task runner runs: `turbo run a b` (or `turbo a b`), `lerna run a`, `nx run-many -t a,b`."""
    if runner == "nx":
        targets = options.get("-t") or options.get("--target") or options.get("--targets") or ""
        return [task for task in targets.split(",") if task] if words[:1] in (["run-many"], ["affected"]) else []
    if words[:1] == ["run"]:
        return words[1:]
    return words if runner == "turbo" else []


def _workspace_tasks(command: Command, context: Context) -> list[Expansion] | None:
    """Each workspace package's script for each task a monorepo task runner runs."""
    argv = resolved(command)
    if (runner := program(argv)) not in _TASK_RUNNERS:
        return None
    words, options = positional(argv, _TASK_OPTIONS)
    return [found for task in _tasks(runner, words, options) for found in _in_workspaces(command, context, task)]


WORKSPACE_TASKS = CommandExpander(name="workspace task runners", expand=_workspace_tasks)


def _task(value: object) -> str | None:
    if isinstance(value, dict):
        value = value.get("command")
    return value if isinstance(value, str) else None


def _deno_tasks(command: Command, context: Context) -> Iterator[Expansion] | None:
    """`deno task lint`: the task in deno.json (or deno.jsonc)."""
    if command.argv[:2] != ("deno", "task") or len(command.argv) < 3:
        return None
    name = command.argv[2]
    path = found_at(context, command.directory, DENO_CONFIG_FILES)
    if path is None or (text := _task(json_value(context, path, "tasks", name, comments=True))) is None:
        return iter((Unknown(origin=command.origin, subject=f"the task {name}", reason="no deno.json defines it"),))
    return iter((Script(text=text, origin=Origin(path=path, at=("tasks", name))),))


DENO_TASKS = CommandExpander(name="deno.json tasks", expand=_deno_tasks)


JS_LANGUAGES = frozenset({JAVASCRIPT, TYPESCRIPT})
PRETTIER_CONFIG_FILES = tuple(
    f"{stem}{suffix}"
    for stem, suffixes in (
        (".prettierrc", ("", ".json", ".json5", ".yaml", ".yml", ".toml", ".js", ".cjs", ".mjs", ".ts")),
        ("prettier.config", (".js", ".cjs", ".mjs", ".ts", ".cts", ".mts")),
    )
    for suffix in suffixes
)


def _read_prettier_key(path: str, text: str) -> Iterator[Fact]:
    """The `prettier` key of package.json: its options, or the name of a shared configuration."""
    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        yield unreadable("prettier", path, error)
        return
    if isinstance(document, dict) and "prettier" in document:
        yield from settings("prettier", path, (("prettier", plain(document["prettier"])),))


PRETTIER_FILES = file_reader("prettier", PRETTIER_CONFIG_FILES)
PRETTIER_IN_PACKAGE_JSON = SettingsReader(name="package.json prettier", files=(PACKAGE_JSON,), read=_read_prettier_key)
BIOME_FILES = file_reader("biome", ("biome.json", "biome.jsonc"))
DPRINT_FILES = file_reader("dprint", ("dprint.json", ".dprint.json"))
OXFMT_FILES = file_reader("oxfmt", (".oxfmtrc.json", ".oxfmtrc.jsonc"))

# Every one of them has a default style, so a configuration file is not needed.
PRETTIER = format_tool(
    name="prettier",
    languages=JS_LANGUAGES,
    can={Enforcement.CHECK: "prettier --check .", Enforcement.APPLY: "prettier --write ."},
    formats=flagged(("prettier",), checks=("--check", "-c", "--list-different", "-l"), applies=("--write", "-w")),
    style=defined_by(files=("prettier",), settings=("prettier",)),
    reads=("prettier", "package.json prettier"),
)
DENO_FMT = format_tool(
    name="deno fmt",
    languages=JS_LANGUAGES,
    can={Enforcement.CHECK: "deno fmt --check", Enforcement.APPLY: "deno fmt"},
    formats=flagged(("deno", "fmt"), checks=("--check",)),
    style=defined_by(),
)
OXFMT = format_tool(
    name="oxfmt",
    languages=JS_LANGUAGES,
    can={Enforcement.CHECK: "oxfmt --check", Enforcement.APPLY: "oxfmt"},
    formats=flagged(("oxfmt",), checks=("--check", "--list-different")),
    style=defined_by(files=("oxfmt",)),
)
DPRINT = format_tool(
    name="dprint",
    languages=JS_LANGUAGES,
    can={Enforcement.CHECK: "dprint check", Enforcement.APPLY: "dprint fmt"},
    formats=flagged(("dprint", "check"), ("dprint", "fmt"), checks=("check",)),
    style=defined_by(files=("dprint",)),
)

JS_SUFFIXES = (".js", ".mjs", ".cjs", ".jsx")
TS_SUFFIXES = (".ts", ".mts", ".cts", ".tsx")
SOURCE_SUFFIXES = (*JS_SUFFIXES, *TS_SUFFIXES)
# app.test.ts, app.spec.js, app_test.ts (Deno), or any source in a __tests__ directory (Jest).
JS_TEST_FILES = TestFiles(
    name="*.test.*, *.spec.* or __tests__/ files",
    languages=JS_LANGUAGES,
    path=re.compile(r"(?:^|/)(?:[^/]*(?:[._]test|\.spec)\.[^/]+|__tests__/.+)$"),
)
_JS_RUNNERS = frozenset({"jest", "vitest", "mocha", "ava"})


def _js_tests(command: Command, _facts: Facts) -> Run | None:
    """jest, vitest, mocha, ava, `playwright test`, `node --test`, `deno test` or `bun test`."""
    argv = resolved(command)
    name = program(argv)
    runs = (
        name in _JS_RUNNERS
        or starts_with(argv, ("playwright", "test"), ("deno", "test"), ("bun", "test"))
        or (name == "node" and "--test" in argv)
    )
    return tested() if runs else None


JS_TESTS = test_runner(
    name="a JavaScript test runner",
    languages=JS_LANGUAGES,
    how="jest, vitest, mocha, node --test, deno test, bun test or playwright (or npm test)",
    runs=_js_tests,
    tests=tests_of(JS_TEST_FILES.name),
)


JEST_CONFIG_FILES = tuple(f"jest.config.{suffix}" for suffix in ("js", "cjs", "mjs", "ts", "mts", "cts", "json"))
VITEST_CONFIG_FILES = tuple(
    f"{tool}.config.{suffix}" for tool in ("vitest", "vite") for suffix in ("js", "cjs", "mjs", "ts", "mts", "cts")
)
_JEST_COLLECTS = re.compile(r"[\"']?collectCoverage[\"']?\s*:\s*true\b")
_VITEST_ENABLES = re.compile(r"\bcoverage\s*:\s*\{[^}]*\benabled\s*:\s*true\b")
BOTH = (Granularity.LINE, Granularity.BRANCH)


def _named_config(name: str) -> Callable[[Command], list[str]]:
    """The configuration file a command of the runner `name` names (`--config`), relative to the project."""

    def named(command: Command) -> list[str]:
        argv = resolved(command)
        return (
            [joined(command.directory, path) for path in option_values(argv, "--config", "-c")]
            if program(argv) == name
            else []
        )

    return named


def _runner_settings(tool: str, key: str, pattern: re.Pattern[str]) -> Read:
    """A runner's settings: a JSON configuration (or package.json's `jest`) as written, code matched by `pattern`."""

    def read(path: str, text: str) -> Iterable[Fact]:
        if path.endswith(PACKAGE_JSON):
            return json_settings(tool, path, text, "jest")
        if path.endswith(".json"):
            return json_settings(tool, path, text)
        return matched_settings(tool, path, text, {key: (pattern, True)})

    return read


JEST_SETTINGS = SettingsReader(
    name="Jest",
    files=(*JEST_CONFIG_FILES, PACKAGE_JSON),
    read=_runner_settings("Jest", "collectCoverage", _JEST_COLLECTS),
    named_by=_named_config("jest"),
)
VITEST_SETTINGS = SettingsReader(
    name="Vitest",
    files=VITEST_CONFIG_FILES,
    read=_runner_settings("Vitest", "coverage.enabled", _VITEST_ENABLES),
    named_by=_named_config("vitest"),
)


def _asks_for_coverage(argv: tuple[str, ...], *flags: str) -> bool:
    return any(word in flags or word in (f"{flag}=true" for flag in flags) for word in argv)


def _test_runner(name: str, tool: str, flags: tuple[str, ...], files: tuple[str, ...], key: str) -> Claim:
    """A test runner that reports coverage when one of `flags` asks it to, or when the configuration it reads (the
    file it is given, else the first of `files`; for Jest, else package.json's `jest`) turns `key` on."""

    def measures(command: Command, facts: Facts) -> Run | None:
        argv = resolved(command)
        if program(argv) != name:
            return None
        if _asks_for_coverage(argv, *flags):
            return measured(*BOTH)
        candidates = _named_config(name)(command) or [joined(command.directory, file) for file in files]
        configuration = facts.first_file(tool, candidates) or joined(command.directory, PACKAGE_JSON)
        setting = facts.setting(tool, key, paths=[configuration])
        return measured(*BOTH, read=[setting]) if setting is not None and setting.value is True else None

    return measures


def _instrumenter(name: str) -> Claim:
    """c8 or nyc, which run a command and report its coverage."""

    def measures(command: Command, _: Facts) -> Run | None:
        return measured(*BOTH) if program(resolved(command)) == name else None

    return measures


def _deno(command: Command, _: Facts) -> Run | None:
    argv = resolved(command)
    asked = any(word.partition("=")[0] == "--coverage" for word in argv)
    return measured(*BOTH) if starts_with(argv, ("deno", "test")) and asked else None


_node = when(all_of(starts(("node",)), with_option("--experimental-test-coverage")), lambda: measured(*BOTH))
# Bun's test runner counts lines (and functions), not branches.
_bun = when(all_of(starts(("bun", "test")), with_option("--coverage")), lambda: measured(Granularity.LINE))


def _reports_branches(name: str, how: str, measures: Claim, reads: tuple[str, ...] = ()) -> Tool:
    return coverage_tool(
        name=name,
        languages=JS_LANGUAGES,
        can={Granularity.LINE: how, Granularity.BRANCH: how},
        measures=measures,
        reads=reads,
    )


# Istanbul (nyc, Jest, Vitest's istanbul provider) and V8 coverage (c8, Vitest, Node.js, Deno) both count branches.
C8 = _reports_branches("c8", "c8", _instrumenter("c8"))
NYC = _reports_branches("nyc", "nyc", _instrumenter("nyc"))
JEST = _reports_branches(
    "Jest",
    "jest --coverage",
    _test_runner("jest", "Jest", ("--coverage", "--collectCoverage"), JEST_CONFIG_FILES, "collectCoverage"),
    reads=("Jest",),
)
VITEST = _reports_branches(
    "Vitest",
    "vitest --coverage",
    _test_runner("vitest", "Vitest", ("--coverage", "--coverage.enabled"), VITEST_CONFIG_FILES, "coverage.enabled"),
    reads=("Vitest",),
)
DENO_TEST = _reports_branches("deno test", "deno test --coverage", _deno)
NODE_TEST = _reports_branches("node --test", "node --test --experimental-test-coverage", _node)
BUN_TEST = coverage_tool(
    name="bun test", languages=JS_LANGUAGES, can={Granularity.LINE: "bun test --coverage"}, measures=_bun
)
# The commands that run a package's binary (`npx c8`).
PACKAGE_RUNNERS = launcher(
    "package runners",
    (
        ("npx",),
        ("pnpx",),
        ("bunx",),
        ("npm", "exec"),
        ("pnpm", "exec"),
        ("pnpm", "dlx"),
        ("yarn", "exec"),
        ("yarn", "dlx"),
        ("bun", "x"),
    ),
    with_values=frozenset({"-p", "--package", "-c", "--call"}),
)

ESLINT_CONFIG_FILES = (
    *(f"eslint.config.{suffix}" for suffix in ("js", "mjs", "cjs", "ts", "mts", "cts")),
    *(f".eslintrc{suffix}" for suffix in ("", ".js", ".cjs", ".json", ".yaml", ".yml")),
)
RUNS_ESLINT = r"(?<![\w-])eslint(?![\w-])(?!\.config)"
RUNS_BIOME_LINT = r"\bbiome\s+(?:lint|check|ci)\b"
RUNS_DENO_LINT = r"\bdeno\s+lint\b"

LINTERS = (
    pattern("eslint", RUNS_ESLINT),
    pattern("biome lint", RUNS_BIOME_LINT),
    pattern("deno lint", RUNS_DENO_LINT),
)


def _linters_required(facts: Facts, _compiler: str | None) -> tuple[Requirement, ...]:
    """One linter is enough: the ones that run, or eslint when none does."""
    linters = tuple(
        required(linter, in_files=False, tools=(tool,)) for linter, tool in zip(LINTERS, _LINTER_TOOLS, strict=True)
    )
    running = tuple(linter for linter in linters if met(WARNINGS, linter, facts, None))
    return running or linters[:1]


# The tools that run each of LINTERS.
_LINTER_TOOLS = ("eslint", "biome", "deno lint")


# JavaScript has no compiler warnings; its linters report what other compilers warn about.
# JavaScript has no compiler warnings; its linters report what other compilers warn about.
WARNINGS = Practice(
    name=PracticeName.WARNINGS,
    languages=JS_LANGUAGES,
    requirements=_linters_required,
    words=Wording(
        kind="JavaScript linters",
        hint="run eslint (or biome lint, or deno lint) in CI",
    ),
)

WARNINGS_AS_ERRORS = Practice(
    name=PracticeName.WARNINGS_AS_ERRORS,
    languages=JS_LANGUAGES,
    requirements=always(
        required(pattern("eslint --max-warnings 0", rf"{RUNS_ESLINT}[^\n]*\s--max-warnings[=\s]+0\b"), in_files=False),
        required(pattern("biome ci", r"\bbiome\s+ci\b|\bbiome\b[^\n]*\s--error-on-warnings\b"), in_files=False),
        # deno lint fails on any finding.
        required(pattern("deno lint", RUNS_DENO_LINT), in_files=False),
    ),
    any_one=True,
    words=Wording(
        kind="warnings as errors",
        searched="CI configuration or the package scripts it runs",
        hint="run eslint with --max-warnings 0 (or biome ci, or deno lint), so that a lint warning fails CI",
    ),
)


def _npm_audit(command: Command, _facts: Facts) -> Run | None:
    """`npm audit`; `npm audit signatures` checks provenance, not vulnerabilities."""
    argv = resolved(command)
    return audited() if starts(("npm", "audit"))(command) and argv[2:3] != ("signatures",) else None


AUDITORS = (
    auditor(name="npm audit", languages=JS_LANGUAGES, how="npm audit", audits=_npm_audit),
    *(
        auditor(
            name=" ".join(prefix), languages=JS_LANGUAGES, how=" ".join(prefix), audits=when(starts(prefix), audited)
        )
        for prefix in (("pnpm", "audit"), ("yarn", "npm", "audit"), ("bun", "audit"))
    ),
    # yarn classic's own audit.
    auditor(
        name="yarn audit", languages=JS_LANGUAGES, how="yarn audit", audits=when(starts(("yarn", "audit")), audited)
    ),
    *multi_ecosystem_audits(JS_LANGUAGES),
)

LOCKFILES = (
    "package-lock.json",
    "npm-shrinkwrap.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lock",
    "bun.lockb",
    "deno.lock",
)
DEPENDENCY_FIELDS = ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies")


JS_PACKAGES = "npm packages"


def _package_json_declares(_path: str, text: str) -> bool:
    manifest = json.loads(text)
    return isinstance(manifest, dict) and any(manifest.get(field) for field in DEPENDENCY_FIELDS)


def _deno_declares(_path: str, text: str) -> bool:
    config = json.loads(strip_json_comments(text))
    return isinstance(config, dict) and bool(config.get("imports"))


PACKAGE_JSON_DEPENDENCIES = manifest_reader(
    name="package.json dependencies", manager=JS_PACKAGES, files=(PACKAGE_JSON,), declares=_package_json_declares
)
DENO_DEPENDENCIES = manifest_reader(
    name="Deno imports", manager=JS_PACKAGES, files=DENO_CONFIG_FILES, declares=_deno_declares
)
JS_LOCKFILES = lockfile_reader(manager=JS_PACKAGES, files=LOCKFILES)
# A package's lockfile is not published, so even a library commits one: its CI and contributors then install the
# dependencies it was tested with.
JS_PACKAGE_MANAGER = PackageManager(
    name=JS_PACKAGES,
    languages=JS_LANGUAGES,
    lock_hint="commit the package manager's lockfile (package-lock.json, pnpm-lock.yaml, yarn.lock, bun.lock or "
    "deno.lock) and install from it in CI (npm ci, pnpm install --frozen-lockfile, yarn install --immutable)",
)


def _package_license(text: str) -> str | None:
    manifest = json.loads(text)
    license_ = manifest.get("license") if isinstance(manifest, dict) else None
    return license_ if isinstance(license_, str) else None


PACKAGE_JSON_LICENSE = declared_license_reader(
    name="package.json license", files=(PACKAGE_JSON,), languages=JS_LANGUAGES, declared=_package_license
)

NODE_MODULES = BuildOutput(
    languages=JS_LANGUAGES,
    name="node_modules",
    globs=ignored_at_top_level("node_modules"),
    paths=directories("node_modules"),
    hint="consider ignoring node_modules/ (and coverage/ and dist/)",
    # dist/ is left out: a GitHub Action written in JavaScript must commit its bundle.
    artifacts=("node_modules/", "/coverage/", "*.tsbuildinfo"),
)

_VERSION = r"(\d+(?:\.(?:\d+|x))*"
RUNTIME_VERSIONS = (
    re.compile(rf"\bnode-version\W+{_VERSION}|lts/[\w*-]+|latest|current|node)"),
    re.compile(r"\bnode:(\d+(?:\.\d+)*)"),
    re.compile(rf"\bdeno-version\W+v?{_VERSION}|canary|lts|rc)"),
    re.compile(r"\bdenoland/deno:(?:\w+-)?(\d+(?:\.\d+)*)"),
    re.compile(rf"\bbun-version\W+{_VERSION}|latest|canary)"),
    re.compile(r"\boven/bun:(\d+(?:\.\d+)*)"),
)

JAVASCRIPT_AND_TYPESCRIPT = Ecosystem(
    label="JavaScript/TypeScript",
    languages=frozenset({JAVASCRIPT, TYPESCRIPT}),
    build_systems=(NPM, DENO),
    source_suffixes={
        **dict.fromkeys(JS_SUFFIXES, JAVASCRIPT),
        **dict.fromkeys(TS_SUFFIXES, TYPESCRIPT),
    },
    toolchain=toolchain_patterns(
        "JavaScript runtime",
        more=RUNTIME_VERSIONS,
        # Not npx alone: other ecosystems' CI runs tools such as jscpd with it.
        commands=r"\bnpm\s+(?:ci|install|i|test|t|run)\b|\b(?:pnpm|yarn)\s+\w|\bnode\s+(?:-\S|[\w./-]+\.[mc]?[jt]s\b)"
        r"|\bdeno\s+(?:test|task|run|check|lint|fmt)\b|\bbun\s+(?:install|test|run)\b",
        setup=("deno", "bun"),
    ),
)

RUNTIME_AXIS = versions_axis("runtime version", "JavaScript runtime", JS_LANGUAGES)
