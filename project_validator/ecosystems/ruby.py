"""Ruby: managed with Bundler, judged by the Ruby versions and implementations CI runs.

Ruby projects run their tools through Rake (`bundle exec rake`): the Rakefile defines the test and lint tasks
(`RSpec::Core::RakeTask`, `RuboCop::RakeTask`) and the default task that runs them. So the Rakefile counts as CI
configuration when CI runs rake.
"""

import re
from collections.abc import Iterator
from pathlib import PurePosixPath

from project_validator.core import Context
from project_validator.ecosystems.model import BuildSystem, Ecosystem, ToolchainPatterns, versions_axis
from project_validator.evidence import ci_and_hook_texts, existing_texts
from project_validator.facts import Command, Facts, Setting, resolved
from project_validator.facts.analysis import Strictness, analysed, analyzer, type_checked, type_checker
from project_validator.facts.arguments import has_option, positional, program
from project_validator.facts.audit import audited, auditor
from project_validator.facts.coverage import Granularity, coverage_tool, measured
from project_validator.facts.expansion import joined, launcher
from project_validator.facts.formatting import Enforcement, flagged, format_tool, formatted
from project_validator.facts.limits import Rule, limiter
from project_validator.facts.security import scanned, scanner
from project_validator.facts.settings import SettingsReader, file_reader, matched_settings, settings, yaml_settings
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import Claim, Run, combined, defined_by, either, starts, when
from project_validator.rules import (
    BuildOutputs,
    DeclaredLicense,
    DependencyManagement,
    WarningPolicy,
    directories,
    ignored_at_top_level,
)
from project_validator.text import Pattern, pattern
from project_validator.tools.audits import multi_ecosystem_audits
from project_validator.tools.limits import function_length_limiters
from project_validator.tools.scanners import multi_language_scanners

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


# RSpec::Core::RakeTask.new(:spec), Rake::TestTask.new(:test), Minitest::TestTask.create: their name, if given.
_TEST_TASK = re.compile(
    r"\b(RSpec::Core::RakeTask|Rake::TestTask|Minitest::TestTask)\.(?:new|create)(?:\s*\(?\s*:(\w+))?"
)


def _read_rake_tasks(path: str, text: str) -> Iterator[Setting]:
    """The RuboCop, Standard and test tasks a Rakefile defines, and its default task's prerequisites: matched in its
    code."""
    rubocop = (match[1] or "rubocop" for match in _RUBOCOP_TASK.finditer(text))
    standard = ("standard" for _ in _STANDARD_TASK.finditer(text))
    tests = (match[2] or ("spec" if match[1].startswith("RSpec") else "test") for match in _TEST_TASK.finditer(text))
    defaults = (re.findall(r"\w+", match[1]) for match in _DEFAULT_TASK.finditer(text))
    found = [*(("task.RuboCop", name) for name in rubocop), *(("task.Standard", name) for name in standard)]
    found += [("task.tests", name) for name in tests]
    found += [("default", tuple(names)) for names in defaults]
    yield from settings("Rake", path, found, heuristic=True)


RAKE_TASKS = SettingsReader(name="Rake", files=(*RAKEFILES, "*.rake"), read=_read_rake_tasks)


def _rake_tasks(command: Command, facts: Facts, tool: str) -> list[Setting]:
    """The tasks of `tool` a Rakefile defines that `rake` runs: those it names, or its default task's."""
    argv = resolved(command)
    if program(argv) != "rake":
        return []
    targets = set(positional(argv)[0]) or {"default"}
    if "default" in targets:
        defaults = (found.value for found in facts.where(Setting, tool="Rake", key="default"))
        targets |= {str(name) for names in defaults if isinstance(names, tuple) for name in names}
    return [task for task in facts.where(Setting, tool="Rake", key=f"task.{tool}") if task.value in targets]


def _rake_task(tool: str) -> Claim:
    """`rake rubocop`, or `rake` whose default task runs it: the task a Rakefile defines for `tool` checks."""

    def formats(command: Command, facts: Facts) -> Run | None:
        read = _rake_tasks(command, facts, tool)
        return formatted(command, facts, checks=True, read=read) if read else None

    return formats


def _lints(program_name: str, autocorrects: frozenset[str], tool: str) -> Claim:
    """A linter run that reports what it finds, rather than correcting it, or the Rake task that runs it."""

    def analyses(command: Command, facts: Facts) -> Run | None:
        argv = resolved(command)
        if program(argv) == program_name and not has_option(argv, *autocorrects):
            return analysed()
        read = _rake_tasks(command, facts, tool)
        return analysed(read=read) if read else None

    return analyses


