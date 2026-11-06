"""Java and Kotlin on the JVM: built with Maven or Gradle, judged by the JDK versions CI runs.

Maven and Gradle projects wire their tools into the build: a Maven plugin binds a goal to a lifecycle phase
(`<goal>check</goal>` runs in `mvn verify`), and a Gradle plugin adds its task to `check`. So the build files count as
CI configuration when CI runs the build far enough to run them.
"""

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from project_validator.core import Context, Result
from project_validator.ecosystems.model import BuildSystem, Ecosystem, ToolchainPatterns, versions_axis
from project_validator.evidence import ci_and_hook_texts, configuration, first_existing
from project_validator.facts import Command, Facts, Setting, Unknown, resolved
from project_validator.facts.coverage import CoverageTool, Granularity, Measure, Measurement, measured
from project_validator.facts.expansion import positional, program
from project_validator.facts.settings import SettingsReader, matched_settings, settings, xml_root
from project_validator.rules import (
    MULTI_ECOSYSTEM_AUDITS,
    SUGGESTED_LIZARD,
    Analyzer,
    BuildOutputs,
    DependencyAudit,
    DependencyManagement,
    Formatter,
    FunctionLimits,
    SecurityLints,
    StaticAnalysis,
    TestSuite,
    WarningPolicy,
    WarningsAsErrors,
    directories,
    ignored_at_top_level,
)
from project_validator.text import Pattern, matching_names, pattern

JAVA = "Java"
KOTLIN = "Kotlin"
POM = "pom.xml"
GRADLE_BUILD_FILES = ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts")


def _output_beside(name: str, build_files: tuple[str, ...]) -> Callable[[Path], bool]:
    def is_build_tree(directory: Path) -> bool:
        return directory.name == name and any((directory.parent / build_file).is_file() for build_file in build_files)

    return is_build_tree


def _build_outputs(name: str, directory: str, *more: str) -> BuildOutputs:
    return BuildOutputs(
        name=f"the {name} directory",
        globs=ignored_at_top_level(directory),
        paths=directories(directory),
        hint=f"consider ignoring {' and '.join((f'{directory}/', *more))}",
        artifacts=(f"{directory}/", *more, "*.class"),
    )


