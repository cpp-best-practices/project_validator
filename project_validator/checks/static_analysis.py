"""Static analyzers (linters) are configured and run, so the bugs they find are found before review."""

from project_validator.core import Context, Result
from project_validator.ecosystems import practice
from project_validator.rules import Analyzer, StaticAnalysis


def _named(analyzer: Analyzer, context: Context) -> str:
    config = analyzer.configured(context)
    return f"{analyzer.name} ({config})" if config else analyzer.name


def _not_running(analyzer: Analyzer, context: Context) -> str:
    config = analyzer.configured(context)
    return f"{analyzer.name} is configured ({config}) but does not run" if config else f"{analyzer.name} does not run"


def _joined(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def _none_running(rule: StaticAnalysis, context: Context) -> Result:
    if configured := [_not_running(analyzer, context) for analyzer in rule.analyzers if analyzer.configured(context)]:
        return Result.warned("; ".join(configured), rule.hint)
    return Result.failed("no static analyzer runs", rule.hint)


def _problems(rule: StaticAnalysis, running: list[Analyzer], context: Context) -> list[str]:
    """Analyzers that are required but do not run, and the shortfalls of those that run."""
    idle = [_not_running(analyzer, context) for analyzer in rule.analyzers if analyzer not in running]
    shortfalls = [shortfall for analyzer in running if (shortfall := analyzer.shortfall(context))]
    return [*(idle if rule.all_required else ()), *shortfalls]


@practice(
    name="static-analysis",
    description="Static analyzers are configured and run (e.g. clang-tidy and cppcheck, ruff check, clippy)",
    rule=StaticAnalysis,
)
def static_analysis(rule: StaticAnalysis, context: Context) -> Result:
    texts = rule.texts(context)
    running = [analyzer for analyzer in rule.analyzers if any(analyzer.runs.search(text) for text in texts)]
    if not running:
        return _none_running(rule, context)
    ran = f"{_joined([_named(analyzer, context) for analyzer in running])} {'runs' if len(running) == 1 else 'run'}"
    if problems := _problems(rule, running, context):
        return Result.warned(f"{ran}, but {'; '.join(problems)}", rule.hint)
    return Result.passed(ran)
