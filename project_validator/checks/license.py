"""The project says under which license it may be used: a license file of a known license, matching the manifests."""

import itertools
import re
from pathlib import PurePosixPath

from project_validator.core import Context, Result, check
from project_validator.ecosystems import ecosystems_for, registered, rules_of
from project_validator.rules import DeclaredLicense

# LICENSE, LICENSE.md, LICENSE-MIT, LICENCE, COPYING, COPYING.LESSER, UNLICENSE, ...
LICENSE_FILE = re.compile(r"(?:LICEN[CS]E|COPYING|UNLICENSE)(?:[-._].*)?", re.IGNORECASE)
# REUSE (reuse.software): one file per license, named by its SPDX identifier.
REUSE_DIRECTORY = "LICENSES"
SPDX_IDENTIFIER = re.compile(r"SPDX-License-Identifier:\s*([^\n*]+?)\s*(?:\*/|-->)?\s*$", re.MULTILINE)

# SPDX identifier -> the opening of its text, lowercase with whitespace collapsed. The first match wins, so a
# license that quotes another one comes first.
KNOWN_LICENSES = tuple(
    (spdx, re.compile(text))
    for spdx, text in (
        ("AGPL-3.0", r"gnu affero general public license version 3"),
        ("LGPL-3.0", r"gnu lesser general public license version 3"),
        ("LGPL-2.1", r"gnu lesser general public license version 2\.1"),
        ("LGPL-2.0", r"gnu library general public license version 2"),
        ("GPL-3.0", r"gnu general public license version 3"),
        ("GPL-2.0", r"gnu general public license version 2"),
        ("Apache-2.0", r"apache license,? version 2\.0"),
        ("MPL-2.0", r"mozilla public license,? version 2\.0"),
        ("EPL-2.0", r"eclipse public license -? ?v(?:ersion)? ?2\.0"),
        ("BSL-1.0", r"boost software license -? ?version 1\.0"),
        ("Unlicense", r"this is free and unencumbered software released into the public domain"),
        ("CC0-1.0", r"cc0 1\.0 universal"),
        ("MIT", r"permission is hereby granted, free of charge, to any person obtaining a copy"),
        ("BSD-3-Clause", r"redistribution and use in source and binary forms.*neither the name"),
        ("BSD-2-Clause", r"redistribution and use in source and binary forms"),
        ("ISC", r"permission to use, copy, modify, and/?or distribute this software for any purpose .*provided that"),
        ("0BSD", r"permission to use, copy, modify, and/?or distribute this software for any purpose"),
        ("Zlib", r"this software is provided 'as-is', without any express or implied warranty"),
    )
)
# How much of a license file is read: every known license is recognised by its first few paragraphs.
HEAD_SIZE = 16384
_WITH = "WITH"
_OPERATORS = frozenset({"AND", "OR", _WITH})
HINT = "add a LICENSE file with the text of a license (see https://choosealicense.com)"


def license_files(context: Context) -> list[str]:
    """The license files at the root of the project and, for REUSE, in LICENSES/."""
    project = context.project
    root = [
        path.name for path in sorted(project.root.iterdir()) if path.is_file() and LICENSE_FILE.fullmatch(path.name)
    ]
    return [*root, *project.files_in(REUSE_DIRECTORY, (".txt", ".md", ""))]


def recognised(context: Context, path: str) -> frozenset[str]:
    """The SPDX identifiers of the licenses in `path`; none when it is not recognised."""
    if PurePosixPath(path).parent.name == REUSE_DIRECTORY:
        return frozenset({PurePosixPath(path).stem})
    head = context.project.read_head(path, HEAD_SIZE)
    if identifiers := SPDX_IDENTIFIER.findall(head):
        return frozenset(spdx for expression in identifiers for spdx in identifiers_in(expression))
    text = " ".join(head.lower().split())
    return frozenset(next(([spdx] for spdx, opening in KNOWN_LICENSES if opening.search(text)), []))


def identifiers_in(expression: str) -> frozenset[str]:
    """The licenses an SPDX expression names (`MIT OR Apache-2.0`), without exceptions (`WITH LLVM-exception`)."""
    tokens = re.findall(r"[\w.+-]+", expression)
    exceptions = {following for word, following in itertools.pairwise(tokens) if word == _WITH}
    return frozenset(token for token in tokens if token not in _OPERATORS and token not in exceptions)


def _comparable(identifiers: frozenset[str]) -> frozenset[str]:
    """A license text says nothing of `-only` or `-or-later`, so those are compared as the license itself."""
    return frozenset(re.sub(r"(?:-only|-or-later|\+)$", "", spdx) for spdx in identifiers)


def _mismatches(context: Context, found: frozenset[str]) -> list[str]:
    rules = rules_of(DeclaredLicense)
    used = [
        rules[ecosystem]
        for ecosystem in ecosystems_for(context.structure.languages, registered())
        if ecosystem in rules
    ]
    return [
        f"{rule.manifest} declares {declared}, but the license files are {', '.join(sorted(found))}"
        for rule in used
        if (declared := rule.declared(context)) and _comparable(identifiers_in(declared)) != _comparable(found)
    ]


@check(name="license", description="The project has a license file of a known license")
def license_(context: Context) -> Result:
    files = license_files(context)
    if not files:
        return Result.failed("no license file", HINT)
    licenses = {path: recognised(context, path) for path in files}
    if unknown := [path for path, spdx in licenses.items() if not spdx]:
        return Result.warned(
            f"the license in {', '.join(unknown)} is not recognised",
            "use the license's standard text, or add an SPDX-License-Identifier line",
        )
    found = frozenset().union(*licenses.values())
    if mismatches := _mismatches(context, found):
        return Result.warned("the manifest declares another license than the license files", *mismatches)
    return Result.passed(f"the project is licensed under {', '.join(sorted(found))}", *files)
