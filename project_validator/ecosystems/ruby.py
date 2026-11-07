"""Ruby: managed with Bundler, judged by the Ruby versions and implementations CI runs.

Ruby projects run their tools through Rake (`bundle exec rake`): the Rakefile defines the test and lint tasks
(`RSpec::Core::RakeTask`, `RuboCop::RakeTask`) and the default task that runs them. So the Rakefile counts as CI
configuration when CI runs rake.
"""

import re
from collections.abc import Iterator
from pathlib import PurePosixPath

from project_validator.core import Context, Result
from project_validator.ecosystems.model import BuildSystem, Ecosystem, ToolchainPatterns, versions_axis
from project_validator.evidence import ci_and_hook_texts, configuration, existing_texts, first_existing
from project_validator.facts import Command, Facts, Setting, resolved
from project_validator.facts.arguments import positional, program
from project_validator.facts.coverage import Granularity, coverage_tool, measured
from project_validator.facts.expansion import joined, launcher
from project_validator.facts.formatting import Enforcement, flagged, format_tool, formatted
from project_validator.facts.settings import SettingsReader, file_reader, matched_settings, settings
from project_validator.facts.tools import Claim, Run, defined_by, either
from project_validator.rules import (
    MULTI_ECOSYSTEM_AUDITS,
    SUGGESTED_LIZARD,
    Analyzer,
    BuildOutputs,
    DeclaredLicense,
    DependencyAudit,
    DependencyManagement,
    FunctionLimits,
    SecurityLints,
    StaticAnalysis,
    TestSuite,
    TypeChecking,
    WarningPolicy,
    directories,
    ignored_at_top_level,
)
from project_validator.text import Pattern, matching_names, pattern

RUBY_LANGUAGE = "Ruby"
RUBY_ONLY = frozenset({RUBY_LANGUAGE})
GEMFILE = "Gemfile"
BUNDLER = BuildSystem(name="Bundler", files=(GEMFILE, "*.gemspec"), languages=RUBY_ONLY)
RAKEFILES = ("Rakefile", "rakefile", "Rakefile.rb")
RUNS_RAKE = re.compile(r"(?<![\w-])rake\b")


def _rake_texts(context: Context) -> tuple[str, ...]:
    """The Rakefile and the task files it loads from rakelib/."""
    tasks = (path for path in context.project.files() if path.startswith("rakelib/") and path.endswith(".rake"))
    return existing_texts(context, (*RAKEFILES, *tasks))


def _run_texts(context: Context) -> tuple[str, ...]:
    """CI configuration and pre-commit hooks, with the Rakefile when CI runs rake."""
    texts = ci_and_hook_texts(context)
    return (*texts, *_rake_texts(context)) if any(map(RUNS_RAKE.search, texts)) else texts


def _gemspecs(context: Context) -> list[str]:
    return [path for path in context.project.files() if "/" not in path and path.endswith(".gemspec")]


RUBOCOP_CONFIG = ".rubocop.yml"
# rubocop -a corrects what it can and passes; it enforces nothing.
RUNS_RUBOCOP = r"(?<![\w-])rubocop\b(?!\.yml|-)(?![^\n]*\s(?:-a|-A|--autocorrect(?:-all)?)\b)|\bRuboCop::RakeTask\b"
RUNS_STANDARD = r"\bstandardrb\b(?![^\n]*\s--fix\b)|\brake\s+standard\b|\bStandard::RakeTask\b|\bstandard/rake\b"

_RUBOCOP_TASK = re.compile(r"\bRuboCop::RakeTask\.new(?:\s*\(?\s*:(\w+))?")
_STANDARD_TASK = re.compile(r"\bStandard::RakeTask\b|\bstandard/rake\b")
_DEFAULT_TASK = re.compile(r"\btask\s*\(?\s*:?default\s*(?:=>|:)\s*((?:%[iwIW])?\[[^\]]*\]|:\w+|[\"']\w+[\"'])")


def _read_rake_tasks(path: str, text: str) -> Iterator[Setting]:
    """The RuboCop and Standard tasks a Rakefile defines, and its default task's prerequisites: matched in its code."""
    rubocop = (match[1] or "rubocop" for match in _RUBOCOP_TASK.finditer(text))
    standard = ("standard" for _ in _STANDARD_TASK.finditer(text))
    defaults = (re.findall(r"\w+", match[1]) for match in _DEFAULT_TASK.finditer(text))
    found = [*(("task.RuboCop", name) for name in rubocop), *(("task.Standard", name) for name in standard)]
    found += [("default", tuple(names)) for names in defaults]
    yield from settings("Rake", path, found, heuristic=True)


RAKE_TASKS = SettingsReader(name="Rake", files=(*RAKEFILES, "*.rake"), read=_read_rake_tasks)


