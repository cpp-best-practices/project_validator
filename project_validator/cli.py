"""Command line interface: `python3 -m project_validator [options] [path]`."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from project_validator import yaml_support
from project_validator.core import Check, Context, Options, Project
from project_validator.plugins import PluginError, discover
from project_validator.runner import Report, SelectionError, run_checks, select, succeeded

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2


def _names(values: list[str]) -> list[str]:
    return [name.strip() for value in values for name in value.split(",") if name.strip()]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="project_validator", description="Validate a CMake based project against C++ Best Practices."
    )
    parser.add_argument("path", nargs="?", default=".", type=Path, help="project to validate (default: .)")
    parser.add_argument("--list", action="store_true", help="list the available checks and exit")
    parser.add_argument("--only", action="append", default=[], metavar="CHECKS", help="run only these checks")
    parser.add_argument("--skip", action="append", default=[], metavar="CHECKS", help="do not run these checks")
    parser.add_argument("--format", choices=("text", "json"), default="text", help="output format")
    parser.add_argument("--build", action="store_true", help="configure and build the project to list its tests")
    parser.add_argument("--strict", action="store_true", help="treat warnings as failures")
    parser.add_argument("--no-yaml", action="store_true", help="do not use PyYAML even if it is installed")
    parser.add_argument("--cmake", default="cmake", help="cmake executable used by --build")
    parser.add_argument("--ctest", default="ctest", help="ctest executable used by --build")
    parser.add_argument(
        "--plugin-dir", action="append", default=[], type=Path, metavar="DIR", help="load extra plugins from DIR/*.py"
    )
    return parser


def _format_text(reports: list[Report]) -> str:
    lines: list[str] = []
    for report in reports:
        lines.append(f"[{report.result.status}] {report.check.name}: {report.result.message}")
        lines.extend(f"    {detail}" for detail in report.result.details)
    return "\n".join(lines)


def _format_json(reports: list[Report]) -> str:
    return json.dumps(
        [
            {
                "check": report.check.name,
                "status": str(report.result.status),
                "message": report.result.message,
                "details": list(report.result.details),
            }
            for report in reports
        ],
        indent=2,
    )


def _format_list(checks: Sequence[Check]) -> str:
    width = max((len(c.name) for c in checks), default=0)
    return "\n".join(f"{c.name:<{width}}  {c.description}" for c in checks)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    arguments = parser.parse_args(argv)
    try:
        plugins = discover(arguments.plugin_dir)
        selected = select(plugins.checks, _names(arguments.only), _names(arguments.skip))
    except (PluginError, SelectionError) as error:
        parser.print_usage(sys.stderr)
        print(f"{parser.prog}: error: {error}", file=sys.stderr)
        return EXIT_USAGE

    if arguments.list:
        print(_format_list(plugins.checks))
        return EXIT_SUCCESS
    if not arguments.path.is_dir():
        print(f"{parser.prog}: error: {arguments.path} is not a directory", file=sys.stderr)
        return EXIT_USAGE

    options = Options(
        build=arguments.build,
        use_yaml=not arguments.no_yaml and yaml_support.available(),
        cmake=arguments.cmake,
        ctest=arguments.ctest,
    )
    context = Context(Project(arguments.path.resolve()), plugins.providers, options)
    reports = run_checks(selected, context)
    print(_format_json(reports) if arguments.format == "json" else _format_text(reports))
    return EXIT_SUCCESS if succeeded(reports, strict=arguments.strict) else EXIT_FAILURE
