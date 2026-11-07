"""JavaScript and TypeScript: packaged with package.json (npm, pnpm, yarn, bun) or deno.json, judged by the Node.js,
Deno and Bun versions CI runs.

Much of a JavaScript project's tooling runs through the scripts of its package.json (`npm run lint`), so the scripts
CI runs count as CI configuration wherever a rule reads more than CI configuration.
"""

import json
import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import PurePosixPath

from project_validator import yaml_support
from project_validator.core import Context, Result
from project_validator.ecosystems.model import BuildSystem, Ecosystem, ToolchainPatterns, versions_axis
from project_validator.evidence import (
    ci_and_hook_texts,
    existing_texts,
    first_existing,
    json_value,
    scripts_run,
)
from project_validator.facts import Command, Fact, Facts, Origin, Unknown, resolved
from project_validator.facts.arguments import option_values, positional, program
from project_validator.facts.audit import audited, auditor
from project_validator.facts.coverage import Granularity, coverage_tool, measured
from project_validator.facts.expansion import CommandExpander, Expansion, Script, found_at, joined, launcher
from project_validator.facts.formatting import Enforcement, flagged, format_tool
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
from project_validator.facts.tools import Claim, Run, Tool, defined_by, starts, when
from project_validator.rules import (
    SUGGESTED_LIZARD,
    BuildOutputs,
    DeclaredLicense,
    DependencyManagement,
    FunctionLimits,
    SecurityLints,
    WarningPolicy,
    WarningsAsErrors,
    directories,
    ignored_at_top_level,
)
from project_validator.text import Pattern, matching_names, pattern
from project_validator.tools.audits import multi_ecosystem_audits

JAVASCRIPT = "JavaScript"
TYPESCRIPT = "TypeScript"
PACKAGE_JSON = "package.json"
DENO_CONFIG_FILES = ("deno.json", "deno.jsonc")
# A package.json that names what it provides is a JavaScript package, even before any source is found.
ENTRY_POINTS = ("main", "module", "exports", "bin")


def _declared_by_package(text: str) -> frozenset[str]:
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


def _scripts(context: Context) -> dict[str, str]:
    """The package.json scripts and deno.json tasks, by name."""
    tasks = (json_value(context, path, "tasks", comments=True) for path in DENO_CONFIG_FILES)
    found = {name: script for value in tasks for name, script in _json_strings(value).items()}
    return {**found, **_json_strings(json_value(context, PACKAGE_JSON, "scripts"))}


# `npm test`, `npm run lint`, `pnpm lint`, `yarn run lint`, `bun run lint`, `deno task lint`.
RUNS_SCRIPT = re.compile(
    r"\bnpm\s+(?:run(?:-script)?\s+(?P<npm>[\w:.-]+)|(?P<npm_lifecycle>test|t|start)\b)"
    r"|\b(?:pnpm|yarn)\s+(?:run\s+)?(?P<pnpm>[\w:.-]+)"
    r"|\bbun\s+run\s+(?P<bun>[\w:.-]+)"
    r"|\bdeno\s+task\s+(?P<deno>[\w:.-]+)"
)
NPM_LIFECYCLE_ALIASES = {"t": "test"}


def _named_scripts(text: str) -> Iterator[str]:
    for match in RUNS_SCRIPT.finditer(text):
        name = next(group for group in match.groups() if group)
        yield NPM_LIFECYCLE_ALIASES.get(name, name)


def _pre_and_post(name: str) -> tuple[str, ...]:
    return (f"pre{name}", f"post{name}")


def _run_texts(context: Context) -> tuple[str, ...]:
    """CI configuration, pre-commit hooks, and the package scripts they run."""
    texts = ci_and_hook_texts(context)
    return (*texts, *scripts_run(texts, _scripts(context), _named_scripts, _pre_and_post))


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
        or argv[:2] in (("playwright", "test"), ("deno", "test"), ("bun", "test"))
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
    return measured(*BOTH) if program(argv) == "deno" and argv[1:2] == ("test",) and asked else None


def _node(command: Command, _: Facts) -> Run | None:
    argv = resolved(command)
    return measured(*BOTH) if program(argv) == "node" and "--experimental-test-coverage" in argv else None


def _bun(command: Command, _: Facts) -> Run | None:
    """Bun's test runner counts lines (and functions), not branches."""
    argv = resolved(command)
    return (
        measured(Granularity.LINE)
        if program(argv) == "bun" and argv[1:2] == ("test",) and "--coverage" in argv
        else None
    )


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


def _linters_required(context: Context) -> tuple[Pattern, ...]:
    """One linter is enough: the ones that run, or eslint when none does."""
    texts = _run_texts(context)
    return tuple(linter for linter in LINTERS if matching_names(texts, (linter,))) or LINTERS[:1]


