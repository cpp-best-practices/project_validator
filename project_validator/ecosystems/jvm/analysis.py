"""The JVM static analyzers: SpotBugs, PMD and Checkstyle (Java), detekt (Kotlin), run by their goals and tasks or by
the plugins a build's verification brings in, and Error Prone, which the compiler runs on every build that compiles."""

import re
from collections.abc import Iterator

from project_validator.ecosystems.jvm import (
    GRADLE_PLUGIN,
    JAVA,
    JVM_LANGUAGES,
    KOTLIN,
    POM,
    Wiring,
    build_steps,
    plugin_definition,
    wired_run,
)
from project_validator.facts import Command, Fact, Facts, Setting
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.security import scanned, scanner
from project_validator.facts.settings import SettingsReader, file_reader, matched_settings
from project_validator.facts.tools import Claim, Run, Tool, defined_by, either
from project_validator.tools.scanners import multi_language_scanners


def _wired(wiring: Wiring) -> Claim:
    def analyses(command: Command, facts: Facts) -> Run | None:
        read = wired_run(wiring, command, facts)
        return None if read is None else analysed(read=read)

    return analyses


def _goal(plugin: str, goal: str = "check") -> re.Pattern[str]:
    """`plugin:goal`, as Maven runs it by prefix (`pmd:check`) or by coordinates."""
    return re.compile(rf"(?:[\w.-]+:)?(?:maven-)?{plugin}(?:-maven-plugin)?(?::[^:]+)?:{goal}")


SPOTBUGS = analyzer(
    name="SpotBugs",
    languages=JVM_LANGUAGES,
    how="SpotBugs (spotbugs-maven-plugin bound to check, or the com.github.spotbugs Gradle plugin)",
    analyses=_wired(
        Wiring(
            report=re.compile(rf"{_goal('spotbugs').pattern}|spotbugs\w*"),
            maven_plugin="spotbugs-maven-plugin",
            bound_goal=re.compile("check"),
            gradle_plugin="com.github.spotbugs",
        )
    ),
    rules=plugin_definition("spotbugs-maven-plugin", "com.github.spotbugs"),
    reads=("Maven", "Gradle"),
)
PMD = analyzer(
    name="PMD",
    languages=frozenset({JAVA}),
    how="PMD (maven-pmd-plugin bound to check, or Gradle's pmd plugin)",
    analyses=either(
        _wired(
            Wiring(
                report=re.compile(rf"{_goal('pmd').pattern}|pmd\w*"),
                maven_plugin="maven-pmd-plugin",
                bound_goal=re.compile("check"),
                gradle_plugin="pmd",
            )
        ),
        lambda command, _facts: analysed() if command.argv[:2] == ("pmd", "check") else None,
    ),
    rules=plugin_definition("maven-pmd-plugin", "pmd"),
    reads=("Maven", "Gradle"),
)
CHECKSTYLE_FILES = file_reader("Checkstyle", ("*checkstyle*.xml", "*Checkstyle*.xml"))
CHECKSTYLE = analyzer(
    name="Checkstyle",
    languages=frozenset({JAVA}),
    how="Checkstyle (maven-checkstyle-plugin bound to check, or Gradle's checkstyle plugin)",
    analyses=_wired(
        Wiring(
            report=re.compile(rf"{_goal('checkstyle').pattern}|checkstyle\w*"),
            maven_plugin="maven-checkstyle-plugin",
            bound_goal=re.compile("check"),
            gradle_plugin="checkstyle",
        )
    ),
    rules=defined_by(files=("Checkstyle",)),
    reads=("Maven", "Gradle"),
)
DETEKT_FILES = file_reader("detekt", ("detekt.yml", "detekt-config.yml", "config/detekt/detekt.yml"))
DETEKT = analyzer(
    name="detekt",
    languages=frozenset({KOTLIN}),
    how="detekt (the io.gitlab.arturbosch.detekt Gradle plugin, run by gradle check)",
    analyses=either(
        _wired(
            Wiring(
                report=re.compile(r"detekt\w*"),
                maven_plugin="detekt-maven-plugin",
                bound_goal=re.compile("check"),
                gradle_plugin="io.gitlab.arturbosch.detekt",
            )
        ),
        lambda command, _facts: analysed() if command.argv[:1] == ("detekt",) else None,
    ),
    rules=defined_by(files=("detekt",)),
    reads=("Maven", "Gradle"),
)

