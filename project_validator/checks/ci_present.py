from project_validator.core import Context, Result, check


@check(name="ci-present", description="The project has continuous integration configured")
def ci_present(context: Context) -> Result:
    if not context.ci_files:
        searched = ", ".join(provider.name for provider in context.providers)
        return Result.failed(f"no CI configuration found (looked for {searched})")
    providers = dict.fromkeys(ci_file.provider.name for ci_file in context.ci_files)
    return Result.passed(
        f"CI configuration found for {', '.join(providers)}", *(ci_file.path for ci_file in context.ci_files)
    )
