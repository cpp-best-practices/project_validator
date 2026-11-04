from project_validator.core import Context, Result, check
from project_validator.ecosystems import Ecosystem, ecosystems_for, registered, rules_of
from project_validator.rules import SecurityLints
from project_validator.text import matching_names, pattern

SECURITY_SCANNERS = (
    pattern("CodeQL", r"\bgithub/codeql-action\b"),
    pattern("GitLab SAST", r"\bSecurity/SAST\.gitlab-ci\.ya?ml\b"),
)
SCANNER_HINT = "consider adding CodeQL (github/codeql-action) or GitLab SAST (Security/SAST.gitlab-ci.yml)"


def _lints_found(context: Context) -> dict[Ecosystem, list[str]]:
    """The security lints enabled for each ecosystem the project uses; none for one that has no security lints."""
    lints = rules_of(SecurityLints)
    return {
        ecosystem: matching_names(rule.texts(context), rule.lints) if (rule := lints.get(ecosystem)) else []
        for ecosystem in ecosystems_for(context.structure.languages, registered())
    }


def _listed(found: dict[Ecosystem, list[str]]) -> str:
    if len(found) == 1:
        return ", ".join(next(iter(found.values())))
    return "; ".join(f"{ecosystem.label}: {', '.join(names)}" for ecosystem, names in found.items())


def _hints(missing: list[Ecosystem]) -> tuple[str, ...]:
    lints = rules_of(SecurityLints)
    named = [
        f"{ecosystem.label}: {', '.join(lint.name for lint in lints[ecosystem].lints)}"
        for ecosystem in missing
        if ecosystem in lints
    ]
    return (SCANNER_HINT, *((f"or enable each language's security lints ({'; '.join(named)})",) if named else ()))


@check(
    name="security-scanning",
    description="CI scans the code for security problems (CodeQL, GitLab SAST, or each language's security lints)",
)
def security_scanning(context: Context) -> Result:
    """A language without security lints of its own is only scanned by a multi-language scanner such as CodeQL."""
    if scanners := matching_names(context.ci_texts, SECURITY_SCANNERS):
        return Result.passed(f"CI runs code security scanning with {', '.join(scanners)}")
    found = _lints_found(context)
    enabled = {ecosystem: names for ecosystem, names in found.items() if names}
    missing = [ecosystem for ecosystem, names in found.items() if not names]
    if enabled and not missing:
        return Result.passed(f"security lints are enabled: {_listed(enabled)}")
    if enabled:
        unscanned = ", ".join(ecosystem.label for ecosystem in missing)
        return Result.warned(
            f"no code security scanning for {unscanned}", f"found {_listed(enabled)}", *_hints(missing)
        )
    return Result.warned("no code security scanning found in CI configuration", *_hints(missing))