# Error Prone is a compiler plugin: on a Maven compiler's processor path or arguments, or the net.ltgt.errorprone
# Gradle plugin. Matched in the build files until they are read structurally.
_ERROR_PRONE_GRADLE = GRADLE_PLUGIN.format(re.escape("net.ltgt.errorprone"))
_ERROR_PRONE = re.compile(rf"error_prone_core|-Xplugin:ErrorProne|{_ERROR_PRONE_GRADLE}")
_COMPILES = {
    "maven": frozenset({"compile", "test-compile", "test", "package", "verify", "install", "deploy"}),
    "gradle": frozenset({"build", "check", "test", "assemble", "classes", "compileJava", "jar"}),
}


def _read_error_prone(path: str, text: str) -> Iterator[Fact]:
    return matched_settings("Error Prone", path, text, {"enabled": (_ERROR_PRONE, True)})


ERROR_PRONE_SETTINGS = SettingsReader(
    name="Error Prone", files=(POM, "*.gradle", "*.gradle.kts"), read=_read_error_prone
)


def _error_prone(command: Command, facts: Facts) -> Run | None:
    found = build_steps(command)
    if found is None or not set(found[1]) & _COMPILES[found[0]]:
        return None
    read = facts.where(Setting, tool="Error Prone")
    return analysed(read=read) if read else None


ERROR_PRONE = analyzer(
    name="Error Prone",
    languages=frozenset({JAVA}),
    how="Error Prone (a compiler plugin, run by every build)",
    analyses=_error_prone,
    rules=defined_by(settings=("Error Prone",)),
    reads=("Error Prone",),
)

# The security rules of SpotBugs and PMD, configured in the build files: matched in their text until they are read
# structurally.
_FIND_SECURITY_BUGS = re.compile(r"\bfindsecbugs-plugin\b|\bcom\.h3xstream\.findsecbugs\b")
_PMD_SECURITY_RULES = re.compile(r"\bcategory/java/security\.xml\b")
JVM_SECURITY_SETTINGS = SettingsReader(
    name="JVM security rules",
    files=(POM, "*.gradle", "*.gradle.kts"),
    read=lambda path, text: matched_settings(
        "JVM security rules",
        path,
        text,
        {"Find Security Bugs": (_FIND_SECURITY_BUGS, True), "PMD security rules": (_PMD_SECURITY_RULES, True)},
    ),
)


def _with_rules(analyser: Tool, rules: str) -> Claim:
    """A run of `analyser` whose build configures its security `rules`."""

    def scans(command: Command, facts: Facts) -> Run | None:
        run = analyser.claims(command, facts)
        read = facts.where(Setting, tool="JVM security rules", key=rules)
        return scanned(read=(*run.read, *read)) if run is not None and read else None

    return scans


SECURITY_SCANNERS = (
    scanner(
        name="Find Security Bugs",
        languages=JVM_LANGUAGES,
        how="Find Security Bugs (the findsecbugs-plugin of SpotBugs)",
        scans=_with_rules(SPOTBUGS, "Find Security Bugs"),
        reads=("Maven", "Gradle", "JVM security rules"),
    ),
    scanner(
        name="PMD security rules",
        languages=frozenset({JAVA}),
        how="PMD with category/java/security.xml",
        scans=_with_rules(PMD, "PMD security rules"),
        reads=("Maven", "Gradle", "JVM security rules"),
    ),
    *multi_language_scanners(JVM_LANGUAGES),
)
