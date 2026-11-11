"""PHP: managed with Composer, judged by the PHP versions CI runs.

PHP projects run their tools through Composer scripts (`composer test`, `composer cs-check`), so the scripts CI runs
count as CI configuration, as package scripts do for JavaScript."""

from __future__ import annotations

import json
import re
from collections.abc import Callable

from project_validator.ecosystems.model import BuildSystem, Ecosystem, toolchain_patterns
from project_validator.facts import Command, Facts, Setting, resolved
from project_validator.facts.analysis import Strictness, analysed, analyzer, type_checked, type_checker
from project_validator.facts.arguments import option_values, program
from project_validator.facts.axes import versions_axis
from project_validator.facts.dependencies import Lock, PackageManager, lockfile_reader, manifest_reader
from project_validator.facts.licenses import declared_license_reader
from project_validator.facts.outputs import BuildOutput, directories, ignored_at_top_level
from project_validator.facts.tools import Claim, Run, Tool, combined, defined_by

PHP_LANGUAGE = "PHP"


PHP_ONLY = frozenset({PHP_LANGUAGE})


COMPOSER_JSON = "composer.json"


COMPOSER = BuildSystem(name="Composer", files=(COMPOSER_JSON,), languages=PHP_ONLY)


PHPUNIT_CONFIG_FILES = ("phpunit.xml", "phpunit.xml.dist", "phpunit.dist.xml")


# `composer test`, `composer run-script lint`, and `@lint` or `@composer lint` inside a script.
CALLS_SCRIPT = re.compile(
    r"\bcomposer\s+(?:run(?:-script)?\s+)?(?P<command>[\w:.-]+)|(?:^|\s)@(?!composer\b|php\b)(?P<script>[\w:.-]+)"
)


# Strict: PHPStan at level 8 or higher, Psalm at error level 1 or 2.
_STRICT_PHPSTAN = re.compile(r"[89]|1\d|max")


_STRICT_PSALM = frozenset({"1", "2"})


def _phpstan_strict(argv: tuple[str, ...], facts: Facts) -> list[Setting] | bool:
    if any(_STRICT_PHPSTAN.fullmatch(level) for level in option_values(argv, "--level", "-l")):
        return True
    return [setting for setting in facts.settings("PHPStan") if _STRICT_PHPSTAN.fullmatch(str(setting.value))]


def _psalm_strict(_argv: tuple[str, ...], facts: Facts) -> list[Setting] | bool:
    return [setting for setting in facts.settings("Psalm") if str(setting.value) in _STRICT_PSALM]


type _Strict = Callable[[tuple[str, ...], Facts], list[Setting] | bool]


def runs_analyzer(name: str) -> Callable[[Command, Facts], Run | None]:
    return lambda command, _facts: analysed() if program(resolved(command)) == name else None


def _type_checks(name: str, strict: _Strict) -> Claim:
    def checks(command: Command, facts: Facts) -> Run | None:
        argv = resolved(command)
        if program(argv) != name:
            return None
        found = strict(argv, facts)
        return type_checked(strict=bool(found), read=found if isinstance(found, list) else ())

    return checks


def _analyser_and_checker(name: str, strict: _Strict, how: str, strict_how: str) -> Tool:
    """PHPStan or Psalm: a run analyses the code and type checks it, strictly at a strict level."""
    command = name.lower()
    definition = defined_by(files=(name,), settings=(name,))
    return combined(
        analyzer(
            name=name, languages=PHP_ONLY, how=how, analyses=runs_analyzer(command), rules=definition, reads=(name,)
        ),
        type_checker(
            name=name,
            languages=PHP_ONLY,
            can={Strictness.CHECKS: how, Strictness.STRICT: strict_how},
            checks=_type_checks(command, strict),
            configuration=definition,
            reads=(name,),
        ),
    )


PHPSTAN = _analyser_and_checker("PHPStan", _phpstan_strict, "phpstan analyse", "level: 8 (or max) in phpstan.neon")


PSALM = _analyser_and_checker("Psalm", _psalm_strict, "psalm", 'errorLevel="2" in psalm.xml')


# The platform (php, ext-*, lib-*) is not a package Composer installs.
PLATFORM_PACKAGE = re.compile(r"^(?:php|php-64bit|hhvm|composer(?:-plugin|-runtime)?-api|(?:ext|lib)-.+)$")


def _composer(text: str) -> dict[str, object]:
    manifest = json.loads(text)
    return manifest if isinstance(manifest, dict) else {}


def _composer_declares(_path: str, text: str) -> bool:
    """composer.json requires packages beyond the platform (PHP itself, its extensions)."""
    manifest = _composer(text)
    tables = (manifest.get(table) for table in ("require", "require-dev"))
    packages = (name for table in tables if isinstance(table, dict) for name in table)
    return any(not PLATFORM_PACKAGE.match(name) for name in packages)


COMPOSER_DEPENDENCIES = manifest_reader(
    name="Composer dependencies",
    manager="Composer",
    files=(COMPOSER_JSON,),
    declares=_composer_declares,
    library=lambda _path, text: _composer(text).get("type") == "library",
)


COMPOSER_LOCK = lockfile_reader(manager="Composer", files=("composer.lock",))


# A library's users resolve its dependencies themselves; anything not declared a library locks them.
COMPOSER_PACKAGES = PackageManager(
    name="Composer",
    languages=PHP_ONLY,
    lock=Lock.APPLICATIONS,
    lock_hint="commit composer.lock, so the application is installed with the dependencies it was tested with",
)


def _composer_license(text: str) -> str | None:
    """Composer's license is an SPDX expression, or a list of licenses to choose from."""
    license_ = _composer(text).get("license")
    if isinstance(license_, list) and all(isinstance(item, str) for item in license_):
        return " OR ".join(license_) or None
    return license_ if isinstance(license_, str) else None


COMPOSER_LICENSE = declared_license_reader(
    name="composer.json license", files=(COMPOSER_JSON,), languages=PHP_ONLY, declared=_composer_license
)


VENDOR = BuildOutput(
    languages=PHP_ONLY,
    name="vendor",
    globs=ignored_at_top_level("vendor"),
    paths=directories("vendor"),
    hint="consider ignoring /vendor/ (and .phpunit.cache/ or .phpunit.result.cache)",
    artifacts=("/vendor/", ".phpunit.cache/", ".phpunit.result.cache"),
)


_PHP_VERSION = r"(\d+\.\d+)"


PHP = Ecosystem(
    label="PHP",
    languages=PHP_ONLY,
    build_systems=(COMPOSER,),
    source_suffixes={".php": PHP_LANGUAGE},
    toolchain=toolchain_patterns(
        PHP_LANGUAGE,
        version=_PHP_VERSION,
        inputs=("php-version",),
        images=("php",),
        commands=r"\bcomposer\s+(?:install|update|test|run|audit)\b|\bvendor/bin/|\bphp\s+-",
        setup=("php",),
    ),
)


PHP_VERSIONS = versions_axis("PHP version", PHP_LANGUAGE, PHP_ONLY)
