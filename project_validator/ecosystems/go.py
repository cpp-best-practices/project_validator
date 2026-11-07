"""Go: built with Go modules, judged by the Go versions CI runs and the go tool's own test, vet and format commands."""

import re
import shlex
from collections.abc import Iterator

from project_validator.core import Context, Result, Status
from project_validator.ecosystems.model import BuildSystem, Ecosystem, ToolchainPatterns, versions_axis
from project_validator.evidence import existing_texts, first_existing
from project_validator.facts import Command, Fact, Facts, resolved
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.arguments import has_option, positional, program
from project_validator.facts.audit import audited, auditor
from project_validator.facts.coverage import Granularity, coverage_tool, measured
from project_validator.facts.expansion import Action, CommandExpander, Expansion, Launched
from project_validator.facts.expansion import Action as AuditAction
from project_validator.facts.formatting import Enforcement, flagged, format_tool, formatted
from project_validator.facts.settings import SettingsReader, json_settings, toml_settings, yaml_settings
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import Definition, Run, defined_by, either, starts, when
from project_validator.rules import (
    SUGGESTED_LIZARD,
    BuildOutputs,
    DependencyManagement,
    FunctionLimits,
    Hardening,
    SecurityLints,
    WarningPolicy,
    ci_configuration,
    directories,
    ignored_at_top_level,
)
from project_validator.text import Pattern, matching_names, pattern
from project_validator.tools.audits import multi_ecosystem_audits

_USE = re.compile(r"^\s*(?:use\s+)?(?:\(\s*)?(\.{1,2}/[^\s)]*|\.)\s*\)?\s*$", re.MULTILINE)


def _go_work_members(text: str) -> tuple[str, ...]:
    """The modules a go.work file uses (`use ./api`, or a `use (...)` block)."""
    if not re.search(r"^\s*use\b", text, re.MULTILINE):
        return ()
    return tuple(match[1] for match in _USE.finditer(text) if match[1] != ".")


GO_LANGUAGE = frozenset({"Go"})
GO_MODULES = BuildSystem(
    name="Go modules",
    files=("go.mod", "go.sum", "go.work", "go.work.sum"),
    languages=GO_LANGUAGE,
    members=_go_work_members,
)

GOLANGCI_CONFIG_FILES = (".golangci.yml", ".golangci.yaml", ".golangci.toml", ".golangci.json")
RUNS_GOLANGCI_LINT = r"\bgolangci-lint\b(?!\s+fmt)|\bgolangci/golangci-lint-action\b"


# gofmt and the tools in its style list the files they would change (`-l`, `-d`), which CI fails on
# (`test -z "$(gofmt -l .)"`), or rewrite them (`-w`; `go fmt` runs `gofmt -l -w`).
_GOFMT_STYLE = (("gofmt",), ("gofumpt",), ("goimports",))

_GO_RUN_VALUES = frozenset({"-C", "-exec", "-tags", "-ldflags", "-gcflags", "-mod", "-modfile", "-o", "-p"})


def _go_run(command: Command, _context: Context) -> list[Expansion] | None:
    """`go run <package>[@version] args` and `go tool <name> args` run the program the package's last element names
    (`go run github.com/golangci/golangci-lint/v2/cmd/golangci-lint@v2.6.1 run`); a local package (`.`) is the
    project's own code."""
    argv = resolved(command)
    if program(argv) != "go" or argv[1:2] not in (("run",), ("tool",)):
        return None
    words, _ = positional(argv[1:], _GO_RUN_VALUES)
    if not words or words[0].startswith((".", "/")) or words[0].endswith(".go"):
        return []
    name = words[0].partition("@")[0].rstrip("/").rsplit("/", 1)[-1]
    return [Launched(argv=(name, *argv[argv.index(words[0]) + 1 :]))]


GO_RUN = CommandExpander(name="go run and go tool", expand=_go_run)

# golangci-lint runs the formatters its configuration enables (`formatters.enable` since v2, `linters.enable` before).
_GOFMT_FORMATTERS = frozenset({"gofmt", "gofumpt", "goimports", "gci", "golines", "swaggo"})


def _read_golangci(path: str, text: str) -> Iterator[Fact]:
    if path.endswith(".json"):
        return json_settings("golangci-lint", path, text)
    if path.endswith(".toml"):
        return toml_settings("golangci-lint", path, text)
    return yaml_settings("golangci-lint", path, text)


GOLANGCI_SETTINGS = SettingsReader(name="golangci-lint", files=GOLANGCI_CONFIG_FILES, read=_read_golangci)