# JavaScript has no compiler warnings; its linters report what other compilers warn about.
WARNINGS = WarningPolicy(
    kind="JavaScript linters", recognised=LINTERS, required=_linters_required, texts=_run_texts, separator=", "
)

WARNINGS_AS_ERRORS = WarningsAsErrors(
    flags=(
        pattern("eslint --max-warnings 0", rf"{RUNS_ESLINT}[^\n]*\s--max-warnings[=\s]+0\b"),
        pattern("biome ci", r"\bbiome\s+ci\b|\bbiome\b[^\n]*\s--error-on-warnings\b"),
        # deno lint fails on any finding.
        pattern("deno lint", RUNS_DENO_LINT),
    ),
    texts=_run_texts,
    searched="CI configuration or the package scripts it runs",
    hint="run eslint with --max-warnings 0 (or biome ci, or deno lint), so that a lint warning fails CI",
)


def _security_texts(context: Context) -> tuple[str, ...]:
    return (*_run_texts(context), *existing_texts(context, (PACKAGE_JSON, *ESLINT_CONFIG_FILES)))


SECURITY_LINTS = SecurityLints(
    texts=_security_texts,
    lints=(
        pattern("eslint-plugin-security", r"\beslint-plugin-security\b|@microsoft/eslint-plugin-sdl\b"),
        pattern(
            "semgrep JavaScript rules",
            r"\bsemgrep\b[^\n]*--config[=\s]+[\"']?(?:p/)?(?:javascript|typescript|nodejs|react|expressjs)\b",
        ),
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

# The rule's options are "off", 0, or anything else (a severity, or a severity and its limit).
MAX_LINES_PER_FUNCTION = re.compile(
    r"""["']?max-lines-per-function["']?\s*:(?!\s*\[?\s*(?:["']off["']|0\b))""", re.IGNORECASE
)


def _max_lines_per_function(context: Context) -> Result:
    """eslint's max-lines-per-function rule limits function length, when it is enabled and eslint runs."""
    config = first_existing(context, ESLINT_CONFIG_FILES)
    if config is None or not MAX_LINES_PER_FUNCTION.search(context.project.read_text(config)):
        return Result.failed(
            "function length is never limited; enable eslint's max-lines-per-function rule "
            f"or run {SUGGESTED_LIZARD} in CI"
        )
    if not matching_names(_run_texts(context), LINTERS[:1]):
        return Result.warned(f"max-lines-per-function is enabled in {config} but CI does not run eslint")
    return Result.passed(f"function length is limited with eslint max-lines-per-function ({config})")


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


def _declared_dependencies(context: Context) -> str | None:
    if any(json_value(context, PACKAGE_JSON, field) for field in DEPENDENCY_FIELDS):
        return f"declared in {PACKAGE_JSON}"
    deno = next((path for path in DENO_CONFIG_FILES if json_value(context, path, "imports", comments=True)), None)
    return f"declared in {deno}" if deno else None


def _lockfile(context: Context) -> str | None:
    return next((path for path in LOCKFILES if context.committed(path)), None)


# A package's lockfile is not published, so even a library commits one: its CI and contributors then install the
# dependencies it was tested with.
DEPENDENCIES = DependencyManagement(
    managed=_declared_dependencies,
    locked=_lockfile,
    lock_hint="commit the package manager's lockfile (package-lock.json, pnpm-lock.yaml, yarn.lock, bun.lock or "
    "deno.lock) and install from it in CI (npm ci, pnpm install --frozen-lockfile, yarn install --immutable)",
)


def _package_license(context: Context) -> str | None:
    license_ = json_value(context, PACKAGE_JSON, "license")
    return license_ if isinstance(license_, str) else None


LICENSE = DeclaredLicense(manifest=PACKAGE_JSON, declared=_package_license)

NODE_MODULES = BuildOutputs(
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
    toolchain=ToolchainPatterns(
        language="JavaScript runtime",
        versions=RUNTIME_VERSIONS,
        # Not npx alone: other ecosystems' CI runs tools such as jscpd with it.
        usage=re.compile(
            r"\bnpm\s+(?:ci|install|i|test|t|run)\b|\b(?:pnpm|yarn)\s+\w|\bnode\s+(?:-\S|[\w./-]+\.[mc]?[jt]s\b)|\bsetup-(?:deno|bun)\b"
            r"|\bdeno\s+(?:test|task|run|check|lint|fmt)\b|\bbun\s+(?:install|test|run)\b"
        ),
    ),
    rules=(
        versions_axis("runtime version", "JavaScript runtime"),
        WARNINGS,
        WARNINGS_AS_ERRORS,
        SECURITY_LINTS,
        FunctionLimits(without_lizard=_max_lines_per_function),
        DEPENDENCIES,
        NODE_MODULES,
        LICENSE,
    ),
)
