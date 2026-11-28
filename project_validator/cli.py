"""Command line interface: `python3 -m project_validator [options] [path]`."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import traceback
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

from project_validator import __version__, gitignore, yaml_support
from project_validator.analysis import Analysis, analyse
from project_validator.core import DEFAULT_MAX_FILE_SIZE, Check, Context, ExtractionError, Observer, Options, Project
from project_validator.ecosystems import applies_to
from project_validator.explanations import explain
from project_validator.facts.auxiliary import Selectors
from project_validator.grid import render_grid
from project_validator.plugins import PluginError, discover
from project_validator.questions.answers import answers
from project_validator.runner import Report, SelectionError, select, succeeded
from project_validator.score import TOP_LEVEL, shortfalls
from project_validator.support_matrix import as_dict, render, support_matrix
from project_validator.views import console as console_view
from project_validator.views import html as html_view
from project_validator.views import text as text_view
from project_validator.views import tui as tui_view
from project_validator.views.progress import ProgressView

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2


def _names(values: list[str]) -> list[str]:
    return [name.strip() for value in values for name in value.split(",") if name.strip()]


def _relative_directory(value: str) -> PurePosixPath:
    return PurePosixPath(Path(value).as_posix())


def _mebibytes(value: str) -> int:
    """A positive size in MiB, as bytes."""
    try:
        size = float(value)
    except ValueError:
        size = 0
    if not size > 0:
        raise argparse.ArgumentTypeError(f"expected a positive number of MiB, got {value!r}")
    return int(size * 1024 * 1024)


def _percent(value: str) -> float:
    """A share from 0 to 100."""
    try:
        share = float(value)
    except ValueError:
        share = -1.0
    if not 0 <= share <= 100:
        raise argparse.ArgumentTypeError(f"expected a percent from 0 to 100, got {value!r}")
    return share


# What --map, --facts and --answers print.
_DUMPS = {
    "map": "the detected project structure",
    "facts": "the facts found about the project",
    "answers": "the answers to every question about the project",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="project_validator", description="Validate a project's build, CI and tooling against best practices."
    )
    parser.add_argument("path", nargs="?", default=".", type=Path, help="project to validate (default: .)")
    parser.add_argument("--version", action="version", version=f"project_validator {__version__}")
    _add_listing_options(parser)
    parser.add_argument("--only", action="append", default=[], metavar="CHECKS", help="run only these checks")
    parser.add_argument("--skip", action="append", default=[], metavar="CHECKS", help="do not run these checks")
    _add_output_options(parser)
    _add_score_options(parser)
    _add_scope_options(parser)
    parser.add_argument("--strict", action="store_true", help="treat warnings as failures")
    parser.add_argument(
        "--plugin-dir", action="append", default=[], type=Path, metavar="DIR", help="load extra plugins from DIR/*.py"
    )
    _add_check_options(parser)
    _add_network_options(parser)
    return parser


def _add_listing_options(parser: argparse.ArgumentParser) -> None:
    """The options that print information about the validator or the project and exit."""
    parser.add_argument(
        "--support-matrix",
        action="store_true",
        help="print what each check recognises for each ecosystem (markdown; as JSON with --format json) and exit",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="list the checks (as JSON: with what each applies to; as markdown: a table with the same)",
    )
    for name, what in _DUMPS.items():
        parser.add_argument(f"--{name}", action="store_true", help=f"print {what} as JSON and exit")
    parser.add_argument(
        "--explain",
        metavar="CHECK",
        help="explain a check: what it looks for, why it matters, and the tools it recognises for each language",
    )


def _add_scope_options(parser: argparse.ArgumentParser) -> None:
    """The options that say which code is judged, and as what."""
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        type=_relative_directory,
        metavar="DIR",
        help="leave DIR, relative to the project, out of the validation (e.g. test fixtures)",
    )
    parser.add_argument(
        "--auxiliary",
        action="append",
        default=[],
        metavar="WHAT",
        help="judge this code as auxiliary, not the product's: by role (tooling, docs, example, benchmark, test), "
        "language or ecosystem (python, c++), or directory (scripts/); its failures are warnings, labelled; "
        "may be repeated",
    )
    parser.add_argument(
        "--primary",
        action="append",
        default=[],
        metavar="WHAT",
        help="judge only this code as the product's, every other language's as auxiliary: by language or ecosystem "
        "(python, c++) or directory (src/); formats are judged as they are; may be repeated; not with --auxiliary",
    )


def _add_output_options(parser: argparse.ArgumentParser) -> None:
    """The options that choose how the results are printed."""
    parser.add_argument(
        "--format",
        choices=("text", "json", "markdown", "html"),
        default="text",
        help="output format (text: in color with rich on a terminal; markdown: a grid of checks by language, for a "
        "job summary; html: the self-contained HTML report)",
    )
    parser.add_argument(
        "--html", type=Path, metavar="FILE", help="also write the self-contained HTML report of the findings to FILE"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="show every detail, the checks that do not apply and the stages"
    )
    parser.add_argument(
        "--tui", action="store_true", help="browse the results and the facts interactively (needs textual)"
    )
    parser.add_argument(
        "--color", choices=("auto", "always", "never"), default="auto", help="color the text output (needs rich)"
    )


def _add_score_options(parser: argparse.ArgumentParser) -> None:
    """The options of the tooling score: whether to print it, and the floors it must reach."""
    parser.add_argument(
        "--score",
        action="store_true",
        help="also score the project's tooling: the share of the quality gates that apply to it that are in place "
        "(100%%: all of them; extra credit above for complementary tools), its level, and the next steps (the "
        "statuses and exit code do not change)",
    )
    parser.add_argument(
        "--min-level",
        type=int,
        choices=range(TOP_LEVEL + 1),
        metavar="LEVEL",
        help=f"fail unless the score reaches this level (0 to {TOP_LEVEL})",
    )
    parser.add_argument(
        "--min-completeness",
        type=_percent,
        metavar="PERCENT",
        help="fail unless at least this share of the quality gates that apply is in place (0 to 100)",
    )


def _add_network_options(parser: argparse.ArgumentParser) -> None:
    """The options that say what may be asked of the network: the source-control host, other repositories' files."""
    parser.add_argument(
        "--fetch-remote",
        action="store_true",
        help="read the reusable workflows and actions of other repositories CI uses, fetched at their pinned ref",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="never ask the source-control host (GitHub, GitLab, ...) for the repository's settings",
    )


