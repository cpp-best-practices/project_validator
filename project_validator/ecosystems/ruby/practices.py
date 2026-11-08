"""Ruby's practices: the settings it asks for, and how they are worded (see
`project_validator.facts.practices`)."""

import re

from project_validator.ecosystems.ruby import RUBY_ONLY, TEST_HELPERS
from project_validator.facts.practices import Practice, PracticeName, Wording, always, required, requirement_reader
from project_validator.text import Pattern, pattern

# rubocop -a corrects what it can and passes; it enforces nothing.
RUNS_RUBOCOP = r"(?<![\w-])rubocop\b(?!\.yml|-)(?![^\n]*\s(?:-a|-A|--autocorrect(?:-all)?)\b)|\bRuboCop::RakeTask\b"


RUNS_STANDARD = r"\bstandardrb\b(?![^\n]*\s--fix\b)|\brake\s+standard\b|\bStandard::RakeTask\b|\bstandard/rake\b"


RUBY_WARNINGS = Pattern(
    "Ruby warnings",
    re.compile(
        r"\bruby\s+(?:-\w+\s+)*-w\b|\bRUBYOPT\W+-[wW]\b|\$VERBOSE\s*=\s*true\b"
        r"|\.warnings\s*=\s*true\b|\.warning\s*=\s*true\b|^\s*--warnings\b",
        re.MULTILINE,
    ),
)


RUBY_LINTER = pattern("RuboCop or Standard", rf"{RUNS_RUBOCOP}|{RUNS_STANDARD}")


# Ruby warns only when asked to; a linter reports what other compilers warn about.
RUBY_WARNING_SETTINGS = requirement_reader(
    "Ruby warning settings", (".rspec", *TEST_HELPERS), (required(RUBY_WARNINGS),)
)


WARNINGS = Practice(
    name=PracticeName.WARNINGS,
    languages=RUBY_ONLY,
    requirements=always(required(RUBY_WARNINGS), required(RUBY_LINTER, in_files=False, tools=("RuboCop", "Standard"))),
    reads=(RUBY_WARNING_SETTINGS.name,),
    words=Wording(
        kind="Ruby warning settings",
        hint="run Ruby with -w (RUBYOPT=-w, or --warnings in .rspec) and run RuboCop or Standard",
    ),
)
