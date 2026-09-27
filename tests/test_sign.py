"""packaging/sign-extension.sh: credential handling and the whole pipeline, with a fake npx standing in for
web-ext so Mozilla is never contacted."""
import os
import pty
import select
import shutil
import stat
import subprocess
import tempfile
import time
import unittest
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPT = os.path.join(ROOT, "packaging", "sign-extension.sh")
ISSUER = "user:12345678:123"
SECRET = "3f9c1a7e5b2d84606a1c9e0f7d3b5a2c8e4f61a09d7b3c5e2f8a4b6d1c0e9f73"  # fake, 64 characters
assert len(SECRET) == 64
with open(os.path.join(ROOT, "VERSION")) as f:
    VERSION = f.read().strip()

FAKE_NPX = r"""#!/usr/bin/env bash
# stands in for `npx --yes web-ext <lint|sign> ...`
log="${FAKE_NPX_LOG:?}"
printf 'argv: %s\n' "$*" >> "$log"
if [[ -n ${WEB_EXT_API_KEY:-} && ${#WEB_EXT_API_SECRET} -eq 64 ]]; then echo "credentials in environment" >> "$log"; fi
case " $* " in
    *" lint "*) exit "${FAKE_LINT_STATUS:-0}" ;;
    *" sign "*)
        [[ ${FAKE_SIGN_STATUS:-0} -eq 0 ]] || { echo "WebExtError: Upload failed: 401" >&2; exit 1; }
        dir="" prev=""
        for a in "$@"; do [[ $prev == --artifacts-dir ]] && dir=$a; prev=$a; done
        mkdir -p "$dir"
        python3 - "$dir/${FAKE_SIGNED_NAME:-ab12cd34ef56ab78cd90-$FAKE_VERSION.xpi}" <<'PY'
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1], "w") as z:
    z.writestr("manifest.json", "{}")
    z.writestr("META-INF/mozilla.rsa", "signature")
PY
        echo "Signed xpi downloaded" ;;
esac
"""


def make_zip(path, signed):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("manifest.json", "{}")
        if signed:
            z.writestr("META-INF/mozilla.rsa", "signature")


class SignScriptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.artifacts = os.path.join(self.tmp.name, "artifacts")
        self.config = os.path.join(self.tmp.name, "config")
        self.saved = os.path.join(self.config, "tabdock", "amo-credentials")
        self.log = os.path.join(self.tmp.name, "npx.log")
        bindir = os.path.join(self.tmp.name, "bin")
        os.makedirs(bindir)
        with open(os.path.join(bindir, "npx"), "w") as f:
            f.write(FAKE_NPX)
        os.chmod(os.path.join(bindir, "npx"), 0o755)
        self.env = {
            **os.environ,
            "PATH": bindir + ":" + os.environ["PATH"],
            "FAKE_NPX_LOG": self.log,
            "FAKE_VERSION": VERSION,
            "ARTIFACTS_DIR": self.artifacts,
            "XDG_CONFIG_HOME": self.config,
        }
        self.env.pop("WEB_EXT_API_KEY", None)
        self.env.pop("WEB_EXT_API_SECRET", None)

    def run_script(self, *args, stdin="", dry=False, **fake):
        env = {**self.env, **{k: str(v) for k, v in fake.items()}}
        return subprocess.run([SCRIPT, *(["--dry-run"] if dry else []), *args], input=stdin,
                              capture_output=True, text=True, env=env)

    def out(self, done):
        return done.stdout + done.stderr

    def npx_log(self):
        try:
            with open(self.log) as f:
                return f.read()
        except FileNotFoundError:
            return ""

    # -- credentials: shape checks, never echoed --------------------------------------------------

    def test_good_credentials_pass_and_nothing_typed_is_printed_back(self):
        done = self.run_script(stdin=f"{ISSUER}\n{SECRET}\n", dry=True)
        self.assertEqual(done.returncode, 0, self.out(done))
        self.assertIn("credentials look right", done.stdout)
        self.assertIn("dry run", done.stdout)
        self.assertNotIn(SECRET, self.out(done))
        self.assertNotIn("12345678", self.out(done))

    def test_an_issuer_without_user_is_explained(self):
        done = self.run_script(stdin=f"12345678:123\n{SECRET}\n", dry=True)  # the mistake made in real life
        self.assertEqual(done.returncode, 2)
        self.assertIn("does not start with user:", done.stderr)
        self.assertNotIn(SECRET, self.out(done))

    def test_swapped_values_are_recognised_and_never_echoed(self):
        done = self.run_script(stdin=f"{SECRET}\n{ISSUER}\n", dry=True)  # the secret pasted at the visible prompt
        self.assertEqual(done.returncode, 2)
        self.assertIn("swapped", done.stderr)
        self.assertNotIn(SECRET, self.out(done))  # the script must not print what you pasted
        done = self.run_script(stdin=f"{ISSUER}\n{ISSUER}\n", dry=True)  # the issuer at the secret prompt
        self.assertEqual(done.returncode, 2)
        self.assertIn("swapped", done.stderr)
        self.assertNotIn("12345678", self.out(done))

    def test_a_secret_of_the_wrong_length_reports_only_the_length(self):
        for secret in ("", SECRET[:-1], SECRET + "0", "x"):
            with self.subTest(length=len(secret)):
                done = self.run_script(stdin=f"{ISSUER}\n{secret}\n", dry=True)
                self.assertEqual(done.returncode, 2)
                self.assertIn(f"{len(secret)} characters long", done.stderr)
                if secret:
                    self.assertNotIn(secret, self.out(done))

    def test_copy_paste_debris_is_stripped(self):
        for issuer, secret in (
            (f"  {ISSUER}  ", f"{SECRET}\r"),  # spaces and a Windows line ending
            (f"'{ISSUER}'", f'"{SECRET}"'),  # quotes copied along
        ):
            with self.subTest(issuer=issuer):
                done = self.run_script(stdin=f"{issuer}\n{secret}\n", dry=True)
                self.assertEqual(done.returncode, 0, self.out(done))

    # -- the whole pipeline, with a fake web-ext ----------------------------------------------------

    def test_a_full_run_lints_then_signs_with_the_credentials_in_the_environment_only(self):
        done = self.run_script(stdin=f"{ISSUER}\n{SECRET}\n")
        self.assertEqual(done.returncode, 0, self.out(done))
        self.assertIn("signed and verified", done.stdout)
        signed = [f for f in os.listdir(self.artifacts) if f.endswith(f"-{VERSION}.xpi")]
        self.assertEqual(len(signed), 1)
        log = self.npx_log()
        self.assertLess(log.index(" lint "), log.index(" sign "))  # lint first
        self.assertIn("credentials in environment", log)  # the child got them...
        self.assertNotIn(SECRET, log)  # ...but never on a command line
        self.assertNotIn("12345678", log)
        self.assertNotIn(SECRET, self.out(done))

    def test_a_failing_lint_stops_before_anything_is_signed(self):
        done = self.run_script(stdin=f"{ISSUER}\n{SECRET}\n", FAKE_LINT_STATUS=1)
        self.assertNotEqual(done.returncode, 0)
        self.assertNotIn(" sign ", self.npx_log())
        self.assertFalse(os.path.exists(self.artifacts))

    def test_a_rejected_signing_saves_nothing(self):
        done = self.run_script("--save", stdin=f"{ISSUER}\n{SECRET}\n", FAKE_SIGN_STATUS=1)  # a 401 from Mozilla
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("401", done.stderr)
        self.assertFalse(os.path.exists(self.saved))  # wrong credentials are not remembered
        self.assertNotIn(SECRET, self.out(done))

    def test_save_keeps_a_private_file_only_after_signing_worked_and_later_runs_reuse_it(self):
        dry = self.run_script("--save", stdin=f"{ISSUER}\n{SECRET}\n", dry=True)
        self.assertEqual(dry.returncode, 0, self.out(dry))
        self.assertFalse(os.path.exists(self.saved))  # nothing proven yet
        done = self.run_script("--save", stdin=f"{ISSUER}\n{SECRET}\n")
        self.assertEqual(done.returncode, 0, self.out(done))
        self.assertEqual(stat.S_IMODE(os.stat(self.saved).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(self.saved)).st_mode), 0o700)
        self.assertTrue(self.saved.startswith(self.tmp.name))  # under the config dir, never inside the repo
        shutil.rmtree(self.artifacts)  # a signed file would (rightly) end the next run before it asks anything
        again = self.run_script(stdin="", dry=True)  # nothing to type
        self.assertEqual(again.returncode, 0, self.out(again))
        self.assertIn("saved in", again.stdout)
        self.assertNotIn(SECRET, self.out(again))

    def test_the_umask_of_saving_does_not_leak_into_the_rest_of_the_run(self):
        self.run_script("--save", stdin=f"{ISSUER}\n{SECRET}\n")
        mode = stat.S_IMODE(os.stat(os.path.join(self.artifacts, os.listdir(self.artifacts)[0])).st_mode)
        self.assertEqual(mode & 0o044, 0o044)  # the signed file is a normal readable file, not mode 600

    def test_forget_deletes_the_saved_credentials(self):
        self.run_script("--save", stdin=f"{ISSUER}\n{SECRET}\n")
        done = self.run_script("--forget")
        self.assertEqual(done.returncode, 0)
        self.assertFalse(os.path.exists(self.saved))
        self.assertEqual(self.run_script("--forget").returncode, 0)  # idempotent

    def write_saved(self, issuer, secret, mode=0o600):
        os.makedirs(os.path.dirname(self.saved), exist_ok=True)
        with open(self.saved, "w") as f:
            f.write(f"{issuer}\n{secret}\n")
        os.chmod(self.saved, mode)

    def test_saved_credentials_readable_by_others_are_refused(self):
        self.write_saved(ISSUER, SECRET, mode=0o644)
        done = self.run_script(dry=True)
        self.assertEqual(done.returncode, 1)
        self.assertIn("chmod 600", done.stderr)
        self.assertNotIn(SECRET, self.out(done))

    def test_bad_saved_credentials_name_their_file_and_the_way_out(self):
        self.write_saved("12345678:123", "not-the-secret")
        done = self.run_script(dry=True)
        self.assertEqual(done.returncode, 2)
        self.assertIn(self.saved, done.stderr)
        self.assertIn("--forget", done.stderr)

    def test_credentials_saved_before_the_rename_to_tabdock_are_still_used_and_forgotten(self):
        self.saved = os.path.join(self.config, "openbox-sidepanel", "amo-credentials")
        self.write_saved(ISSUER, SECRET)
        done = self.run_script(dry=True)
        self.assertEqual(done.returncode, 0, self.out(done))
        self.assertIn(f"saved in {self.saved}", done.stdout)
        self.assertEqual(self.run_script("--forget").returncode, 0)
        self.assertFalse(os.path.exists(self.saved))

    # -- already signed: decided by what is inside the file, not by its name ---------------------------

    def test_an_unsigned_file_never_counts_however_it_is_named(self):
        os.makedirs(self.artifacts)
        make_zip(os.path.join(self.artifacts, f"openbox-sidepanel-{VERSION}.xpi"), signed=False)
        make_zip(os.path.join(self.artifacts, f"ab12cd34ef56ab78cd90-{VERSION}.xpi"), signed=False)
        done = self.run_script(stdin=f"{ISSUER}\n{SECRET}\n", dry=True)
        self.assertIn("credentials look right", done.stdout)  # not "already signed"

    def test_a_signed_file_counts_whatever_it_is_named(self):
        os.makedirs(self.artifacts)
        make_zip(os.path.join(self.artifacts, f"openbox-sidepanel-{VERSION}.xpi"), signed=True)  # a slug-style name
        done = self.run_script(stdin="", dry=True)  # no credentials given, and none needed
        self.assertEqual(done.returncode, 0, self.out(done))
        self.assertIn("already signed", done.stdout)
        self.assertEqual(self.npx_log(), "")

    def test_signing_that_names_the_file_like_the_slug_is_still_found(self):
        done = self.run_script(stdin=f"{ISSUER}\n{SECRET}\n", FAKE_SIGNED_NAME=f"openbox-sidepanel-{VERSION}.xpi")
        self.assertEqual(done.returncode, 0, self.out(done))
        self.assertIn("signed and verified", done.stdout)

    # -- the terminal itself ----------------------------------------------------------------------

    def test_at_a_real_terminal_the_secret_is_typed_hidden_and_the_prompts_are_separate(self):
        master, slave = pty.openpty()
        proc = subprocess.Popen([SCRIPT, "--dry-run"], stdin=slave, stdout=slave, stderr=slave, env=self.env)
        os.close(slave)
        seen = b""

        def read_until(marker):
            nonlocal seen
            deadline = time.monotonic() + 10
            while marker not in seen:
                self.assertLess(time.monotonic(), deadline, f"never saw {marker!r} in {seen!r}")
                if select.select([master], [], [], 0.2)[0]:
                    try:
                        chunk = os.read(master, 4096)
                    except OSError:  # the child closed the terminal
                        break
                    seen += chunk

        read_until(b"JWT issuer")
        os.write(master, f"{ISSUER}\n".encode())  # typed visibly: the terminal echoes it
        read_until(b"JWT secret")  # a separate prompt, so a multi-line paste cannot be swallowed by the wrong one
        os.write(master, f"{SECRET}\n".encode())
        read_until(b"dry run")
        proc.wait(timeout=10)
        os.close(master)
        text = seen.decode(errors="replace")
        self.assertEqual(proc.returncode, 0, text)
        self.assertIn(ISSUER, text)
        self.assertNotIn(SECRET, text)  # the terminal never echoed the secret
        self.assertIn("credentials look right", text)

    def test_help_prints_the_usage_and_nothing_else(self):
        done = self.run_script("--help")
        self.assertEqual(done.returncode, 0)
        self.assertIn("--dry-run", done.stdout)
        self.assertNotIn("set -euo pipefail", done.stdout)  # the header comment ends where the code starts

    def test_bad_flag(self):
        done = subprocess.run([SCRIPT, "--bogus"], capture_output=True, text=True, env=self.env)
        self.assertEqual(done.returncode, 2)


if __name__ == "__main__":
    unittest.main()
