# Scala

Recognised by `.scala` sources and the build tools: sbt (`*.sbt`), Mill (`build.mill`, `build.sc`) and scala-cli
(`project.scala`). `.sc` scripts (Ammonite, Mill) are Scala's once the project is; `.sbt` files name no language of
their own. The build's `target/`, `out/` and `.scala-build/` directories are build trees and are never read.

The tools run tasks, and one command may run several: `sbt coverage test coverageReport`, `sbt "scalafixAll --check"`,
`sbt "; core/test; Test/scalafmtCheck"` (a scope and a cross-building `+` are dropped; `++3.3.5` only switches the
Scala version), `mill __.fix --check + __.compile` (a selector whose last segment is the task), `scala-cli test .`
(also as the `scala` runner since Scala 3.5). Every rule below is about the task, however it is run.

The compiled-language checks that need a C-family compiler (hardening, build types, extensions, sanitizers) do not
apply, and nor do type checking (Scala is statically typed), fuzz and mutation testing (no fuzzer or mutation tool for
Scala is known) and dependency management (sbt, Mill and scala-cli lock nothing).

## `tests-run`

munit, ScalaTest, specs2, utest, ZIO Test or ScalaCheck suites under `src/test/scala` (or Mill's `test/src`),
recognised by their import or the suite they extend, run by `sbt test` (`testOnly`, `testQuick`), `mill __.test` or
`scala-cli test`.

## `coverage`

scoverage, which instruments statements and branches: `sbt coverage test coverageReport` (or `coverageAggregate`), or
Mill's `__.scoverage.xmlReport` (`htmlReport`, `consoleReport`). sbt-jacoco (`sbt jacoco`) counts lines and
branches too.

## `platform-matrix`

The toolchains are the JDK versions (the JVM profile's: `java-version`, the JDK images, coursier's `jvm` input) and the
Scala versions a job switches to (`sbt ++3.3.5 test`, `scala-cli --scala 3.3.5`, `-S 3.3.5`, a `scala-version`
input). A job naming both runs each Scala version on each JDK (`JDK 21 / Scala 3.3.5`); one that switches to no Scala
version builds the version its build names, and counts its JDKs.

## `compiler-warnings`

`-deprecation`, `-feature` and `-Xlint` (Scala 2) or `-Wunused`/`-Wall` (Scala 3) in `scalacOptions` (in the sbt or
Mill build, or scala-cli's `//> using options`), or sbt-tpolecat, which sets them all.

## `warnings-as-errors`

`-Werror` (or `-Xfatal-warnings`) in `scalacOptions`, or sbt-tpolecat's CI mode (`SBT_TPOLECAT_CI=true` in CI, or
`tpolecatDefaultOptionsMode := CiMode`).

## `code-formatting`

scalafmt, which refuses to run without a `.scalafmt.conf` naming its version: `sbt scalafmtCheckAll` (`scalafmtCheck`,
`scalafmtSbtCheck`), `scalafmt --check` (`--test`, `--list`), Mill's `__.checkFormat` (`checkFormatAll`) or
`scala-cli fmt --check`, each failing on a file it would change; `scalafmtAll`, `scalafmt`, `__.reformat` and plain
`scala-cli fmt` rewrite.

## `static-analysis`

scalafix with the rules `.scalafix.conf` names: `sbt "scalafixAll --check"` (or `scalafix`), Mill's `__.fix --check`.

## `security-scanning`

semgrep or GitLab SAST; CodeQL does not analyse Scala.

## `dependency-audit`

sbt-dependency-check (`sbt dependencyCheck`, `dependencyCheckAggregate`), snyk or GitLab Dependency Scanning;
osv-scanner and trivy read no sbt build.

## `committed-artifacts`

sbt's `target/`, Mill's `out/`, scala-cli's `.scala-build/`.

## `vcs-ignore`

The build tool's output directory (`target/`, `out/` or `.scala-build/`); `.bsp/`, `.bloop/` and `.metals/` are
worth ignoring too.

## `function-limits`

lizard parses Scala, so CI runs it with a length limit.
