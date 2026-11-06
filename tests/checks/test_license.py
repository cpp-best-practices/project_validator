import unittest
from collections.abc import Mapping

from project_validator.checks.license import license_
from project_validator.core import Result, Status
from tests.support import FIXTURES, make_context, temp_project

MIT = (FIXTURES / "well_configured_c_cpp" / "LICENSE").read_text(encoding="utf-8")
APACHE = "                                 Apache License\n                           Version 2.0, January 2004\n"

# SPDX identifier -> the opening of the license's text, as it appears in a license file.
OPENINGS = {
    "AGPL-3.0": "GNU AFFERO GENERAL PUBLIC LICENSE\n   Version 3, 19 November 2007",
    "LGPL-3.0": "GNU LESSER GENERAL PUBLIC LICENSE\n   Version 3, 29 June 2007",
    "LGPL-2.1": "GNU LESSER GENERAL PUBLIC LICENSE\n   Version 2.1, February 1999",
    "LGPL-2.0": "GNU LIBRARY GENERAL PUBLIC LICENSE\n   Version 2, June 1991",
    "GPL-3.0": "GNU GENERAL PUBLIC LICENSE\n   Version 3, 29 June 2007",
    "GPL-2.0": "GNU GENERAL PUBLIC LICENSE\n   Version 2, June 1991",
    "Apache-2.0": APACHE,
    "MPL-2.0": "Mozilla Public License Version 2.0\n==================================",
    "EPL-2.0": "Eclipse Public License - v 2.0\n\n    THE ACCOMPANYING PROGRAM IS PROVIDED",
    "BSL-1.0": "Boost Software License - Version 1.0 - August 17th, 2003",
    "Unlicense": "This is free and unencumbered software released into the public domain.",
    "CC0-1.0": "Creative Commons Legal Code\n\nCC0 1.0 Universal",
    "MIT": MIT,
    "BSD-3-Clause": (
        "Redistribution and use in source and binary forms, with or without\nmodification, are permitted"
        "...\n3. Neither the name of the copyright holder nor the names of its contributors"
    ),
    "BSD-2-Clause": "Redistribution and use in source and binary forms, with or without\nmodification, are permitted",
    "ISC": (
        "Permission to use, copy, modify, and/or distribute this software for any\npurpose with or without fee"
        " is hereby granted, provided that the above copyright notice"
    ),
    "0BSD": (
        "Permission to use, copy, modify, and/or distribute this software for any\npurpose with or without fee"
        " is hereby granted.\n\nTHE SOFTWARE IS PROVIDED"
    ),
    "Zlib": "This software is provided 'as-is', without any express or implied\nwarranty.",
}


def _run(files: Mapping[str, str]) -> Result:
    with temp_project(files) as root:
        return license_.run(make_context(root))


class LicenseTests(unittest.TestCase):
    def assert_licensed(self, files: Mapping[str, str], licenses: str, *paths: str) -> None:
        self.assertEqual(_run(files), Result.passed(f"the project is licensed under {licenses}", *paths))

    def test_applies_to_every_language(self) -> None:
        self.assertEqual(license_.languages, frozenset())

    def test_fails_without_a_license_file(self) -> None:
        for files in ({}, {"docs/LICENSE": MIT, "src/license.cpp": ""}):
            with self.subTest(files=list(files)):
                result = _run(files)
                self.assertEqual(result.status, Status.FAIL)
                self.assertEqual(result.message, "no license file")

    def test_recognises_the_text_of_known_licenses(self) -> None:
        for spdx, opening in OPENINGS.items():
            with self.subTest(spdx):
                self.assert_licensed({"LICENSE": opening}, spdx, "LICENSE")

    def test_license_files_go_by_many_names(self) -> None:
        for name in (
            "LICENSE",
            "LICENSE.md",
            "LICENSE.txt",
            "license",
            "LICENCE",
            "COPYING",
            "UNLICENSE",
            "COPYING.LESSER",
        ):
            with self.subTest(name):
                self.assert_licensed({name: MIT}, "MIT", name)

    def test_each_license_of_a_dual_licensed_project_is_recognised(self) -> None:
        self.assert_licensed(
            {"LICENSE-APACHE": APACHE, "LICENSE-MIT": MIT}, "Apache-2.0, MIT", "LICENSE-APACHE", "LICENSE-MIT"
        )

    def test_an_spdx_identifier_names_the_license(self) -> None:
        files = {"LICENSE": "/* SPDX-License-Identifier: GPL-2.0-only WITH Linux-syscall-note */\nCustom text\n"}
        self.assert_licensed(files, "GPL-2.0-only", "LICENSE")
        self.assert_licensed({"COPYING": "SPDX-License-Identifier: MIT OR Apache-2.0\n"}, "Apache-2.0, MIT", "COPYING")

    def test_reuse_names_each_license_file_by_its_identifier(self) -> None:
        files = {"LICENSES/MIT.txt": "any text", "LICENSES/CC-BY-4.0.txt": "any text", "src/main.c": ""}
        self.assert_licensed(files, "CC-BY-4.0, MIT", "LICENSES/CC-BY-4.0.txt", "LICENSES/MIT.txt")

    def test_warns_when_the_license_is_not_recognised(self) -> None:
        result = _run({"LICENSE": "All rights reserved.\n", "COPYING": MIT})
        self.assertEqual(result.status, Status.WARN)
        self.assertEqual(result.message, "the license in LICENSE is not recognised")


class DeclaredLicenseTests(unittest.TestCase):
    def test_passes_when_the_manifests_declare_the_license_of_the_files(self) -> None:
        cases = {
            "pyproject.toml": ("[project]\nlicense = 'MIT'\n", {"LICENSE": MIT}),
            "Cargo.toml": (
                "[package]\nlicense = 'MIT OR Apache-2.0'\n",
                {"LICENSE-MIT": MIT, "LICENSE-APACHE": APACHE},
            ),
        }
        for manifest, (text, licenses) in cases.items():
            with self.subTest(manifest):
                self.assertEqual(_run({manifest: text, **licenses}).status, Status.PASS)

    def test_or_later_and_exceptions_are_not_part_of_the_license_text(self) -> None:
        cases = {
            "GPL-3.0-or-later": OPENINGS["GPL-3.0"],
            "GPL-2.0+": OPENINGS["GPL-2.0"],
            "Apache-2.0 WITH LLVM-exception": APACHE,
            "(MIT)": MIT,
        }
        for declared, text in cases.items():
            with self.subTest(declared):
                result = _run({"Cargo.toml": f"[package]\nlicense = '{declared}'\n", "LICENSE": text})
                self.assertEqual(result.status, Status.PASS, result)

    def test_warns_when_a_manifest_declares_another_license(self) -> None:
        result = _run({"pyproject.toml": "[project]\nlicense = 'Apache-2.0'\n", "LICENSE": MIT})
        self.assertEqual(
            result,
            Result.warned(
                "the manifest declares another license than the license files",
                "pyproject.toml declares Apache-2.0, but the license files are MIT",
            ),
        )

    def test_manifests_that_name_no_spdx_expression_are_not_compared(self) -> None:
        for text in ("[project]\nlicense = {text = 'Apache'}\n", "[project\n", "project = 1\n", "[project]\n"):
            with self.subTest(text=text):
                self.assertEqual(_run({"pyproject.toml": text, "LICENSE": MIT}).status, Status.PASS)
        # A Python project without a pyproject.toml declares nothing.
        self.assertEqual(_run({"setup.py": "", "LICENSE": MIT}).status, Status.PASS)