def _rake_task(tool: str) -> Claim:
    """`rake rubocop`, or `rake` whose default task runs it: the task a Rakefile defines for `tool` checks."""

    def formats(command: Command, facts: Facts) -> Run | None:
        argv = resolved(command)
        if program(argv) != "rake":
            return None
        tasks = facts.where(Setting, tool="Rake", key=f"task.{tool}")
        targets = set(positional(argv)[0]) or {"default"}
        if "default" in targets:
            defaults = (found.value for found in facts.where(Setting, tool="Rake", key="default"))
            targets |= {str(name) for names in defaults if isinstance(names, tuple) for name in names}
        read = [task for task in tasks if task.value in targets]
        return formatted(command, facts, checks=True, read=read) if read else None

    return formats


RUBOCOP_FILES = file_reader("RuboCop", (RUBOCOP_CONFIG,))
STANDARD_FILES = file_reader("Standard", (".standard.yml",))
SYNTAX_TREE_FILES = file_reader("syntax_tree", (".streerc",))

# RuboCop and Standard have a default style; syntax_tree's is its own.
RUBOCOP = format_tool(
    name="RuboCop",
    languages=RUBY_ONLY,
    can={Enforcement.CHECK: "rubocop", Enforcement.APPLY: "rubocop -a"},
    formats=either(
        flagged(("rubocop",), applies=("-a", "-A", "--autocorrect", "--autocorrect-all", "-x", "--fix-layout")),
        _rake_task("RuboCop"),
    ),
    style=defined_by(files=("RuboCop",)),
    reads=("Rake",),
)
STANDARD = format_tool(
    name="Standard",
    languages=RUBY_ONLY,
    can={Enforcement.CHECK: "standardrb", Enforcement.APPLY: "standardrb --fix"},
    formats=either(flagged(("standardrb",), applies=("--fix", "--fix-unsafely")), _rake_task("Standard")),
    style=defined_by(files=("Standard",)),
    reads=("Rake",),
)
SYNTAX_TREE = format_tool(
    name="syntax_tree",
    languages=RUBY_ONLY,
    can={Enforcement.CHECK: "stree check", Enforcement.APPLY: "stree write"},
    formats=flagged(("stree", "check"), ("stree", "write"), checks=("check",)),
    style=defined_by(files=("syntax_tree",)),
)

# RSpec specs, and Minitest (or test-unit) tests.
TEST_FILE = re.compile(r"(?:^|/)spec/(?:.+/)?[^/]+_spec\.rb$|(?:^|/)test/(?:.+/)?(?:[^/]+_test|test_[^/]+)\.rb$")
RUNS_TESTS = (
    pattern(
        "Ruby tests",
        r"(?<![\w-])rspec\b|\brake\s+(?:test|spec)\b|\brails\s+test\b|\bruby\s+-Itest\b"
        r"|\bRSpec::Core::RakeTask\b|\b(?:Rake|Minitest)::TestTask\b",
    ),
)


def _ruby_tests(context: Context) -> Result:
    count = sum(1 for path in context.project.files() if TEST_FILE.search(path))
    if count == 0:
        return Result.failed("no Ruby tests found (spec/**/*_spec.rb or test/**/*_test.rb files)")
    return Result.passed(f"Ruby tests found in {count} file(s)")


TESTS = TestSuite(found=_ruby_tests, runs=RUNS_TESTS, runner="rspec, rake test or rails test", texts=_run_texts)

TEST_HELPERS = (".simplecov", "spec/spec_helper.rb", "spec/rails_helper.rb", "test/test_helper.rb")


# The commands that run Ruby tests, and so the test helpers that start SimpleCov.
_TEST_RUNNERS = frozenset({"rspec", "rake", "rails", "ruby", "cucumber", "parallel_rspec", "turbo_tests", "m"})
SIMPLECOV_STARTED = re.compile(r"\bSimpleCov\.start\b")
SIMPLECOV_BRANCHES = re.compile(r"\b(?:enable|primary)_coverage\s*\(?\s*:branch\b")


def _read_simplecov_settings(path: str, text: str) -> Iterator[Setting]:
    """Whether a test helper (or .simplecov, which SimpleCov loads when it starts) starts SimpleCov, and whether it
    counts branches: matched in Ruby code."""
    started = SIMPLECOV_STARTED.search(text) or path.endswith(".simplecov")
    patterns = {"enable_coverage": (SIMPLECOV_BRANCHES, "branch")}
    yield from settings("SimpleCov", path, (("start", True),) if started else (), heuristic=True)
    yield from matched_settings("SimpleCov", path, text, patterns)


SIMPLECOV_SETTINGS = SettingsReader(
    name="SimpleCov", files=tuple(PurePosixPath(path).name for path in TEST_HELPERS), read=_read_simplecov_settings
)


