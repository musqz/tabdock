"""The extension manifest, its consistency with the rest of the project, and the xpi build."""
import hashlib
import json
import os
import struct
import subprocess
import tempfile
import unittest
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
EXT = os.path.join(ROOT, "extension")
BUILD = os.path.join(ROOT, "packaging", "build-extension.sh")


def read(path):
    with open(path) as f:
        return f.read()


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    assert head[:8] == b"\x89PNG\r\n\x1a\n", f"{path} is not a PNG"
    return struct.unpack(">II", head[16:24])


class ManifestTest(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads(read(os.path.join(EXT, "manifest.json")))

    def test_version_matches_the_project_version(self):
        self.assertEqual(self.manifest["version"], read(os.path.join(ROOT, "VERSION")).strip())

    def test_gecko_id_matches_the_native_messaging_manifest(self):
        template = json.loads(read(os.path.join(ROOT, "configs", "openbox_sidepanel.json.in")))
        self.assertEqual(template["allowed_extensions"], [self.manifest["browser_specific_settings"]["gecko"]["id"]])

    def test_permissions_stay_minimal(self):
        self.assertEqual(
            sorted(self.manifest["permissions"]),
            # storage: the container order and the workspaces; tabHide: a workspace hides the others' tabs;
            # sessions: which workspace a tab is in, and which one a window shows, across browser restarts
            ["contextualIdentities", "cookies", "nativeMessaging", "sessions", "storage", "tabHide", "tabs"],
        )

    def test_amo_requirements(self):
        gecko = self.manifest["browser_specific_settings"]["gecko"]
        self.assertEqual(gecko["data_collection_permissions"], {"required": ["none"]})  # nothing collected
        self.assertIn("strict_min_version", gecko)
        self.assertLessEqual(len(self.manifest["description"]), 132)  # AMO's limit

    def test_icons_exist_with_the_declared_sizes(self):
        for size, rel in self.manifest["icons"].items():
            self.assertEqual(png_size(os.path.join(EXT, rel)), (int(size), int(size)), rel)

    def test_workspace_shortcuts_are_changeable_keys_that_do_not_collide(self):
        commands = self.manifest["commands"]
        self.assertEqual(list(commands), ["next-workspace", "previous-workspace", *(f"workspace-{n}" for n in range(1, 10))])
        keys = [c["suggested_key"]["default"] for c in commands.values()]
        self.assertEqual(len(set(keys)), len(keys))
        for key in keys:
            # Ctrl+Alt+arrows switch desktops in Openbox's default rc.xml, so they would never reach the browser
            self.assertTrue(key.startswith("Ctrl+Alt+"), key)
            self.assertNotIn(key.split("+")[-1], ("Left", "Right", "Up", "Down"))
        self.assertTrue(all(c["description"] for c in commands.values()))  # what about:addons lists them by
        background = read(os.path.join(EXT, "background.js"))
        self.assertIn('/^workspace-([1-9])$/', background)  # the names the extension answers to
        self.assertIn('"next-workspace"', background)
        self.assertIn('"previous-workspace"', background)

    def test_background_script_exists(self):
        for rel in self.manifest["background"]["scripts"]:
            self.assertTrue(os.path.isfile(os.path.join(EXT, rel)), rel)


class BuildTest(unittest.TestCase):
    def build(self, out_dir):
        done = subprocess.run([BUILD], env={**os.environ, "OUT_DIR": out_dir}, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        return os.path.join(out_dir, f"tabdock-{read(os.path.join(ROOT, 'VERSION')).strip()}.xpi")

    def test_xpi_holds_exactly_what_the_manifest_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            xpi = self.build(tmp)
            with zipfile.ZipFile(xpi) as z:
                self.assertIsNone(z.testzip())
                self.assertEqual(
                    sorted(z.namelist()), ["background.js", "icons/icon-48.png", "icons/icon-96.png", "manifest.json"]
                )  # manifest at the archive root, no stray files (icon.svg source stays out)
                self.assertEqual(json.loads(z.read("manifest.json"))["name"], "Tabdock")

    def test_build_is_reproducible(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            first, second = self.build(a), self.build(b)
            digests = []
            for path in (first, second):
                with open(path, "rb") as f:
                    digests.append(hashlib.sha256(f.read()).hexdigest())
            self.assertEqual(digests[0], digests[1])


if __name__ == "__main__":
    unittest.main()
