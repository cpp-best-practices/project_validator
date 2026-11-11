"""The JVM static analyzers: SpotBugs, PMD and Checkstyle (Java), detekt (Kotlin), run by their goals and tasks or by
the plugins a build's verification brings in, and Error Prone, which the compiler runs on every build that compiles."""

from __future__ import annotations

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
from project_validator.facts import Command, Fact, Facts, Setting, Unknown
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.limits import Rule, limiter
from project_validator.facts.security import scanned, scanner
from project_validator.facts.settings import (
    SettingsReader,
    matched_settings,
    settings,
    xml_root,
    yaml_settings,
)
from project_validator.facts.tools import Claim, Run, Tool, defined_by, either
from project_validator.tools.limits import function_length_limiters
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


def _read_checkstyle(path: str, text: str) -> Iterator[Fact]:
    """The modules (checks) a Checkstyle configuration names."""
    root = xml_root("Checkstyle", path, text)
    if isinstance(root, Unknown):
        yield root
        return
    names = tuple(module.get("name", "") for module in root.iter("module"))
    yield from settings("Checkstyle", path, (("modules", names),))


CHECKSTYLE_SETTINGS = SettingsReader(
    name="Checkstyle", files=("*checkstyle*.xml", "*Checkstyle*.xml"), read=_read_checkstyle
)
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
DETEKT_SETTINGS = SettingsReader(
    name="detekt",
    files=("detekt.yml", "detekt-config.yml", "config/detekt/detekt.yml"),
    read=lambda path, text: yaml_settings("detekt", path, text),
)
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


def _method_length_module(facts: Facts) -> list[Setting]:
    return [setting for setting in facts.settings("Checkstyle") if "MethodLength" in _names(setting)]


def _names(setting: Setting) -> tuple[object, ...]:
    return setting.value if isinstance(setting.value, tuple) else ()


def _long_method(facts: Facts, *, on: bool) -> list[Setting]:
    """The detekt settings that turn LongMethod off (it or its rule set inactive), or, unless they do, on (its
    settings)."""
    found = facts.settings("detekt")
    off = [setting for setting in found if setting.key in _LONG_METHOD_OFF and setting.value is False]
    if not on or off:
        return [] if on else off
    return [setting for setting in found if setting.key.startswith("complexity.LongMethod.")]


_LONG_METHOD_OFF = frozenset({"complexity.LongMethod.active", "complexity.active"})
METHOD_LENGTH = limiter(
    name="Checkstyle's MethodLength",
    languages=frozenset({JAVA}),
    how="Checkstyle with its MethodLength check",
    runs=CHECKSTYLE.claims,
    rule=Rule(describe="the MethodLength module in the Checkstyle configuration", enabled=_method_length_module),
    reads=("Maven", "Gradle", "Checkstyle"),
)
# detekt's LongMethod rule is active by default.
LONG_METHOD = limiter(
    name="detekt's LongMethod",
    languages=frozenset({KOTLIN}),
    how="detekt",
    runs=DETEKT.claims,
    rule=Rule(
        describe="LongMethod active in the detekt configuration",
        enabled=lambda facts: _long_method(facts, on=True),
        disabled=lambda facts: _long_method(facts, on=False),
        default=True,
    ),
    reads=("Maven", "Gradle", "detekt"),
)
FUNCTION_LENGTH_LIMITERS = (METHOD_LENGTH, LONG_METHOD, *function_length_limiters(JVM_LANGUAGES))

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