def _add_check_options(parser: argparse.ArgumentParser) -> None:
    """The options that change what some checks do (see `Options`)."""
    parser.add_argument("--build", action="store_true", help="configure and build the project to list its tests")
    parser.add_argument("--cmake", default="cmake", help="cmake executable used by --build")
    parser.add_argument("--ctest", default="ctest", help="ctest executable used by --build")
    parser.add_argument(
        "--max-file-size",
        type=_mebibytes,
        default=DEFAULT_MAX_FILE_SIZE,
        metavar="MIB",
        help="committed files larger than this belong in Git LFS or DVC (default: 5)",
    )
    parser.add_argument(
        "--allow-official-tags", action="store_true", help="let actions from actions/ and github/ be pinned to tags"
    )
    parser.add_argument(
        "--local-checks",
        metavar="SCRIPT",
        help="without CI, read this script as the pipeline (by default, a check script or task is looked for)",
    )
    parser.add_argument(
        "--allow-unknown",
        action="store_true",
        help="judge by what could be read when an answer depends on configuration that could not be (else an error)",
    )


def _options(arguments: argparse.Namespace) -> Options:
    return Options(
        build=arguments.build,
        cmake=arguments.cmake,
        ctest=arguments.ctest,
        max_file_size=arguments.max_file_size,
        allow_official_tags=arguments.allow_official_tags,
        allow_unknown=arguments.allow_unknown,
        local_checks=arguments.local_checks,
        offline=arguments.offline,
        fetch_remote=arguments.fetch_remote,
    )


def report_dicts(reports: list[Report]) -> list[dict[str, object]]:
    """The reports as `--format json` prints them: each check's result, and one result per ecosystem in each unit
    (the places), as the markdown grid lays them out."""
    return [
        {
            "check": report.check.name,
            "status": str(report.result.status),
            "message": report.result.message,
            "details": list(report.result.details),
            "places": [
                {
                    "ecosystem": place.ecosystem,
                    "unit": place.unit,
                    "status": str(place.result.status),
                    "message": place.result.message,
                    "details": list(place.result.details),
                    "tools": list(place.tools),
                    "auxiliary": list(place.auxiliary),
                }
                for place in report.result.places
            ],
        }
        for report in reports
    ]


# The JSON outputs, each with the version of its format (upstream #337). A 0.x release may change a format, but bumps
# its version and says so in the changelog.
JSON_FORMATS = {"results": "1", "facts": "1", "answers": "1", "map": "1", "checks": "1", "support-matrix": "1"}


def versioned(kind: str, payload: object, **beside: object) -> dict[str, object]:
    """A JSON output: which format it is, that format's version, and what it holds (under the format's name)."""
    return {"format": kind, "version": JSON_FORMATS[kind], kind: payload, **beside}


