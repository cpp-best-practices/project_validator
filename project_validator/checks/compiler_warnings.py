from project_validator.core import Context, Result
from project_validator.ecosystems import practice
from project_validator.rules import WarningPolicy
from project_validator.text import found_and_missing, matching_names


@practice(
    name="compiler-warnings", description="A strict compiler warning (or lint) set is enabled", rule=WarningPolicy
)
def compiler_warnings(policy: WarningPolicy, context: Context) -> Result:
    required = policy.required(context)
    texts = policy.texts(context)
    found, missing = found_and_missing(texts, required)

    if not matching_names(texts, policy.recognised):
        return Result.failed(f"no {policy.kind} found; enable at least {' '.join(f.name for f in required)}")
    if missing:
        return Result.warned(f"missing {policy.kind}: {', '.join(missing)}", f"found {' '.join(found)}")
    return Result.passed(f"strict {policy.kind} are enabled: {' '.join(found)}")
