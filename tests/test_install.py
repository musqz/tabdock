"""install.sh against a throwaway $HOME (never touches the real browser config)."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
INSTALL = os.path.join(ROOT, "install.sh")
RELAY = os.path.join(ROOT, "lib", "native-host", "sidepanel-nmhost")


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.manifest = os.path.join(self.tmp.name, ".mozilla", "native-messaging-hosts", "openbox_sidepanel.json")

    def run_install(self, *args):
        env = {**os.environ, "HOME": self.tmp.name}
        return subprocess.run([INSTALL, *args], env=env, capture_output=True, text=True)

    def test_install_update_uninstall(self):
        first = self.run_install()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("installed", first.stdout)
        with open(self.manifest) as f:
            manifest = json.load(f)
        self.assertEqual(manifest["name"], "openbox_sidepanel")
        self.assertEqual(manifest["path"], RELAY)
        self.assertEqual(manifest["allowed_extensions"], ["openbox-sidepanel@musqz.local"])
        self.assertTrue(os.access(manifest["path"], os.X_OK))

        again = self.run_install()
        self.assertEqual(again.returncode, 0)
        self.assertIn("updated", again.stdout)

        removed = self.run_install("--uninstall")
        self.assertEqual(removed.returncode, 0)
        self.assertIn("removed", removed.stdout)
        self.assertFalse(os.path.exists(self.manifest))

        gone = self.run_install("--uninstall")
        self.assertEqual(gone.returncode, 0)
        self.assertIn("absent", gone.stdout)

    def test_ampersand_in_checkout_path(self):
        # bash 5.2 expands '&' in a pattern-substitution replacement unless patsub_replacement is off
        checkout = os.path.join(self.tmp.name, "a&b")
        for rel in ("install.sh", "configs/openbox_sidepanel.json.in", "lib/native-host/sidepanel-nmhost"):
            os.makedirs(os.path.dirname(os.path.join(checkout, rel)), exist_ok=True)
            shutil.copy2(os.path.join(ROOT, rel), os.path.join(checkout, rel))
        env = {**os.environ, "HOME": self.tmp.name}
        done = subprocess.run([os.path.join(checkout, "install.sh")], env=env, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        with open(self.manifest) as f:
            self.assertEqual(json.load(f)["path"], os.path.join(checkout, "lib", "native-host", "sidepanel-nmhost"))

    def test_bad_flag(self):
        self.assertEqual(self.run_install("--bogus").returncode, 2)
        self.assertFalse(os.path.exists(self.manifest))


if __name__ == "__main__":
    unittest.main()