RUBOCOP_SETTINGS = SettingsReader(
    name="RuboCop", files=(RUBOCOP_CONFIG,), read=lambda path, text: yaml_settings("RuboCop", path, text)
)
STANDARD_FILES = file_reader("Standard", (".standard.yml",))
SYNTAX_TREE_FILES = file_reader("syntax_tree", (".streerc",))

# RuboCop and Standard have a default style; syntax_tree's is its own.
_RUBOCOP_CORRECTS = frozenset({"-a", "-A", "--autocorrect", "--autocorrect-all", "-x", "--fix-layout"})
_STANDARD_CORRECTS = frozenset({"--fix", "--fix-unsafely"})
RUBOCOP = combined(
    format_tool(
        name="RuboCop",
        languages=RUBY_ONLY,
        can={Enforcement.CHECK: "rubocop", Enforcement.APPLY: "rubocop -a"},
        formats=either(flagged(("rubocop",), applies=_RUBOCOP_CORRECTS), _rake_task("RuboCop")),
        style=defined_by(files=("RuboCop",)),
        reads=("Rake",),
    ),
    analyzer(
        name="RuboCop",
        languages=RUBY_ONLY,
        how="rubocop",
        analyses=_lints("rubocop", _RUBOCOP_CORRECTS, "RuboCop"),
        rules=defined_by(files=("RuboCop",)),
        reads=("Rake",),
    ),
)
STANDARD = combined(
    format_tool(
        name="Standard",
        languages=RUBY_ONLY,
        can={Enforcement.CHECK: "standardrb", Enforcement.APPLY: "standardrb --fix"},
        formats=either(flagged(("standardrb",), applies=_STANDARD_CORRECTS), _rake_task("Standard")),
        style=defined_by(files=("Standard",)),
        reads=("Rake",),
    ),
    analyzer(
        name="Standard",
        languages=RUBY_ONLY,
        how="standardrb",
        analyses=_lints("standardrb", _STANDARD_CORRECTS, "Standard"),
        rules=defined_by(files=("Standard",)),
        reads=("Rake",),
    ),
)
SYNTAX_TREE = format_tool(
    name="syntax_tree",
    languages=RUBY_ONLY,
    can={Enforcement.CHECK: "stree check", Enforcement.APPLY: "stree write"},
    formats=flagged(("stree", "check"), ("stree", "write"), checks=("check",)),
    style=defined_by(files=("syntax_tree",)),
)

# RSpec specs, and Minitest (or test-unit) tests.
RUBY_TEST_FILES = TestFiles(
    name="spec/**/*_spec.rb or test/**/*_test.rb files",
    languages=RUBY_ONLY,
    path=re.compile(r"(?:^|/)spec/(?:.+/)?[^/]+_spec\.rb$|(?:^|/)test/(?:.+/)?(?:[^/]+_test|test_[^/]+)\.rb$"),
)
_RUBY_RUNNERS = frozenset({"rspec", "m", "turbo_tests", "parallel_rspec", "cucumber"})


def _ruby_tests(command: Command, facts: Facts) -> Run | None:
    """rspec and the like, `rails test`, `ruby -Itest`, `rake test` or `rake spec`, or the test task of a Rakefile
    that rake runs."""
    argv = resolved(command)
    name = program(argv)
    if name in _RUBY_RUNNERS or argv[:2] == ("rails", "test") or (name == "ruby" and "-Itest" in argv):
        return tested()
    if read := _rake_tasks(command, facts, "tests"):
        return tested(read=read)
    return tested(heuristic=True) if name == "rake" and {"test", "spec"} & set(argv[1:]) else None


RUBY_TESTS = test_runner(
    name="rspec, rake test or rails test",
    languages=RUBY_ONLY,
    how="rspec, rake test or rails test",
    runs=_ruby_tests,
    tests=tests_of(RUBY_TEST_FILES.name),
    reads=("Rake",),
)


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

AUDITORS = (
    auditor(
        name="bundler-audit",
        languages=RUBY_ONLY,
        how="bundle audit check --update",
        audits=when(starts(("bundler-audit",), ("bundle-audit",), ("bundle", "audit")), audited),
    ),
    *multi_ecosystem_audits(RUBY_ONLY),
)


