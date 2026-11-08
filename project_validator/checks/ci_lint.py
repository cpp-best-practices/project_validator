"""CI lints its own configuration, so a broken or unsafe pipeline is caught before it runs."""

from project_validator.core import Context, Result, check
from project_validator.facts.practices import named


@check(name="ci-lint", description="CI lints its own configuration (e.g. actionlint or zizmor)")
def ci_lint(context: Context) -> Result:
    providers = list(dict.fromkeys(ci_file.provider for ci_file in context.ci_files))
    if not providers:
        return Result.skipped("no CI configuration")
    lintable = [provider for provider in providers if provider.linters]
    if not lintable:
        names = ", ".join(provider.name for provider in providers)
        return Result.skipped(f"no configuration linter is known for {names}")
    found = {provider: named(context.facts, provider.linters) for provider in lintable}
    if missing := [provider for provider, linters in found.items() if not linters]:
        return Result.warned(
            f"CI does not lint its {', '.join(provider.name for provider in missing)} configuration",
            *(provider.lint_hint for provider in missing),
        )
    listed = "; ".join(f"{provider.name}: {', '.join(linters)}" for provider, linters in found.items())
    return Result.passed(f"CI lints its configuration ({listed})")
