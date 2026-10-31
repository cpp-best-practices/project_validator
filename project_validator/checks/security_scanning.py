from project_validator.core import Context, Result, check
from project_validator.text import matching_names, pattern

SECURITY_SCANNERS = (
    pattern("CodeQL", r"\bgithub/codeql-action\b"),
    pattern("GitLab SAST", r"\bSecurity/SAST\.gitlab-ci\.ya?ml\b"),
)


@check(name="security-scanning", description="CI runs code security scanning (e.g. CodeQL or GitLab SAST)")
def security_scanning(context: Context) -> Result:
    if scanners := matching_names(context.ci_texts, SECURITY_SCANNERS):
        return Result.passed(f"CI runs code security scanning with {', '.join(scanners)}")
    return Result.warned(
        "no code security scanning found in CI configuration",
        "consider adding CodeQL (github/codeql-action) or GitLab SAST (Security/SAST.gitlab-ci.yml)",
    )
