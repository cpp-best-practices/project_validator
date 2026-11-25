"""File soundness (upstream #383, part B): where a project holds binary or asset files (images, PDFs, fonts, audio
and video, archives, 3D models), CI runs a tool that checks they are sound: ClamAV or YARA for every kind, or one
that decodes the kind (magick, pngcheck, qpdf, fontbakery, ffprobe, gltf_validator)."""

from __future__ import annotations

import unittest
from collections.abc import Mapping

from project_validator.checks.file_soundness import file_soundness
from project_validator.core import Result, Status
from tests.support import github_job, make_context, temp_project


def _run(files: Mapping[str, str], *steps: str) -> Result:
    with temp_project({**files, **(github_job("ubuntu-latest", *steps) if steps else {})}) as root:
        return file_soundness.run(make_context(root))


class FileSoundnessTests(unittest.TestCase):
    def test_a_project_without_such_files_skips(self) -> None:
        self.assertEqual(_run({"src/a.py": ""}).status, Status.SKIP)

    def test_a_tool_for_each_kind_passes(self) -> None:
        for files, step, tool in (
            ({"docs/logo.png": ""}, "magick identify -regard-warnings docs/logo.png", "ImageMagick"),
            ({"docs/logo.png": ""}, "pngcheck docs/*.png", "pngcheck"),
            ({"docs/guide.pdf": ""}, "qpdf --check docs/guide.pdf", "qpdf"),
            ({"fonts/a.ttf": ""}, "fontbakery check-universal fonts/a.ttf", "fontbakery"),
            ({"media/a.mp3": ""}, "ffprobe -v error media/a.mp3", "ffprobe"),
            ({"models/a.glb": ""}, "gltf_validator models/a.glb", "glTF Validator"),
            ({"docs/logo.png": "", "dist/a.zip": ""}, "clamscan -r .", "ClamAV"),
        ):
            with self.subTest(step=step):
                self.assertEqual(_run(files, step), Result.passed(f"CI checks the binary files with {tool}"))

    def test_a_kind_no_tool_checks_warns_naming_it(self) -> None:
        result = _run({"docs/logo.png": "", "docs/guide.pdf": ""}, "pngcheck docs/*.png")
        self.assertEqual(result.status, Status.WARN)
        self.assertEqual(result.message, "no tool checks the PDF files (docs/guide.pdf)")
        self.assertEqual(_run({"docs/LOGO.PNG": ""}).message, "no tool checks the image files (docs/LOGO.PNG)")
        many = {f"docs/{name}.png": "" for name in "abcde"}
        self.assertEqual(
            _run({**many, "a.ttf": ""}).message,
            "no tool checks the image files (docs/a.png, docs/b.png, docs/c.png and 2 more); "
            "no tool checks the font files (a.ttf)",
        )

    def test_vendored_files_are_not_the_projects(self) -> None:
        self.assertEqual(_run({"third_party/x/logo.png": ""}).status, Status.SKIP)
