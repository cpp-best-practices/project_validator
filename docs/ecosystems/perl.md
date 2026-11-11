# Perl

Recognised by `.pm` modules and by the build systems of a distribution: ExtUtils::MakeMaker (`Makefile.PL`),
Module::Build (`Build.PL`), Dist::Zilla (`dist.ini`) and a `cpanfile` of dependencies. Once the project is known to be
Perl, `.pl` scripts (Prolog's suffix too), `.t` tests and `.psgi` applications are Perl; POD and XS files belong to the
distribution without being Perl.

## `tests-run`

Test::More or Test2 tests in `t/*.t` (or `xt/`), run by `prove`, `make test`, `./Build test`, `dzil test`,
`minil test`, `yath test`, or Devel::Cover's `cover -test`, which runs them instrumented.

## `coverage`

Devel::Cover counts statements and branches, and conditions besides (the bonus): `cover -test` (or `cover -report`
after the tests), or the tests run with `HARNESS_PERL_SWITCHES=-MDevel::Cover`.

## `platform-matrix`

The toolchains are Perl versions: shogo82148/actions-setup-perl's `perl-version`, a `perl:` image, or
`perlbrew install`.

## `compiler-warnings`

Perl's pragmas and lints: every module, script and `.psgi` starts with `use strict` and `use warnings` (or a module
that implies them: Moose, Moo, Mouse, Modern::Perl, Mojo::Base, Test2::V0, `use v5.36`; `use v5.12` implies strict
alone), and perlcritic runs in CI (or Test::Perl::Critic in the tests).

## `warnings-as-errors`

`use warnings FATAL => 'all'` in the modules, or Test::Warnings (Test::NoWarnings, Test::FailWarnings) in the tests,
which fail on a warning.

## `code-formatting`

perltidy: `perltidy --assert-tidy` fails on a file it would change, `perltidy -b` rewrites; `tidyall --check-only`
checks, `tidyall -a` rewrites. `.perltidyrc` holds the style; perltidy has a default without it.

## `static-analysis`

perlcritic (or tidyall), with the policies `.perlcriticrc` names (severity 5 without).

## `dependency-audit`

cpan-audit (CPAN::Audit): `cpan-audit deps .`.

## `function-limits`

lizard parses Perl, so CI runs it with a length limit.

## `committed-artifacts`

`blib/` and the `MYMETA.*` files of a MakeMaker or Module::Build distribution, Module::Build's `_build/`, Carton's
`local/` beside a cpanfile, and Devel::Cover's `cover_db/`.

## `vcs-ignore`

The same, each of those the project's build systems write: `blib/`, `MYMETA.*`, `cover_db/` for a MakeMaker
distribution; `_build/` too for Module::Build; `local/` beside a cpanfile. Plain modules without a build system need
only `cover_db/` ignored.

## Not judged

Perl is interpreted (`hardening`, `cxx-extensions`, `ci-build-types`) and dynamically typed (`type-checking`); no code
security scanner, fuzzer or mutation testing tool the validator knows reads Perl; Carton's `cpanfile.snapshot` for
applications belongs to `dependency-management`, not judged for Perl yet.
