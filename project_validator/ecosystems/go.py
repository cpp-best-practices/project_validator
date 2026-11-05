"""Go: built with Go modules, judged by the Go versions CI runs and the go tool's own test, vet and format commands."""

import re
from pathlib import PurePosixPath

from project_validator.core import Context, Result, Status
from project_validator.ecosystems.model import BuildSystem, Ecosystem, ToolchainPatterns, versions_axis
from project_validator.evidence import existing_texts, first_existing
from project_validator.rules import (
    MULTI_ECOSYSTEM_AUDITS,
    SUGGESTED_LIZARD,
    BuildOutputs,
    CoverageTools,
    DependencyAudit,
    Formatter,
    FunctionLimits,
    Hardening,
    SecurityLints,
    TestSuite,
    WarningPolicy,
    directories,
    ignored_at_top_level,
)
from project_validator.text import Pattern, matching_names, pattern

GO_MODULES = BuildSystem(
    name="Go modules", files=("go.mod", "go.sum", "go.work", "go.work.sum"), languages=frozenset({"Go"})
)

GOLANGCI_CONFIG_FILES = (".golangci.yml", ".golangci.yaml", ".golangci.toml", ".golangci.json")
RUNS_GOLANGCI_LINT = r"\bgolangci-lint\b(?!\s+fmt)|\bgolangci/golangci-lint-action\b"


def _ci_texts(context: Context) -> tuple[str, ...]:
    return context.ci_texts


def _no_config(_: Context) -> str | None:
    """gofmt has one style and no configuration."""
    return None


GOFMT = Formatter(
    name="gofmt",
    config_file=_no_config,
    runs=(
        pattern("gofmt", r"(?<![\w-])gofmt\b"),
        pattern("gofumpt", r"\bgofumpt\b"),
        pattern("goimports", r"\bgoimports\b"),
        pattern("golangci-lint fmt", r"\bgolangci-lint\s+fmt\b"),
    ),
    hint='consider a CI job that fails when gofmt -l . lists files (test -z "$(gofmt -l .)")',
    default_style=True,
)

# The go tool measures statement coverage only.
COVERAGE = CoverageTools(
    searched="CI configuration",
    texts=_ci_texts,
    granularity="statement",
    branch=(pattern("go test -cover", r"\bgo\s+test\b[^\n]*\s-(?:cover|coverprofile|covermode)\b"),),
)

GO_TEST = re.compile(r"^func\s+(?:Test|Fuzz|Example)\w*\s*\(", re.MULTILINE)


def _go_tests_result(context: Context) -> Result:
    test_files = (path for path in context.project.files() if PurePosixPath(path).name.endswith("_test.go"))
    count = sum(1 for path in test_files if GO_TEST.search(context.project.read_text(path)))
    if count == 0:
        return Result.failed("no Go tests found (Test functions in *_test.go files)")
    return Result.passed(f"Go tests found in {count} file(s)")


TESTS = TestSuite(found=_go_tests_result, runs=(pattern("go test", r"\bgo\s+test\b|\bgotestsum\b"),), runner="go test")


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

DEPENDENCY_AUDIT = DependencyAudit(
    tools=(pattern("govulncheck", r"\bgovulncheck\b"), *MULTI_ECOSYSTEM_AUDITS),
    hint="consider running govulncheck ./... in CI (golang/govulncheck-action)",
)

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


HARDENING = Hardening(texts=_ci_texts, judge=_position_independent)

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
    languages=frozenset({"Go"}),
    build_systems=(GO_MODULES,),
    source_suffixes={".go": "Go"},
    toolchain=ToolchainPatterns(
        language="Go",
        versions=(re.compile(rf"\bgo-version\W+{_GO_VERSION}"), re.compile(r"\bgolang:(\d+\.\d+)")),
        usage=re.compile(r"\bgo\s+(?:build|test|vet|run|mod|install|generate)\b|\bsetup-go\b"),
    ),
    rules=(
        versions_axis("Go version", "Go"),
        GOFMT,
        COVERAGE,
        TESTS,
        WARNINGS,
        HARDENING,
        SECURITY_LINTS,
        DEPENDENCY_AUDIT,
        FunctionLimits(without_lizard=_funlen_enforced),
        BUILD_OUTPUTS,
    ),
)
