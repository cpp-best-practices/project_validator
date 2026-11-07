"""JavaScript and TypeScript: packaged with package.json (npm, pnpm, yarn, bun) or deno.json, judged by the Node.js,
Deno and Bun versions CI runs.

Much of a JavaScript project's tooling runs through the scripts of its package.json (`npm run lint`), so the scripts
CI runs count as CI configuration wherever a rule reads more than CI configuration.
"""

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass

from project_validator.core import Context, Result
from project_validator.ecosystems.model import BuildSystem, Ecosystem, ToolchainPatterns, versions_axis
from project_validator.evidence import (
    ci_and_hook_texts,
    configuration,
    existing_texts,
    first_existing,
    json_value,
    scripts_run,
)
from project_validator.facts import Command, Origin, Unknown
from project_validator.facts.expansion import CommandExpander, Expansion, Script, found_at, joined, positional
from project_validator.rules import (
    MULTI_ECOSYSTEM_AUDITS,
    SUGGESTED_LIZARD,
    Analyzer,
    BuildOutputs,
    CoverageTools,
    DeclaredLicense,
    DependencyAudit,
    DependencyManagement,
    Formatter,
    FunctionLimits,
    SecurityLints,
    StaticAnalysis,
    TestSuite,
    TypeChecking,
    WarningPolicy,
    WarningsAsErrors,
    directories,
    ignored_at_top_level,
)
from project_validator.text import Pattern, matching_names, pattern

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


NPM = BuildSystem(name="npm", files=(PACKAGE_JSON,), declared_languages=_declared_by_package)
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


def _script_named(argv: tuple[str, ...]) -> _ScriptRun | None:
    words, options = positional(argv, _DIRECTORY_OPTIONS)
    if not words:
        return None
    directory = next((value for value in options.values() if value), None)
    program, first = argv[0], words[0]
    if first in _NPM_RUN:
        return _ScriptRun(words[1], directory, explicit=True) if len(words) > 1 else None
    if program == "npm":
        return (
            _ScriptRun(_NPM_SCRIPT_COMMANDS[first], directory, explicit=True) if first in _NPM_SCRIPT_COMMANDS else None
        )
    return None if first in _OWN_COMMANDS[program] else _ScriptRun(first, directory, explicit=False)


def _package_scripts(command: Command, context: Context) -> Iterator[Expansion] | None:
    """`npm test`, `npm run lint`, `pnpm lint`, `yarn run lint`, `bun run lint`: the package.json scripts they run,
    with npm's and yarn's pre and post scripts around them."""
    if not command.argv or command.argv[0] not in ("npm", *_OWN_COMMANDS) or not (run := _script_named(command.argv)):
        return None
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


PRETTIER_CONFIG_FILES = tuple(
    f"{stem}{suffix}"
    for stem, suffixes in (
        (".prettierrc", ("", ".json", ".json5", ".yaml", ".yml", ".toml", ".js", ".cjs", ".mjs", ".ts")),
        ("prettier.config", (".js", ".cjs", ".mjs", ".ts", ".cts", ".mts")),
    )
    for suffix in suffixes
)
FORMATTER_CONFIG_FILES = (*PRETTIER_CONFIG_FILES, "biome.json", "biome.jsonc", "dprint.json", ".dprint.json")


def _formatter_config(context: Context) -> str | None:
    if found := first_existing(context, FORMATTER_CONFIG_FILES):
        return found
    return PACKAGE_JSON if json_value(context, PACKAGE_JSON, "prettier") is not None else None


# Every one of them has a default style, so a configuration file is not needed.
FORMATTERS = Formatter(
    name="prettier, biome, deno fmt or dprint",
    config_file=_formatter_config,
    runs=(
        pattern("prettier", r"\bprettier\b[^\n]*\s(?:--check|-c|--list-different|-l)\b"),
        pattern("biome", r"\bbiome\s+(?:format|check|ci)\b"),
        pattern("deno fmt", r"\bdeno\s+fmt\b[^\n]*\s--check\b"),
        pattern("dprint", r"\bdprint\s+check\b"),
    ),
    hint="consider a CI job that runs prettier --check . (or biome ci, deno fmt --check or dprint check)",
    default_style=True,
    texts=_run_texts,
)

JS_SUFFIXES = (".js", ".mjs", ".cjs", ".jsx")
TS_SUFFIXES = (".ts", ".mts", ".cts", ".tsx")
SOURCE_SUFFIXES = (*JS_SUFFIXES, *TS_SUFFIXES)
# app.test.ts, app.spec.js, app_test.ts (Deno), or any source in a __tests__ directory (Jest).
TEST_FILE = re.compile(r"(?:^|/)(?:[^/]*(?:[._]test|\.spec)\.[^/]+|__tests__/.+)$")
RUNS_TESTS = (
    pattern(
        "JavaScript tests",
        r"\b(?:jest|vitest|mocha|ava|playwright\s+test)\b|\bnode\s+(?:[^\n]*\s)?--test\b|\b(?:deno|bun)\s+test\b"
        r"|\bnpm\s+(?:t|test|run\s+test)\b|\b(?:pnpm|yarn)\s+(?:run\s+)?test\b",
    ),
)


def _javascript_tests(context: Context) -> Result:
    tests = [path for path in context.project.files() if path.endswith(SOURCE_SUFFIXES) and TEST_FILE.search(path)]
    if not tests:
        return Result.failed("no JavaScript or TypeScript tests found (*.test.*, *.spec.* or __tests__/ files)")
    return Result.passed(f"JavaScript or TypeScript tests found in {len(tests)} file(s)")


