"""The JVM profile's rules, judged by the generic checks in the Maven and Gradle project layouts."""

import unittest

from project_validator.core import Check, Result, Status
from project_validator.ecosystems.jvm import GRADLE_PACKAGES, JVM, MAVEN_PACKAGES
from tests.support import (
    GITHUB_WORKFLOW,
    checks_named,
    github_job,
    make_context,
    run_as,
    run_in_layout,
    temp_project,
)

(
    CODE_FORMATTING,
    COMMITTED_ARTIFACTS,
    COMPILER_WARNINGS,
    COVERAGE,
    DEPENDENCY_AUDIT,
    DEPENDENCY_MANAGEMENT,
    FUNCTION_LIMITS,
    PLATFORM_MATRIX,
    SECURITY_SCANNING,
    STATIC_ANALYSIS,
    TESTS_RUN,
    VCS_IGNORE,
    WARNINGS_AS_ERRORS,
) = checks_named(
    "code-formatting",
    "committed-artifacts",
    "compiler-warnings",
    "coverage",
    "dependency-audit",
    "dependency-management",
    "function-limits",
    "platform-matrix",
    "security-scanning",
    "static-analysis",
    "tests-run",
    "vcs-ignore",
    "warnings-as-errors",
)
MAVEN_VERIFY = "./mvnw -B verify"
GRADLE_CHECK = "./gradlew check"


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


def _pom(plugins: str = "", dependencies: str = "") -> dict[str, str]:
    return {
        "pom.xml": f"<project><dependencies>{dependencies}</dependencies>"
        f"<build><plugins>{plugins}</plugins></build></project>\n"
    }


def _plugin(artifact: str, *goals: str) -> str:
    bound = "".join(f"<goal>{goal}</goal>" for goal in goals)
    executions = f"<executions><execution><goals>{bound}</goals></execution></executions>"
    return f"<plugin><artifactId>{artifact}</artifactId>{executions}</plugin>"


def _gradle(build: str) -> dict[str, str]:
    return {"build.gradle.kts": build}


def _maven(test: unittest.TestCase, selected: Check, files: dict[str, str]) -> Result:
    return run_in_layout(test, "Maven Java", selected, files)


def _gradle_kotlin(test: unittest.TestCase, selected: Check, files: dict[str, str]) -> Result:
    return run_in_layout(test, "Gradle Kotlin", selected, files)


class RecognitionTests(unittest.TestCase):
    def _structure(self, files: dict[str, str]) -> tuple[frozenset[str], tuple[tuple[str, int], ...]]:
        with temp_project(files) as root:
            structure = make_context(root).structure
            return structure.languages, structure.unrecognised_suffixes

    def test_kotlin_and_groovy_scripts_add_no_language(self) -> None:
        files = {"build.gradle.kts": "", "gradle/publish.gradle": "", "src/main/java/App.java": "", "x.kts": ""}
        self.assertEqual(self._structure(files), (frozenset({"Java"}), ()))

    def test_build_output_beside_a_build_file_is_not_inspected(self) -> None:
        files = {"pom.xml": "", "target/generated/App.kt": "", "lib/build.gradle": "", "lib/build/Gen.kt": ""}
        self.assertEqual(self._structure(files)[0], frozenset())


class BuildLifecycleTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_as(self, selected, files, JVM)

    def test_a_bound_maven_plugin_runs_when_ci_verifies(self) -> None:
        spotless = _pom(_plugin("spotless-maven-plugin", "check"))
        self.assertEqual(_maven(self, CODE_FORMATTING, {**spotless, **_ci(MAVEN_VERIFY)}).status, Status.PASS)
        # mvn test stops before the verify phase, and an unbound plugin never runs.
        self.assertEqual(_maven(self, CODE_FORMATTING, {**spotless, **_ci("mvn test")}).status, Status.WARN)
        unbound = _pom("<plugin><artifactId>spotless-maven-plugin</artifactId></plugin>")
        self.assertEqual(_maven(self, CODE_FORMATTING, {**unbound, **_ci(MAVEN_VERIFY)}).status, Status.WARN)

    def test_a_gradle_plugin_runs_with_check(self) -> None:
        build = _gradle('plugins {\n    id("com.diffplug.spotless") version "7.0.0"\n}\n')
        self.assertEqual(_gradle_kotlin(self, CODE_FORMATTING, {**build, **_ci(GRADLE_CHECK)}).status, Status.PASS)
        self.assertEqual(_gradle_kotlin(self, CODE_FORMATTING, {**build, **_ci("./gradlew test")}).status, Status.WARN)

    def test_a_convention_plugin_applies_its_plugins(self) -> None:
        convention = {
            "buildSrc/src/main/kotlin/conventions.gradle.kts": 'plugins {\n    id("com.diffplug.spotless")\n}\n',
            **_gradle('plugins {\n    id("conventions")\n}\n'),
        }
        result = _gradle_kotlin(self, CODE_FORMATTING, {**convention, **_ci(GRADLE_CHECK)})
        self.assertEqual(
            result, Result.passed("buildSrc/src/main/kotlin/conventions.gradle.kts is defined and CI runs Spotless")
        )

    def test_formatters_run_directly(self) -> None:
        for command in ("mvn spotless:check", "./gradlew spotlessCheck"):
            with self.subTest(command=command):
                self.assertEqual(self._run(CODE_FORMATTING, _ci(command)).status, Status.PASS)
        # Each formatter formats its own language: ktlint and ktfmt Kotlin, google-java-format Java.
        for command in ("ktlint", "ktfmt --set-exit-if-changed src", "./gradlew ktlintCheck"):
            with self.subTest(command=command):
                self.assertEqual(_gradle_kotlin(self, CODE_FORMATTING, _ci(command)).status, Status.PASS)
                self.assertEqual(_maven(self, CODE_FORMATTING, _ci(command)).status, Status.FAIL)
        java = _maven(self, CODE_FORMATTING, _ci("google-java-format --set-exit-if-changed -n src/**/*.java"))
        self.assertEqual(java.status, Status.PASS)
        rewritten = _gradle_kotlin(self, CODE_FORMATTING, _ci("ktlint -F"))
        self.assertEqual(
            rewritten.message, "CI runs ktlint but only to rewrite files; nothing fails when they are not formatted"
        )

    def test_tests_are_annotated_or_kotest_specs_under_src_test(self) -> None:
        kotest = {"src/test/kotlin/AppSpec.kt": "class AppSpec : FunSpec({})\n"}
        self.assertEqual(self._run(TESTS_RUN, {**kotest, **_ci(GRADLE_CHECK)}).status, Status.PASS)
        self.assertEqual(self._run(TESTS_RUN, kotest).status, Status.WARN)
        self.assertEqual(
            self._run(TESTS_RUN, {"src/main/java/AppTest.java": "@Test void a() {}\n"}).status, Status.FAIL
        )

    def test_coverage_is_jacoco_or_kover(self) -> None:
        for files in (
            _ci("./gradlew test jacocoTestReport"),
            _ci("./gradlew koverXmlReport"),
            {**_pom(_plugin("jacoco-maven-plugin", "prepare-agent", "report")), **_ci(MAVEN_VERIFY)},
        ):
            with self.subTest(files=files):
                self.assertEqual(self._run(COVERAGE, files).status, Status.PASS)
        prepared_only = {**_pom(_plugin("jacoco-maven-plugin", "prepare-agent")), **_ci(MAVEN_VERIFY)}
        self.assertEqual(self._run(COVERAGE, prepared_only).status, Status.FAIL)


class WarningTests(unittest.TestCase):
    def test_java_needs_xlint_all(self) -> None:
        flags = _pom("<plugin><compilerArgs><arg>-Xlint:all</arg><arg>-Werror</arg></compilerArgs></plugin>")
        result = _maven(self, COMPILER_WARNINGS, {**flags, **_ci("mvn test")})
        self.assertEqual(result, Result.passed("strict JVM compiler warnings are enabled: -Xlint:all"))
        self.assertEqual(_maven(self, WARNINGS_AS_ERRORS, {**flags, **_ci("mvn test")}).status, Status.PASS)
        # The build files count only when CI builds the project.
        self.assertEqual(_maven(self, COMPILER_WARNINGS, flags).status, Status.FAIL)

    def test_kotlin_warns_by_default_and_fails_on_warnings_when_told(self) -> None:
        build = _gradle('plugins { kotlin("jvm") }\nkotlin { compilerOptions { allWarningsAsErrors = true } }\n')
        files = {**build, **_ci("./gradlew build")}
        expected = Result.passed("strict JVM compiler warnings are enabled: Kotlin's default warnings")
        self.assertEqual(_gradle_kotlin(self, COMPILER_WARNINGS, files), expected)
        result = _gradle_kotlin(self, WARNINGS_AS_ERRORS, files)
        self.assertEqual(result, Result.passed("warnings are treated as errors with allWarningsAsErrors"))

    def test_mixed_java_and_kotlin_still_need_xlint(self) -> None:
        files = {"src/main/java/A.java": "", **_gradle('plugins { kotlin("jvm") }\n'), **_ci("./gradlew build")}
        result = _gradle_kotlin(self, COMPILER_WARNINGS, files)
        self.assertEqual(result.message, "missing JVM compiler warnings: -Xlint:all")


