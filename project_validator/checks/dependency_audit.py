from project_validator.core import Context, Result
from project_validator.ecosystems import practice
from project_validator.rules import DependencyAudit
from project_validator.text import matching_names


@practice(
    name="dependency-audit",
    description="CI checks the dependencies against known vulnerabilities (e.g. pip-audit, cargo audit, govulncheck)",
    rule=DependencyAudit,
)
def dependency_audit(audit: DependencyAudit, context: Context) -> Result:
    if tools := matching_names(audit.texts(context), audit.tools):
        return Result.passed(f"CI audits the dependencies with {', '.join(tools)}")
    return Result.warned("no dependency vulnerability audit found in CI configuration", audit.hint)
