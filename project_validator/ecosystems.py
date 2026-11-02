"""Language ecosystems: the languages a check can judge, and judging a project once per ecosystem it uses."""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from project_validator.core import Context, Result, Status
from project_validator.structure import C_FAMILY


@dataclass(frozen=True, slots=True, kw_only=True)
class Ecosystem:
    label: str
    languages: frozenset[str]


C_AND_CXX = Ecosystem(label="C/C++", languages=C_FAMILY)
PYTHON = Ecosystem(label="Python", languages=frozenset({"Python"}))
RUST = Ecosystem(label="Rust", languages=frozenset({"Rust"}))

ECOSYSTEMS = (C_AND_CXX, PYTHON, RUST)

_SEVERITY = (Status.PASS, Status.WARN, Status.FAIL, Status.ERROR)


def languages_of(ecosystems: Iterable[Ecosystem]) -> frozenset[str]:
    return frozenset().union(*(ecosystem.languages for ecosystem in ecosystems))


def ecosystems_for(languages: frozenset[str], supported: Iterable[Ecosystem]) -> tuple[Ecosystem, ...]:
    """The supported ecosystems in `languages`; a project whose languages are unknown is judged as C/C++."""
    supported = tuple(supported)
    used = tuple(ecosystem for ecosystem in supported if ecosystem.languages & (languages or C_FAMILY))
    return used or supported


def _combined(results: Mapping[Ecosystem, Result]) -> Result:
    if len(results) == 1:
        return next(iter(results.values()))
    return Result(
        status=max((result.status for result in results.values()), key=_SEVERITY.index),
        message="; ".join(f"{ecosystem.label}: {result.message}" for ecosystem, result in results.items()),
        details=tuple(
            f"{ecosystem.label}: {detail}" for ecosystem, result in results.items() for detail in result.details
        ),
    )


def check_each_ecosystem[Rules](
    context: Context, rules: Mapping[Ecosystem, Rules], judge: Callable[[Rules, Context], Result]
) -> Result:
    """Judge each ecosystem the project uses by its rules: the worst result wins, and findings are labelled."""
    used = ecosystems_for(context.structure.languages, rules)
    return _combined({ecosystem: judge(rules[ecosystem], context) for ecosystem in used})
