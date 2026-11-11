"""Elixir and Erlang on the BEAM: built with Mix or rebar3, judged by the Erlang/OTP and Elixir versions CI runs and by
the Mix and rebar3 tasks CI runs on the code.

Both build tools run tasks: `mix test --cover`, `rebar3 ct`, and several at once (`mix do format --check-formatted,
credo --strict`; `rebar3 do eunit, ct, cover`; `rebar3 as test cover`). Every tool here is one of those tasks, so
the tasks a command runs are read once (`mix_tasks`, `rebar3_tasks`) and each tool asks for its own. A Mix alias
(`aliases: [ci: ["format --check-formatted", "test"]]` in `mix.exs`) runs other tasks, as a package script does."""

import re
from collections.abc import Callable, Iterator

from project_validator.core import Context
from project_validator.ecosystems.model import BuildSystem, Ecosystem, toolchain_patterns
from project_validator.facts import Command, Facts, Origin, Setting, resolved
from project_validator.facts.analysis import Strictness, analysed, analyzer, type_checked, type_checker
from project_validator.facts.arguments import program
from project_validator.facts.audit import audited, auditor
from project_validator.facts.axes import ToolchainAxis, toolchain_versions
from project_validator.facts.coverage import Granularity, coverage_tool, measured
from project_validator.facts.dependencies import PackageManager, lockfile_reader, manifest_reader
from project_validator.facts.expansion import Action, CommandExpander, Expansion, Script, joined
from project_validator.facts.formatting import Enforcement, flagged, format_tool, formatted
from project_validator.facts.jobs import Job
from project_validator.facts.outputs import BuildOutput, directories, ignored_at_top_level
from project_validator.facts.practices import Practice, PracticeName, Wording, always, required, requirement_reader
from project_validator.facts.security import scanned, scanner
from project_validator.facts.settings import SettingsReader, file_reader, matched_settings
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import Condition, Run, any_of, defined_by, either, starts, when
from project_validator.text import Pattern
from project_validator.tools.audits import multi_ecosystem_audits
from project_validator.tools.limits import function_length_limiters
from project_validator.tools.scanners import multi_language_scanners

ELIXIR = "Elixir"
ERLANG = "Erlang"
BEAM_LANGUAGES = frozenset({ELIXIR, ERLANG})
ELIXIR_ONLY = frozenset({ELIXIR})
ERLANG_ONLY = frozenset({ERLANG})

MIX_FILE = "mix.exs"
REBAR_CONFIG = "rebar.config"

_APPS_PATH = re.compile(r"\bapps_path:\s*\"([^\"]+)\"")


def _umbrella_members(text: str) -> tuple[str, ...]:
    """The applications of an umbrella project (`apps_path: "apps"`), each a unit of its own."""
    found = _APPS_PATH.search(text)
    return (f"{found[1].strip('/')}/*",) if found else ()


# A Mix project compiles the Erlang sources in `src/` too; an umbrella's applications are the units.
MIX = BuildSystem(name="Mix", files=(MIX_FILE,), languages=ELIXIR_ONLY, members=_umbrella_members)
REBAR3 = BuildSystem(name="rebar3", files=(REBAR_CONFIG, "rebar.config.script"), languages=ERLANG_ONLY)


# --- The tasks a command runs ---------------------------------------------------------------------------------------

type Tasks = tuple[tuple[str, ...], ...]
"""Each task a command runs, with its arguments: `(("format", "--check-formatted"), ("credo", "--strict"))`."""


def _split_tasks(words: tuple[str, ...], separators: frozenset[str]) -> Tasks:
    """`words` split into tasks at `separators` (`,` or `+`), standing alone or ending a word (`eunit,`)."""
    tasks: list[list[str]] = [[]]
    for word in words:
        if word in separators:
            tasks.append([])
        elif word[-1:] in separators:
            tasks[-1].append(word[:-1])
            tasks.append([])
        else:
            tasks[-1].append(word)
    return tuple(tuple(task) for task in tasks if task)


def mix_tasks(argv: tuple[str, ...]) -> Tasks:
    """The tasks a `mix` command runs: one (`mix test --cover`), or several with `mix do`, separated by `,` or `+`
    (`mix do format --check-formatted, credo --strict`)."""
    if program(argv) != "mix" or len(argv) < 2:
        return ()
    if argv[1] == "do":
        return _split_tasks(argv[2:], frozenset({",", "+"}))
    return (argv[1:],)


