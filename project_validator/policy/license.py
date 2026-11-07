"""The license policy: the project has license files of known licenses, and its manifests declare the same."""

from project_validator.core import Result
from project_validator.questions.license import LicenseAnswer

HINT = "add a LICENSE file with the text of a license (see https://choosealicense.com)"


def judge_license(answer: LicenseAnswer) -> Result:
    """No license file fails, unless the project's packages each have one (a monorepo), which warns; one not
    recognised, or a manifest that declares another license, warns."""
    if not answer.files and answer.packages:
        names = ", ".join(sorted(answer.packages_licenses())) or "unrecognised licenses"
        return Result.warned(
            f"no license file at the root; {len(answer.packages)} package license file(s) ({names})",
            "add a LICENSE at the root too, so that the repository says how it is licensed",
            *(path for path, _ in answer.packages),
        )
    if not answer.files:
        return Result.failed("no license file", HINT)
    if unknown := answer.unrecognised():
        return Result.warned(
            f"the license in {', '.join(unknown)} is not recognised",
            "use the license's standard text, or add an SPDX-License-Identifier line",
        )
    if answer.mismatches:
        return Result.warned(
            "the manifest declares another license than the license files",
            *(
                f"{found.manifest} declares {found.declared}, but the license files are "
                f"{', '.join(sorted(found.licenses))}"
                for found in answer.mismatches
            ),
        )
    return Result.passed(
        f"the project is licensed under {', '.join(sorted(answer.licenses()))}", *(path for path, _ in answer.files)
    )


__all__ = ["HINT", "judge_license"]