def _use_color(choice: str) -> bool:
    if choice == "auto":
        return sys.stdout.isatty() and "NO_COLOR" not in os.environ
    return choice == "always"


def _format_list(checks: Sequence[Check]) -> str:
    width = max((len(c.name) for c in checks), default=0)
    return "\n".join(f"{c.name:<{width}}  {c.description}" for c in checks)


def _format_list_markdown(checks: Sequence[Check]) -> str:
    """The checks as a Markdown table, with the ecosystems each applies to ("every project" when it names none)."""
    rows = [
        f"| `{c.name}` | {', '.join(applies_to(c)) or 'every project'} | {c.description.replace('|', chr(92) + '|')} |"
        for c in checks
    ]
    return "\n".join(["| Check | Applies to | Passes when |", "|---|---|---|", *rows])


def check_list(checks: Sequence[Check]) -> list[dict[str, object]]:
    """Each check and the ecosystems it judges; an empty `applies_to` means every project."""
    return [{"check": c.name, "description": c.description, "applies_to": list(applies_to(c))} for c in checks]


def _print_listing(checks: Sequence[Check], arguments: argparse.Namespace) -> None:
    """What --list or --support-matrix prints."""
    as_json = arguments.format == "json"
    if arguments.list:
        if as_json:
            print(json.dumps(versioned("checks", check_list(checks)), indent=2))
        else:
            print(_format_list_markdown(checks) if arguments.format == "markdown" else _format_list(checks))
        return
    matrix = support_matrix(checks)
    shown = json.dumps(versioned("support-matrix", as_dict(matrix)), indent=2) if as_json else render(matrix)
    print(shown, end="\n" if as_json else "")


def _usage_error(parser: argparse.ArgumentParser, message: str) -> int:
    print(f"{parser.prog}: error: {message}", file=sys.stderr)
    return EXIT_USAGE


def _results_json(analysis: Analysis, *, scored: bool) -> dict[str, object]:
    """`--format json`: each result, what is shown without being judged (`about`), and the score when asked for."""
    beside: dict[str, object] = {"about": [detail.as_dict() for detail in analysis.about]}
    if scored and analysis.score is not None:
        beside["score"] = analysis.score.as_dict()
    return versioned("results", report_dicts(list(analysis.reports)), **beside)


def _markdown(analysis: Analysis, *, scored: bool) -> str:
    """`--format markdown`: the grid of results, what is shown without being judged, and the score when asked for."""
    shown = render_grid(list(analysis.reports))
    if lines := text_view.about_lines(analysis):
        shown += (
            "\n" + "\n".join([f"**{lines[0].rstrip(':')}**", "", *(f"- {line.strip()}" for line in lines[1:])]) + "\n"
        )
    if scored and analysis.score is not None:
        shown += "\n" + "\n".join(text_view.score_lines(analysis.score, markdown=True)) + "\n"
    return shown


def _print_analysis(analysis: Analysis, arguments: argparse.Namespace) -> None:
    """Print the analysis in the format asked for, and write the HTML report when `--html` asks for one."""
    if arguments.html is not None:
        arguments.html.write_text(html_view.render(analysis), encoding="utf-8")
    if arguments.format == "json":
        print(json.dumps(_results_json(analysis, scored=arguments.score), indent=2))
    elif arguments.format == "html":
        print(html_view.render(analysis), end="")
    elif arguments.format == "markdown":
        print(_markdown(analysis, scored=arguments.score), end="")
    elif _use_color(arguments.color) and console_view.available():
        console_view.render(analysis, sys.stdout, verbose=arguments.verbose)
    else:
        if _use_color(arguments.color):
            print("note: install rich for colored output (pip install project_validator[pretty])", file=sys.stderr)
        print(text_view.render(analysis, scored=arguments.score))


def _progress(arguments: argparse.Namespace) -> contextlib.AbstractContextManager[Observer | None]:
    """Progress on stderr while the validator works, when stderr is a terminal and rich is installed."""
    if arguments.tui or not sys.stderr.isatty() or not console_view.available() or arguments.color == "never":
        return contextlib.nullcontext(None)
    return ProgressView(sys.stderr)


def _dump(context: Context, arguments: argparse.Namespace) -> object:
    """What --facts, --answers or --map prints."""
    if arguments.facts:
        return versioned("facts", context.facts.as_dicts())
    if arguments.answers:
        return versioned("answers", answers(context))
    return versioned("map", context.structure.as_dict())


