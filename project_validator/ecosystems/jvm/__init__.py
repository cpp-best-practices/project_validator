"""Java and Kotlin on the JVM: built with Maven or Gradle, judged by the JDK versions CI runs.

Maven and Gradle projects wire their tools into the build: a Maven plugin binds a goal to a lifecycle phase
(`<goal>check</goal>` runs in `mvn verify`), and a Gradle plugin adds its task to `check`. So the build files count as
CI configuration when CI runs the build far enough to run them."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from project_validator.ecosystems.model import BuildSystem, Ecosystem, toolchain_patterns
from project_validator.facts import Command, Facts, Setting, resolved
from project_validator.facts.arguments import positional, program
from project_validator.facts.axes import versions_axis
from project_validator.facts.dependencies import PackageManager, lockfile_reader, manifest_reader
from project_validator.facts.outputs import BuildOutput, directory_output, ignored_at_top_level
from project_validator.facts.tools import Definition

JAVA = "Java"


KOTLIN = "Kotlin"


JVM_LANGUAGES = frozenset({JAVA, KOTLIN})


POM = "pom.xml"


GRADLE_BUILD_FILES = ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts")


def _output_beside(name: str, build_files: tuple[str, ...]) -> Callable[[Path], bool]:
    def is_build_tree(directory: Path) -> bool:
        return directory.name == name and any((directory.parent / build_file).is_file() for build_file in build_files)

    return is_build_tree


def _build_outputs(build_system: str, directory: str, *more: str) -> BuildOutput:
    languages, systems = JVM_LANGUAGES, frozenset({build_system})
    return directory_output(
        directory, languages=languages, build_systems=systems, also=more, artifacts=(*more, "*.class")
    )


MAVEN_TARGET = _build_outputs("Maven", "target")


GRADLE_BUILD = _build_outputs("Gradle", "build", ".gradle/")


MAVEN = BuildSystem(
    name="Maven",
    files=(POM,),
    is_build_tree=_output_beside("target", (POM,)),
)


GRADLE = BuildSystem(
    name="Gradle",
    files=GRADLE_BUILD_FILES,
    is_build_tree=_output_beside("build", GRADLE_BUILD_FILES),
)


# How far CI runs the build: a phase or task that compiles, and one that also runs the verification plugins.
MAVEN_COMMAND = r"(?<![\w-])(?:\./)?mvnw?(?:\.cmd)?\b"


GRADLE_COMMAND = r"(?<![\w-])(?:\./)?gradlew?(?:\.bat)?\b"


MVN = rf"{MAVEN_COMMAND}[^\n]*"


GRADLE_RUN = rf"{GRADLE_COMMAND}[^\n]*"


RUNS_BUILD = re.compile(
    rf"{MVN}\b(?:compile|test|package|verify|install|deploy)\b"
    rf"|{GRADLE_RUN}\b(?:build|check|test|assemble|classes|compile\w*)\b"
)


GRADLE_PLUGIN = r"""(?:id\s*\(?\s*|apply\s+plugin:\s*|plugins\.apply\s*\(\s*)["']{}["']"""


SOURCE_SUFFIXES = (".java", ".kt")


# Options of mvn and gradle that take a value, so that their values are not taken for goals or tasks.
_MAVEN_VALUES = frozenset(
    {
        "-f",
        "--file",
        "-s",
        "--settings",
        "-gs",
        "-P",
        "--activate-profiles",
        "-pl",
        "--projects",
        "-T",
        "--threads",
        "-rf",
        "--resume-from",
        "-l",
        "--log-file",
    }
)


_GRADLE_VALUES = frozenset(
    {
        "-x",
        "--exclude-task",
        "-p",
        "--project-dir",
        "-c",
        "-I",
        "--init-script",
        "--max-workers",
        "-g",
        "--gradle-user-home",
    }
)


def build_steps(command: Command) -> tuple[str, list[str]] | None:
    """Whether a command runs Maven or Gradle, and the goals, phases or tasks it runs."""
    argv = resolved(command)
    name = program(argv)
    if name in ("mvn", "mvnw"):
        return "maven", positional(argv, _MAVEN_VALUES)[0]
    if name in ("gradle", "gradlew"):
        return "gradle", [step.rsplit(":", 1)[-1] for step in positional(argv, _GRADLE_VALUES)[0]]
    return None


def _verifies(kind: str, steps: list[str]) -> bool:
    """Whether the build runs as far as the plugins that verify it: Maven's verify phase, Gradle's check task."""
    return bool(set(steps) & ({"verify", "install", "deploy"} if kind == "maven" else {"build", "check"}))


@dataclass(frozen=True, slots=True, kw_only=True)
class Wiring:
    """How a JVM tool runs: a goal or task that runs it (`report`), or a Maven plugin (with a goal matching
    `bound_goal`, when given) or Gradle plugin or linked task that the verification CI runs brings in."""

    report: re.Pattern[str]
    maven_plugin: str
    bound_goal: re.Pattern[str] | None
    gradle_plugin: str | None = None


def _wired(wiring: Wiring, kind: str, facts: Facts) -> list[Setting]:
    if kind == "maven":
        plugins = facts.where(Setting, tool="Maven", key=f"plugin.{wiring.maven_plugin}")
        goal = wiring.bound_goal
        return [found for found in plugins if goal is None or any(map(goal.fullmatch, found.value))]  # type: ignore[call-overload]
    applied = [
        found for found in facts.where(Setting, tool="Gradle", key="plugin") if found.value == wiring.gradle_plugin
    ]
    linked = [
        found for found in facts.where(Setting, tool="Gradle", key="task") if wiring.report.fullmatch(str(found.value))
    ]
    return [*applied, *linked]


def wired_run(wiring: Wiring, command: Command, facts: Facts) -> tuple[Setting, ...] | None:
    """Whether a Maven or Gradle command runs the wiring's goal or task: directly (reading no settings), or through a
    plugin its verification brings in (reading the settings that wire it). None when it does not."""
    found = build_steps(command)
    if found is None:
        return None
    kind, steps = found
    if any(wiring.report.fullmatch(step) for step in steps):
        return ()
    if _verifies(kind, steps) and (read := _wired(wiring, kind, facts)):
        return tuple(read)
    return None


def plugin_definition(maven_plugin: str, gradle_plugin: str | None = None) -> Definition:
    """A tool a build plugin runs is defined where the build declares the plugin."""

    def found(facts: Facts) -> Iterator[str]:
        yield from (setting.path for setting in facts.where(Setting, tool="Maven", key=f"plugin.{maven_plugin}"))
        gradle = (setting for setting in facts.where(Setting, tool="Gradle", key="plugin"))
        yield from (setting.path for setting in gradle if setting.value == gradle_plugin)

    return Definition(found=found)


MAVEN_DEPENDENCY = re.compile(r"<dependency>")


GRADLE_DEPENDENCY = re.compile(r"^\s*(?:implementation|api|compileOnly|runtimeOnly|testImplementation)\b", re.MULTILINE)


GRADLE_LOCKS = ("gradle/verification-metadata.xml", "gradle.lockfile")


STRICT_CHECKSUMS = frozenset({"--strict-checksums", "-C"})


MAVEN_DEPENDENCIES = manifest_reader(
    name="Maven dependencies",
    manager="Maven",
    files=(POM,),
    declares=lambda _path, text: bool(MAVEN_DEPENDENCY.search(text)),
)


GRADLE_DEPENDENCIES = manifest_reader(
    name="Gradle dependencies",
    manager="Gradle",
    files=("build.gradle", "build.gradle.kts"),
    declares=lambda _path, text: bool(GRADLE_DEPENDENCY.search(text)),
)


# Gradle's dependency verification metadata, or its lockfile.
GRADLE_LOCKFILES = lockfile_reader(manager="Gradle", files=GRADLE_LOCKS)


def _maven_verifies(command: Command) -> bool:
    argv = resolved(command)
    return program(argv) in {"mvn", "mvnw"} and bool(STRICT_CHECKSUMS & set(argv))


MAVEN_PACKAGES = PackageManager(
    name="Maven",
    languages=JVM_LANGUAGES,
    lock_hint="verify them: run Maven with --strict-checksums (in .mvn/maven.config)",
    verified_by=_maven_verifies,
)


GRADLE_PACKAGES = PackageManager(
    name="Gradle",
    languages=JVM_LANGUAGES,
    lock_hint="verify them: commit gradle/verification-metadata.xml (gradle --write-verification-metadata sha256) "
    "or a gradle.lockfile",
)


CLASS_FILES = BuildOutput(
    languages=JVM_LANGUAGES,
    name="compiled classes",
    globs=ignored_at_top_level(r"\*\.class"),
    paths=("App.class",),
    hint="consider ignoring *.class",
    artifacts=("*.class",),
)


_JDK = r"(\d+(?:\.\d+)*)"


JDK_VERSIONS = (
    re.compile(rf"\bjava-version\W+{_JDK}"),
    # coursier/setup-action installs the JDK its `jvm` input names: `jvm: 21`, `jvm: temurin:21`.
    re.compile(rf"\bjvm:\s*(?:[\w-]+:)?{_JDK}\b"),
    re.compile(rf"\b(?:eclipse-temurin|openjdk|amazoncorretto|sapmachine|azul/zulu-openjdk\w*):{_JDK}"),
    re.compile(rf"\bmaven:[\d.]+-[a-z-]+?-{_JDK}\b"),
    re.compile(rf"\bgradle:[\w.-]*?jdk-?{_JDK}\b"),
)


JVM = Ecosystem(
    label="JVM",
    languages=frozenset({JAVA, KOTLIN}),
    build_systems=(MAVEN, GRADLE),
    source_suffixes={".java": JAVA, ".kt": KOTLIN},
    # Kotlin and Groovy scripts are mostly Gradle builds and their helpers, which name no language.
    ambiguous_suffixes={".kts": None, ".gradle": None},
    toolchain=toolchain_patterns(
        "JDK", more=JDK_VERSIONS, programs=("mvn", "mvnw", "gradle", "gradlew", "javac"), setup=("java",)
    ),
)


JDK_AXIS = versions_axis("JDK version", "JDK", JVM_LANGUAGES)
