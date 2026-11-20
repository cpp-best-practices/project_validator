"""The README shows, at a glance, whether the build passes and how the code fares."""

from __future__ import annotations

import re

from project_validator.ci import CiProvider
from project_validator.core import Context, Result, check
from project_validator.evidence import documents
from project_validator.text import matching_names, pattern

README = re.compile(r"README(?:\.(?:md|markdown|rst|txt|adoc|asciidoc|org|textile|pod|rdoc))?", re.IGNORECASE)
QUALITY_BADGES = (
    pattern("Codecov", r"codecov\.io/\S+(?:badge|graph|coverage\.svg)|img\.shields\.io/codecov/|badgen\.net/codecov/"),
    pattern(
        "Coveralls", r"coveralls\.io/repos/\S+badge|img\.shields\.io/coveralls(?:Coverage)?/|badgen\.net/coveralls/"
    ),
    pattern("SonarCloud", r"sonarcloud\.io/api/project_badges/|img\.shields\.io/sonar/"),
    pattern("Codacy", r"(?:app|api)\.codacy\.com/project/badge/|img\.shields\.io/codacy/"),
    pattern("Code Climate", r"(?:api\.)?codeclimate\.com/\S*badges/|img\.shields\.io/codeclimate/"),
    pattern("DeepSource", r"(?:app\.)?deepsource\.(?:io|com)/\S+\.svg"),
    pattern("Coverity Scan", r"scan\.coverity\.com/projects/\S+/badge\.svg|img\.shields\.io/coverity/"),
    pattern(
        "OpenSSF Scorecard",
        r"api\.(?:scorecard\.dev|securityscorecards\.dev)/projects/\S+/badge|img\.shields\.io/ossf-scorecard/",
    ),
    pattern(
        "OpenSSF Best Practices", r"(?:bestpractices\.dev|bestpractices\.coreinfrastructure\.org)/projects/\d+/badge"
    ),
)
# What an HTML comment hides is not shown.
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
CI_HINT = "add a CI status badge, e.g. ![ci](https://github.com/<owner>/<repo>/actions/workflows/ci.yml/badge.svg)"
QUALITY_HINT = "add a quality badge: coverage (Codecov, Coveralls) or analysis (SonarCloud, Codacy, OpenSSF Scorecard)"


@check(name="status-badges", description="The README shows CI status and code quality badges")
def status_badges(context: Context) -> Result:
    readmes = documents(context, README)
    if not readmes:
        return Result.failed("no README", CI_HINT, QUALITY_HINT)
    readme = readmes[0]
    text = _COMMENT.sub("", context.project.read_text(readme))
    used = {found.provider.name for found in context.ci_files}
    shown = {
        provider.name: matching_names((text,), provider.badges) for provider in context.providers if provider.badges
    }
    ci = [name for provider in context.providers for name in shown.get(provider.name, ()) if _shows(provider, used)]
    stale = tuple(
        f"{readme}'s {name} badge is of a CI the project does not configure"
        for provider in context.providers
        if not _shows(provider, used)
        for name in shown.get(provider.name, ())
    )
    quality = matching_names((text,), QUALITY_BADGES)
    if not ci and not quality:
        return Result.failed(f"{readme} shows no status badges", *stale, CI_HINT, QUALITY_HINT)
    if not quality:
        return Result.warned(f"{readme} shows a CI badge ({', '.join(ci)}) but no quality badge", QUALITY_HINT)
    if not ci:
        return Result.warned(f"{readme} shows a quality badge ({', '.join(quality)}) but no CI badge", *stale, CI_HINT)
    return Result.passed(f"{readme} shows CI ({', '.join(ci)}) and quality ({', '.join(quality)}) badges")


def _shows(provider: CiProvider, used: set[str]) -> bool:
    """Whether a badge of `provider` shows the project's CI: one the project configures, or can configure
    elsewhere."""
    return provider.configured_elsewhere or provider.name in used
