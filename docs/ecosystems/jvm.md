# JVM

Java and Kotlin, recognised by `.java` and `.kt` sources and Maven (`pom.xml`) or Gradle builds. The Maven or Gradle
build counts as CI configuration when CI runs it (`mvn verify`, `gradle check`), since that is where its plugins are
wired in.

## `tests-run`

`@Test` methods or Kotest specs under `src/test/java` or `src/test/kotlin`, run by `mvn test` / `verify` or
`gradle test` / `check` / `build`.

## `coverage`

JaCoCo (`jacoco:report`, `jacocoTestReport`, or `jacoco-maven-plugin` with its `report` goal bound when CI runs
`mvn verify`) or Kover (a `kover…Report` task, or its plugin when CI runs `gradle check`).

## `platform-matrix`

The toolchains are JDK versions.

## `compiler-warnings`

javac's `-Xlint:all`; a Kotlin-only project passes on Kotlin's default warnings.

## `warnings-as-errors`

`-Werror` for javac or kotlinc, or Kotlin's `allWarningsAsErrors`.

## `code-formatting`

Spotless (`spotless:check` or `spotlessCheck`, or the plugin bound to `check` in pom.xml or applied in a Gradle
build, run by `mvn verify` or `gradle check`) and fmt-maven-plugin for Java and Kotlin or Java; google-java-format
(`--set-exit-if-changed`) for Java; ktfmt (`--set-exit-if-changed`) and ktlint (without `-F`, or `ktlintCheck`) for
Kotlin. They have a default style, so CI enforcement alone passes.

## `function-limits`

lizard runs with a length limit, or Checkstyle runs with `MethodLength`, or detekt runs with `LongMethod` (on by
default).

## `static-analysis`

Error Prone, SpotBugs, PMD, Checkstyle or detekt.

## `security-scanning`

SpotBugs with Find Security Bugs, or PMD's `category/java/security.xml` rules.

## `dependency-management`

Dependencies declared in `pom.xml` or a Gradle build are verified by a committed `gradle/verification-metadata.xml`
or `gradle.lockfile`, or Maven runs with `--strict-checksums`.

## `dependency-audit`

OWASP dependency-check (`dependency-check-maven` bound to `check`, or `dependencyCheckAnalyze`).

## `committed-artifacts`

`*.class`, plus Maven's `target/` or Gradle's `build/` and `.gradle/`.

## `vcs-ignore`

Maven's `target/` or Gradle's `build/`.
