"""The project says under which license it may be used: a license file of a known license, matching the manifests."""

from project_validator.core import Context, Result, check
from project_validator.policy.license import judge_license
from project_validator.questions.license import license_answer


@check(name="license", description="The project has a license file of a known license")
def license_(context: Context) -> Result:
    return judge_license(license_answer(context.facts))