def _simplecov(command: Command, facts: Facts) -> Run | None:
    """SimpleCov, started by .simplecov or a test helper when CI runs the tests; it counts lines unless told to count
    branches too."""
    argv = resolved(command)
    if program(argv) not in _TEST_RUNNERS or (program(argv) == "rails" and argv[1:2] != ("test",)):
        return None
    read = facts.settings("SimpleCov", paths=[joined(command.directory, path) for path in TEST_HELPERS])
    if not any(setting.key == "start" for setting in read):
        return None
    branch = any(setting.key == "enable_coverage" for setting in read)
    return measured(Granularity.LINE, Granularity.BRANCH if branch else None, read=read)


SIMPLECOV = coverage_tool(
    name="SimpleCov",
    languages=RUBY_ONLY,
    can={Granularity.LINE: "SimpleCov", Granularity.BRANCH: "SimpleCov enable_coverage :branch"},
    measures=_simplecov,
    reads=("SimpleCov",),
)
BUNDLE_EXEC = launcher("bundle exec", (("bundle", "exec"), ("bundler", "exec")))

RUBY_WARNINGS = Pattern(
    "Ruby warnings",
    re.compile(
        r"\bruby\s+(?:-\w+\s+)*-w\b|\bRUBYOPT\W+-[wW]\b|\$VERBOSE\s*=\s*true\b"
        r"|\.warnings\s*=\s*true\b|\.warning\s*=\s*true\b|^\s*--warnings\b",
        re.MULTILINE,
    ),
)
RUBY_LINTER = pattern("RuboCop or Standard", rf"{RUNS_RUBOCOP}|{RUNS_STANDARD}")


def _required_warnings(_: Context) -> tuple[Pattern, ...]:
    return (RUBY_WARNINGS, RUBY_LINTER)


def _warning_texts(context: Context) -> tuple[str, ...]:
    return (*_run_texts(context), *existing_texts(context, (".rspec", *TEST_HELPERS)))


# Ruby warns only when asked to; a linter reports what other compilers warn about.
WARNINGS = WarningPolicy(
    kind="Ruby warning settings",
    recognised=(RUBY_WARNINGS, RUBY_LINTER),
    required=_required_warnings,
    texts=_warning_texts,
    separator=", ",
)

DEPENDENCY_AUDIT = DependencyAudit(
    tools=(pattern("bundler-audit", r"\bbundler?-audit\b|\bbundle\s+(?:exec\s+)?audit\b"), *MULTI_ECOSYSTEM_AUDITS),
    hint="consider running bundle audit check --update in CI (bundler-audit)",
    texts=_run_texts,
)

# RuboCop's Security cops are on by default.
SECURITY_LINTS = SecurityLints(
    texts=_run_texts,
    lints=(pattern("brakeman", r"\bbrakeman\b"), pattern("RuboCop Security cops", RUNS_RUBOCOP)),
)

# Metrics/MethodLength is on by default; Standard turns the Metrics cops off.
METHOD_LENGTH_OFF = re.compile(
    r"^Metrics(?:/MethodLength)?:\s*\n(?:[ \t]+.*\n)*?[ \t]+Enabled:\s*false\b", re.MULTILINE
)


def _method_length_enforced(context: Context) -> Result:
    """RuboCop limits method length with Metrics/MethodLength, unless its configuration turns the cop off."""
    config = first_existing(context, (RUBOCOP_CONFIG,))
    if config is not None and METHOD_LENGTH_OFF.search(context.project.read_text(config) + "\n"):
        return Result.failed(f"Metrics/MethodLength is disabled in {config}; enable it or run {SUGGESTED_LIZARD} in CI")
    if matching_names(_run_texts(context), (pattern("RuboCop", RUNS_RUBOCOP),)):
        return Result.passed("function length is limited with RuboCop Metrics/MethodLength")
    return Result.failed(
        f"function length is never limited; run rubocop (Metrics/MethodLength) or {SUGGESTED_LIZARD} in CI"
    )


STATIC_ANALYSIS = StaticAnalysis(
    analyzers=(
        Analyzer(name="RuboCop", runs=re.compile(RUNS_RUBOCOP), configured=configuration((RUBOCOP_CONFIG,))),
        Analyzer(name="Standard", runs=re.compile(RUNS_STANDARD), configured=configuration((".standard.yml",))),
        Analyzer(name="Reek", runs=re.compile(r"(?<![\w-])reek\b"), configured=configuration((".reek.yml",))),
    ),
    texts=_run_texts,
    hint="consider running rubocop (or standardrb) in CI",
)

SORBET_STRICT = re.compile(r"^#\s*typed:\s*(?:strict|strong)\b", re.MULTILINE)
STEEP_STRICT = re.compile(r"\bD::Ruby\.strict\b")


