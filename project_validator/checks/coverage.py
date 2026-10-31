from project_validator.core import Context, Result, check
from project_validator.structure import C_FAMILY
from project_validator.text import matching_names, pattern

BRANCH_COVERAGE = (
    pattern("gcovr", r"--txt-metric[\s=]+branch|--fail-under-branch|--branches\b"),
    pattern("lcov", r"\b(lcov_)?branch_coverage\s*=\s*1"),
    pattern("genhtml", r"--branch-coverage\b"),
    pattern("gcov", r"--branch-(probabilities|counts)\b"),
    pattern("llvm-cov", r"-show-branch(es|-summary)\b"),
)

PATH_COVERAGE = (
    pattern("gcc -fcondition-coverage", r"-fcondition-coverage\b"),
    pattern("gcc -fpath-coverage", r"-fpath-coverage\b"),
    pattern("gcov --prime-paths", r"--prime-paths\b"),
    pattern("clang MC/DC", r"-fcoverage-mcdc\b|-show-mcdc\b"),
)


@check(name="coverage", description="CI reports branch coverage (path coverage is a bonus)", languages=C_FAMILY)
def coverage(context: Context) -> Result:
    texts = (*context.ci_texts, *context.cmake_texts)
    branch_tools = matching_names(texts, BRANCH_COVERAGE)
    if not branch_tools:
        return Result.failed("no branch coverage reporting found in CI configuration or CMake files")

    message = f"branch coverage is reported with {', '.join(branch_tools)}"
    if path_tools := matching_names(texts, PATH_COVERAGE):
        return Result.passed(f"{message}; path coverage bonus: {', '.join(path_tools)}")
    return Result.passed(message, "consider adding path coverage (e.g. -fcondition-coverage or -fcoverage-mcdc)")
