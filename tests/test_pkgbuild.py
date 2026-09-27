"""packaging/PKGBUILD's prepare() and package(), run the way makepkg runs them, against this checkout."""
import json
import os
import subprocess
import tempfile
import unittest
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PKGBUILD = os.path.join(ROOT, "packaging", "PKGBUILD")
SHARE = "/usr/share/tabdock"

with open(os.path.join(ROOT, "VERSION")) as f:
    VERSION = f.read().strip()


def files_under(path):
    return sorted(os.path.relpath(os.path.join(d, f), path) for d, _, fs in os.walk(path) for f in fs)


class PkgbuildTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.srcdir = os.path.join(tmp.name, "src")
        self.pkgdir = os.path.join(tmp.name, "pkg")
        os.makedirs(self.srcdir)

    def sources(self, version=VERSION, signed=True, stale=False):
        """What makepkg leaves in $srcdir: the unpacked tag tarball (this checkout) and the release .xpi,
        built by packaging/build-extension.sh and "signed" by adding Mozilla's signature file to it."""
        os.symlink(ROOT, os.path.join(self.srcdir, f"tabdock-{version}"))
        built = os.path.join(self.srcdir, "built")
        subprocess.run([os.path.join(ROOT, "packaging", "build-extension.sh")], env={**os.environ, "OUT_DIR": built},
                       check=True, capture_output=True)
        [name] = os.listdir(built)
        with zipfile.ZipFile(os.path.join(built, name)) as unsigned, \
                zipfile.ZipFile(os.path.join(self.srcdir, f"tabdock-{version}.xpi"), "w") as z:
            for item in unsigned.namelist():
                data = unsigned.read(item)
                if stale and item == "background.js":
                    data += b"\n// signed from older code\n"
                z.writestr(item, data)
            if signed:
                z.writestr("META-INF/mozilla.rsa", "signature")

    def run_function(self, name, version=VERSION):
        # makepkg sources the PKGBUILD and calls each function from $srcdir
        script = f'source "$1"; pkgver="$2"; srcdir="$3"; pkgdir="$4"; cd "$srcdir"; umask 022; {name}'
        return subprocess.run(["bash", "-euo", "pipefail", "-c", script, "bash",
                               PKGBUILD, version, self.srcdir, self.pkgdir],
                              capture_output=True, text=True)

    def path(self, abs_path):
        return os.path.join(self.pkgdir, abs_path.lstrip("/"))

    def test_prepare_accepts_a_signed_extension(self):
        self.sources()
        done = self.run_function("prepare")
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_prepare_refuses_an_unsigned_extension(self):
        self.sources(signed=False)
        done = self.run_function("prepare")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("not signed", done.stderr)

    def test_prepare_refuses_an_extension_signed_from_other_code(self):
        # 0.3.0 was signed before the new-tab button reached background.js; its .xpi must not ship with 0.3.0's sources
        self.sources(stale=True)
        done = self.run_function("prepare")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("differs from extension/", done.stderr)
        self.assertIn("background.js", done.stderr)

    def test_prepare_refuses_sources_whose_version_differs(self):
        self.sources(version="9.9.9")
        done = self.run_function("prepare", version="9.9.9")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn(f"says {VERSION}", done.stderr)

    def test_package_ships_the_install_sh_layout_under_usr(self):
        self.sources()
        done = self.run_function("package")
        self.assertEqual(done.returncode, 0, done.stderr)
        share = self.path(SHARE)
        for rel in ("tabdock", "VERSION", "configs/config.toml", "icon.png", "tabdock.xpi"):
            self.assertTrue(os.path.isfile(os.path.join(share, rel)), rel)
        self.assertTrue(os.access(os.path.join(share, "tabdock"), os.X_OK))
        self.assertEqual(os.readlink(self.path("/usr/bin/tabdock")), f"{SHARE}/tabdock")
        # the whole panel package, so a new module is never left out; no bytecode
        shipped = files_under(os.path.join(share, "lib", "tabdock"))
        expected = [f for f in files_under(os.path.join(ROOT, "lib", "tabdock")) if "__pycache__" not in f]
        self.assertEqual(shipped, expected)
        self.assertTrue(os.path.isfile(self.path("/usr/share/licenses/tabdock/LICENSE")))

    def test_the_packaged_panel_names_the_packaged_extension(self):
        self.sources()
        self.assertEqual(self.run_function("package").returncode, 0)
        lib = os.path.join(self.path(SHARE), "lib")
        ran = subprocess.run(["python3", "-c", "import sys; sys.path.insert(0, sys.argv[1]); "
                              "from tabdock.model import waiting_text; print(waiting_text())", lib],
                             capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertTrue(ran.stdout.strip().endswith(self.path(f"{SHARE}/tabdock.xpi")))

    def test_manifest_points_at_the_packaged_relay(self):
        self.sources()
        self.assertEqual(self.run_function("package").returncode, 0)
        with open(self.path("/usr/lib/mozilla/native-messaging-hosts/openbox_sidepanel.json")) as f:
            manifest = json.load(f)
        relay = f"{SHARE}/lib/native-host/tabdock-nmhost"
        self.assertEqual(manifest["path"], relay)
        self.assertTrue(os.access(self.path(relay), os.X_OK))
        # the relay starts the panel at ../../tabdock from its own location
        self.assertTrue(os.path.isfile(os.path.normpath(os.path.join(self.path(relay), "..", "..", "..", "tabdock"))))
        self.assertEqual(manifest["allowed_extensions"], ["openbox-sidepanel@musqz.local"])

    def test_menu_entry_runs_the_packaged_launcher(self):
        self.sources()
        self.assertEqual(self.run_function("package").returncode, 0)
        with open(self.path("/usr/share/applications/tabdock.desktop")) as f:
            entry = f.read()
        self.assertIn("Exec=/usr/bin/tabdock\n", entry)
        self.assertIn(f"Icon={SHARE}/icon.png\n", entry)
        self.assertNotIn("@", entry)


if __name__ == "__main__":
    unittest.main()