def _golangci_formatters(command: Command, facts: Facts) -> Run | None:
    """`golangci-lint run`, which fails on what the formatters its configuration enables would change."""
    argv = resolved(command)
    if program(argv) != "golangci-lint" or argv[1:2] != ("run",):
        return None
    read = [
        setting
        for setting in facts.settings("golangci-lint")
        if setting.key in ("formatters.enable", "linters.enable")
        and isinstance(setting.value, tuple)
        and _GOFMT_FORMATTERS & set(map(str, setting.value))
    ]
    return formatted(command, facts, checks=True, read=read) if read else None


GOLANGCI_LINT_ACTION = Action(
    name="golangci/golangci-lint-action",
    runs=lambda inputs: (("golangci-lint", "run", *shlex.split(inputs.get("args", ""))),),
)

GOFMT = format_tool(
    name="gofmt",
    languages=GO_LANGUAGE,
    can={Enforcement.CHECK: 'test -z "$(gofmt -l .)"', Enforcement.APPLY: "gofmt -w ."},
    formats=either(
        flagged(*_GOFMT_STYLE, checks=("-l", "-d"), applies=("-w",)),
        flagged(("go", "fmt"), checks=()),
        flagged(("golangci-lint", "fmt"), checks=("--diff", "-d")),
        _golangci_formatters,
    ),
    style=defined_by(),
    reads=("golangci-lint",),
)

# The go tool measures statement coverage only.
_COVER = ("-cover", "-coverprofile", "-covermode", "-coverpkg")


def _go_cover(command: Command, _: Facts) -> Run | None:
    """`go test -cover` (or `go build -cover`), which counts statements (and so lines): nothing finer."""
    argv = resolved(command)
    if program(argv) != "go" or argv[1:2] not in (("test",), ("build",)) or not has_option(argv, *_COVER):
        return None
    return measured(Granularity.LINE, Granularity.STATEMENT)


GO_COVER = coverage_tool(
    name="go test -cover",
    languages=GO_LANGUAGE,
    can={Granularity.LINE: "go test -cover", Granularity.STATEMENT: "go test -cover"},
    measures=_go_cover,
)

GO_TEST_FILES = TestFiles(
    name="Test functions in *_test.go files",
    languages=GO_LANGUAGE,
    path=re.compile(r"_test\.go$"),
    contains=re.compile(r"^func\s+(?:Test|Fuzz|Example)\w*\s*\(", re.MULTILINE),
)


def _go_test(command: Command, _facts: Facts) -> Run | None:
    argv = resolved(command)
    return tested() if argv[:2] == ("go", "test") or program(argv) == "gotestsum" else None


GO_TEST = test_runner(
    name="go test", languages=GO_LANGUAGE, how="go test", runs=_go_test, tests=tests_of(GO_TEST_FILES.name)
)


def _lint_texts(context: Context) -> tuple[str, ...]:
    return (*context.ci_texts, *existing_texts(context, GOLANGCI_CONFIG_FILES))


# The Go compiler has no warnings; go vet and staticcheck report what other compilers warn about.
# golangci-lint runs both by default.
GO_LINTS = (
    pattern("go vet", rf"\bgo\s+vet\b|{RUNS_GOLANGCI_LINT}"),
    pattern("staticcheck", rf"\bstaticcheck\b|{RUNS_GOLANGCI_LINT}"),
)


def _required_lints(_: Context) -> tuple[Pattern, ...]:
    return GO_LINTS


WARNINGS = WarningPolicy(
    kind="Go linters", recognised=GO_LINTS, required=_required_lints, texts=_lint_texts, separator=", "
)

SECURITY_LINTS = SecurityLints(texts=_lint_texts, lints=(pattern("gosec", r"\bgosec\b|\bsecurego/gosec\b"),))

AUDITORS = (
    auditor(
        name="govulncheck",
        languages=GO_LANGUAGE,
        how="govulncheck ./...",
        audits=when(starts(("govulncheck",)), audited),
    ),
    *multi_ecosystem_audits(GO_LANGUAGE),
)
GOVULNCHECK_ACTION = AuditAction(name="golang/govulncheck-action", runs=lambda _inputs: (("govulncheck", "./..."),))

MAIN_PACKAGE = re.compile(r"^package\s+main\b", re.MULTILINE)
PIE = pattern("-buildmode=pie", r"-buildmode[=\s]+pie\b|\bbuildmode:\s*[\"']?pie\b")
BUILD_SETTINGS_FILES = ("Makefile", "GNUmakefile", "makefile", "justfile", ".goreleaser.yml", ".goreleaser.yaml")


def _builds_a_program(context: Context) -> bool:
    sources = (path for path in context.project.files() if path.endswith(".go") and not path.endswith("_test.go"))
    return any(MAIN_PACKAGE.search(context.project.read_text(path)) for path in sources)