def _strict_type_checking(context: Context) -> str | None:
    """Sorbet's strict sigils, or Steep's strict diagnostics."""
    if context.project.exists("Steepfile") and STEEP_STRICT.search(context.project.read_text("Steepfile")):
        return "D::Ruby.strict in Steepfile"
    sources = (path for path in context.project.files() if path.endswith(".rb"))
    strict = next((path for path in sources if SORBET_STRICT.search(context.project.read_head(path, 512))), None)
    return f"# typed: strict in {strict}" if strict else None


TYPE_CHECKING = TypeChecking(
    checkers=(
        Analyzer(name="Sorbet", runs=re.compile(r"\bsrb\s+tc\b"), configured=configuration(("sorbet/config",))),
        Analyzer(name="Steep", runs=re.compile(r"\bsteep\s+check\b"), configured=configuration(("Steepfile",))),
    ),
    texts=_run_texts,
    strict=_strict_type_checking,
    hint="consider running a type checker in CI: srb tc (Sorbet) or steep check (Steep, with RBS signatures)",
    strict_hint="consider strict checking: # typed: strict files (Sorbet), or D::Ruby.strict in the Steepfile",
)

GEM = re.compile(r"^\s*gem\s+[\"']", re.MULTILINE)
GEMSPEC_DEPENDENCY = re.compile(r"\.add_(?:runtime_|development_)?dependency\b")


def _declared_dependencies(context: Context) -> str | None:
    if context.project.exists(GEMFILE) and GEM.search(context.project.read_text(GEMFILE)):
        return f"declared in {GEMFILE}"
    gemspec = next(
        (path for path in _gemspecs(context) if GEMSPEC_DEPENDENCY.search(context.project.read_text(path))), None
    )
    return f"declared in {gemspec}" if gemspec else None


def _gemfile_lock(context: Context) -> str | None:
    return "Gemfile.lock" if context.committed("Gemfile.lock") else None


def _is_application(context: Context) -> bool:
    """A gem's users resolve its dependencies themselves; an application locks them."""
    return not _gemspecs(context)


DEPENDENCIES = DependencyManagement(
    managed=_declared_dependencies,
    locked=_gemfile_lock,
    lock_required=_is_application,
    lock_hint="commit Gemfile.lock, so the application is installed with the gems it was tested with",
)

GEMSPEC_LICENSES = re.compile(r"""\.licenses?\s*=\s*(?:\[(?P<list>[^\]]*)\]|["'](?P<one>[^"']+)["'])""")


def _gemspec_license(context: Context) -> str | None:
    """A gemspec's licenses are a choice, as an SPDX expression joins them with OR."""
    texts = (context.project.read_text(path) for path in _gemspecs(context))
    match = next((found for text in texts if (found := GEMSPEC_LICENSES.search(text))), None)
    if match is None:
        return None
    return match["one"] or " OR ".join(re.findall(r"""["']([^"']+)["']""", match["list"])) or None


LICENSE = DeclaredLicense(manifest="the gemspec", declared=_gemspec_license)

BUNDLE = BuildOutputs(
    name="the installed gems",
    globs=ignored_at_top_level(r"\.bundle|vendor/bundle"),
    paths=directories(".bundle", "vendor/bundle"),
    hint="consider ignoring .bundle/ and vendor/bundle/ (and coverage/, pkg/ and *.gem)",
    # A committed vendor/bundle/ is reported by dependency-management, as any committed vendor/ is.
    artifacts=(".bundle/", "/coverage/", "/pkg/", "*.gem"),
)

_RUBY_VERSION = r"(\d+\.\d+(?:\.\d+)?|head|(?:jruby|truffleruby)(?:-[\w.]+)?)"

RUBY = Ecosystem(
    label=RUBY_LANGUAGE,
    languages=RUBY_ONLY,
    build_systems=(BUNDLER,),
    source_suffixes={".rb": RUBY_LANGUAGE, ".rake": RUBY_LANGUAGE},
    # Rack configuration and ERB templates belong to Ruby projects, but name no language on their own.
    ambiguous_suffixes={".ru": None, ".erb": None},
    toolchain=ToolchainPatterns(
        language=RUBY_LANGUAGE,
        versions=(re.compile(rf"\bruby-version\W+{_RUBY_VERSION}"), re.compile(r"\bruby:(\d+\.\d+(?:\.\d+)?)")),
        usage=re.compile(r"\bbundle\s+(?:exec|install)\b|\bsetup-ruby\b|(?<![\w-])(?:rake|rspec)\b"),
    ),
    rules=(
        versions_axis("Ruby version", RUBY_LANGUAGE),
        TESTS,
        WARNINGS,
        SECURITY_LINTS,
        DEPENDENCY_AUDIT,
        FunctionLimits(without_lizard=_method_length_enforced),
        STATIC_ANALYSIS,
        TYPE_CHECKING,
        DEPENDENCIES,
        BUNDLE,
        LICENSE,
    ),
)
