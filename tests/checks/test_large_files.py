import shutil
import unittest
from collections.abc import Mapping
from pathlib import PurePosixPath

from project_validator.checks.large_files import HINT, large_files
from project_validator.core import DEFAULT_MAX_FILE_SIZE, Context, Options, Project, Result, Status
from tests.support import FIXTURES, make_context, temp_project
from tests.test_project import git

LIMIT = 200
LARGE = "x" * (LIMIT + 1)


def _run(files: Mapping[str, str], *, exclude: str = "", tracked: tuple[str, ...] = ()) -> Result:
    with temp_project(files) as root:
        if tracked:
            git(root, "init", "-q")
            git(root, "add", *tracked)
        context = Context(
            Project(root, frozenset({PurePosixPath(exclude)} if exclude else ())),
            make_context(root).providers,
            Options(max_file_size=LIMIT),
        )
        return large_files.run(context)


class LargeFilesTests(unittest.TestCase):
    def assert_passes(self, files: Mapping[str, str]) -> None:
        self.assertEqual(_run(files), Result.passed("no committed file is larger than 0 KiB"))

    def test_applies_to_every_language(self) -> None:
        self.assertEqual(large_files.languages, frozenset())

    def test_passes_with_the_well_configured_fixture(self) -> None:
        result = large_files.run(make_context(FIXTURES / "well_configured_c_cpp"))
        self.assertEqual(result, Result.passed("no committed file is larger than 5 MiB"))
        self.assertEqual(DEFAULT_MAX_FILE_SIZE, 5 * 1024 * 1024)

    def test_warns_listing_the_largest_files(self) -> None:
        files = {f"data/{index}.bin": "x" * (LIMIT + index) for index in range(1, 8)}
        result = _run({**files, "small.bin": "x" * LIMIT})
        self.assertEqual(result.status, Status.WARN)
        self.assertEqual(result.message, "7 committed files are larger than 0 KiB")
        self.assertEqual(
            result.details,
            (*(f"data/{index}.bin (0 KiB)" for index in range(7, 2, -1)), "and 2 more", HINT),
        )
        self.assertEqual(_run({"a.bin": LARGE}).message, "1 committed file is larger than 0 KiB")

    def test_sizes_are_shown_in_mib_from_one_mib(self) -> None:
        with temp_project({"model.onnx": "x" * (3 * 1024 * 1024 // 2)}) as root:
            context = Context(Project(root), (), Options(max_file_size=1024 * 1024))
            self.assertEqual(large_files.run(context).details[0], "model.onnx (1.5 MiB)")

    def test_files_stored_in_git_lfs_pass(self) -> None:
        attributes = "# assets\n*.psd filter=lfs diff=lfs merge=lfs -text\n/video/*.mp4 filter=lfs\n*.txt diff\n"
        self.assert_passes({".gitattributes": attributes, "art/logo.psd": LARGE, "video/intro.mp4": LARGE})
        result = _run({".gitattributes": attributes, "art/video/intro.mp4": LARGE, "notes.txt": LARGE})
        self.assertEqual(result.details[:2], ("art/video/intro.mp4 (0 KiB)", "notes.txt (0 KiB)"))

    def test_a_nested_gitattributes_applies_below_its_directory(self) -> None:
        files = {"assets/.gitattributes": "*.bin filter=lfs\nraw/*.dat filter=lfs\n"}
        self.assert_passes({**files, "assets/deep/a.bin": LARGE, "assets/raw/b.dat": LARGE})
        self.assertEqual(_run({**files, "other/a.bin": LARGE}).details[0], "other/a.bin (0 KiB)")

    def test_files_tracked_by_dvc_pass(self) -> None:
        self.assert_passes({"data/train.csv": LARGE, "data/train.csv.dvc": "outs:\n- path: train.csv\n"})

    def test_excluded_directories_are_not_judged(self) -> None:
        self.assertEqual(_run({"tests/fixtures/big.bin": LARGE}, exclude="tests/fixtures").status, Status.PASS)

    @unittest.skipUnless(shutil.which("git"), "git is not installed")
    def test_in_a_git_checkout_only_tracked_files_are_judged(self) -> None:
        files = {"build/output.bin": LARGE, "src/table.bin": LARGE, ".github/big.json": LARGE}
        result = _run(files, tracked=("src", ".github"))
        self.assertEqual(result.details[:2], (".github/big.json (0 KiB)", "src/table.bin (0 KiB)"))
