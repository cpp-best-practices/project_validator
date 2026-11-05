"""CI lints its own configuration, so a broken or unsafe pipeline is caught before it runs."""

from project_validator.core import Context, Result, Status, check
from project_validator.evidence import PRE_COMMIT_CONFIGURATION, existing_texts
from project_validator.text import matching_names


@check(name="ci-lint", description="CI lints its own configuration (e.g. actionlint or zizmor)")
def ci_lint(context: Context) -> Result:
    providers = list(dict.fromkeys(ci_file.provider for ci_file in context.ci_files))
    if not providers:
        return Result(status=Status.SKIP, message="no CI configuration")
    lintable = [provider for provider in providers if provider.linters]
    if not lintable:
        names = ", ".join(provider.name for provider in providers)
        return Result(status=Status.SKIP, message=f"no configuration linter is known for {names}")
    texts = (*context.ci_texts, *existing_texts(context, PRE_COMMIT_CONFIGURATION))
    found = {provider: matching_names(texts, provider.linters) for provider in lintable}
    if missing := [provider for provider, linters in found.items() if not linters]:
        return Result.warned(
            f"CI does not lint its {', '.join(provider.name for provider in missing)} configuration",
            *(provider.lint_hint for provider in missing),
        )
    listed = "; ".join(f"{provider.name}: {', '.join(linters)}" for provider, linters in found.items())
    return Result.passed(f"CI lints its configuration ({listed})")