def rebar3_tasks(argv: tuple[str, ...]) -> Tasks:
    """The tasks a `rebar3` command runs: one (`rebar3 ct`), several with `rebar3 do` separated by `,` (`rebar3 do
    eunit, ct`), either under a profile (`rebar3 as test cover`)."""
    if program(argv) != "rebar3":
        return ()
    words = argv[1:]
    if words[:1] == ("as",):
        words = words[2:]
    if words[:1] == ("do",):
        return _split_tasks(words[1:], frozenset({","}))
    return (words,) if words else ()


def _runs(tasks: Callable[[tuple[str, ...]], Tasks], *names: str, options: tuple[str, ...] = ()) -> Condition:
    """Whether a command runs a task called one of `names`, given one of `options` when any are named."""

    def matches(command: Command) -> bool:
        return any(
            task[0] in names and (not options or any(option in task[1:] for option in options))
            for task in tasks(resolved(command))
        )

    return matches


def mix(*names: str, options: tuple[str, ...] = ()) -> Condition:
    return _runs(mix_tasks, *names, options=options)


def rebar3(*names: str, options: tuple[str, ...] = ()) -> Condition:
    return _runs(rebar3_tasks, *names, options=options)


# --- Mix aliases --------------------------------------------------------------------------------------------------

_ALIASES_START = re.compile(r"\baliases(?:\(\))?\s*(?:,\s*)?do:?\s*\[|\baliases:\s*\[")
_ALIAS = re.compile(r"(\w[\w.]*):\s*(\[[^\[\]]*\]|\"[^\"]*\")")
_STRING = re.compile(r"\"([^\"]*)\"")


def _bracketed(text: str, start: int) -> str:
    """The text of the list that opens at `start` (a `[`), with its nested lists; to the end when it never closes."""
    depth = 0
    for index in range(start, len(text)):
        depth += {"[": 1, "]": -1}.get(text[index], 0)
        if depth == 0:
            return text[start : index + 1]
    return text[start:]


def mix_aliases(text: str) -> dict[str, tuple[str, ...]]:
    """The aliases a `mix.exs` defines (in `aliases/0` or inline under `aliases:`): alias -> the task lines it runs.
    An alias that runs functions (`&do_it/1`) runs no task line for them."""
    found: dict[str, tuple[str, ...]] = {}
    for start in _ALIASES_START.finditer(text):
        for alias in _ALIAS.finditer(_bracketed(text, start.end() - 1)):
            found[alias[1]] = tuple(_STRING.findall(alias[2]))
    return found


def _mix_alias_tasks(command: Command, context: Context) -> Iterator[Expansion] | None:
    """`mix ci`, where `ci` is an alias in the `mix.exs` the command runs with: the task lines the alias runs."""
    argv = resolved(command)
    if program(argv) != "mix" or len(argv) < 2:
        return None
    path = joined(command.directory, MIX_FILE)
    if not context.project.exists(path):
        return None
    aliases = mix_aliases(context.project.read_text(path))
    return (
        Script(text=f"mix {line}", origin=Origin(path=path, at=("aliases", task[0])), directory=command.directory)
        for task in mix_tasks(argv)
        for line in aliases.get(task[0], ())
    )


MIX_ALIASES = CommandExpander(name="mix.exs aliases", expand=_mix_alias_tasks)


# --- Formatting ---------------------------------------------------------------------------------------------------

FORMATTER_SETTINGS = file_reader("mix format", (".formatter.exs",))


def _mix_format(command: Command, facts: Facts) -> Run | None:
    """`mix format --check-formatted` fails on a file it would change; `mix format` rewrites it; `--dry-run` alone
    only lists."""
    for task in mix_tasks(resolved(command)):
        if task[0] == "format":
            if "--check-formatted" in task:
                return formatted(command, facts, checks=True)
            return None if "--dry-run" in task else formatted(command, facts, checks=False)
    return None


