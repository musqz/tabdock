#!/usr/bin/env python3
"""End-to-end check with a real headless Firefox (slow, needs /usr/bin/firefox; not part of discovery).

Scratch profile + throwaway $HOME, so your real profile, ~/.local and native-messaging dir are
untouched. It exercises what ships: install.sh puts the program into the scratch $HOME and the
panel runs from that installed copy; packaging/build-extension.sh builds the .xpi, which is
installed as a temporary add-on through Marionette. Then, against a real `sidepanel --debug`:
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


def last_snapshot(text):
    """The last snapshot in the panel's console output (from its final '== ' header)."""
    return text[text.rfind("== "):]


def tab_order(snapshot):
    """Tab ids in the order the console prints them (tab lines end with ' [id]')."""
    return [int(i) for i in re.findall(r"\[(\d+)\]$", snapshot, re.M)]


def sections(snapshot):
    """[(name, cookieStoreId)] in display order; section lines read '[name] (count) cookieStoreId'."""
    return re.findall(r"^\[(.+?)\] \(\d+\) (\S+)$", snapshot, re.M)


def section_order(snapshot):
    return [name for name, _ in sections(snapshot)]


def eventually(fn, what, timeout=TIMEOUT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if fn():
            return
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for: {what}")


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
    installed = os.path.join(env["HOME"], ".local", "bin", "sidepanel")  # the copy install.sh made
    proc = subprocess.Popen(
        [installed, "--debug"],
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

        with open(os.path.join(ROOT, "VERSION")) as f:
            version = f.read().strip()
        subprocess.run([os.path.join(ROOT, "packaging", "build-extension.sh")], env={**env, "OUT_DIR": tmp},
                       check=True, capture_output=True)
        xpi = os.path.join(tmp, f"openbox-sidepanel-{version}.xpi")

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

        # -- reordering, in the real browser: tabs.move and the stored container order --------------
        for title in ("tab-c", "tab-d"):
            handle = m.call("WebDriver:NewWindow", {"type": "tab", "focus": True})["handle"]
            m.call("WebDriver:SwitchToWindow", {"handle": handle})
            m.call("WebDriver:Navigate", {"url": f"data:text/html,<title>{title}</title>"})
        eventually(lambda: "tab-d [" in out.text, "the extra tabs")
        time.sleep(0.5)
        before = tab_order(last_snapshot(out.text))
        assert len(before) >= 4, before
        last = before[-1]  # whichever tab this browser puts last (Zen opens new tabs at the front)

        panel.stdin.write(f"move {last} 0\n")
        panel.stdin.flush()
        eventually(lambda: tab_order(last_snapshot(out.text))[0] == last, "the last tab moved to the front")
        assert tab_order(last_snapshot(out.text)) == [last] + before[:-1], tab_order(last_snapshot(out.text))
        print("OK move_tab: tabs.move put the tab first in the real tab strip")

        # The containers this browser really has (FireDragon and Waterfox ship other defaults than Firefox).
        original = sections(last_snapshot(out.text))
        containers = [s for s in original if s[1] != "firefox-default"]
        assert len(containers) >= 2, f"need two containers to reorder, got {original}"
        first_id, last_id = containers[0][1], containers[-1][1]
        wanted_ids = [last_id, first_id] + [i for _, i in containers if i not in (first_id, last_id)]
        by_id = dict((i, n) for n, i in original)
        wanted = [n for n, i in original if i == "firefox-default"] + [by_id[i] for i in wanted_ids]
        panel.stdin.write(f"order {last_id},{first_id}\n")  # the last container first, then the first
        panel.stdin.flush()
        eventually(lambda: section_order(last_snapshot(out.text)) == wanted, f"the container order {wanted}")
        print(f"OK set_container_order: {by_id[last_id]} now precedes {by_id[first_id]}, stored by the extension")

        panel.terminate()
        panel.wait(timeout=TIMEOUT)
        panel, out = start_panel(env)
        procs.append(panel)
        out.wait_for(r"== \S+ .* window \d+ ==")
        out.wait_for(r"marionette-tab \[\d+\]")
        eventually(lambda: section_order(last_snapshot(out.text)) == wanted, "the order after a panel restart")
        print("OK panel restart: relay reconnected, extension resynced, and the container order survived")
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