# RuboCop's Security cops are on by default.
def _rubocop_security(command: Command, facts: Facts) -> Run | None:
    """RuboCop linting, whose Security cops are on by default."""
    linted = _lints("rubocop", _RUBOCOP_CORRECTS, "RuboCop")(command, facts)
    return None if linted is None else scanned(read=linted.read)


SECURITY_SCANNERS = (
    scanner(name="brakeman", languages=RUBY_ONLY, how="brakeman", scans=when(starts(("brakeman",)), scanned)),
    scanner(name="RuboCop Security cops", languages=RUBY_ONLY, how="rubocop", scans=_rubocop_security, reads=("Rake",)),
    *multi_language_scanners(RUBY_ONLY),
)

_METHOD_LENGTH = "Metrics/MethodLength"


def _method_length(facts: Facts, *, on: bool) -> list[Setting]:
    """The RuboCop settings that turn Metrics/MethodLength on (setting its Max, or enabling it), or off (disabling it,
    or every Metrics cop)."""
    if on:
        keys = {f"{_METHOD_LENGTH}.Max": None, f"{_METHOD_LENGTH}.Enabled": True}
    else:
        keys = {f"{_METHOD_LENGTH}.Enabled": False, "Metrics.Enabled": False}
    return [
        setting
        for setting in facts.settings("RuboCop")
        if setting.key in keys and keys[setting.key] in (None, setting.value)
    ]


# Metrics/MethodLength is on by default; Standard turns the Metrics cops off.
METHOD_LENGTH = limiter(
    name="RuboCop's Metrics/MethodLength",
    languages=RUBY_ONLY,
    how="rubocop",
    runs=_lints("rubocop", _RUBOCOP_CORRECTS, "RuboCop"),
    rule=Rule(
        describe=f"{_METHOD_LENGTH} on in {RUBOCOP_CONFIG}",
        enabled=lambda facts: _method_length(facts, on=True),
        disabled=lambda facts: _method_length(facts, on=False),
        default=True,
    ),
    reads=("Rake", "RuboCop"),
)
FUNCTION_LENGTH_LIMITERS = (METHOD_LENGTH, *function_length_limiters(RUBY_ONLY))


REEK_FILES = file_reader("Reek", (".reek.yml",))
REEK = analyzer(
    name="Reek",
    languages=RUBY_ONLY,
    how="reek",
    analyses=lambda command, _facts: analysed() if program(resolved(command)) == "reek" else None,
    rules=defined_by(files=("Reek",)),
)

SORBET_STRICT = re.compile(r"^#\s*typed:\s*(?:strict|strong)\b", re.MULTILINE)
STEEP_STRICT = re.compile(r"\bD::Ruby\.strict\b")


def _read_sigils(path: str, text: str) -> Iterator[Setting]:
    """Sorbet's strictness sigil, in the first lines of a Ruby file (`# typed: strict`)."""
    return matched_settings("Sorbet", path, text[:512], {"strict": (SORBET_STRICT, True)})


SORBET_SIGILS = SettingsReader(name="Sorbet", files=("*.rb", "*.rbi"), read=_read_sigils)
SORBET_FILES = file_reader("Sorbet configuration", ("sorbet/config",))
STEEPFILE = SettingsReader(
    name="Steep",
    files=("Steepfile",),
    read=lambda path, text: matched_settings("Steep", path, text, {"strict": (STEEP_STRICT, True)}),
)


def _type_checks(prefix: tuple[str, ...], tool: str) -> Claim:
    def checks(command: Command, facts: Facts) -> Run | None:
        if resolved(command)[: len(prefix)] != prefix:
            return None
        strict = facts.where(Setting, tool=tool, key="strict")[:1]
        return type_checked(strict=bool(strict), read=strict)

    return checks


SORBET = type_checker(
    name="Sorbet",
    languages=RUBY_ONLY,
    can={Strictness.CHECKS: "srb tc (Sorbet)", Strictness.STRICT: "# typed: strict files (Sorbet)"},
    checks=_type_checks(("srb", "tc"), "Sorbet"),
    configuration=defined_by(files=("Sorbet configuration",)),
    reads=("Sorbet",),
)
STEEP = type_checker(
    name="Steep",
    languages=RUBY_ONLY,
    can={
        Strictness.CHECKS: "steep check (Steep, with RBS signatures)",
        Strictness.STRICT: "D::Ruby.strict in the Steepfile",
    },
    checks=_type_checks(("steep", "check"), "Steep"),
    configuration=defined_by(files=("Steep",)),
    reads=("Steep",),
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
        WARNINGS,
        DEPENDENCIES,
        BUNDLE,
        LICENSE,
    ),
)