def _check_scope(arguments: argparse.Namespace) -> None:
    """Refuse what --auxiliary and --primary name, when it is nothing known or both are given (a `ValueError`)."""
    if arguments.primary and arguments.auxiliary:
        raise ValueError("--primary and --auxiliary cannot be given together")
    Selectors.parse(arguments.auxiliary, primary=arguments.primary)


def _project(arguments: argparse.Namespace) -> Project:
    return Project(
        arguments.path.resolve(),
        frozenset(arguments.exclude),
        tuple(arguments.auxiliary),
        primary=tuple(arguments.primary),
    )


def deprecated_main(argv: Sequence[str] | None = None) -> int:
    """The command's old name (`project-validator`), kept for one release: it says so, then runs `main`."""
    print("`project-validator` is deprecated: run `project_validator`", file=sys.stderr)
    return main(argv)


def _path_problem(arguments: argparse.Namespace) -> str | None:
    """What is wrong with the project's path, or the script `--local-checks` names in it; None when nothing is."""
    if not arguments.path.is_dir():
        return f"{arguments.path} is not a directory"
    if arguments.local_checks is not None and not (arguments.path / arguments.local_checks).is_file():
        return f"--local-checks {arguments.local_checks} is not a file of the project"
    return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    arguments = parser.parse_args(argv)
    try:
        plugins = discover(arguments.plugin_dir)
        selected = select(plugins.checks, _names(arguments.only), _names(arguments.skip))
        _check_scope(arguments)
    except (PluginError, SelectionError, ValueError) as error:
        parser.print_usage(sys.stderr)
        return _usage_error(parser, str(error))

    if arguments.list or arguments.support_matrix:
        _print_listing(plugins.checks, arguments)
        return EXIT_SUCCESS
    if arguments.explain:
        try:
            (found,) = select(plugins.checks, [arguments.explain])
        except SelectionError as error:
            return _usage_error(parser, str(error))
        print("\n".join(explain(found, tuple(plugins.checks)).lines()))
        return EXIT_SUCCESS
    for required in (yaml_support, gitignore):
        if not required.available():
            return _usage_error(parser, required.MISSING_MESSAGE)
    if problem := _path_problem(arguments):
        return _usage_error(parser, problem)

    context = Context(_project(arguments), plugins.providers, _options(arguments))
    return _run(parser, arguments, context, selected, [found.name for found in plugins.checks])


def _run(
    parser: argparse.ArgumentParser,
    arguments: argparse.Namespace,
    context: Context,
    selected: list[Check],
    every_check: Sequence[str],
) -> int:
    """Print what was asked (a dump, or the analysis) and say how it went; `every_check` names every check there is,
    for the score."""
    if (dump := _unscored(arguments)) and (arguments.min_level is not None or arguments.min_completeness is not None):
        return _usage_error(parser, f"--min-level and --min-completeness need the analysis, not {dump}")
    if arguments.facts or arguments.map or arguments.answers:
        try:
            print(json.dumps(_dump(context, arguments), indent=2))
        except ExtractionError as failed:
            return _extraction_failed(parser, failed)
        return EXIT_SUCCESS
    if arguments.tui:
        return tui_view.run(context, selected, every_check)
    with _progress(arguments) as progress:
        analysis = analyse(context, selected, every_check=every_check, progress=progress)
    _print_analysis(analysis, arguments)
    if (cause := analysis.error) is not None:
        return _extraction_failed(parser, cause)
    passed = succeeded(list(analysis.reports), strict=arguments.strict)
    return EXIT_SUCCESS if _meets_floors(parser, arguments, analysis) and passed else EXIT_FAILURE


def _unscored(arguments: argparse.Namespace) -> str:
    """The option that prints something other than the analysis (so no score); "" when none does."""
    return next((f"--{name}" for name in ("facts", "map", "answers", "tui") if getattr(arguments, name)), "")


def _meets_floors(parser: argparse.ArgumentParser, arguments: argparse.Namespace, analysis: Analysis) -> bool:
    """Whether the score meets the floors `--min-level` and `--min-completeness` set; when not, says why on stderr."""
    assert analysis.score is not None  # noqa: S101 - a run that raised nothing is scored
    short = shortfalls(analysis.score, min_level=arguments.min_level, min_completeness=arguments.min_completeness)
    for reason in short:
        print(f"{parser.prog}: score below its floor: {reason}", file=sys.stderr)
    return not short


def _extraction_failed(parser: argparse.ArgumentParser, failed: ExtractionError) -> int:
    """The one cause of every "not judged" result, with where it raised, once, on stderr."""
    print(f"{parser.prog}: error: {failed}", file=sys.stderr)
    traceback.print_exception(failed.error, file=sys.stderr)
    return EXIT_FAILURE
