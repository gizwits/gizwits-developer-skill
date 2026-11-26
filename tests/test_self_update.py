import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import self_update as updater


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.remote = self.root / "remote"
        self.local = self.root / "skill"
        self.state = self.root / "state/update.json"
        self.remote.mkdir()
        self.run_git(self.remote, "init", "-b", "main")
        self.run_git(self.remote, "config", "user.email", "test@example.invalid")
        self.run_git(self.remote, "config", "user.name", "Test")
        (self.remote / "SKILL.md").write_text("version one\n")
        (self.remote / ".gitignore").write_text("outputs/\n")
        self.commit(self.remote)
        self.run_git(self.root, "clone", str(self.remote), str(self.local))
        self.old = updater.revision(self.local)
        self.patch = patch.object(updater, "REMOTE", str(self.remote))
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def run_git(self, root, *args):
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                                text=True, check=True)
        return result.stdout.strip()

    def commit(self, root):
        self.run_git(root, "add", "-A")
        self.run_git(root, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                     "commit", "-m", "Test change")
        return self.run_git(root, "rev-parse", "HEAD")

    def publish(self, text="version two\n"):
        (self.remote / "SKILL.md").write_text(text)
        return self.commit(self.remote)

    def test_daily_check_skips_network_until_24_hours(self):
        self.assertEqual(updater.check(self.local, self.state, now=100)["status"], "up_to_date")
        with patch.object(updater, "git", side_effect=AssertionError("should not access git")):
            self.assertEqual(updater.check(self.local, self.state, now=100 + 86399)["status"], "not_due")
        self.assertEqual(updater.check(self.local, self.state, now=100 + 86400)["status"], "up_to_date")

    def test_check_only_prepares_review_then_exact_approved_update(self):
        target = self.publish()
        result = updater.check(self.local, self.state)
        self.assertEqual(result["status"], "update_available")
        self.assertIn("SKILL.md", result["changes"])
        self.assertEqual(updater.revision(self.local), self.old)
        self.assertEqual((self.local / "SKILL.md").read_text(), "version one\n")
        # Upstream advances during approval; never silently update to the new tip.
        newest = self.publish("version three\n")
        self.assertNotEqual(newest, target)
        result = updater.upgrade(self.local, self.state, target)
        self.assertEqual(result["previous"], self.old)
        self.assertEqual(updater.revision(self.local), target)
        self.assertEqual((self.local / "SKILL.md").read_text(), "version two\n")

    def test_no_pending_or_wrong_target_cannot_upgrade(self):
        target = self.publish()
        with self.assertRaisesRegex(ValueError, "待升级"):
            updater.upgrade(self.local, self.state, target)
        updater.check(self.local, self.state)
        with self.assertRaisesRegex(ValueError, "待升级"):
            updater.upgrade(self.local, self.state, "f" * 40)
        self.assertEqual(updater.revision(self.local), self.old)

    def test_defer_removes_pending_and_waits_a_day(self):
        target = self.publish()
        updater.check(self.local, self.state)
        with patch.object(updater.time, "time", return_value=1000):
            updater.defer(self.state)
        self.assertEqual(json.loads(self.state.read_text())["next_check"], 87400)
        with self.assertRaises(ValueError):
            updater.upgrade(self.local, self.state, target)

    def test_dirty_files_not_changed_and_rechecked_after_consent(self):
        target = self.publish()
        updater.check(self.local, self.state)
        (self.local / "SKILL.md").write_text("my customization\n")
        with self.assertRaisesRegex(ValueError, "本地修改"):
            updater.upgrade(self.local, self.state, target)
        self.assertEqual((self.local / "SKILL.md").read_text(), "my customization\n")
        self.assertEqual(updater.check(self.local, self.state, force=True)["status"], "blocked")

    def test_ignored_private_output_survives_upgrade(self):
        (self.local / "outputs").mkdir()
        private = self.local / "outputs/private.json"
        private.write_text("private data")
        target = self.publish()
        updater.check(self.local, self.state)
        updater.upgrade(self.local, self.state, target)
        self.assertEqual(private.read_text(), "private data")

    def test_new_remote_file_cannot_overwrite_ignored_local_file(self):
        for root in (self.remote, self.local):
            (root / "outputs").mkdir()
            (root / "outputs/private.json").write_text("keep me" if root == self.local else "upstream")
        self.run_git(self.remote, "add", "-f", "outputs/private.json")
        self.commit(self.remote)
        result = updater.check(self.local, self.state)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("冲突", result["reason"])
        self.assertEqual((self.local / "outputs/private.json").read_text(), "keep me")

    def test_untracked_files_and_divergence_block_update(self):
        self.publish()
        (self.local / "custom.md").write_text("local work")
        self.assertEqual(updater.check(self.local, self.state)["status"], "blocked")
        self.commit(self.local)
        result = updater.check(self.local, self.state, force=True)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("历史", result["reason"])

    def test_remote_rename_cannot_overwrite_ignored_file(self):
        for root in (self.remote, self.local):
            (root / "outputs").mkdir()
        (self.local / "outputs/notes.md").write_text("local notes")
        self.run_git(self.remote, "mv", "SKILL.md", "outputs/notes.md")
        self.commit(self.remote)
        self.assertEqual(updater.check(self.local, self.state)["status"], "blocked")
        self.assertEqual((self.local / "outputs/notes.md").read_text(), "local notes")

    def test_detached_head_not_updated(self):
        self.publish()
        self.run_git(self.local, "checkout", "--detach", "HEAD")
        result = updater.check(self.local, self.state)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("detached", result["reason"])

    def test_local_commit_after_check_requires_new_review(self):
        target = self.publish()
        updater.check(self.local, self.state)
        (self.local / "custom.md").write_text("committed customization")
        self.commit(self.local)
        with self.assertRaisesRegex(ValueError, "本地版本已变化"):
            updater.upgrade(self.local, self.state, target)

    def test_non_git_or_nested_install_never_updates_parent(self):
        folder = self.local / "nested"
        folder.mkdir()
        (folder / "SKILL.md").write_text("copied skill")
        with self.assertRaisesRegex(ValueError, "独立 Git"):
            updater.check(folder, self.state)
        with self.assertRaises(ValueError):
            updater.check(self.root, self.state, force=True)
        self.assertEqual(updater.revision(self.local), self.old)

    def test_network_failure_has_daily_backoff_and_force_can_retry(self):
        with patch.object(updater, "REMOTE", str(self.root / "missing-remote")):
            with self.assertRaises(ValueError):
                updater.check(self.local, self.state, now=100)
        self.assertEqual(updater.check(self.local, self.state, now=200)["status"], "not_due")
        self.assertEqual(updater.check(self.local, self.state, force=True, now=200)["status"], "up_to_date")

    def test_corrupt_state_can_be_recovered(self):
        self.state.parent.mkdir()
        self.state.write_text("broken json")
        self.assertEqual(updater.check(self.local, self.state)["status"], "up_to_date")


if __name__ == "__main__":
    unittest.main()