MIX_FORMAT = format_tool(
    name="mix format",
    languages=ELIXIR_ONLY,
    can={Enforcement.CHECK: "mix format --check-formatted", Enforcement.APPLY: "mix format"},
    formats=_mix_format,
    style=defined_by(files=(FORMATTER_SETTINGS.name,)),
)


def _rebar3_fmt(command: Command, facts: Facts) -> Run | None:
    """`rebar3 fmt --check` (the erlfmt plugin) fails on a file it would change; `rebar3 fmt` rewrites it."""
    for task in rebar3_tasks(resolved(command)):
        if task[0] == "fmt":
            return formatted(command, facts, checks="--check" in task or "-c" in task)
    return None


# erlfmt is opinionated: one style, no settings worth the name.
ERLFMT = format_tool(
    name="erlfmt",
    languages=ERLANG_ONLY,
    can={Enforcement.CHECK: "rebar3 fmt --check (or erlfmt --check)", Enforcement.APPLY: "rebar3 fmt"},
    formats=either(flagged(("erlfmt",), checks=("-c", "--check"), applies=("-w", "--write")), _rebar3_fmt),
    style=defined_by(),
)


# --- Tests and coverage -------------------------------------------------------------------------------------------

EXUNIT_TEST_FILES = TestFiles(
    name="ExUnit tests (test/**/*_test.exs)",
    languages=ELIXIR_ONLY,
    path=re.compile(r"(?:^|/)test/.+_test\.exs$"),
    contains=re.compile(r"^\s*(?:test|describe|property|doctest)\b", re.MULTILINE),
)
EUNIT_TEST_FILES = TestFiles(
    name="EUnit tests (*_test() functions)",
    languages=ERLANG_ONLY,
    path=re.compile(r"\.erl$"),
    contains=re.compile(r"^\w+_test_?\(\)\s*->", re.MULTILINE),
)
COMMON_TEST_SUITES = TestFiles(
    name="Common Test suites (*_SUITE.erl)",
    languages=ERLANG_ONLY,
    path=re.compile(r"_SUITE\.erl$"),
    contains=re.compile(r"^all\(\)\s*->", re.MULTILINE),
)

# excoveralls' tasks run the tests and measure them.
_COVERALLS_TASKS = ("coveralls", "coveralls.json", "coveralls.lcov", "coveralls.github", "coveralls.html")

# A Mix project's tests, coverage, Dialyzer and audit cover the Erlang modules it compiles from `src/` too.
MIX_TEST = test_runner(
    name="mix test",
    languages=BEAM_LANGUAGES,
    how="mix test",
    runs=when(mix("test", *_COVERALLS_TASKS), tested),
    tests=tests_of(EXUNIT_TEST_FILES.name, EUNIT_TEST_FILES.name, COMMON_TEST_SUITES.name),
)
REBAR3_TEST = test_runner(
    name="rebar3 eunit or rebar3 ct",
    languages=ERLANG_ONLY,
    how="rebar3 eunit (or rebar3 ct)",
    runs=when(rebar3("eunit", "ct"), tested),
    tests=tests_of(EUNIT_TEST_FILES.name, COMMON_TEST_SUITES.name),
)

# The BEAM's cover tool counts lines; nothing on the BEAM measures branches.
MIX_COVER = coverage_tool(
    name="mix test --cover",
    languages=BEAM_LANGUAGES,
    can={Granularity.LINE: "mix test --cover"},
    measures=when(mix("test", options=("--cover",)), lambda: measured(Granularity.LINE)),
)
EXCOVERALLS = coverage_tool(
    name="excoveralls",
    languages=BEAM_LANGUAGES,
    can={Granularity.LINE: "mix coveralls (excoveralls)"},
    measures=when(mix(*_COVERALLS_TASKS), lambda: measured(Granularity.LINE)),
)
REBAR3_COVER = coverage_tool(
    name="rebar3 cover",
    languages=ERLANG_ONLY,
    can={Granularity.LINE: "rebar3 cover (after eunit or ct with --cover)"},
    measures=when(
        any_of(rebar3("cover"), rebar3("eunit", "ct", options=("--cover", "-c"))), lambda: measured(Granularity.LINE)
    ),
)


# --- Warnings -----------------------------------------------------------------------------------------------------


