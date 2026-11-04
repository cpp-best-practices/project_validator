from project_validator.core import Context, Result
from project_validator.ecosystems import practice
from project_validator.rules import Hardening
from project_validator.text import found_and_missing


@practice(name="hardening", description="Security hardening options are enabled", rule=Hardening)
def hardening(rule: Hardening, context: Context) -> Result:
    if rule.judge is not None:
        return rule.judge(context)
    found, missing = found_and_missing(rule.texts(context), rule.options)
    if not found:
        return Result.failed(f"no hardening options found; enable {', '.join(option.name for option in rule.options)}")
    if missing:
        return Result.warned(f"missing hardening options: {', '.join(missing)}", f"found {', '.join(found)}")
    return Result.passed(f"hardening options are enabled: {', '.join(found)}")
