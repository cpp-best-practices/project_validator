"""Java and Kotlin on the JVM: built with Maven or Gradle, judged by the JDK versions CI runs.

Maven and Gradle projects wire their tools into the build: a Maven plugin binds a goal to a lifecycle phase
(`<goal>check</goal>` runs in `mvn verify`), and a Gradle plugin adds its task to `check`. So the build files count as
CI configuration when CI runs the build far enough to run them.
"""

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from project_validator.ecosystems.model import BuildSystem, Ecosystem, toolchain_patterns
from project_validator.facts import Command, Fact, Facts, Origin, Setting, Unknown, resolved
from project_validator.facts.arguments import positional, program
from project_validator.facts.audit import audited, auditor
from project_validator.facts.axes import versions_axis
from project_validator.facts.coverage import Granularity, coverage_tool, measured
from project_validator.facts.dependencies import Locked, PackageManager, lockfile_reader, manifest_reader
from project_validator.facts.expansion import Action
from project_validator.facts.formatting import Enforcement, flagged, format_tool, formatted
from project_validator.facts.outputs import BuildOutput, directories, ignored_at_top_level
from project_validator.facts.practices import Practice, PracticeName, Wording, always, required, requirement_reader
from project_validator.facts.settings import SettingsReader, matched_settings, settings, xml_root
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import Claim, Definition, Run, defined_by, either, starts
from project_validator.text import Pattern
from project_validator.tools.audits import multi_ecosystem_audits

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
    return BuildOutput(
        name=f"the {directory} directory",
        languages=JVM_LANGUAGES,
        build_systems=frozenset({build_system}),
        globs=ignored_at_top_level(directory),
        paths=directories(directory),
        hint=f"consider ignoring {' and '.join((f'{directory}/', *more))}",
        artifacts=(f"{directory}/", *more, "*.class"),
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


def _setting(name: str, regex: str) -> Pattern:
    return Pattern(name, re.compile(regex, re.IGNORECASE | re.DOTALL))


GRADLE_PLUGIN = r"""(?:id\s*\(?\s*|apply\s+plugin:\s*|plugins\.apply\s*\(\s*)["']{}["']"""


SOURCE_SUFFIXES = (".java", ".kt")
# JUnit and TestNG annotate tests; Kotest specs extend a spec style.
JVM_TEST_FILES = TestFiles(
    name="@Test methods or Kotest specs under src/test/java or src/test/kotlin",
    languages=frozenset({JAVA, KOTLIN}),
    path=re.compile(r"(?:^|/)src/test/(?:java|kotlin)/.+\.(?:java|kt)$"),
    contains=re.compile(
        r"@(?:org\.junit\.(?:jupiter\.api\.)?)?Test\b"
        r"|:\s*(?:Fun|String|Describe|Behavior|Should|Free|Word|Feature|Expect|Annotation)Spec\b"
    ),
)
# The lifecycle phases and tasks that run the tests.
_TESTS = {
    "maven": frozenset({"test", "package", "verify", "install", "deploy"}),
    "gradle": frozenset({"test", "check", "build"}),
}


def _build_tests(command: Command, _facts: Facts) -> Run | None:
    found = build_steps(command)
    return tested() if found is not None and set(found[1]) & _TESTS[found[0]] else None


BUILD_TESTS = test_runner(
    name="mvn test or gradle test",
    languages=frozenset({JAVA, KOTLIN}),
    how="mvn test or gradle test",
    runs=_build_tests,
    tests=tests_of(JVM_TEST_FILES.name),
)


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


_PLUGIN_BLOCK = re.compile(r"<plugin>(.*?)</plugin>", re.DOTALL)
_ARTIFACT = re.compile(r"<artifactId>\s*([\w.-]+)\s*</artifactId>")
_GOAL = re.compile(r"<goal>\s*([\w.:-]+)\s*</goal>")


def _read_maven_plugins(path: str, text: str) -> Iterator[Setting]:
    """Each plugin a POM declares, with the goals its executions bind (`plugin.<artifactId>`); matched in its text
    when it does not parse."""
    root = xml_root("Maven", path, text)
    if isinstance(root, Unknown):
        blocks = ((_ARTIFACT.search(block), _GOAL.findall(block)) for block in _PLUGIN_BLOCK.findall(text))
        found = ((f"plugin.{artifact[1]}", tuple(goals)) for artifact, goals in blocks if artifact)
        yield from settings("Maven", path, found, heuristic=True)
        return
    for plugin in root.iter("plugin"):
        artifact = (plugin.findtext("artifactId") or "").strip()
        goals = tuple((goal.text or "").strip() for goal in plugin.iter("goal"))
        yield from settings("Maven", path, ((f"plugin.{artifact}", goals),))


MAVEN_PLUGINS = SettingsReader(name="Maven", files=(POM,), read=_read_maven_plugins)
_GRADLE_PLUGIN_ID = re.compile(GRADLE_PLUGIN.format(r"([\w.-]+)"))
_GRADLE_TASK_LINK = re.compile(r"\b(?:finalizedBy|dependsOn)\b\s*\(?\s*(?:tasks\.(?:named\s*\(\s*)?)?[\"']?(\w+)")


def _read_gradle_settings(path: str, text: str) -> Iterator[Setting]:
    """The plugins a Gradle build applies, and the tasks it links to others (`finalizedBy`): matched in its code."""
    yield from matched_settings(
        "Gradle", path, text, {"plugin": (_GRADLE_PLUGIN_ID, None), "task": (_GRADLE_TASK_LINK, None)}
    )


# Every Gradle script: a convention plugin (`buildSrc/src/main/kotlin/conventions.gradle.kts`) applies plugins too.
GRADLE_SETTINGS = SettingsReader(name="Gradle", files=("*.gradle", "*.gradle.kts"), read=_read_gradle_settings)


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


def _jvm_coverage(wiring: Wiring) -> Claim:
    def measures(command: Command, facts: Facts) -> Run | None:
        read = wired_run(wiring, command, facts)
        return None if read is None else measured(Granularity.LINE, Granularity.BRANCH, read=read)

    return measures


# JaCoCo and Kover count branches; neither reports path coverage.
JACOCO = coverage_tool(
    name="JaCoCo",
    languages=JVM_LANGUAGES,
    can={
        Granularity.LINE: "jacoco:report or jacocoTestReport",
        Granularity.BRANCH: "jacoco:report or jacocoTestReport",
    },
    measures=_jvm_coverage(
        Wiring(
            report=re.compile(r"(?:org\.jacoco:)?jacoco(?:-maven-plugin)?(?::[^:]+)?:report[\w-]*|jacoco\w*Report"),
            maven_plugin="jacoco-maven-plugin",
            bound_goal=re.compile(r"report[\w-]*"),
        )
    ),
    reads=("Maven", "Gradle"),
)
KOVER = coverage_tool(
    name="Kover",
    languages=JVM_LANGUAGES,
    can={Granularity.LINE: "koverXmlReport", Granularity.BRANCH: "koverXmlReport"},
    measures=_jvm_coverage(
        Wiring(
            report=re.compile(
                r"kover\w*Report|(?:org\.jetbrains\.kotlinx:)?kover(?:-maven-plugin)?(?::[^:]+)?:report[\w-]*"
            ),
            maven_plugin="kover-maven-plugin",
            bound_goal=None,
            gradle_plugin="org.jetbrains.kotlinx.kover",
        )
    ),
    reads=("Maven", "Gradle"),
)


def _build_formatter(check: Wiring, apply: re.Pattern[str]) -> Claim:
    """A formatter a Maven or Gradle build runs: its check goal or task, directly or bound to the verification the
    build runs; or its apply goal or task."""

    def formats(command: Command, facts: Facts) -> Run | None:
        read = wired_run(check, command, facts)
        if read is not None:
            return formatted(command, facts, checks=True, read=read)
        found = build_steps(command)
        applies = found is not None and any(map(apply.fullmatch, found[1]))
        return formatted(command, facts, checks=False) if applies else None

    return formats


def plugin_definition(maven_plugin: str, gradle_plugin: str | None = None) -> Definition:
    """A tool a build plugin runs is defined where the build declares the plugin."""

    def found(facts: Facts) -> Iterator[str]:
        yield from (setting.path for setting in facts.where(Setting, tool="Maven", key=f"plugin.{maven_plugin}"))
        gradle = (setting for setting in facts.where(Setting, tool="Gradle", key="plugin"))
        yield from (setting.path for setting in gradle if setting.value == gradle_plugin)

    return Definition(found=found)


# Every formatter here has a built-in style (Spotless applies one of them).
SPOTLESS = format_tool(
    name="Spotless",
    languages=JVM_LANGUAGES,
    can={Enforcement.CHECK: "mvn spotless:check or gradle spotlessCheck", Enforcement.APPLY: "spotless:apply"},
    formats=_build_formatter(
        Wiring(
            report=re.compile(
                r"(?:com\.diffplug\.spotless:)?spotless(?:-maven-plugin)?(?::[^:]+)?:check|spotlessCheck"
            ),
            maven_plugin="spotless-maven-plugin",
            bound_goal=re.compile("check"),
            gradle_plugin="com.diffplug.spotless",
        ),
        apply=re.compile(r"(?:\S+:)?spotless(?:-maven-plugin)?(?::[^:]+)?:apply|spotlessApply"),
    ),
    style=plugin_definition("spotless-maven-plugin", "com.diffplug.spotless"),
    reads=("Maven", "Gradle"),
)
FMT_MAVEN_PLUGIN = format_tool(
    name="fmt-maven-plugin",
    languages=frozenset({JAVA}),
    can={Enforcement.CHECK: "mvn fmt:check", Enforcement.APPLY: "mvn fmt:format"},
    formats=_build_formatter(
        Wiring(
            report=re.compile(r"(?:com\.spotify\.fmt:)?fmt(?:-maven-plugin)?(?::[^:]+)?:check"),
            maven_plugin="fmt-maven-plugin",
            bound_goal=re.compile("check"),
        ),
        apply=re.compile(r"(?:com\.spotify\.fmt:)?fmt(?:-maven-plugin)?(?::[^:]+)?:format"),
    ),
    style=plugin_definition("fmt-maven-plugin"),
    reads=("Maven",),
)
GOOGLE_JAVA_FORMAT = format_tool(
    name="google-java-format",
    languages=frozenset({JAVA}),
    can={
        Enforcement.CHECK: "google-java-format --set-exit-if-changed",
        Enforcement.APPLY: "google-java-format --replace",
    },
    formats=flagged(("google-java-format",), checks=("--set-exit-if-changed",), applies=("--replace", "-i", "-r")),
    style=defined_by(),
)
KTFMT = format_tool(
    name="ktfmt",
    languages=frozenset({KOTLIN}),
    can={Enforcement.CHECK: "ktfmt --set-exit-if-changed", Enforcement.APPLY: "ktfmt"},
    formats=flagged(("ktfmt",), checks=("--set-exit-if-changed",)),
    style=defined_by(),
)
KTLINT = format_tool(
    name="ktlint",
    languages=frozenset({KOTLIN}),
    can={Enforcement.CHECK: "ktlint or gradle ktlintCheck", Enforcement.APPLY: "ktlint --format"},
    formats=either(
        flagged(("ktlint",), applies=("-F", "--format")),
        _build_formatter(
            Wiring(
                report=re.compile(r"ktlint(?:-maven-plugin)?(?::[^:]+)?:check|ktlint\w*Check"),
                maven_plugin="ktlint-maven-plugin",
                bound_goal=re.compile("check"),
                gradle_plugin="org.jlleitschuh.gradle.ktlint",
            ),
            apply=re.compile(r"ktlint(?:-maven-plugin)?(?::[^:]+)?:format|ktlint\w*Format"),
        ),
    ),
    style=plugin_definition("ktlint-maven-plugin", "org.jlleitschuh.gradle.ktlint"),
    reads=("Maven", "Gradle"),
)

XLINT = _setting("-Xlint:all", r"-Xlint(?::all)?(?![:\w-])")
# The Kotlin compiler warns by default; a Kotlin-only project is judged by warnings-as-errors.
KOTLIN_WARNINGS = _setting(
    "Kotlin's default warnings", r"\bkotlin-maven-plugin\b|\borg\.jetbrains\.kotlin\b|\bkotlin\s*\(\s*[\"']jvm[\"']"
)


_JVM_WARNINGS_AS_ERRORS = (
    required(_setting("-Werror", r"-Werror\b")),
    required(_setting("allWarningsAsErrors", r"\ballWarningsAsErrors\b(?:\s*(?:=|\.set\s*\()\s*|>\s*)true\b")),
)
JVM_WARNING_SETTINGS = requirement_reader(
    "JVM warning settings",
    (POM, *GRADLE_BUILD_FILES),
    (required(XLINT), required(KOTLIN_WARNINGS), *_JVM_WARNINGS_AS_ERRORS),
)
JAVA_WARNINGS = Practice(
    name=PracticeName.WARNINGS,
    languages=frozenset({JAVA}),
    requirements=always(required(XLINT)),
    reads=(JVM_WARNING_SETTINGS.name,),
    words=Wording(
        kind="JVM compiler warnings",
        hint="add -Xlint:all to javac's compilerArgs",
    ),
)
KOTLIN_WARNINGS_PRACTICE = Practice(
    name=PracticeName.WARNINGS,
    languages=frozenset({KOTLIN}),
    requirements=always(required(KOTLIN_WARNINGS)),
    reads=(JVM_WARNING_SETTINGS.name,),
    words=Wording(
        kind="JVM compiler warnings",
        hint="build Kotlin with the Kotlin compiler plugin, whose warnings are on by default",
    ),
)

WARNINGS_AS_ERRORS = Practice(
    name=PracticeName.WARNINGS_AS_ERRORS,
    languages=JVM_LANGUAGES,
    requirements=always(*_JVM_WARNINGS_AS_ERRORS),
    any_one=True,
    reads=(JVM_WARNING_SETTINGS.name,),
    words=Wording(
        kind="warnings as errors",
        searched="the Maven or Gradle build, or CI configuration",
        hint="add -Werror to javac's compilerArgs (Kotlin: allWarningsAsErrors = true)",
    ),
)


def _dependency_check(command: Command, facts: Facts) -> Run | None:
    """OWASP dependency-check: its goal or task, the plugin a build's verification brings in, or its CLI."""
    if starts(("dependency-check",), ("dependency-check.sh",))(command):
        return audited()
    wiring = Wiring(
        report=re.compile(
            r"(?:org\.owasp:)?dependency-check(?:-maven)?(?::[^:]+)?:(?:check|aggregate)|dependencyCheck(?:Analyze|Aggregate)"
        ),
        maven_plugin="dependency-check-maven",
        bound_goal=re.compile("check|aggregate"),
    )  # the Gradle plugin adds no task to check, so applying it runs nothing
    read = wired_run(wiring, command, facts)
    return None if read is None else audited(read=read)


AUDITORS = (
    auditor(
        name="OWASP dependency-check",
        languages=JVM_LANGUAGES,
        how="OWASP dependency-check (dependency-check:check, or gradle dependencyCheckAnalyze)",
        audits=_dependency_check,
        reads=("Maven", "Gradle"),
    ),
    *multi_ecosystem_audits(JVM_LANGUAGES),
)
DEPENDENCY_CHECK_ACTION = Action(
    name="dependency-check/Dependency-Check_Action", runs=lambda _inputs: (("dependency-check",),)
)


MAVEN_DEPENDENCY = re.compile(r"<dependency>")
GRADLE_DEPENDENCY = re.compile(r"^\s*(?:implementation|api|compileOnly|runtimeOnly|testImplementation)\b", re.MULTILINE)
GRADLE_LOCKS = ("gradle/verification-metadata.xml", "gradle.lockfile")
MAVEN_CONFIG = ".mvn/maven.config"
_STRICT_CHECKSUMS = frozenset({"--strict-checksums", "-C"})

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


def _read_maven_config(path: str, text: str) -> Iterator[Fact]:
    """Maven's own options: with --strict-checksums, it fails on a dependency whose checksum does not match."""
    if _STRICT_CHECKSUMS & set(text.split()):
        yield Locked(origin=Origin(path=path), manager="Maven")


MAVEN_STRICT_CHECKSUMS = SettingsReader(name="Maven options", files=(MAVEN_CONFIG,), read=_read_maven_config)


def _maven_verifies(command: Command) -> bool:
    argv = resolved(command)
    return program(argv) in {"mvn", "mvnw"} and bool(_STRICT_CHECKSUMS & set(argv))


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
        "JDK", more=JDK_VERSIONS, commands=rf"{MAVEN_COMMAND}|{GRADLE_COMMAND}|\bjavac\b", setup=("java",)
    ),
)

JDK_AXIS = versions_axis("JDK version", "JDK", JVM_LANGUAGES)