class SecurityTests(unittest.TestCase):
    def test_dependency_check_runs_bound_or_as_a_task(self) -> None:
        bound = {**_pom(_plugin("dependency-check-maven", "aggregate")), **_ci(MAVEN_VERIFY)}
        for files in (bound, _ci("./gradlew dependencyCheckAnalyze"), _ci("dependency-check.sh --scan .")):
            with self.subTest(files=files):
                self.assertEqual(run_as(self, DEPENDENCY_AUDIT, files, JVM).status, Status.PASS)
        # The Gradle plugin adds no task to check.
        applied = {**_gradle('plugins { id("org.owasp.dependencycheck") }\n'), **_ci(GRADLE_CHECK)}
        self.assertEqual(run_as(self, DEPENDENCY_AUDIT, applied, JVM).status, Status.WARN)

    def test_security_lints_are_find_security_bugs_or_pmd_security_rules(self) -> None:
        pmd = "<plugin><artifactId>maven-pmd-plugin</artifactId><ruleset>category/java/security.xml</ruleset></plugin>"
        files = {**_pom(pmd), **_ci(MAVEN_VERIFY)}
        # PMD's security rules count where PMD runs: its check goal, here.
        self.assertEqual(_maven(self, SECURITY_SCANNING, files).status, Status.WARN)
        result = _maven(self, SECURITY_SCANNING, {**_pom(pmd), **_ci("mvn pmd:check")})
        self.assertEqual(result, Result.passed("CI scans the code for security problems with PMD security rules"))
        findsecbugs = _pom(
            _plugin("spotbugs-maven-plugin", "check") + "<plugin><artifactId>findsecbugs-plugin</artifactId></plugin>"
        )
        bugs = _maven(self, SECURITY_SCANNING, {**findsecbugs, **_ci(MAVEN_VERIFY)})
        self.assertEqual(bugs, Result.passed("CI scans the code for security problems with Find Security Bugs"))
        # A plugin with no execution bound to its check goal never runs; once bound, mvn verify runs it.
        self.assertEqual(
            _maven(self, STATIC_ANALYSIS, files),
            Result.warned("PMD is configured (pom.xml) but does not run", JVM_HINT),
        )
        bound = {**_pom(_plugin("maven-pmd-plugin", "check")), **_ci(MAVEN_VERIFY)}
        self.assertEqual(_maven(self, STATIC_ANALYSIS, bound), Result.passed("PMD (pom.xml) runs"))

    def test_any_analyzer_of_the_language_counts_as_static_analysis(self) -> None:
        self.assertEqual(run_as(self, STATIC_ANALYSIS, _ci("mvn spotbugs:check"), JVM).status, Status.PASS)
        # Error Prone, PMD and Checkstyle analyse Java; detekt analyses Kotlin.
        error_prone = {**_gradle('plugins { id("net.ltgt.errorprone") }\n'), **_ci(GRADLE_CHECK)}
        self.assertEqual(_maven(self, STATIC_ANALYSIS, error_prone).status, Status.PASS)
        self.assertEqual(_gradle_kotlin(self, STATIC_ANALYSIS, error_prone).status, Status.FAIL)
        self.assertEqual(_gradle_kotlin(self, STATIC_ANALYSIS, _ci("./gradlew detekt")).status, Status.PASS)
        self.assertEqual(_maven(self, STATIC_ANALYSIS, _ci("./gradlew detekt")).status, Status.FAIL)
        # PMD's copy-paste detector is not its static analysis.
        self.assertEqual(_maven(self, STATIC_ANALYSIS, _ci("pmd cpd --minimum-tokens 100")).status, Status.FAIL)


JVM_HINT = (
    "consider running SpotBugs (spotbugs-maven-plugin bound to check, or the com.github.spotbugs Gradle plugin), "
    "PMD (maven-pmd-plugin bound to check, or Gradle's pmd plugin), Checkstyle (maven-checkstyle-plugin bound to "
    "check, or Gradle's checkstyle plugin) or Error Prone (a compiler plugin, run by every build) in CI"
)
CHECKSTYLE = {
    "config/checkstyle/checkstyle.xml": '<module name="MethodLength"><property name="max" value="40"/></module>'
}