def _position_independent(context: Context) -> Result:
    """Go is memory safe and bounds checked; what the build adds is a position-independent executable, so that the
    program's own code is randomised in memory (ASLR). That is the default on Windows and macOS, not on Linux."""
    if not _builds_a_program(context):
        return Result(status=Status.SKIP, message="no Go program (package main) is built; a library has no binary")
    if matching_names((*context.ci_texts, *existing_texts(context, BUILD_SETTINGS_FILES)), (PIE,)):
        return Result.passed(f"hardening options are enabled: {PIE.name}")
    return Result.failed(
        "Go programs are not built as position-independent executables",
        "build them with -buildmode=pie (GOFLAGS=-buildmode=pie, or buildmode: pie in .goreleaser.yaml); "
        "it is the default on Windows and macOS but not on Linux",
    )


HARDENING = Hardening(texts=ci_configuration, judge=_position_independent)

FUNLEN = re.compile(r"(?<![\w-])funlen\b")


def _funlen_enforced(context: Context) -> Result:
    """golangci-lint's funlen linter limits function length, when it is enabled and golangci-lint runs."""
    config = first_existing(context, GOLANGCI_CONFIG_FILES)
    enabled = config is not None and FUNLEN.search(context.project.read_text(config))
    if not enabled:
        return Result.failed(
            f"function length is never limited; enable golangci-lint's funlen linter or run {SUGGESTED_LIZARD} in CI"
        )
    if not matching_names(context.ci_texts, (pattern("golangci-lint", RUNS_GOLANGCI_LINT),)):
        return Result.warned(f"funlen is enabled in {config} but CI does not run golangci-lint")
    return Result.passed(f"function length is limited with golangci-lint funlen ({config})")


# golangci-lint enables a few linters by default; a configuration that enables more asks for more.
def _more_linters(facts: Facts) -> Iterator[str]:
    """The golangci-lint configurations that enable linters beyond its defaults (`linters.enable`, `enable-all`, or
    `linters.default: all`)."""
    enabling = {"linters.enable", "linters.enable-all"}
    for setting in facts.settings("golangci-lint"):
        more = setting.value not in ((), False, None) if setting.key in enabling else setting.value == "all"
        if setting.key in (*enabling, "linters.default") and more:
            yield setting.path


def _golangci_lint(command: Command, _facts: Facts) -> Run | None:
    argv = resolved(command)
    return analysed() if program(argv) == "golangci-lint" and argv[1:2] == ("run",) else None


# go vet and staticcheck are required as warnings (see WARNINGS); static analysis asks for golangci-lint's others.
GOLANGCI_LINT = analyzer(
    name="golangci-lint",
    languages=GO_LANGUAGE,
    how="golangci-lint (with linters enabled beyond its defaults in a .golangci.yml)",
    analyses=_golangci_lint,
    rules=Definition(found=_more_linters, default=False),
    reads=("golangci-lint",),
)


REQUIRE = re.compile(r"^\s*require\b", re.MULTILINE)


def _requires_modules(context: Context) -> str | None:
    if context.project.exists("go.mod") and REQUIRE.search(context.project.read_text("go.mod")):
        return "managed with Go modules"
    return None


def _go_sum(context: Context) -> str | None:
    return "go.sum" if context.committed("go.sum") else None


DEPENDENCIES = DependencyManagement(
    managed=_requires_modules,
    locked=_go_sum,
    lock_hint="commit go.sum, which holds the checksum of every module go.mod requires",
    vendor_outputs=("vendor/modules.txt",),
)


BUILD_OUTPUTS = BuildOutputs(
    name="Go test binaries and coverage profiles",
    globs=ignored_at_top_level(r"\*\.test|\*\.out|bin"),
    paths=(*directories("bin"), "app.test", "coverage.out"),
    hint="consider ignoring *.test and *.out (and bin/ if binaries are built there)",
    artifacts=("*.test", "*.out", "/bin/"),
)

_GO_VERSION = r"(\d+\.\d+(?:\.\d+|\.x)?|stable|oldstable)"

GO = Ecosystem(
    label="Go",
    languages=GO_LANGUAGE,
    build_systems=(GO_MODULES,),
    source_suffixes={".go": "Go"},
    toolchain=ToolchainPatterns(
        language="Go",
        versions=(re.compile(rf"\bgo-version\W+{_GO_VERSION}"), re.compile(r"\bgolang:(\d+\.\d+)")),
        usage=re.compile(r"\bgo\s+(?:build|test|vet|run|mod|install|generate)\b|\bsetup-go\b"),
    ),
    rules=(
        versions_axis("Go version", "Go"),
        WARNINGS,
        HARDENING,
        SECURITY_LINTS,
        FunctionLimits(without_lizard=_funlen_enforced),
        DEPENDENCIES,
        BUILD_OUTPUTS,
    ),
)
