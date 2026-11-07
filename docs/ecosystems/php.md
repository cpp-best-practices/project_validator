# PHP

Recognised by `.php` sources and Composer (`composer.json`). The Composer scripts CI runs (`composer test`) count as
CI configuration.

## `tests-run`

`*Test.php` files with PHPUnit test cases or Pest tests, run by phpunit, pest, paratest or `composer test`, in CI or
the Composer scripts it runs.

## `coverage`

PHPUnit (or Pest, or ParaTest) reporting coverage with `--path-coverage` (or `pathCoverage="true"` in the
configuration it reads, with a report), which reports branch and path coverage together, so it also earns the path
bonus. Line coverage alone counts no branches.

## `platform-matrix`

The toolchains are PHP versions.

## `compiler-warnings`

Every error is reported while testing: `error_reporting` `-1` or `E_ALL` in `phpunit.xml`, `php.ini` or CI.

## `warnings-as-errors`

PHPUnit's `failOnWarning`, `failOnNotice` and `failOnDeprecation` (or `failOnAllIssues`).

## `type-checking`

PHPStan or Psalm, also through the Composer scripts CI runs. Strict mode is a bonus: PHPStan `level` 8 or higher, or
Psalm `errorLevel` 1 or 2.

## `code-formatting`

`php-cs-fixer check` / `--dry-run`, phpcs or `pint --test`, in CI or the Composer scripts it runs; they have a
default style, so CI enforcement alone passes.

## `function-limits`

lizard runs with a length limit, or PHPMD runs with its `codesize` rules (`ExcessiveMethodLength`).

## `static-analysis`

PHPStan, Psalm, PHPMD or Phan.

## `security-scanning`

Psalm's taint analysis or phpcs-security-audit.

## `dependency-management`

Dependencies required in `composer.json` (besides `php` and extensions) are locked by a committed `composer.lock`,
unless the package is a `"type": "library"`.

## `dependency-audit`

`composer audit`, or `roave/security-advisories` required.

## `license`

`license` in `composer.json`.

## `committed-artifacts`

A top-level `vendor/`, `.phpunit.cache/` and `.phpunit.result.cache`.

## `vcs-ignore`

`vendor/`.
