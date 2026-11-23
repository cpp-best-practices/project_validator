"""Why each check matters, in a sentence or two, and its category, for the reports to explain a result and for
`--explain CHECK`. What a check looks for is its description; the tools it recognises are the support matrix's.

A plugin's check without an explanation is explained by its description alone.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from project_validator.core import Check
from project_validator.ecosystems import applies_to
from project_validator.score import LEVEL_NAMES, UNSCORED, level_of
from project_validator.support_matrix import support_matrix

# The categories the reports group the checks by, in order.
CATEGORIES = ("Build", "Tests", "Analysis", "Security", "CI", "Dependencies", "Repository", "Data and schemas")


@dataclass(frozen=True, slots=True)
class Why:
    category: str
    why: str


WHY: Mapping[str, Why] = {
    "action-pinning": Why(
        "Security",
        "A tag can be moved to point at different code; a commit cannot. Pinning each action to a full commit means "
        "a compromised or rewritten release can not run in your CI with your secrets.",
    ),
    "ci-build-types": Why(
        "CI",
        "Debug and release builds exercise different code: assertions, optimisations and undefined behaviour show up "
        "in one and not the other. Building both, with and without sanitizers, everywhere, catches what each hides.",
    ),
    "ci-current": Why(
        "CI",
        "A configuration left from a CI the project moved away from no longer runs, yet reads as if it did: it "
        "claims platforms and checks nothing tests any more, and its readers trust what nothing enforces.",
    ),
    "ci-lint": Why(
        "CI",
        "CI configuration is code too. A linter catches the typo that silently skips a job, and the injection or "
        "permission mistake that a workflow runs with every push.",
    ),
    "ci-present": Why(
        "CI",
        "Every other gate depends on it: a check only protects the project when something runs it on every change.",
    ),
    "code-formatting": Why(
        "Analysis",
        "A formatter enforced by CI ends style debates in review and keeps diffs about behaviour, so reviewers read "
        "what changed rather than how it was spaced.",
    ),
    "committed-artifacts": Why(
        "Repository",
        "Build outputs in version control go stale, bloat every clone, cause merge conflicts and can hide code that "
        "does not match its sources.",
    ),
    "compile-commands": Why(
        "Build",
        "compile_commands.json is how clang-tidy, clangd and IDEs learn how each file is built. Without it they guess, "
        "and analysis is wrong or impossible.",
    ),
    "compiler-extensions": Why(
        "Build",
        "Compiler extensions tie the code to one compiler and hide portability bugs. Asking for the standard "
        "(-std=c++20, not gnu++20) keeps every compiler honest.",
    ),
    "compiler-warnings": Why(
        "Analysis",
        "Warnings are the cheapest static analysis there is: the compiler already knows about conversions, shadowing "
        "and unused results. A strict set turns them on.",
    ),
    "copy-paste-detection": Why(
        "Analysis",
        "Duplicated code duplicates bugs: a fix applied to one copy leaves the others broken. Detecting copies in CI "
        "keeps them from spreading.",
    ),
    "coverage": Why(
        "Tests",
        "Coverage shows what the tests never run. Branch coverage, reported and gated in CI, keeps untested code "
        "from growing unnoticed.",
    ),
    "data-wellformed": Why(
        "Data and schemas",
        "A data file that does not parse fails at the worst moment: when something finally reads it. Parsing each "
        "one in CI fails early instead.",
    ),
    "dependency-audit": Why(
        "Security",
        "Most of a program is its dependencies. Auditing them against known vulnerabilities in CI finds the one that "
        "needs updating before an attacker does.",
    ),
    "dependency-management": Why(
        "Dependencies",
        "Dependencies declared to a package manager and locked are reproducible, auditable and updatable; copies "
        "committed by hand are none of these.",
    ),
    "dependency-updates": Why(
        "Dependencies",
        "Dependencies age. Automated update pull requests keep them current in small, testable steps instead of one "
        "painful upgrade years later.",
    ),
    "function-limits": Why(
        "Analysis",
        "Long functions are hard to read, test and change. A length limit in CI keeps each function small enough to "
        "understand.",
    ),
    "fuzz-testing": Why(
        "Tests",
        "Fuzzers find the inputs nobody thought to test: crashes, hangs and memory errors in parsers and decoders. "
        "Running them in CI keeps finding them.",
    ),
    "hardening": Why(
        "Security",
        "Hardening flags make the binary itself resist exploitation (stack protectors, control-flow protection, "
        "fortified library calls), so a bug is less likely to become an exploit.",
    ),
    "large-files": Why(
        "Repository",
        "Large binaries in git make every clone slow forever, even after they are deleted. Git LFS or DVC keeps them "
        "out of the history.",
    ),
    "license": Why(
        "Repository",
        "Without a licence nobody may legally use, change or share the code. A known licence file says what they "
        "may do.",
    ),
    "link-check": Why(
        "Data and schemas",
        "Documentation with broken links fails its readers. Checking links in CI catches pages that moved or "
        "disappeared.",
    ),
    "migration-safety": Why(
        "Data and schemas",
        "Some schema migrations lock tables or lose data when applied to a live database. A migration linter in CI "
        "flags them before they reach production.",
    ),
    "mutation-testing": Why(
        "Tests",
        "Coverage says the tests run the code; mutation testing says whether they would notice it breaking. Each "
        "surviving mutant is a bug the tests would miss.",
    ),
    "out-of-source-build": Why(
        "Build",
        "An in-source build mixes generated files with sources, pollutes the repository and breaks a second build "
        "configuration. Refusing it keeps the tree clean.",
    ),
    "platform-matrix": Why(
        "CI",
        "Code that works on one OS with one compiler (or one interpreter version) often fails on another. A matrix "
        "in CI finds it before users do.",
    ),
    "sanitizers": Why(
        "Tests",
        "Sanitizers turn silent memory errors, undefined behaviour and data races into loud failures while the "
        "tests run, where they are cheap to fix.",
    ),
    "schema-compatibility": Why(
        "Data and schemas",
        "A schema change that breaks existing clients is an outage for someone else. Checking compatibility against "
        "the published schema catches it in review.",
    ),
    "schema-declared": Why(
        "Data and schemas",
        "A schema that declares its dialect and identity can be validated and referenced unambiguously by every "
        "tool that reads it.",
    ),
    "schema-examples": Why(
        "Data and schemas",
        "Examples that must pass, and invalid ones that must fail, test the schema itself: that it accepts what it "
        "should and rejects what it should not.",
    ),
    "schema-validation": Why(
        "Data and schemas",
        "Documents validated against their schemas in CI fail in review rather than in production.",
    ),
    "secret-scanning": Why(
        "Security",
        "A key committed once is in the history forever. Scanning for secrets in CI catches them before they are "
        "pushed, or at least before they are used.",
    ),
    "security-policy": Why(
        "Security",
        "Someone who finds a vulnerability needs to know how to report it privately; without a policy they open a "
        "public issue, or give up.",
    ),
    "security-scanning": Why(
        "Security",
        "Security scanners know the patterns behind injections, unsafe deserialisation and weak crypto, and find "
        "them in the code before an attacker does.",
    ),
    "static-analysis": Why(
        "Analysis",
        "Static analysers find whole classes of bugs without running the code: null dereferences, leaks, misuse of "
        "APIs. Each one finds different things.",
    ),
    "status-badges": Why(
        "Repository",
        "Badges show visitors at a glance that CI runs and passes. Reported, but not scored: they are not a gate.",
    ),
    "tests-run": Why(
        "Tests",
        "Tests only protect the project when they run on every change. This is the foundation every other testing "
        "gate builds on.",
    ),
    "top-level-guard": Why(
        "Build",
        "A library pulled in with FetchContent, CPM or add_subdirectory should not build its tests and developer "
        "options into its users' builds.",
    ),
    "type-checking": Why(
        "Analysis",
        "In a dynamically typed language, a type checker finds the wrong argument, the missing attribute and the "
        "None nobody handled, before the code runs.",
    ),
    "vcs-ignore": Why(
        "Repository",
        "An ignore file that covers the build outputs keeps them from being committed by accident.",
    ),
    "warnings-as-errors": Why(
        "Analysis",
        "Warnings that do not fail the build are soon ignored by the hundred. Treating them as errors in at least "
        "one configuration keeps the count at zero.",
    ),
}


def why(name: str) -> Why | None:
    return WHY.get(name)


def category(name: str) -> str:
    found = WHY.get(name)
    return found.category if found else "Other"


@dataclass(frozen=True, slots=True, kw_only=True)
class Explanation:
    """Everything a reader needs to understand a check."""

    name: str
    description: str
    why: str
    category: str
    level: int
    scored: bool
    applies_to: tuple[str, ...]
    tools: Mapping[str, tuple[str, ...]]  # ecosystem -> the tools recognised for it

    def lines(self) -> list[str]:
        """The explanation as `--explain` prints it."""
        level = f"Level {self.level} ({LEVEL_NAMES[self.level]})" if self.level < 4 else "Level 4 (Complete)"
        lines = [self.name, "", f"What it looks for: {self.description}"]
        if self.why:
            lines.append(f"Why it matters: {self.why}")
        scored = "" if self.scored else "; reported but not scored"
        lines += [
            f"Category: {self.category}. Needed for {level}{scored}.",
            f"Applies to: {', '.join(self.applies_to) or 'every project'}.",
        ]
        if self.tools:
            lines += [
                "",
                "Tools recognised:",
                *(f"  {label}: {', '.join(tools)}" for label, tools in self.tools.items()),
            ]
        return lines


def explain(found: Check, every_check: tuple[Check, ...]) -> Explanation:
    """The explanation of `found`, with the tools the support matrix recognises for it in each ecosystem."""
    reason = WHY.get(found.name)
    matrix = support_matrix(every_check)
    row = next((row for row in matrix.rows if row.check == found.name), None)
    tools = (
        {label: cell for label, cell in zip(matrix.ecosystems, row.cells, strict=True) if cell}
        if row is not None
        else {}
    )
    return Explanation(
        name=found.name,
        description=found.description,
        why=reason.why if reason else "",
        category=reason.category if reason else "Other",
        level=level_of(found.name),
        scored=found.name not in UNSCORED,
        applies_to=applies_to(found),
        tools=tools,
    )


__all__ = ["CATEGORIES", "WHY", "Explanation", "Why", "category", "explain", "why"]
