"""Kinds of Perl project, for tests that run a check in every layout."""

from __future__ import annotations

from tests.layouts.model import ProjectLayout

MODULE = "package Shop;\nuse strict;\nuse warnings;\n\nsub total { my $sum = 0; $sum += $_ for @_; $sum }\n\n1;\n"

LAYOUTS = (
    ProjectLayout(
        name="MakeMaker distribution",
        files={
            "Makefile.PL": "use ExtUtils::MakeMaker;\nWriteMakefile(NAME => 'Shop', VERSION => '0.01');\n",
            "lib/Shop.pm": MODULE,
        },
        languages=frozenset({"Perl"}),
        build_systems=frozenset({"ExtUtils::MakeMaker"}),
    ),
    ProjectLayout(
        name="Perl modules",
        files={"lib/Shop.pm": MODULE},
        languages=frozenset({"Perl"}),
        build_systems=frozenset(),
    ),
)
