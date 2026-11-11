# Dart

Dart and Flutter, recognised by `.dart` sources and pub's `pubspec.yaml` (a pub workspace's `workspace:` packages are
units of their own). Flutter is Dart with a framework: `flutter test`, `flutter analyze` and a Flutter SDK count
wherever `dart test`, `dart analyze` and a Dart SDK do. A `build/` directory next to a pubspec is a build tree and is
never read.

The compiled-language checks that need a C-family compiler (hardening, build types, extensions, sanitizers) do not
apply, and nor do type checking (Dart is statically typed, with sound null safety), fuzz testing and mutation testing
(no fuzzer or mutation tool for Dart is known).

## `tests-run`

`test()`, `testWidgets()` or `group()` calls in `test/**/*_test.dart`, run by `dart test`, `flutter test`,
`dart run test` or `very_good test`.

## `coverage`

`dart test --coverage=<dir>` and `flutter test --coverage` write line coverage; with `--branch-coverage` (Dart 2.17+),
branches too, which is what is asked for. `dart run coverage:test_with_coverage` (package:coverage) is the same
collection; `very_good test --coverage` counts lines.

## `platform-matrix`

The toolchains are Dart or Flutter SDK versions: dart-lang/setup-dart's `sdk` (a version or a channel: `3.5`,
`stable`), the `dart` image (`dart:3.5`), subosito/flutter-action's `flutter-version`, the cirruslabs Flutter image.

## `compiler-warnings`

The analyzer reports what other compilers warn about, so two things are asked for: a lint set included in
`analysis_options.yaml` (`package:lints/recommended.yaml`, `flutter_lints`, `very_good_analysis`, `lint/strict`) and
`dart analyze` (or `flutter analyze`) run in CI.

## `warnings-as-errors`

`dart analyze` fails on errors and warnings already; `dart analyze --fatal-infos` makes the infos, the lints' level,
fatal too.

## `code-formatting`

`dart format --set-exit-if-changed` (with `--output=none`, without writing), which fails on a file it would change;
plain `dart format` rewrites, and `--output=none` alone only lists. The style is the formatter's own.

## `static-analysis`

`dart analyze` (or `flutter analyze`), with its lints and `analyzer:` settings in `analysis_options.yaml`;
custom_lint (`dart run custom_lint`); DCM (`dcm analyze`).

## `security-scanning`

semgrep, which reads Dart; CodeQL and GitLab SAST do not.

## `dependency-audit`

osv-scanner or trivy, which read `pubspec.lock`; snyk and GitLab Dependency Scanning do not.

## `dependency-management`

pub's guidance: an application (`publish_to: none`) commits `pubspec.lock`; a package that may be published leaves it
out, so a publishable package without one passes.

## `committed-artifacts`

`.dart_tool/` and `build/`.

## `vcs-ignore`

`.dart_tool/`; `build/` and `coverage/` are worth ignoring too.

## `function-limits`

lizard parses Dart, so CI runs it with a length limit.
