from project_validator.core import Context, Result, check
from project_validator.text import matching_names, pattern

COPY_PASTE_DETECTORS = (
    pattern("PMD CPD", r"\b(pmd|run\.sh|pmd\.bat)\s+cpd\b|\bcpd(\.sh|\.bat)?\s+--|\bnet\.sourceforge\.pmd\.cpd\b"),
    pattern("jscpd", r"\bjscpd\b"),
    pattern("Duplo", r"\bduplo\b"),
    pattern("Simian", r"\bsimian\b"),
    pattern("CCFinderX", r"\bccfx\b|\bccfinderx?\b"),
    pattern("SonarQube", r"\bsonar-scanner\b|\bSonarSource/(sonarqube-scan|sonarcloud-github)-action\b"),
)


@check(name="copy-paste-detection", description="CI runs copy-paste detection (e.g. PMD CPD or jscpd)")
def copy_paste_detection(context: Context) -> Result:
    if detectors := matching_names(context.ci_texts, COPY_PASTE_DETECTORS):
        return Result.passed(f"CI runs copy-paste detection with {', '.join(detectors)}")
    return Result.warned(
        "no copy-paste detection found in CI configuration",
        "consider adding PMD CPD (pmd cpd --language cpp), jscpd, Duplo or Simian",
    )
