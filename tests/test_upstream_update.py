import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("upstream_update", ROOT / "scripts/update.py")
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


class UpstreamUpdateTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name).resolve()
        self.upstream = self.directory / "official"
        self.upstream.mkdir()
        updater.git(self.upstream, "init", "--initial-branch=main")
        self.identity(self.upstream)
        (self.upstream / "README.md").write_text("Chinese guide\n")
        (self.upstream / "feature.py").write_text("value = 1\n")
        self.commit(self.upstream, "Original")
        self.fork = self.directory / "fork"
        updater.git(self.directory, "clone", str(self.upstream), str(self.fork))
        self.identity(self.fork)
        (self.fork / "README.md").write_text("日本語ガイド\n")
        self.commit(self.fork, "Japanese localization")
        self.initial = updater.git(self.fork, "rev-parse", "HEAD").stdout.strip()
        upstream_url = patch.object(updater, "UPSTREAM", str(self.upstream))
        upstream_url.start()
        self.addCleanup(upstream_url.stop)

    def identity(self, root):
        updater.git(root, "config", "user.name", "Test")
        updater.git(root, "config", "user.email", "test@example.invalid")
        updater.git(root, "config", "commit.gpgsign", "false")

    def commit(self, root, message):
        updater.git(root, "add", ".")
        updater.git(root, "commit", "-m", message)

    def invoke(self, prepare=False):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return updater.update(self.fork, prepare=prepare)

    def change_upstream(self, conflict=False):
        (self.upstream / "feature.py").write_text("value = 2\n")
        if conflict:
            (self.upstream / "README.md").write_text("Updated Chinese guide\n")
        self.commit(self.upstream, "Official fix")

    def test_no_update_keeps_branch_head_and_working_files(self):
        self.assertEqual(self.invoke(prepare=True), 0)
        self.assertEqual(updater.git(self.fork, "rev-parse", "HEAD").stdout.strip(), self.initial)
        self.assertEqual(updater.git(self.fork, "branch", "--show-current").stdout.strip(), "main")
        self.assertEqual(updater.git(self.fork, "status", "--porcelain").stdout, "")

    def test_check_fetches_without_changing_localized_files_or_head(self):
        self.change_upstream()
        self.assertEqual(self.invoke(), 0)
        self.assertEqual((self.fork / "feature.py").read_text(), "value = 1\n")
        self.assertEqual((self.fork / "README.md").read_text(), "日本語ガイド\n")
        self.assertEqual(updater.git(self.fork, "rev-parse", "HEAD").stdout.strip(), self.initial)

    def test_prepare_merges_fix_retains_japanese_and_stops_before_commit(self):
        self.change_upstream()
        self.assertEqual(self.invoke(prepare=True), 0)
        self.assertEqual((self.fork / "feature.py").read_text(), "value = 2\n")
        self.assertEqual((self.fork / "README.md").read_text(), "日本語ガイド\n")
        self.assertTrue(updater.git(self.fork, "branch", "--show-current").stdout.startswith("codex/upstream-"))
        self.assertEqual(updater.git(self.fork, "rev-parse", "main").stdout.strip(), self.initial)
        self.assertEqual(updater.git(self.fork, "rev-parse", "HEAD").stdout.strip(), self.initial)
        self.assertTrue((self.fork / ".git/MERGE_HEAD").is_file())

    def test_conflict_is_left_for_review_and_can_be_aborted(self):
        self.change_upstream(conflict=True)
        self.assertEqual(self.invoke(prepare=True), 2)
        self.assertIn("README.md", updater.git(self.fork, "diff", "--name-only", "--diff-filter=U").stdout)
        self.assertEqual(updater.git(self.fork, "rev-parse", "main").stdout.strip(), self.initial)
        updater.git(self.fork, "merge", "--abort")
        self.assertEqual((self.fork / "README.md").read_text(), "日本語ガイド\n")

    def test_dirty_work_is_preserved_and_wrong_upstream_is_rejected(self):
        (self.fork / "feature.py").write_text("local edit\n")
        with self.assertRaisesRegex(ValueError, "未保存"):
            self.invoke(prepare=True)
        self.assertEqual((self.fork / "feature.py").read_text(), "local edit\n")
        updater.git(self.fork, "remote", "add", "upstream", str(self.directory / "wrong"))
        with self.assertRaisesRegex(ValueError, "本家"):
            self.invoke()
        self.assertEqual(updater.git(self.fork, "rev-parse", "HEAD").stdout.strip(), self.initial)

    def test_source_directory_must_be_repository_root(self):
        subdirectory = self.fork / "nested"
        subdirectory.mkdir()
        with self.assertRaisesRegex(ValueError, "ルート"):
            updater.update(subdirectory)


if __name__ == "__main__":
    unittest.main()