def _setting(name: str, regex: str) -> Pattern:
    return Pattern(name, re.compile(regex, re.MULTILINE))


# Elixir's compiler warns about everything it knows, without options; the strict set is Credo's.
CREDO_STRICT = _setting("mix credo --strict", r"\bcredo\b[^\n,+]*--strict\b|\bstrict:\s*true\b")
# The Erlang compiler warns by default; `erl_opts` turns on the optional warnings, and elvis lints the style.
ERL_WARNINGS = _setting("warn_* erl_opts", r"\bwarn_\w+")
ELVIS = _setting("elvis", r"\belvis\b|\brebar3\b[^\n]*\blint\b")

ELIXIR_WARNINGS_AS_ERRORS = _setting(
    "--warnings-as-errors", r"--warnings-as-errors\b|\bwarnings_as_errors:\s*true\b|:warnings_as_errors\b"
)
ERLANG_WARNINGS_AS_ERRORS = _setting("warnings_as_errors", r"\bwarnings_as_errors\b|\berlc\b[^\n]*\s-Werror\b")

CREDO_SETTINGS = requirement_reader("Credo settings", (".credo.exs",), (required(CREDO_STRICT),))
BEAM_COMPILER_OPTIONS = requirement_reader(
    "BEAM compiler options",
    (MIX_FILE, REBAR_CONFIG),
    (required(ERL_WARNINGS), required(ELIXIR_WARNINGS_AS_ERRORS), required(ERLANG_WARNINGS_AS_ERRORS)),
)

ELIXIR_WARNINGS = Practice(
    name=PracticeName.WARNINGS,
    languages=ELIXIR_ONLY,
    requirements=always(required(CREDO_STRICT)),
    reads=(CREDO_SETTINGS.name,),
    words=Wording(
        kind="Elixir linters",
        hint="run mix credo --strict in CI (or set strict: true in .credo.exs)",
        searched="CI configuration or .credo.exs",
    ),
)
ERLANG_WARNINGS = Practice(
    name=PracticeName.WARNINGS,
    languages=ERLANG_ONLY,
    requirements=always(required(ERL_WARNINGS), required(ELVIS)),
    reads=(BEAM_COMPILER_OPTIONS.name,),
    words=Wording(
        kind="Erlang warnings",
        hint="turn on the optional warnings in rebar.config (erl_opts: warn_missing_spec, warn_export_vars, ...) and "
        "run elvis (rebar3 lint) in CI",
        searched="CI configuration or rebar.config",
    ),
)
ELIXIR_WARNINGS_AS_ERRORS_PRACTICE = Practice(
    name=PracticeName.WARNINGS_AS_ERRORS,
    languages=ELIXIR_ONLY,
    requirements=always(required(ELIXIR_WARNINGS_AS_ERRORS)),
    reads=(BEAM_COMPILER_OPTIONS.name,),
    words=Wording(
        kind="warnings as errors",
        searched="CI configuration or mix.exs",
        hint="run mix compile --warnings-as-errors in CI, or set elixirc_options: [warnings_as_errors: true] in "
        "mix.exs",
    ),
)
ERLANG_WARNINGS_AS_ERRORS_PRACTICE = Practice(
    name=PracticeName.WARNINGS_AS_ERRORS,
    languages=ERLANG_ONLY,
    requirements=always(required(ERLANG_WARNINGS_AS_ERRORS)),
    reads=(BEAM_COMPILER_OPTIONS.name,),
    words=Wording(
        kind="warnings as errors",
        searched="CI configuration or rebar.config",
        hint="add warnings_as_errors to erl_opts in rebar.config",
    ),
)


# --- Analysis, type checking, security and audits -------------------------------------------------------------------

CREDO_CONFIGURATION = file_reader("Credo", (".credo.exs",))
ELVIS_CONFIGURATION = file_reader("elvis", ("elvis.config",))

CREDO = analyzer(
    name="Credo",
    languages=ELIXIR_ONLY,
    how="mix credo",
    analyses=when(mix("credo"), analysed),
    rules=defined_by(files=(CREDO_CONFIGURATION.name,)),
)
ELVIS_ANALYZER = analyzer(
    name="elvis",
    languages=ERLANG_ONLY,
    how="rebar3 lint (elvis)",
    analyses=when(any_of(rebar3("lint"), starts(("elvis", "rock"))), analysed),
    rules=defined_by(files=(ELVIS_CONFIGURATION.name,)),
)
XREF = analyzer(
    name="rebar3 xref",
    languages=ERLANG_ONLY,
    how="rebar3 xref",
    analyses=when(rebar3("xref"), analysed),
)