TESTS = TestSuite(
    found=_javascript_tests,
    runs=RUNS_TESTS,
    runner="jest, vitest, mocha, node --test, deno test, bun test or playwright (or npm test)",
    texts=_run_texts,
)

# Istanbul (nyc, jest, vitest's istanbul provider) and V8 coverage (c8, vitest, node, deno) both report branches.
COVERAGE_CONFIG_FILES = tuple(
    f"{tool}.config.{suffix}" for tool in ("jest", "vitest", "vite") for suffix in ("js", "cjs", "mjs", "ts", "mts")
)


def _coverage_texts(context: Context) -> tuple[str, ...]:
    return (*_run_texts(context), *existing_texts(context, (PACKAGE_JSON, *COVERAGE_CONFIG_FILES)))


COVERAGE = CoverageTools(
    searched="CI configuration, the package scripts it runs, or the test runner's settings",
    texts=_coverage_texts,
    branch=(
        pattern("c8", r"(?<![\w./@-])c8\s"),
        pattern("nyc", r"(?<![\w./@-])nyc\s"),
        pattern("jest --coverage", r"\bjest\b[^\n]*\s--coverage\b|[\"']?collectCoverage[\"']?\s*:\s*true\b"),
        pattern(
            "vitest --coverage",
            r"\bvitest\b[^\n]*\s--coverage\b|\bcoverage\s*:\s*\{[^}]*\benabled\s*:\s*true\b",
        ),
        pattern("deno test --coverage", r"\bdeno\s+test\b[^\n]*\s--coverage\b"),
        pattern("node --experimental-test-coverage", r"\bnode\b[^\n]*\s--experimental-test-coverage\b"),
    ),
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

DEPENDENCY_AUDIT = DependencyAudit(
    tools=(
        # npm audit signatures checks provenance, not known vulnerabilities.
        pattern("npm audit", r"\bnpm\s+audit\b(?!\s+signatures)"),
        pattern("pnpm audit", r"\bpnpm\s+audit\b"),
        pattern("yarn audit", r"\byarn\s+(?:npm\s+)?audit\b"),
        pattern("bun audit", r"\bbun\s+audit\b"),
        *MULTI_ECOSYSTEM_AUDITS,
    ),
    hint="consider running npm audit (or pnpm audit, yarn npm audit or bun audit) in CI",
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


BIOME_CONFIG = configuration(("biome.json", "biome.jsonc"))
DENO_CONFIG = configuration(DENO_CONFIG_FILES)

STATIC_ANALYSIS = StaticAnalysis(
    analyzers=(
        Analyzer(name="eslint", runs=re.compile(RUNS_ESLINT), configured=configuration(ESLINT_CONFIG_FILES)),
        Analyzer(name="biome lint", runs=re.compile(RUNS_BIOME_LINT), configured=BIOME_CONFIG),
        Analyzer(name="deno lint", runs=re.compile(RUNS_DENO_LINT), configured=DENO_CONFIG),
    ),
    texts=_run_texts,
    hint="consider running eslint (or biome lint, or deno lint) in CI",
)

TSCONFIG_FILES = ("tsconfig.json", "jsconfig.json")
# @tsconfig/strictest turns on strict, and more.
STRICTEST_BASE = re.compile(r"@tsconfig/strictest\b")


def _strict_type_checking(context: Context) -> str | None:
    """Where strict type checking is enabled: a tsconfig.json, or Deno, which checks strictly unless told not to."""
    for path in TSCONFIG_FILES:
        if json_value(context, path, "compilerOptions", "strict", comments=True) is True:
            return f'"strict": true in {path}'
        extends = json_value(context, path, "extends", comments=True)
        bases = extends if isinstance(extends, list) else [extends]
        if any(isinstance(base, str) and STRICTEST_BASE.search(base) for base in bases):
            return f"@tsconfig/strictest in {path}"
    deno = first_existing(context, DENO_CONFIG_FILES)
    if deno is not None and json_value(context, deno, "compilerOptions", "strict", comments=True) is not False:
        return f"Deno's default strict mode ({deno})"
    return None


TYPE_CHECKING = TypeChecking(
    checkers=(
        Analyzer(name="tsc", runs=re.compile(r"(?<![\w-])(?:vue-)?tsc\b"), configured=configuration(TSCONFIG_FILES)),
        # deno test type-checks the code it runs, as deno check does.
        Analyzer(name="deno check", runs=re.compile(r"\bdeno\s+(?:check|test)\b"), configured=DENO_CONFIG),
    ),
    texts=_run_texts,
    strict=_strict_type_checking,
    hint="consider running tsc --noEmit in CI (JavaScript is checked with checkJs in a jsconfig.json, or deno check)",
    strict_hint='consider enabling strict mode: "strict": true in the compilerOptions of tsconfig.json',
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
        FORMATTERS,
        COVERAGE,
        TESTS,
        WARNINGS,
        WARNINGS_AS_ERRORS,
        SECURITY_LINTS,
        DEPENDENCY_AUDIT,
        FunctionLimits(without_lizard=_max_lines_per_function),
        STATIC_ANALYSIS,
        TYPE_CHECKING,
        DEPENDENCIES,
        NODE_MODULES,
        LICENSE,
    ),
)
