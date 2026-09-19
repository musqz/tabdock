"""install.sh against a throwaway $HOME (never touches the real browser config or ~/.local)."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
INSTALL = os.path.join(ROOT, "install.sh")


def files_under(path):
    return sorted(os.path.join(d, f) for d, _, fs in os.walk(path) for f in fs)


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "home")
        os.makedirs(self.home)
        self.layout()

    def layout(self, prefix=None):
        self.prefix = prefix or os.path.join(self.home, ".local")
        self.share = os.path.join(self.prefix, "share", "openbox-sidepanel")
        self.bin = os.path.join(self.prefix, "bin", "sidepanel")
        self.relay = os.path.join(self.share, "lib", "native-host", "sidepanel-nmhost")
        self.manifest = os.path.join(self.home, ".mozilla", "native-messaging-hosts", "openbox_sidepanel.json")

    def run_install(self, *args, **env):
        env = {**os.environ, "HOME": self.home, "PATH": os.path.dirname(self.bin) + ":" + os.environ["PATH"], **env}
        return subprocess.run([INSTALL, *args], env=env, capture_output=True, text=True)

    def test_installs_a_self_contained_working_copy(self):
        done = self.run_install()
        self.assertEqual(done.returncode, 0, done.stderr)
        for rel in ("sidepanel", "VERSION", "lib/sidepanel/app.py", "lib/sidepanel/dock.py", "configs/config.toml",
                    "configs/picom-sidepanel.conf", "lib/native-host/sidepanel-nmhost"):
            self.assertTrue(os.path.isfile(os.path.join(self.share, rel)), rel)
        self.assertEqual(os.readlink(self.bin), os.path.join(self.share, "sidepanel"))
        self.assertTrue(os.access(self.relay, os.X_OK))
        with open(self.manifest) as f:
            manifest = json.load(f)
        self.assertEqual(manifest["path"], self.relay)  # the installed relay, not this checkout
        self.assertEqual(manifest["allowed_extensions"], ["openbox-sidepanel@musqz.local"])
        with open(os.path.join(ROOT, "VERSION")) as f:
            version = f.read().strip()
        ran = subprocess.run([self.bin, "--version"], capture_output=True, text=True)
        self.assertEqual(ran.stdout.strip(), f"sidepanel {version}")  # it runs from the installed copy
        self.assertIn("verified", done.stdout)
        self.assertIn("(sleep 5.0s &&", done.stdout)  # the autostart line is printed, not applied

    def test_reinstall_reports_unchanged_then_updated(self):
        self.run_install()
        again = self.run_install()
        self.assertEqual(again.returncode, 0)
        actions = again.stdout.split("Next:")[0]
        self.assertNotRegex(actions, r"(?m)^(installed|updated)\b")  # nothing new on a second run
        self.assertIn("unchanged", actions)
        with open(os.path.join(self.share, "lib", "sidepanel", "app.py"), "a") as f:
            f.write("# local edit\n")
        third = self.run_install()
        self.assertRegex(third.stdout, r"updated\s+\S+app\.py")

    def test_stale_files_from_an_older_version_are_removed(self):
        self.run_install()
        stale = os.path.join(self.share, "lib", "sidepanel", "gone.py")
        with open(stale, "w") as f:
            f.write("old\n")
        with open(os.path.join(self.share, ".installed"), "a") as f:
            f.write(stale + "\n")
        done = self.run_install()
        self.assertFalse(os.path.exists(stale))
        self.assertIn("removed", done.stdout)

    def test_uninstall_leaves_nothing_behind(self):
        self.run_install()
        subprocess.run([self.bin, "--version"], capture_output=True)  # the installed copy writes __pycache__
        removed = self.run_install("--uninstall")
        self.assertEqual(removed.returncode, 0, removed.stderr)
        self.assertFalse(os.path.exists(self.share))
        self.assertFalse(os.path.lexists(self.bin))
        self.assertFalse(os.path.exists(self.manifest))
        self.assertEqual(files_under(self.home), [])
        again = self.run_install("--uninstall")  # idempotent
        self.assertEqual(again.returncode, 0)

    def test_uninstall_keeps_a_link_that_now_points_elsewhere(self):
        self.run_install()
        elsewhere = os.path.join(self.tmp.name, "other-build", "sidepanel")
        os.makedirs(os.path.dirname(elsewhere))
        with open(elsewhere, "w") as f:
            f.write("#!/bin/sh\n")
        os.remove(self.bin)
        os.symlink(elsewhere, self.bin)  # the user repointed the command, e.g. to a dev checkout
        removed = self.run_install("--uninstall")
        self.assertEqual(removed.returncode, 0, removed.stderr)
        self.assertEqual(os.readlink(self.bin), elsewhere)  # not ours any more: left alone
        self.assertIn("skipped", removed.stdout)
        self.assertFalse(os.path.exists(self.share))  # everything else was still removed

    def test_uninstall_removes_the_manifest_even_without_a_receipt(self):
        self.run_install()
        os.remove(os.path.join(self.share, ".installed"))
        removed = self.run_install("--uninstall")
        self.assertEqual(removed.returncode, 0, removed.stderr)
        self.assertFalse(os.path.exists(self.manifest))  # it pointed at this install's relay

    def test_uninstall_with_another_prefix_keeps_the_manifest_and_says_why(self):
        self.run_install()
        other = os.path.join(self.tmp.name, "pfx")
        removed = self.run_install("--uninstall", PREFIX=other)
        self.assertEqual(removed.returncode, 0)
        self.assertTrue(os.path.exists(self.manifest))  # belongs to the install under ~/.local
        self.assertIn("kept", removed.stderr)
        self.assertIn(self.relay, removed.stderr)  # tells where it points, so the PREFIX can be found
        self.assertTrue(os.path.isfile(os.path.join(self.share, "sidepanel")))  # the real install is untouched

    def test_verifying_the_install_leaves_no_bytecode(self):
        self.run_install()
        stray = [d for d, _, _ in os.walk(self.share) if os.path.basename(d) == "__pycache__"]
        self.assertEqual(stray, [])

    def test_whole_package_tree_is_installed(self):
        # a checkout with a subpackage and a non-.py data file the installer has never heard of
        checkout = os.path.join(self.tmp.name, "checkout")
        for rel in ("install.sh", "sidepanel", "VERSION"):
            os.makedirs(os.path.dirname(os.path.join(checkout, rel)), exist_ok=True)
            shutil.copy2(os.path.join(ROOT, rel), os.path.join(checkout, rel))
        for sub in ("lib", "configs"):
            shutil.copytree(os.path.join(ROOT, sub), os.path.join(checkout, sub), ignore=shutil.ignore_patterns("__pycache__"))
        os.makedirs(os.path.join(checkout, "lib", "sidepanel", "newpkg"))
        for rel in ("newpkg/__init__.py", "newpkg/data.css"):
            with open(os.path.join(checkout, "lib", "sidepanel", rel), "w") as f:
                f.write("x\n")
        env = {**os.environ, "HOME": self.home, "PATH": os.path.dirname(self.bin) + ":" + os.environ["PATH"]}
        done = subprocess.run([os.path.join(checkout, "install.sh")], env=env, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        for rel in ("newpkg/__init__.py", "newpkg/data.css"):
            self.assertTrue(os.path.isfile(os.path.join(self.share, "lib", "sidepanel", rel)), rel)

    def test_refuses_to_replace_a_foreign_command(self):
        os.makedirs(os.path.dirname(self.bin))
        with open(self.bin, "w") as f:
            f.write("#!/bin/sh\necho mine\n")
        done = self.run_install()
        self.assertEqual(done.returncode, 1)
        self.assertIn("already exists", done.stderr)
        with open(self.bin) as f:
            self.assertIn("echo mine", f.read())

    def test_ampersand_in_the_install_path(self):
        # bash 5.2 expands '&' in a pattern-substitution replacement unless patsub_replacement is off
        self.home = os.path.join(self.tmp.name, "a&b")
        os.makedirs(self.home)
        self.layout()
        done = self.run_install()
        self.assertEqual(done.returncode, 0, done.stderr)
        with open(self.manifest) as f:
            self.assertEqual(json.load(f)["path"], self.relay)

    def test_prefix_override(self):
        self.layout(prefix=os.path.join(self.tmp.name, "pfx"))
        done = self.run_install(PREFIX=self.prefix)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(os.path.isfile(os.path.join(self.share, "sidepanel")))
        with open(self.manifest) as f:  # manifests are per-user whatever the prefix
            self.assertEqual(json.load(f)["path"], self.relay)

    def test_bad_flag(self):
        self.assertEqual(self.run_install("--bogus").returncode, 2)
        self.assertFalse(os.path.exists(self.share))


if __name__ == "__main__":
    unittest.main()