# Dialyzer's optional warnings (`dialyzer: [flags: [:underspecs, ...]]` in mix.exs, `{dialyzer, [{warnings, [...]}]}`
# in rebar.config) are its strict mode.
_DIALYZER_WARNING = re.compile(
    r":?\b(underspecs|overspecs|specdiffs|unmatched_returns|error_handling|unknown|missing_return|extra_return)\b"
)


def _read_dialyzer(path: str, text: str) -> Iterator[Setting]:
    return matched_settings("Dialyzer", path, text, {"warning": (_DIALYZER_WARNING, None)})


DIALYZER_SETTINGS = SettingsReader(name="Dialyzer", files=(MIX_FILE, REBAR_CONFIG), read=_read_dialyzer)


def _dialyzer(command: Command, facts: Facts) -> Run | None:
    if not (mix("dialyzer")(command) or rebar3("dialyzer")(command)):
        return None
    warnings = facts.where(Setting, tool="Dialyzer", key="warning")
    return type_checked(strict=bool(warnings), read=warnings)


DIALYZER = type_checker(
    name="Dialyzer",
    languages=BEAM_LANGUAGES,
    can={
        Strictness.CHECKS: "mix dialyzer (dialyxir) or rebar3 dialyzer",
        Strictness.STRICT: "Dialyzer's optional warnings (underspecs, unmatched_returns, ...) in mix.exs or "
        "rebar.config",
    },
    checks=_dialyzer,
    reads=("Dialyzer",),
)
EQWALIZER = type_checker(
    name="eqWAlizer",
    languages=ERLANG_ONLY,
    can={Strictness.CHECKS: "elp eqwalize-all (eqWAlizer)"},
    checks=when(starts(("elp", "eqwalize-all"), ("elp", "eqwalize")), lambda: type_checked(strict=False)),
)

# Sobelow finds the security issues of Phoenix applications; nothing scans Erlang, and CodeQL reads neither language.
SOBELOW = scanner(name="Sobelow", languages=ELIXIR_ONLY, how="mix sobelow --exit", scans=when(mix("sobelow"), scanned))
SECURITY_SCANNERS = (
    SOBELOW,
    *(tool for tool in multi_language_scanners(ELIXIR_ONLY) if tool.name != "CodeQL"),
)
SOBELOW_ACTION = Action(name="sobelow/action", runs=lambda _inputs: (("mix", "sobelow", "--exit"),))

# mix_audit knows the advisories of Hex packages; `mix hex.audit` only the retired ones.
MIX_AUDIT = auditor(
    name="mix_audit",
    languages=BEAM_LANGUAGES,
    how="mix deps.audit (mix_audit)",
    audits=when(mix("deps.audit", "hex.audit"), audited),
)
AUDITORS = (MIX_AUDIT, *multi_ecosystem_audits(BEAM_LANGUAGES))

FUNCTION_LENGTH_LIMITERS = function_length_limiters(ERLANG_ONLY)


# --- Dependencies and outputs -------------------------------------------------------------------------------------

_MIX_DEPENDENCY = re.compile(r"\{:\w+,\s*(?:\"|git:|github:|path:|hex:)")
_REBAR_DEPENDENCY = re.compile(r"\{deps,\s*\[\s*[\{\w'\"]")

MIX_DEPENDENCIES = manifest_reader(
    name="Mix dependencies",
    manager="Mix",
    files=(MIX_FILE,),
    declares=lambda _path, text: bool(_MIX_DEPENDENCY.search(text)),
)
MIX_LOCK = lockfile_reader(manager="Mix", files=("mix.lock",))
MIX_PACKAGES = PackageManager(
    name="Mix", languages=ELIXIR_ONLY, lock_hint="commit mix.lock, which mix deps.get writes with each package's hash"
)
REBAR_DEPENDENCIES = manifest_reader(
    name="rebar3 dependencies",
    manager="rebar3",
    files=(REBAR_CONFIG,),
    declares=lambda _path, text: bool(_REBAR_DEPENDENCY.search(text)),
)
REBAR_LOCK = lockfile_reader(manager="rebar3", files=("rebar.lock",))
REBAR_PACKAGES = PackageManager(
    name="rebar3", languages=ERLANG_ONLY, lock_hint="commit rebar.lock, which rebar3 writes with each package's hash"
)

