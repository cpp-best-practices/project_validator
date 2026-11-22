"""Where each language's files are (upstream #332): the folders that hold them, how many files each, in which role,
and the language's share of the project's own files; in the map, its JSON and every view."""

from __future__ import annotations

import dataclasses
import io
import json
import unittest

from project_validator.analysis import Analysis, Git, analyse, folder_url
from project_validator.plugins import discover
from project_validator.project_map import LanguageFiles, Place
from project_validator.views import common, html, text, tui
from project_validator.views import console as console_view
from tests.support import make_context, requires_rich, temp_project

FILES = {
    "pyproject.toml": "[project]\nname = 'a'\n",
    "pkg/a.py": "",
    "pkg/sub/b.py": "",
    "pkg/sub/c.py": "",
    "tests/test_a.py": "",
    "tests/fixtures/data/sleeper.c": "",
    "scripts/x.sh": "",
    "src/main/java/A.java": "",
    "src/test/java/AT.java": "",
    "third_party/lib.c": "",
}


def _analysis(files: dict[str, str]) -> Analysis:
    with temp_project(files) as root:
        return analyse(make_context(root), discover().checks)


def _files(analysis: Analysis) -> tuple[LanguageFiles, ...]:
    if analysis.structure is None:
        raise AssertionError(analysis.error)
    return analysis.structure.files


def _by_language(analysis: Analysis) -> dict[str, LanguageFiles]:
    return {found.language: found for found in _files(analysis)}


class MapTests(unittest.TestCase):
    analysis: Analysis

    @classmethod
    def setUpClass(cls) -> None:
        cls.analysis = _analysis(FILES)

    def test_each_language_s_files_are_placed_in_the_deepest_folder_they_share_by_top_folder_and_role(self) -> None:
        found = _by_language(self.analysis)
        self.assertEqual(
            found["Python"].places,
            (Place(directory="pkg", role="product", files=3), Place(directory="tests", role="test", files=1)),
        )
        self.assertEqual(found["C"].places, (Place(directory="tests/fixtures/data", role="test", files=1),))
        self.assertEqual(
            found["Java"].places,
            (
                Place(directory="src/main/java", role="product", files=1),
                Place(directory="src/test/java", role="test", files=1),
            ),
        )
        self.assertEqual(found["TOML"].places, (Place(directory=".", role="product", files=1),))

    def test_vendored_files_are_no_language_s(self) -> None:
        self.assertEqual(_by_language(self.analysis)["C"].files, 1)

    def test_languages_come_most_files_first_with_their_share_of_the_project_s_own_files(self) -> None:
        files = _files(self.analysis)
        self.assertEqual(files[0].language, "Python")
        self.assertEqual([found.files for found in files], sorted((found.files for found in files), reverse=True))
        self.assertEqual(sum(found.files for found in files), 9)
        self.assertAlmostEqual(files[0].share, 4 / 9)

    def test_the_map_json_lists_each_language_s_places(self) -> None:
        structure = self.analysis.structure
        listed = json.loads(json.dumps(structure.as_dict() if structure else {}))["files"]
        self.assertEqual(
            listed[0],
            {
                "language": "Python",
                "files": 4,
                "share": 0.4444,
                "places": [
                    {"directory": "pkg", "role": "product", "files": 3},
                    {"directory": "tests", "role": "test", "files": 1},
                ],
            },
        )


class WordsTests(unittest.TestCase):
    def test_a_language_s_files_are_counted_with_their_share_and_each_folder(self) -> None:
        found = LanguageFiles(
            language="Python",
            files=6,
            share=0.5,
            places=(
                Place(directory="pkg", role="product", files=4),
                Place(directory=".", role="product", files=1),
                Place(directory="tests/fixtures", role="test", files=1),
            ),
        )
        self.assertEqual(
            common.language_files(found), ("6 files (50%)", "pkg/ (4), the root (1), tests/fixtures/ (1, test)")
        )

    def test_a_small_share_is_shown_below_one_percent_and_one_file_is_singular(self) -> None:
        found = LanguageFiles(language="C", files=1, share=0.004, places=(Place(directory="t", role="test", files=1),))
        self.assertEqual(common.language_files(found), ("1 file (<1%)", "t/ (1, test)"))

    def test_folders_past_the_limit_are_folded_into_a_count(self) -> None:
        places = tuple(Place(directory=f"d{index}", role="product", files=1) for index in range(7))
        found = LanguageFiles(language="Go", files=7, share=1.0, places=places)
        shown = ", ".join(f"d{index}/ (1)" for index in range(common.PLACES_SHOWN))
        rest = 7 - common.PLACES_SHOWN
        self.assertEqual(common.language_files(found)[1], f"{shown} and {rest} more folders ({rest} files)")
        one = LanguageFiles(language="Go", files=5, share=1.0, places=places[: common.PLACES_SHOWN + 1])
        self.assertTrue(common.language_files(one)[1].endswith(" and 1 more folder (1 file)"))


class FolderUrlTests(unittest.TestCase):
    def test_a_folder_is_seen_on_the_web_at_the_commit_analysed(self) -> None:
        git = Git(web="https://github.com/o/r", commit="c" * 40)
        tree = f"https://github.com/o/r/tree/{'c' * 40}"
        self.assertEqual((folder_url(git, "src/app"), folder_url(git, ".")), (f"{tree}/src/app", tree))

    def test_without_a_web_address_or_commit_there_is_no_link(self) -> None:
        self.assertIsNone(folder_url(Git(commit="c" * 40), "src"))
        self.assertIsNone(folder_url(Git(web="https://github.com/o/r"), "src"))


class ViewTests(unittest.TestCase):
    analysis: Analysis

    @classmethod
    def setUpClass(cls) -> None:
        cls.analysis = _analysis(FILES)

    def test_the_text_report_says_where_each_language_is(self) -> None:
        lines = text.detected_lines(self.analysis)
        self.assertIn("  Where: C: 1 file (11%) in tests/fixtures/data/ (1, test)", lines)
        self.assertIn("  Where: Python: 4 files (44%) in pkg/ (3), tests/ (1, test)", lines)

    def test_the_html_report_has_a_card_of_where_each_language_is(self) -> None:
        page = html.render(self.analysis)
        self.assertIn("<h3>Where the files are</h3>", page)
        self.assertIn("<td>4 files (44%)</td>", page)
        self.assertIn("pkg/ (3), tests/ (1, test)", page)

    def test_the_html_report_links_each_folder_to_the_forge_at_the_commit(self) -> None:
        git = Git(web="https://github.com/o/r", commit="c" * 40)
        page = html.render(dataclasses.replace(self.analysis, git=git))
        tree = f"https://github.com/o/r/tree/{'c' * 40}"
        self.assertIn(f'<a href="{tree}/pkg">pkg/</a> (3), <a href="{tree}/tests">tests/</a> (1, test)', page)

    @requires_rich
    def test_the_console_has_a_table_of_where_each_language_is(self) -> None:
        out = io.StringIO()
        console_view.render(self.analysis, out, width=200)
        self.assertIn("tests/fixtures/data/ (1, test)", out.getvalue())

    def test_the_tui_says_where_each_language_is(self) -> None:
        self.assertIn("pkg/ (3), tests/ (1, test)", tui.detected(self.analysis))


if __name__ == "__main__":
    unittest.main()
