"""Size: each language's lines of code, by role, with its tests' share of the product's and how much of it an outside
generator wrote (upstream #412)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator

from project_validator.about.detail import Detail, own_code
from project_validator.facts import Facts
from project_validator.facts.roles import ROLE_NAMES


def _by_role(lines: Counter[str]) -> str:
    return ", ".join(f"{count:,} in {ROLE_NAMES.get(role, role)}" for role, count in lines.items())


def _total(lines: Counter[str]) -> str:
    total = sum(lines.values())
    return f"{total:,} {'line' if total == 1 else 'lines'}"


def _where(lines: Counter[str]) -> str:
    """`3 lines in tests`, or by role when there are several: `5 lines (3 in tests, 2 in examples)`."""
    if len(lines) == 1:
        role = next(iter(lines))
        return f"{_total(lines)} in {ROLE_NAMES.get(role, role)}"
    return f"{_total(lines)} ({_by_role(lines)})"


def _words(lines: Counter[str], generated: Counter[str]) -> str:
    """`15 lines: 10 in the product, 5 in tests (0.50 of the product's); 3 of them generated (protoc)`."""
    words = f"{_total(lines)}: {_by_role(lines)}"
    if lines["product"] and lines["test"]:
        words += f" ({lines['test'] / lines['product']:.2f} of the product's)"
    if generated:
        generators = ", ".join(sorted(generated))
        words += f"; {sum(generated.values()):,} of them generated ({generators})"
    return words


def _counted(found: list[tuple[str, int, str]]) -> tuple[Counter[str], Counter[str]]:
    """A language's lines by role, the product's first, and its generated lines by generator."""
    lines: Counter[str] = Counter()
    generated: Counter[str] = Counter()
    for role, count, generator in sorted(found, key=lambda item: (item[0] != "product", item[0])):
        lines[role] += count
        if generator:
            generated[generator] += count
    return lines, generated


def size(facts: Facts) -> Iterator[Detail]:
    """The lines of code of each language of the product, by role; then, together, the languages found only outside
    it (a test suite's samples in other languages)."""
    by_language: dict[str, list[tuple[str, int, str]]] = {}
    for source in own_code(facts):
        if source.lines:
            by_language.setdefault(str(source.language), []).append((source.role, source.lines, source.generator))
    outside: dict[str, Counter[str]] = {}
    for language, found in sorted(by_language.items()):
        lines, generated = _counted(found)
        if not lines["product"]:
            outside[language] = lines
            continue
        counts: dict[str, object] = {"lines": dict(lines), "generated": dict(generated)}
        yield Detail(group="Size", subject=language, text=_words(lines, generated), data=counts)
    if outside:
        text = "; ".join(f"{language}: {_where(lines)}" for language, lines in outside.items())
        by_language_lines = {"lines": {language: dict(lines) for language, lines in outside.items()}}
        yield Detail(group="Size", subject="outside the product", text=text, data=by_language_lines)


__all__ = ["size"]
