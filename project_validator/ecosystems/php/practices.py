"""PHP's practices: the settings it asks for, and how they are worded (see
`project_validator.facts.practices`)."""

import re

from project_validator.ecosystems.php import PHP_ONLY, PHPUNIT_CONFIG_FILES
from project_validator.facts.practices import Practice, PracticeName, Wording, always, required, requirement_reader
from project_validator.text import Pattern, pattern

# E_ALL & ~E_DEPRECATED leaves some out.
ALL_ERRORS = r"(?:-1|E_ALL)\b(?!\s*(?:&|&amp;|\^|\|))"


ERROR_REPORTING = Pattern(
    "error_reporting = E_ALL",
    re.compile(
        rf"""\berror_reporting["']?\s*(?:[=:,]|value\s*=)\s*["']?{ALL_ERRORS}"""
        rf"""|name\s*=\s*["']error_reporting["']\s+value\s*=\s*["']{ALL_ERRORS}"""
        rf"""|value\s*=\s*["']{ALL_ERRORS}["']\s+name\s*=\s*["']error_reporting["']"""
    ),
)


# PHP reports notices, warnings and deprecations at run time; the tests must see every one of them.
def _fails_on(issue: str) -> str:
    return rf"(?:\b{issue}\s*=\s*[\"']true[\"']|--fail-on-{issue.removeprefix('failOn').lower()}\b)"


_PHP_WARNINGS_AS_ERRORS = (
    required(
        Pattern(
            "PHPUnit failOnWarning, failOnNotice and failOnDeprecation",
            re.compile(
                rf"(?=[\s\S]*{_fails_on('failOnWarning')})(?=[\s\S]*{_fails_on('failOnNotice')})"
                rf"(?=[\s\S]*{_fails_on('failOnDeprecation')})"
            ),
        )
    ),
    required(pattern("PHPUnit failOnAllIssues", r"\bfailOnAllIssues\s*=\s*[\"']true[\"']|--fail-on-all-issues\b")),
)


PHP_WARNING_SETTINGS = requirement_reader(
    "PHPUnit warning settings", PHPUNIT_CONFIG_FILES, (required(ERROR_REPORTING), *_PHP_WARNINGS_AS_ERRORS)
)


# PHP reports notices, warnings and deprecations at run time; the tests must see every one of them.
WARNINGS = Practice(
    name=PracticeName.WARNINGS,
    languages=PHP_ONLY,
    requirements=always(required(ERROR_REPORTING)),
    reads=(PHP_WARNING_SETTINGS.name,),
    words=Wording(
        kind="PHP error reporting settings",
        separator=" ",
        hint='set <ini name="error_reporting" value="-1"/> in phpunit.xml',
    ),
)


WARNINGS_AS_ERRORS = Practice(
    name=PracticeName.WARNINGS_AS_ERRORS,
    languages=PHP_ONLY,
    requirements=always(*_PHP_WARNINGS_AS_ERRORS),
    any_one=True,
    reads=(PHP_WARNING_SETTINGS.name,),
    words=Wording(
        kind="warnings as errors",
        searched="phpunit.xml, CI configuration or the Composer scripts it runs",
        hint='set failOnWarning="true", failOnNotice="true" and failOnDeprecation="true" in phpunit.xml',
    ),
)
