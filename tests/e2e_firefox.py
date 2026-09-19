#!/usr/bin/env python3
"""End-to-end check with a real headless Firefox (slow, needs /usr/bin/firefox; not part of discovery).

Scratch profile + throwaway $HOME, so your real profile and native-messaging dir are untouched.
Installs extension/ as a temporary add-on through Marionette and checks, against
a real `sidepanel --debug` process:
  browser -> panel : tabs appear, new tabs show up, panel restart triggers a resync
  panel -> browser : `activate <id>` switches the active tab

    python3 tests/e2e_firefox.py [--firefox /usr/bin/firefox]
"""
import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TIMEOUT = 60


class Output:
    """Collects a process's stdout in the background so we can wait for text."""

    def __init__(self, proc):
        self.text = ""
        self.lock = threading.Lock()
        threading.Thread(target=self._pump, args=(proc,), daemon=True).start()

    def _pump(self, proc):
        for line in proc.stdout:
            with self.lock:
                self.text += line

    def wait_for(self, pattern, since=0, timeout=TIMEOUT):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.lock:
                m = re.search(pattern, self.text[since:])
                if m:
                    return m
            time.sleep(0.1)
        with self.lock:
            raise AssertionError(f"timed out waiting for {pattern!r}; output was:\n{self.text[since:]}")

    def mark(self):
        with self.lock:
            return len(self.text)


class Marionette:
    def __init__(self, port):
        deadline = time.monotonic() + TIMEOUT
        while True:
            try:
                self.sock = socket.create_connection(("127.0.0.1", port))
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.5)
        self.buf = b""
        self.msg_id = 0
        self._recv()  # handshake

    def _recv(self):
        while b":" not in self.buf:
            self.buf += self.sock.recv(65536)
        head, rest = self.buf.split(b":", 1)
        size = int(head)
        while len(rest) < size:
            rest += self.sock.recv(65536)
        self.buf = rest[size:]
        return json.loads(rest[:size])

    def call(self, command, params=None):
        self.msg_id += 1
        data = json.dumps([0, self.msg_id, command, params or {}]).encode()
        self.sock.sendall(str(len(data)).encode() + b":" + data)
        while True:
            msg = self._recv()
            if msg[0] == 1 and msg[1] == self.msg_id:
                if msg[2]:
                    raise RuntimeError(f"{command}: {msg[2]}")
                return msg[3]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_panel(env):
    proc = subprocess.Popen(
        [os.path.join(ROOT, "sidepanel"), "--debug"],
        env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1,
    )
    return proc, Output(proc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--firefox", default="/usr/bin/firefox")
    args = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="sidepanel-e2e-")
    procs = []
    try:
        home = os.path.join(tmp, "home")
        profile = os.path.join(tmp, "profile")
        os.makedirs(home)
        os.makedirs(profile)
        env = {**os.environ, "HOME": home, "SIDEPANEL_SOCKET": os.path.join(tmp, "sp.sock")}
        subprocess.run([os.path.join(ROOT, "install.sh")], env=env, check=True, capture_output=True)

        port = free_port()
        with open(os.path.join(profile, "user.js"), "w") as f:
            f.write(
                f'user_pref("marionette.port", {port});\n'
                'user_pref("privacy.userContext.enabled", true);\n'
                'user_pref("browser.shell.checkDefaultBrowser", false);\n'
                'user_pref("datareporting.policy.dataSubmissionEnabled", false);\n'
                'user_pref("browser.aboutwelcome.enabled", false);\n'
            )

        xpi = os.path.join(tmp, "sidepanel.xpi")
        with zipfile.ZipFile(xpi, "w") as z:
            for name in ("manifest.json", "background.js"):
                z.write(os.path.join(ROOT, "extension", name), name)

        panel, out = start_panel(env)
        procs.append(panel)
        deadline = time.monotonic() + TIMEOUT
        while not os.path.exists(env["SIDEPANEL_SOCKET"]):
            assert time.monotonic() < deadline, "panel socket never appeared"
            time.sleep(0.1)

        ff = subprocess.Popen(
            [args.firefox, "--headless", "--no-remote", "--marionette", "--profile", profile, "about:blank"],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        procs.append(ff)
        m = Marionette(port)
        m.call("WebDriver:NewSession", {"capabilities": {}})
        m.call("Addon:Install", {"path": xpi, "temporary": True})
        print("extension installed; waiting for first snapshot ...")

        first = out.wait_for(r"== (\S+) (\S+) \(pid (\d+)\) window \d+ ==")
        assert int(first.group(3)) == ff.pid, f"browserPid {first.group(3)} != browser pid {ff.pid}"
        out.wait_for(r"New Tab \[(\d+)\]")
        print(f"OK browser->panel: hello ({first.group(1)} {first.group(2)}, pid matches) + snapshot")
        out.wait_for(r"\[Personal\]")
        print("OK containers listed")

        mark = out.mark()
        handle = m.call("WebDriver:NewWindow", {"type": "tab", "focus": True})["handle"]
        m.call("WebDriver:SwitchToWindow", {"handle": handle})
        m.call("WebDriver:Navigate", {"url": "data:text/html,<title>marionette-tab</title>"})
        out.wait_for(r"\* marionette-tab \[\d+\]", since=mark)
        print("OK new tab appears, marked active")

        blank_id = re.findall(r"New Tab \[(\d+)\]", out.text[mark:])[-1]
        mark = out.mark()
        panel.stdin.write(f"activate {blank_id}\n")
        panel.stdin.flush()
        out.wait_for(rf"\* New Tab \[{blank_id}\]", since=mark)
        print("OK panel->browser: activate_tab switched the active tab")

        panel.terminate()
        panel.wait(timeout=TIMEOUT)
        panel, out = start_panel(env)
        procs.append(panel)
        out.wait_for(r"== \S+ .* window \d+ ==")
        out.wait_for(r"marionette-tab \[\d+\]")
        print("OK panel restart: relay reconnected and extension resynced")
        print("ALL OK")
        return 0
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
