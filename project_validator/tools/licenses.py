"""License files, read as `LicenseFile` facts: `LICENSE`, `COPYING` and the like in any directory, and REUSE's
`LICENSES/` directory, one file per license named by its SPDX identifier (reuse.software)."""

from __future__ import annotations

import itertools
import re
from collections.abc import Iterator
from pathlib import PurePosixPath

from project_validator.facts import Fact, Origin
from project_validator.facts.licenses import LicenseFile
from project_validator.facts.settings import SettingsReader

# LICENSE, LICENSE.md, LICENSE-MIT, LICENCE, COPYING, COPYING.LESSER, UNLICENSE, ...
LICENSE_FILE = re.compile(r"(?:LICEN[CS]E|COPYING|UNLICENSE)(?:[-._].*)?", re.IGNORECASE)
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
        ("EPL-1.0", r"eclipse public license -? ?v(?:ersion)? ?1\.0"),
        ("LPPL-1.3c", r"latex project public license.*lppl version 1\.3c"),
        ("Artistic-2.0", r"the artistic license 2\.0"),
        # "The same terms as Perl itself": the GPL (version 1 or later) or the Artistic License, Perl's dual license.
        (
            "Artistic-1.0-Perl OR GPL-1.0-or-later",
            r"terms (?:as|of) (?:the )?perl(?: 5 programming language system)? itself",
        ),
        ("ODbL-1.0", r"open database license \(odbl\)"),
        ("CC-BY-NC-4.0", r"attribution-noncommercial 4\.0 international"),
        ("CC-BY-4.0", r"attribution 4\.0 international"),
        (
            "PostgreSQL",
            r"permission to use, copy, modify, and distribute this software and its documentation for any purpose, "
            r"without fee, and without a written agreement",
        ),
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
# Manifests that are where their ecosystem declares a license, in place of a license file (a Data Package's
# `licenses`): their declaration stands in for one.
DECLARED_IN_PLACE_OF_A_FILE = ("datapackage.json",)
_QUOTED = re.compile(r"^[ \t]*>[ \t]?", re.MULTILINE)
# How much of a license file is read: every known license is recognised by its first few paragraphs.
HEAD_SIZE = 16384
_WITH = "WITH"
_OPERATORS = frozenset({"AND", "OR", _WITH})


def identifiers_in(expression: str) -> frozenset[str]:
    """The licenses an SPDX expression names (`MIT OR Apache-2.0`), without exceptions (`WITH LLVM-exception`)."""
    tokens = re.findall(r"[\w.+-]+", expression)
    exceptions = {following for word, following in itertools.pairwise(tokens) if word == _WITH}
    return frozenset(token for token in tokens if token not in _OPERATORS and token not in exceptions)


def recognised(path: str, text: str) -> frozenset[str]:
    """The SPDX identifiers of the licenses in a license file; none when it is not recognised."""
    if PurePosixPath(path).parent.name == REUSE_DIRECTORY:
        return frozenset({PurePosixPath(path).stem})
    head = text[:HEAD_SIZE]
    if identifiers := SPDX_IDENTIFIER.findall(head):
        return frozenset(spdx for expression in identifiers for spdx in identifiers_in(expression))
    # A Markdown blockquote (`> Permission is hereby granted…`) is read as its text.
    flat = " ".join(_QUOTED.sub("", head).lower().split())
    # A combined file (a package's license, then its bundled parts') is the license it opens with.
    found = [
        (match.start(), index, spdx)
        for index, (spdx, opening) in enumerate(KNOWN_LICENSES)
        if (match := opening.search(flat))
    ]
    return identifiers_in(min(found)[2]) if found else frozenset()


def _read(path: str, text: str) -> Iterator[Fact]:
    file = PurePosixPath(path)
    reuse = file.parent.name == REUSE_DIRECTORY
    if reuse or (LICENSE_FILE.fullmatch(file.name) and file.suffix not in _code_suffixes()):
        yield LicenseFile(origin=Origin(path=path), licenses=recognised(path, text))


def _code_suffixes() -> frozenset[str]:
    """The suffixes of a language's sources: `License.pm` and `license.t` are code about licenses (Dist::Zilla)."""
    from project_validator.ecosystems import registered  # the profiles define the suffixes; they read licenses

    languages = (ecosystem for ecosystem in registered() if ecosystem.kind == "language")
    found = (suffix for ecosystem in languages for suffix in ecosystem.source_suffixes or {})
    return frozenset((*found, *_TEST_SCRIPTS))


# Perl's test scripts, which its profile finds by directory rather than by suffix.
_TEST_SCRIPTS = (".t",)


def _any_case(name: str) -> str:
    return "".join(f"[{letter.upper()}{letter.lower()}]" for letter in name) + "*"


LICENSE_FILES = SettingsReader(
    name="license files",
    files=(*(_any_case(name) for name in ("licence", "license", "copying", "unlicense")), f"{REUSE_DIRECTORY}/*"),
    read=_read,
)

__all__ = ["LICENSE_FILES", "REUSE_DIRECTORY", "identifiers_in", "recognised"]
