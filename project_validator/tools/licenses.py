"""License files, read as `LicenseFile` facts: `LICENSE`, `COPYING` and the like in any directory, and REUSE's
`LICENSES/` directory, one file per license named by its SPDX identifier (reuse.software)."""

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
    flat = " ".join(head.lower().split())
    return frozenset(next(([spdx] for spdx, opening in KNOWN_LICENSES if opening.search(flat)), []))


def _read(path: str, text: str) -> Iterator[Fact]:
    reuse = PurePosixPath(path).parent.name == REUSE_DIRECTORY
    if reuse or LICENSE_FILE.fullmatch(PurePosixPath(path).name):
        yield LicenseFile(origin=Origin(path=path), licenses=recognised(path, text))


def _any_case(name: str) -> str:
    return "".join(f"[{letter.upper()}{letter.lower()}]" for letter in name) + "*"


LICENSE_FILES = SettingsReader(
    name="license files",
    files=(*(_any_case(name) for name in ("licence", "license", "copying", "unlicense")), f"{REUSE_DIRECTORY}/*"),
    read=_read,
)

__all__ = ["LICENSE_FILES", "REUSE_DIRECTORY", "identifiers_in", "recognised"]
