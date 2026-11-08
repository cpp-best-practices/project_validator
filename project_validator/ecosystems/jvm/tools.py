"""JVM's tools: what runs its tests, measures coverage, formats, analyses, scans and audits, and the
settings each reads (see `project_validator.facts.tools`)."""

import re
from collections.abc import Iterator

from project_validator.ecosystems.jvm import (
    GRADLE_PLUGIN,
    JAVA,
    JVM_LANGUAGES,
    KOTLIN,
    POM,
    STRICT_CHECKSUMS,
    Wiring,
    build_steps,
    plugin_definition,
    wired_run,
)
from project_validator.facts import Command, Fact, Facts, Origin, Setting, Unknown
from project_validator.facts.audit import audited, auditor
from project_validator.facts.coverage import Granularity, coverage_tool, measured
from project_validator.facts.dependencies import Locked
from project_validator.facts.expansion import Action
from project_validator.facts.formatting import Enforcement, flagged, format_tool, formatted
from project_validator.facts.settings import SettingsReader, matched_settings, settings, xml_root
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import Claim, Run, defined_by, either, starts
from project_validator.tools.audits import multi_ecosystem_audits

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


MAVEN_CONFIG = ".mvn/maven.config"


def _read_maven_config(path: str, text: str) -> Iterator[Fact]:
    """Maven's own options: with --strict-checksums, it fails on a dependency whose checksum does not match."""
    if STRICT_CHECKSUMS & set(text.split()):
        yield Locked(origin=Origin(path=path), manager="Maven")


MAVEN_STRICT_CHECKSUMS = SettingsReader(name="Maven options", files=(MAVEN_CONFIG,), read=_read_maven_config)