BUILD_DIRECTORY = BuildOutput(
    languages=BEAM_LANGUAGES,
    name="the _build directory",
    globs=ignored_at_top_level("_build"),
    paths=directories("_build"),
    hint="consider ignoring _build/",
    artifacts=("_build/", "*.beam"),
)
# Only Mix fetches into deps/; an output of a build system hides the shared ones, so it is Elixir's instead.
DEPS_DIRECTORY = BuildOutput(
    languages=ELIXIR_ONLY,
    name="the deps directory",
    globs=ignored_at_top_level("deps"),
    paths=directories("deps"),
    hint="consider ignoring deps/ (mix deps.get fetches it)",
    artifacts=("deps/",),
)
CRASH_DUMPS = BuildOutput(
    languages=BEAM_LANGUAGES,
    name="crash dumps",
    globs=ignored_at_top_level(r"erl_crash\.dump|rebar3\.crashdump|\*\.dump"),
    paths=("erl_crash.dump", "rebar3.crashdump"),
    hint="consider ignoring erl_crash.dump (and rebar3.crashdump)",
    artifacts=("erl_crash.dump", "rebar3.crashdump"),
)


# --- Recognition and toolchains -----------------------------------------------------------------------------------

# Mix's own tasks (an alias, `mix ci`, is known by the setup action or version the job also names).
_MIX_TASK = (
    r"do|test|compile|format|credo|dialyzer|sobelow|xref|docs|release|run|new|clean|cmd|coveralls(?:\.\w+)?"
    r"|(?:deps|hex|escript|local|archive|phx|ecto)\.\w+"
)

_OTP = r"(\d+(?:\.\d+)*)"
_ELIXIR = r"(\d+\.\d+(?:\.\d+)?(?:-rc\.\d+)?)"

# A job names an Erlang/OTP version, an Elixir version or both: `otp-version` and `elixir-version` of
# erlef/setup-beam, the `erlang` and `elixir` images (`elixir:1.18.3-otp-27`, `hexpm/elixir:1.18.3-erlang-27.3`).
_BEAM_VERSIONS = (
    (re.compile(rf"\botp-version\W+{_OTP}"), "OTP {}"),
    (re.compile(rf"\belixir-version\W+{_ELIXIR}"), "Elixir {}"),
    (re.compile(rf"\berlang:{_OTP}"), "OTP {}"),
    (re.compile(rf"\belixir:{_ELIXIR}"), "Elixir {}"),
    (re.compile(rf"-(?:otp|erlang)-{_OTP}"), "OTP {}"),
)

BEAM = Ecosystem(
    label="BEAM",
    languages=BEAM_LANGUAGES,
    build_systems=(MIX, REBAR3),
    source_suffixes={".ex": ELIXIR, ".exs": ELIXIR, ".erl": ERLANG, ".hrl": ERLANG},
    toolchain=toolchain_patterns(
        "BEAM",
        commands=rf"\bmix\s+(?:{_MIX_TASK})\b|\brebar3\b|\berlc\b|\belixir\s+-",
        setup=("beam",),
        labelled=_BEAM_VERSIONS,
    ),
)


def _beam_versions(job: Job) -> frozenset[str]:
    """A job's BEAM versions: each Elixir version paired with each OTP version it runs on, when it names both."""
    found = toolchain_versions(job.toolchains, "BEAM")
    elixir = sorted(version for version in found if version.startswith("Elixir "))
    otp = sorted(version for version in found if version.startswith("OTP "))
    if elixir and otp:
        return frozenset(f"{language} / {runtime}" for language in elixir for runtime in otp)
    return found


BEAM_VERSIONS = ToolchainAxis(languages=BEAM_LANGUAGES, noun="Erlang/OTP or Elixir version", of_job=_beam_versions)
