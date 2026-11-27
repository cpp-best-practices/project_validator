"""The repository's own .gitignore ignores none of the files it commits: mutmut's copy of the tree is made a repository
with `git add -A` (mutation-testing.yml), which leaves out what is ignored. The fixtures commit build outputs on purpose
(`tests/fixtures/bare_javascript/coverage/`), so an ignore entry for a tool's output must be anchored at the root."""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(shutil.which("git") and (ROOT / ".git").exists(), "needs git and a checkout")
class TrackedFilesTests(unittest.TestCase):
    def test_no_committed_file_is_ignored(self) -> None:
        git = shutil.which("git") or "git"
        listed = subprocess.run(  # noqa: S603 - a fixed git command, in this checkout
            [git, "ls-files", "--cached", "--ignored", "--exclude-standard"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(listed.stdout.split(), [])


if __name__ == "__main__":
    unittest.main()