class FunctionLimitTests(unittest.TestCase):
    """Checkstyle measures Java, and detekt Kotlin."""

    def _java(self, files: dict[str, str]) -> Result:
        return run_in_layout(self, "Maven Java", FUNCTION_LIMITS, files)

    def _kotlin(self, files: dict[str, str]) -> Result:
        return run_in_layout(self, "Gradle Kotlin", FUNCTION_LIMITS, files)

    def test_checkstyle_method_length_limits_methods_when_checkstyle_runs(self) -> None:
        result = self._java({**CHECKSTYLE, **_ci("mvn checkstyle:check")})
        expected = "function length is limited with Checkstyle's MethodLength (config/checkstyle/checkstyle.xml)"
        self.assertEqual(result, Result.passed(expected))
        warned = self._java(CHECKSTYLE)
        self.assertEqual(
            warned.message,
            "config/checkstyle/checkstyle.xml limits function length, but CI does not run Checkstyle's MethodLength",
        )
        unreadable = self._java({"config/checkstyle/checkstyle.xml": "<module", **_ci("mvn checkstyle:check")})
        self.assertEqual(unreadable.status, Status.ERROR)

    def test_detekt_limits_methods_unless_long_method_is_off(self) -> None:
        self.assertEqual(
            self._kotlin(_ci("./gradlew detekt")), Result.passed("function length is limited with detekt's LongMethod")
        )
        detekt = "config/detekt/detekt.yml"
        threshold = {detekt: "complexity:\n  LongMethod:\n    threshold: 40\n", **_ci("./gradlew detekt")}
        self.assertEqual(
            self._kotlin(threshold), Result.passed(f"function length is limited with detekt's LongMethod ({detekt})")
        )
        for config in (
            "complexity:\n  LongMethod:\n    active: false\n    threshold: 40\n",
            "complexity:\n  active: false\n",
        ):
            with self.subTest(config=config):
                self.assertEqual(self._kotlin({detekt: config, **_ci("./gradlew detekt")}).status, Status.FAIL)


class DependencyAndOutputTests(unittest.TestCase):
    def test_declared_dependencies_must_be_verified(self) -> None:
        declared = _pom(dependencies="<dependency><artifactId>guava</artifactId></dependency>")
        expected = Result.warned(
            "dependencies are declared in pom.xml (Maven) but not locked", MAVEN_PACKAGES.lock_hint
        )
        self.assertEqual(_maven(self, DEPENDENCY_MANAGEMENT, declared), expected)
        config = {**declared, ".mvn/maven.config": "--strict-checksums\n"}
        locked = _maven(self, DEPENDENCY_MANAGEMENT, config)
        self.assertEqual(locked.message, "dependencies are declared in pom.xml (Maven) and locked in .mvn/maven.config")
        lax = _maven(self, DEPENDENCY_MANAGEMENT, {**declared, ".mvn/maven.config": "-B\n"})
        self.assertEqual(lax.status, Status.WARN)
        in_ci = _maven(self, DEPENDENCY_MANAGEMENT, {**declared, **_ci("./mvnw -B --strict-checksums verify")})
        self.assertEqual(in_ci.status, Status.PASS)

    def test_gradle_verification_metadata_locks_dependencies(self) -> None:
        build = _gradle('dependencies {\n    implementation("com.google.guava:guava:33.4.8-jre")\n}\n')
        files = {**build, "gradle/verification-metadata.xml": "<verification-metadata/>"}
        result = _gradle_kotlin(self, DEPENDENCY_MANAGEMENT, files)
        self.assertEqual(
            result.message,
            "dependencies are declared in build.gradle.kts (Gradle) and locked in gradle/verification-metadata.xml",
        )
        unverified = _gradle_kotlin(self, DEPENDENCY_MANAGEMENT, build)
        self.assertEqual(unverified.details, (GRADLE_PACKAGES.lock_hint,))
        self.assertEqual(_gradle_kotlin(self, DEPENDENCY_MANAGEMENT, {}).message, "no dependencies are declared")

    def test_each_build_system_ignores_its_own_output(self) -> None:
        self.assertEqual(_maven(self, VCS_IGNORE, {".gitignore": "target/\n"}).status, Status.PASS)
        self.assertEqual(_maven(self, VCS_IGNORE, {".gitignore": "build/\n"}).status, Status.WARN)
        self.assertEqual(_gradle_kotlin(self, VCS_IGNORE, {".gitignore": "/build\n"}).status, Status.PASS)
        self.assertEqual(_gradle_kotlin(self, VCS_IGNORE, {".gitignore": "target/\n"}).status, Status.WARN)

    def test_class_files_are_outputs_without_a_build_system(self) -> None:
        with temp_project({"src/App.java": "", "src/App.class": ""}) as root:
            result = COMMITTED_ARTIFACTS.run(make_context(root))
        self.assertEqual(result.message, "1 build output is committed")

    def test_the_platform_matrix_counts_jdk_versions(self) -> None:
        files = {
            GITHUB_WORKFLOW: """\
                jobs:
                  linux:
                    runs-on: ubuntu-latest
                    container: maven:3.9-eclipse-temurin-21
                    steps:
                      - run: mvn verify
                  windows:
                    runs-on: windows-latest
                    steps:
                      - uses: actions/setup-java@v4
                        with:
                          java-version: "17"
                      - run: ./gradlew.bat build
                """
        }
        result = run_as(self, PLATFORM_MATRIX, files, JVM)
        self.assertIn("2 JDK version(s) (17, 21)", result.message)
