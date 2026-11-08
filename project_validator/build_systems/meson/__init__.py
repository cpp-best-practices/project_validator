"""Meson, read without running it: meson.build files are parsed and evaluated as configuring would evaluate them
(see `evaluation`), and meson.options gives the options' defaults. What they set becomes facts (see
`project_validator.facts.build`): compiler and linker options and build settings (`default_options`), each for the
builds it applies to, and tests. `meson compile <target>` (or `ninja <target>`) runs a run target's command.
"""

import shlex
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from project_validator.build_systems.meson import syntax
from project_validator.build_systems.meson.evaluation import BUILD_FILE, Evaluation, Found, Frame
from project_validator.core import Context, Project
from project_validator.facts import Command, Fact, Origin, Setting, Unknown, resolved
from project_validator.facts.arguments import positional, starts_with
from project_validator.facts.build import BuildSetting, CompilerOption, disjuncts, implied_options
from project_validator.facts.conditions import both
from project_validator.facts.expansion import CommandExpander, Expansion, Script
from project_validator.facts.roles import role
from project_validator.facts.settings import SettingsReader
from project_validator.tools.toolchains import GCC_LIKE, MSVC, WARNINGS_AS_ERRORS_BY_COMPILER, ByCompiler

BUILD_SYSTEM = "Meson"
MESON_TOOLS = (BUILD_SYSTEM,)
OPTION_FILES = ("meson.options", "meson_options.txt")
MESON_FILES = (BUILD_FILE, *OPTION_FILES)


_GCC_LEVELS = ("-Wall",), ("-Wall", "-Wextra"), ("-Wall", "-Wextra", "-Wpedantic")
_MSVC_LEVELS = ("/W2",), ("/W3",), ("/W4",)
# What Meson's `warning_level` and `werror` pass each compiler.
_IMPLIED: dict[tuple[str, str], ByCompiler] = {
    **{
        ("warning_level", str(level)): ((GCC_LIKE, gcc), (frozenset({MSVC}), msvc))
        for level, gcc, msvc in zip((1, 2, 3), _GCC_LEVELS, _MSVC_LEVELS, strict=True)
    },
    ("warning_level", "everything"): (
        (GCC_LIKE, (*_GCC_LEVELS[-1], "-Wshadow", "-Wconversion")),
        (frozenset({MSVC}), ("/Wall",)),
    ),
    ("werror", "true"): WARNINGS_AS_ERRORS_BY_COMPILER,
}


@dataclass(slots=True)
class Collector:
    facts: list[Fact] = field(default_factory=list)
    targets: dict[str, list[tuple[tuple[str, ...], Origin, str]]] = field(default_factory=dict)

    def options(self, frame: Frame, name: str, found: Found, target: str | None, *, linking: bool) -> None:
        origin = frame.origin(name)
        for option, when in found:
            for applies in disjuncts(both(frame.condition, when)):
                self.facts.append(
                    CompilerOption(
                        origin=origin,
                        build_system=BUILD_SYSTEM,
                        option=option,
                        applies=applies,
                        target=target,
                        linking=linking,
                    )
                )

    def setting(self, frame: Frame, name: str, key: str, value: str, target: str | None, *, default: bool) -> None:
        if name != "option":
            implied = _IMPLIED.get((key, value), ())
            self.facts += implied_options(frame.origin(name), BUILD_SYSTEM, implied, frame.condition, target)
        for applies in disjuncts(frame.condition):
            self.facts.append(
                BuildSetting(
                    origin=frame.origin(name),
                    build_system=BUILD_SYSTEM,
                    name=key,
                    value=value,
                    applies=applies,
                    target=target,
                    default=default,
                )
            )

    def test(self, frame: Frame) -> None:
        self.facts.append(Setting(origin=Origin(path=frame.path), tool=BUILD_SYSTEM, key="test", value=True))

    def run_target(self, frame: Frame, name: str, command: tuple[str, ...]) -> None:
        self.targets.setdefault(name, []).append((command, frame.origin("run_target"), frame.directory))