MAVEN = BuildSystem(
    name="Maven",
    files=(POM,),
    is_build_tree=_output_beside("target", (POM,)),
    rules=(_build_outputs("target", "target"),),
)
GRADLE = BuildSystem(
    name="Gradle",
    files=GRADLE_BUILD_FILES,
    is_build_tree=_output_beside("build", GRADLE_BUILD_FILES),
    rules=(_build_outputs("build", "build", ".gradle/"),),
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
RUNS_VERIFICATION = re.compile(rf"{MVN}\b(?:verify|install|deploy)\b|{GRADLE_RUN}\b(?:build|check)\b")


def _build_files(context: Context) -> tuple[str, ...]:
    names = {POM, *GRADLE_BUILD_FILES}
    return tuple(path for path in context.project.files() if PurePosixPath(path).name in names)


def _texts_when(runs: re.Pattern[str]) -> Callable[[Context], tuple[str, ...]]:
    """CI configuration and pre-commit hooks, with the build files when CI runs the build as far as `runs`."""

    def texts(context: Context) -> tuple[str, ...]:
        found = ci_and_hook_texts(context)
        if not any(runs.search(text) for text in found):
            return found
        return (*found, *(context.project.read_text(path) for path in _build_files(context)))

    return texts


_build_texts = _texts_when(RUNS_BUILD)
_verification_texts = _texts_when(RUNS_VERIFICATION)


def _bound_goal(artifact: str, goals: str) -> str:
    """A Maven plugin whose execution binds one of `goals`, so that the lifecycle runs it."""
    return rf"<artifactId>{artifact}</artifactId>(?:(?!</plugin>).)*?<goal>(?:{goals})</goal>"


def _setting(name: str, regex: str) -> Pattern:
    return Pattern(name, re.compile(regex, re.IGNORECASE | re.DOTALL))


GRADLE_PLUGIN = r"""(?:id\s*\(?\s*|apply\s+plugin:\s*|plugins\.apply\s*\(\s*)["']{}["']"""


def _gradle_plugin(plugin_id: str) -> str:
    return GRADLE_PLUGIN.format(re.escape(plugin_id))


def _spotless_config(context: Context) -> str | None:
    return next((path for path in _build_files(context) if "spotless" in context.project.read_text(path)), None)


# Every formatter here has a built-in style (Spotless applies one of them).
FORMATTERS = Formatter(
    name="Spotless, google-java-format, ktfmt or ktlint",
    config_file=_spotless_config,
    runs=(
        _setting(
            "Spotless",
            rf"\bspotless:check\b|\bspotlessCheck\b|{_bound_goal('spotless-maven-plugin', 'check')}"
            rf"|{_gradle_plugin('com.diffplug.spotless')}",
        ),
        _setting("fmt-maven-plugin", _bound_goal("fmt-maven-plugin", "check")),
        _setting("google-java-format", r"\bgoogle-java-format\b[^\n]*--set-exit-if-changed\b"),
        _setting("ktfmt", r"\bktfmt\b[^\n]*--set-exit-if-changed\b"),
        _setting(
            "ktlint",
            rf"(?<![\w-])ktlint(?:Check)?\b(?![^\n]*\s(?:-F|--format)\b)|{_gradle_plugin('org.jlleitschuh.gradle.ktlint')}",
        ),
    ),
    hint="consider Spotless (spotless:check bound in pom.xml, or the com.diffplug.spotless Gradle plugin, run by "
    "mvn verify or gradle check) with google-java-format, palantir-java-format, ktfmt or ktlint",
    default_style=True,
    texts=_verification_texts,
)

SOURCE_SUFFIXES = (".java", ".kt")
TEST_SOURCES = re.compile(r"(?:^|/)src/test/(?:java|kotlin)/.+\.(?:java|kt)$")
# JUnit and TestNG annotate tests; Kotest specs extend a spec style.
TEST_CASE = re.compile(
    r"@(?:org\.junit\.(?:jupiter\.api\.)?)?Test\b|:\s*(?:Fun|String|Describe|Behavior|Should|Free|Word|Feature|Expect|Annotation)Spec\b"
)
RUNS_TESTS = (
    pattern(
        "Maven or Gradle tests",
        rf"{MVN}\b(?:test|package|verify|install|deploy)\b|{GRADLE_RUN}\b(?:test|check|build)\b",
    ),
)


def _jvm_tests(context: Context) -> Result:
    tests = (path for path in context.project.files() if TEST_SOURCES.search(path))
    count = sum(1 for path in tests if TEST_CASE.search(context.project.read_text(path)))
    if count == 0:
        return Result.failed(
            "no JVM tests found (@Test methods or Kotest specs under src/test/java or src/test/kotlin)"
        )
    return Result.passed(f"JVM tests found in {count} file(s)")


TESTS = TestSuite(found=_jvm_tests, runs=RUNS_TESTS, runner="mvn test or gradle test")

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


def _build_steps(command: Command) -> tuple[str, list[str]] | None:
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


GRADLE_SETTINGS = SettingsReader(name="Gradle", files=GRADLE_BUILD_FILES, read=_read_gradle_settings)


@dataclass(frozen=True, slots=True, kw_only=True)
class _Wiring:
    """How a JVM coverage tool runs: a goal or task that writes its report (`report`), or a Maven plugin (with a goal
    matching `bound_goal`, when given) or Gradle plugin or linked task that the verification CI runs brings in."""

    report: re.Pattern[str]
    maven_plugin: str
    bound_goal: re.Pattern[str] | None
    gradle_plugin: str | None = None


def _wired(wiring: _Wiring, kind: str, facts: Facts) -> list[Setting]:
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


def _jvm_coverage(wiring: _Wiring) -> Measure:
    def measures(command: Command, facts: Facts) -> Measurement | None:
        found = _build_steps(command)
        if found is None:
            return None
        kind, steps = found
        if any(wiring.report.fullmatch(step) for step in steps):
            return measured(Granularity.LINE, Granularity.BRANCH)
        if _verifies(kind, steps) and (read := _wired(wiring, kind, facts)):
            return measured(Granularity.LINE, Granularity.BRANCH, read=read)
        return None

    return measures


# JaCoCo and Kover count branches; neither reports path coverage.
JVM_LANGUAGES = frozenset({JAVA, KOTLIN})
JACOCO = CoverageTool(
    name="JaCoCo",
    languages=JVM_LANGUAGES,
    can={
        Granularity.LINE: "jacoco:report or jacocoTestReport",
        Granularity.BRANCH: "jacoco:report or jacocoTestReport",
    },
    measures=_jvm_coverage(
        _Wiring(
            report=re.compile(r"(?:org\.jacoco:)?jacoco(?:-maven-plugin)?(?::[^:]+)?:report[\w-]*|jacoco\w*Report"),
            maven_plugin="jacoco-maven-plugin",
            bound_goal=re.compile(r"report[\w-]*"),
        )
    ),
    reads=("Maven", "Gradle"),
)
KOVER = CoverageTool(
    name="Kover",
    languages=JVM_LANGUAGES,
    can={Granularity.LINE: "koverXmlReport", Granularity.BRANCH: "koverXmlReport"},
    measures=_jvm_coverage(
        _Wiring(
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

XLINT = _setting("-Xlint:all", r"-Xlint(?::all)?(?![:\w-])")
# The Kotlin compiler warns by default; a Kotlin-only project is judged by warnings-as-errors.
KOTLIN_WARNINGS = _setting(
    "Kotlin's default warnings", r"\bkotlin-maven-plugin\b|\borg\.jetbrains\.kotlin\b|\bkotlin\s*\(\s*[\"']jvm[\"']"
)


def _required_warnings(context: Context) -> tuple[Pattern, ...]:
    return (XLINT,) if JAVA in context.structure.languages else (KOTLIN_WARNINGS,)


WARNINGS = WarningPolicy(
    kind="JVM compiler warnings",
    recognised=(XLINT, KOTLIN_WARNINGS),
    required=_required_warnings,
    texts=_build_texts,
    separator=", ",
)

WARNINGS_AS_ERRORS = WarningsAsErrors(
    flags=(
        _setting("-Werror", r"-Werror\b"),
        _setting("allWarningsAsErrors", r"\ballWarningsAsErrors\b(?:\s*(?:=|\.set\s*\()\s*|>\s*)true\b"),
    ),
    texts=_build_texts,
    searched="the Maven or Gradle build, or CI configuration",
    hint="add -Werror to javac's compilerArgs (Kotlin: allWarningsAsErrors = true)",
)

SECURITY_LINTS = SecurityLints(
    texts=_verification_texts,
    lints=(
        _setting("Find Security Bugs", r"\bfindsecbugs-plugin\b|\bcom\.h3xstream\.findsecbugs\b"),
        _setting("PMD security rules", r"\bcategory/java/security\.xml\b"),
    ),
)

DEPENDENCY_AUDIT = DependencyAudit(
    tools=(
        _setting(
            "OWASP dependency-check",
            rf"\bdependency-check:(?:check|aggregate)\b|\bdependencyCheck(?:Analyze|Aggregate)\b"
            rf"|\bdependency-check\.sh\b|\bdependency-check/Dependency-Check_Action\b"
            rf"|{_bound_goal('dependency-check-maven', 'check|aggregate')}",
        ),
        *MULTI_ECOSYSTEM_AUDITS,
    ),
    hint="consider OWASP dependency-check in CI (dependency-check-maven bound to check, or gradle "
    "dependencyCheckAnalyze)",
    texts=_verification_texts,
)


def _checkstyle_configs(context: Context) -> list[str]:
    return [
        path
        for path in context.project.files()
        if "checkstyle" in PurePosixPath(path).name.lower() and path.endswith(".xml")
    ]


DETEKT_CONFIG_FILES = ("detekt.yml", "config/detekt/detekt.yml", "detekt-config.yml")
METHOD_LENGTH = re.compile(r"""name\s*=\s*["']MethodLength["']""")
# detekt's LongMethod rule is active by default.
LONG_METHOD_OFF = re.compile(r"^\s*LongMethod:\s*\n\s*active:\s*false\b", re.MULTILINE)
RUNS_CHECKSTYLE = pattern("Checkstyle", r"\bcheckstyle\b")
RUNS_DETEKT = pattern("detekt", r"\bdetekt\b")


def _method_length_check(context: Context) -> str | None:
    """The Checkstyle configuration that enables the MethodLength check, if any."""
    configs = _checkstyle_configs(context)
    return next((path for path in configs if METHOD_LENGTH.search(context.project.read_text(path))), None)


def _long_method_active(context: Context) -> bool:
    config = first_existing(context, DETEKT_CONFIG_FILES)
    return config is None or not LONG_METHOD_OFF.search(context.project.read_text(config))


def _method_length_enforced(context: Context) -> Result:
    """Checkstyle's MethodLength check, or detekt's LongMethod rule, limits method length when the tool runs."""
    texts = _verification_texts(context)
    checkstyle = _method_length_check(context)
    if checkstyle and matching_names(texts, (RUNS_CHECKSTYLE,)):
        return Result.passed(f"function length is limited with Checkstyle MethodLength ({checkstyle})")
    if _long_method_active(context) and matching_names(texts, (RUNS_DETEKT,)):
        return Result.passed("function length is limited with detekt LongMethod")
    if checkstyle:
        return Result.warned(f"MethodLength is enabled in {checkstyle} but Checkstyle does not run")
    return Result.failed(
        "function length is never limited; enable Checkstyle's MethodLength check, run detekt, "
        f"or run {SUGGESTED_LIZARD} in CI"
    )


def _checkstyle_config(context: Context) -> str | None:
    return next(iter(_checkstyle_configs(context)), None)


STATIC_ANALYSIS = StaticAnalysis(
    analyzers=(
        Analyzer(name="Error Prone", runs=re.compile(r"\berror_?prone\b|\bnet\.ltgt\.errorprone\b", re.IGNORECASE)),
        Analyzer(name="SpotBugs", runs=re.compile(r"\bspotbugs\b", re.IGNORECASE)),
        Analyzer(
            name="PMD",
            runs=re.compile(
                rf"<artifactId>maven-pmd-plugin</artifactId>|\bpmd:check\b|\bpmd\s+check\b|{_gradle_plugin('pmd')}"
            ),
        ),
        Analyzer(name="Checkstyle", runs=RUNS_CHECKSTYLE.regex, configured=_checkstyle_config),
        Analyzer(name="detekt", runs=RUNS_DETEKT.regex, configured=configuration(DETEKT_CONFIG_FILES)),
    ),
    texts=_verification_texts,
    hint="consider Error Prone, SpotBugs, PMD or Checkstyle (detekt for Kotlin), run by mvn verify or gradle check",
)

MAVEN_DEPENDENCY = re.compile(r"<dependency>")
GRADLE_DEPENDENCY = re.compile(r"^\s*(?:implementation|api|compileOnly|runtimeOnly|testImplementation)\b", re.MULTILINE)
GRADLE_LOCKS = ("gradle/verification-metadata.xml", "gradle.lockfile")
MAVEN_CONFIG = ".mvn/maven.config"
STRICT_CHECKSUMS = re.compile(rf"{MVN}(?:--strict-checksums|\s-C\b)")


def _managed(context: Context) -> str | None:
    for path in _build_files(context):
        text = context.project.read_text(path)
        if PurePosixPath(path).name == POM and MAVEN_DEPENDENCY.search(text):
            return "managed with Maven"
        if PurePosixPath(path).name != POM and GRADLE_DEPENDENCY.search(text):
            return "managed with Gradle"
    return None


def _verified(context: Context) -> str | None:
    """Gradle's dependency verification metadata or lockfile, or Maven failing on a bad checksum."""
    if lock := next((path for path in GRADLE_LOCKS if context.committed(path)), None):
        return lock
    if context.project.exists(MAVEN_CONFIG) and "--strict-checksums" in context.project.read_text(MAVEN_CONFIG):
        return f"{MAVEN_CONFIG} (--strict-checksums)"
    return "CI (mvn --strict-checksums)" if any(map(STRICT_CHECKSUMS.search, context.ci_texts)) else None


DEPENDENCIES = DependencyManagement(
    managed=_managed,
    locked=_verified,
    lock_hint="verify them: commit gradle/verification-metadata.xml (gradle --write-verification-metadata sha256) "
    "or a gradle.lockfile; with Maven, run with --strict-checksums",
)

CLASS_FILES = BuildOutputs(
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
    toolchain=ToolchainPatterns(
        language="JDK",
        versions=JDK_VERSIONS,
        usage=re.compile(rf"{MAVEN_COMMAND}|{GRADLE_COMMAND}|\bsetup-java\b|\bjavac\b"),
    ),
    rules=(
        versions_axis("JDK version", "JDK"),
        FORMATTERS,
        TESTS,
        WARNINGS,
        WARNINGS_AS_ERRORS,
        SECURITY_LINTS,
        DEPENDENCY_AUDIT,
        FunctionLimits(without_lizard=_method_length_enforced),
        STATIC_ANALYSIS,
        DEPENDENCIES,
        CLASS_FILES,
    ),
)