@dataclass(frozen=True, slots=True, kw_only=True)
class MesonProject:
    facts: tuple[Fact, ...]
    targets: Mapping[str, tuple[tuple[tuple[str, ...], Origin, str], ...]]


def _evaluated(files: Mapping[str, str]) -> MesonProject:
    collector = Collector()
    evaluation = Evaluation(files=files, observer=collector)
    evaluation.evaluate()
    for path in (path for path in files if PurePosixPath(path).name in OPTION_FILES):
        evaluation.evaluate_alone(path)
    problems = (
        Unknown(
            origin=Origin(path=path),
            subject=f"the Meson file {path}",
            reason=reason,
            hides="settings",
            tools=(BUILD_SYSTEM,),
        )
        for path, reason in evaluation.problems.items()
    )
    targets = {name: tuple(found) for name, found in collector.targets.items()}
    return MesonProject(facts=tuple(dict.fromkeys((*collector.facts, *problems))), targets=targets)


def _files(project: Project) -> dict[str, str]:
    paths = (path for path in project.files() if role(path) != "vendored" and PurePosixPath(path).name in MESON_FILES)
    return {path: project.read_text(path) for path in paths}


def meson_project(context: Context) -> MesonProject:
    """The evaluation of the project's Meson files, made once."""
    return context.shared(BUILD_SYSTEM, lambda: _evaluated(_files(context.project)))


def _read_meson(context: Context) -> Iterator[Fact]:
    return iter(meson_project(context).facts)


MESON = SettingsReader(name=BUILD_SYSTEM, files=MESON_FILES, read_project=_read_meson)


def declared_languages(text: str) -> tuple[str, ...]:
    """The languages after the name in `project('name', 'c', ['cpp'], ...)`, as written."""
    try:
        nodes = syntax.parse(text)
    except syntax.MesonSyntaxError:
        return ()
    calls = (node.expression for node in nodes if isinstance(node, syntax.Statement))
    project = next((call for call in calls if isinstance(call, syntax.Call) and call.name == "project"), None)
    if project is None:
        return ()
    return tuple(_literals(project.arguments.positional[1:]))


def _literals(expressions: tuple[syntax.Expression, ...]) -> Iterator[str]:
    for expression in expressions:
        if isinstance(expression, syntax.Literal) and isinstance(expression.value, str):
            yield expression.value
        elif isinstance(expression, syntax.Array):
            yield from _literals(expression.items)


# --- run targets

_OPTIONS = frozenset({"-C", "-j", "--jobs"})


def _run_targets(command: Command, context: Context) -> list[Expansion] | None:
    """`meson compile [-C dir] <target>...` and `ninja [-C dir] <target>...`: the commands of the run targets."""
    argv = resolved(command)
    words, _ = positional(argv, _OPTIONS)
    if starts_with(argv, ("meson", "compile")):
        names = words[1:]
    elif starts_with(argv, ("ninja",)):
        names = words
    else:
        return None
    targets = meson_project(context).targets
    found: list[Expansion] = [
        Script(text=shlex.join(words), origin=origin, directory=None if directory == "." else directory)
        for name in names
        for words, origin, directory in targets.get(name, ())
    ]
    return found or None


RUN_TARGETS = CommandExpander(name="Meson run targets", expand=_run_targets)

# Defined in `build` (which reads declared languages from here), found here.
from project_validator.build_systems.meson.build import MESON as MESON_BUILD_SYSTEM  # noqa: E402
from project_validator.build_systems.meson.build import MESON_TESTS, MESON_WRAPS, MESON_WRAPS_MANAGER  # noqa: E402

__all__ = [
    "BUILD_SYSTEM",
    "MESON",
    "MESON_BUILD_SYSTEM",
    "MESON_TESTS",
    "MESON_WRAPS",
    "MESON_WRAPS_MANAGER",
    "OPTION_FILES",
    "RUN_TARGETS",
    "declared_languages",
    "meson_project",
]
