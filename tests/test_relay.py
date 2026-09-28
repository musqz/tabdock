"""Protocol tests without a browser: this test plays the extension (native-messaging
frames on the relay's stdio) and, in the first class, also the panel (Unix socket).
"""
import json
import os
import select
import shlex
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
RELAY = os.path.join(ROOT, "lib", "native-host", "tabdock-nmhost")
PANEL = os.path.join(ROOT, "tabdock")
TIMEOUT = 10


def read_exact(fd, n):
    deadline = time.monotonic() + TIMEOUT
    data = b""
    while len(data) < n:
        left = deadline - time.monotonic()
        if left <= 0 or not select.select([fd], [], [], left)[0]:
            raise TimeoutError(f"wanted {n} bytes, got {len(data)}")
        chunk = os.read(fd, n - len(data))
        if not chunk:
            raise EOFError("relay closed stdout")
        data += chunk
    return data


def read_frame(proc):
    fd = proc.stdout.fileno()
    (size,) = struct.unpack("=I", read_exact(fd, 4))
    return json.loads(read_exact(fd, size))


def write_frame(proc, obj):
    data = json.dumps(obj).encode()
    proc.stdin.write(struct.pack("=I", len(data)) + data)
    proc.stdin.flush()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sock_path = os.path.join(self.tmp.name, "sp.sock")
        # never start a real panel from a test (it would open dock windows on your desktop)
        self.env = {**os.environ, "TABDOCK_SOCKET": self.sock_path, "TABDOCK_NO_LAUNCH": "1"}
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
            p.wait()
            for f in (p.stdin, p.stdout):
                if f:
                    f.close()
        self.tmp.cleanup()

    def spawn(self, cmd, env=None, **kw):
        p = subprocess.Popen(cmd, env=env or self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0, **kw)
        self.procs.append(p)
        return p


class RelayTest(Base):
    def test_relay_roundtrip_and_reconnect(self):
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(self.sock_path)
        srv.listen(1)
        srv.settimeout(TIMEOUT)
        self.addCleanup(srv.close)

        relay = self.spawn([RELAY])
        conn, _ = srv.accept()
        self.assertEqual(read_frame(relay), {"type": "resync"})

        write_frame(relay, {"type": "hello", "browser": "Firefox", "version": "156.0"})
        line = conn.makefile("rb").readline()
        hello = json.loads(line)
        self.assertEqual(hello["browser"], "Firefox")
        self.assertEqual(hello["browserPid"], os.getpid())  # relay's parent = this process

        conn.sendall(b'{"type":"activate_tab","tabId":7,"windowId":2}\n')
        self.assertEqual(read_frame(relay), {"type": "activate_tab", "tabId": 7, "windowId": 2})

        # panel restarts: relay reconnects and asks for a resync again
        conn.close()
        self.assertEqual(read_frame(relay), {"type": "panel_disconnected"})
        conn2, _ = srv.accept()
        self.addCleanup(conn2.close)
        self.assertEqual(read_frame(relay), {"type": "resync"})

        # malformed input from either side must not kill the relay
        conn2.sendall(b"this is not json\n[1, 2]\n")
        conn2.sendall(b'{"type":"activate_tab","tabId":8,"windowId":2}\n')
        self.assertEqual(read_frame(relay), {"type": "activate_tab", "tabId": 8, "windowId": 2})
        relay.stdin.write(struct.pack("=I", 5) + b"{oops")
        relay.stdin.flush()
        write_frame(relay, {"type": "state", "windows": []})
        self.assertEqual(json.loads(conn2.makefile("rb").readline())["type"], "state")

        # browser goes away: relay exits
        relay.stdin.close()
        self.assertEqual(relay.wait(timeout=TIMEOUT), 0)

    def test_relay_waits_for_panel(self):
        relay = self.spawn([RELAY])
        write_frame(relay, {"type": "state"})  # nobody listening: dropped, no crash
        time.sleep(0.3)
        self.assertIsNone(relay.poll())

        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(self.sock_path)
        srv.listen(1)
        srv.settimeout(TIMEOUT)
        self.addCleanup(srv.close)
        conn, _ = srv.accept()
        self.addCleanup(conn.close)
        self.assertEqual(read_frame(relay), {"type": "resync"})


FAKE_PANEL = """#!/usr/bin/env python3
import os, sys, time
with open(sys.argv[1], "a") as f:
    f.write(f"{os.getpid()} {os.getsid(0)}\\n")
if len(sys.argv) > 2 and sys.argv[2] == "stay":  # a panel that keeps running
    time.sleep(60)
"""


class LaunchTest(Base):
    """The relay starts the panel once, only if none is running when the relay starts."""

    def setUp(self):
        super().setUp()
        self.marker = os.path.join(self.tmp.name, "started")
        fake = os.path.join(self.tmp.name, "fake-panel")
        with open(fake, "w") as f:
            f.write(FAKE_PANEL)
        os.chmod(fake, 0o755)
        self.cfg_home = os.path.join(self.tmp.name, "cfg")
        self.fake_cmd = f"{shlex.quote(fake)} {shlex.quote(self.marker)}"
        self.launch_env = {
            **self.env,
            "TABDOCK_PANEL_CMD": self.fake_cmd,  # exits at once, like a panel that died on startup
            "XDG_RUNTIME_DIR": self.tmp.name,  # where the relay keeps the panel's log
            "XDG_CONFIG_HOME": self.cfg_home,
        }
        del self.launch_env["TABDOCK_NO_LAUNCH"]
        self.stay_env = {**self.launch_env, "TABDOCK_PANEL_CMD": self.fake_cmd + " stay"}
        self.addCleanup(self.kill_started)

    def kill_started(self):
        for line in self.started():  # the "stay" fakes run in their own session: stop them explicitly
            try:
                os.kill(int(line.split()[0]), signal.SIGKILL)
            except ProcessLookupError:
                pass

    def started(self):
        try:
            with open(self.marker) as f:
                return f.read().splitlines()
        except FileNotFoundError:
            return []

    def wait_started(self):
        deadline = time.monotonic() + TIMEOUT
        while not self.started():
            self.assertLess(time.monotonic(), deadline, "the relay never started the panel")
            time.sleep(0.05)
        return self.started()

    def write_config(self, text):
        os.makedirs(os.path.join(self.cfg_home, "tabdock"))
        with open(os.path.join(self.cfg_home, "tabdock", "config.toml"), "w") as f:
            f.write(text)

    def listen(self):
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(self.sock_path)
        srv.listen(1)
        srv.settimeout(TIMEOUT)
        self.addCleanup(srv.close)
        return srv

    def test_starts_the_panel_detached_and_keeps_stdout_clean(self):
        relay = self.spawn([RELAY], env=self.stay_env)
        pid, sid = map(int, self.wait_started()[0].split())
        self.assertEqual(sid, pid)  # its own session: it survives the relay and the browser
        self.assertNotEqual(sid, os.getsid(relay.pid))
        # stdout is the native-messaging channel: the panel must not have touched it
        self.assertEqual(select.select([relay.stdout.fileno()], [], [], 0.3)[0], [])
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "tabdock.log")))

    def test_a_panel_that_is_still_starting_is_not_started_twice(self):
        self.spawn([RELAY], env=self.stay_env)
        self.wait_started()
        time.sleep(2.5)  # two more retry cycles with nobody listening yet: the first panel is still alive
        self.assertEqual(len(self.started()), 1)

    def test_a_panel_that_dies_at_startup_is_retried_but_only_three_times(self):
        relay = self.spawn([RELAY], env=self.launch_env)  # this fake exits at once, every time
        deadline = time.monotonic() + TIMEOUT
        while len(self.started()) < 3:
            self.assertLess(time.monotonic(), deadline, "the relay did not retry")
            time.sleep(0.05)
        time.sleep(2.5)
        self.assertEqual(len(self.started()), 3)  # and then it gives up instead of looping forever
        # every child was reaped: none is left as a zombie of the relay
        children = subprocess.run(["ps", "--ppid", str(relay.pid), "-o", "stat="], capture_output=True, text=True)
        self.assertEqual(children.stdout.split(), [])

    def test_does_not_start_one_when_a_panel_is_listening(self):
        srv = self.listen()
        relay = self.spawn([RELAY], env=self.launch_env)
        conn, _ = srv.accept()
        self.addCleanup(conn.close)
        self.assertEqual(read_frame(relay), {"type": "resync"})
        time.sleep(1.5)
        self.assertEqual(self.started(), [])

    def test_a_panel_that_goes_away_is_not_restarted(self):
        srv = self.listen()
        relay = self.spawn([RELAY], env=self.launch_env)
        conn, _ = srv.accept()
        self.assertEqual(read_frame(relay), {"type": "resync"})
        conn.close()  # the user quits the panel...
        srv.close()
        os.unlink(self.sock_path)
        self.assertEqual(read_frame(relay), {"type": "panel_disconnected"})
        time.sleep(2.5)  # ...and the relay keeps waiting instead of undoing that
        self.assertEqual(self.started(), [])

    def test_config_can_turn_it_off(self):
        self.write_config("start_with_browser = false\n")
        self.spawn([RELAY], env=self.launch_env)
        time.sleep(1.5)
        self.assertEqual(self.started(), [])

    def test_a_config_from_before_the_rename_can_still_turn_it_off(self):
        os.makedirs(os.path.join(self.cfg_home, "openbox-sidepanel"))
        with open(os.path.join(self.cfg_home, "openbox-sidepanel", "config.toml"), "w") as f:
            f.write("start_with_browser = false\n")
        self.spawn([RELAY], env=self.launch_env)
        time.sleep(1.5)
        self.assertEqual(self.started(), [])

    def test_unreadable_config_keeps_the_default(self):
        self.write_config("start_with_browser = [\n")
        self.spawn([RELAY], env=self.launch_env)
        self.wait_started()

    def test_environment_can_turn_it_off(self):
        self.spawn([RELAY], env={**self.launch_env, "TABDOCK_NO_LAUNCH": "1"})
        time.sleep(1.5)
        self.assertEqual(self.started(), [])


class SingleInstanceTest(Base):
    def panel(self):
        return self.spawn([sys.executable, PANEL, "--debug"])

    def wait_connectable(self):
        deadline = time.monotonic() + TIMEOUT
        while True:
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                probe.connect(self.sock_path)
                return
            except OSError:
                self.assertLess(time.monotonic(), deadline, "no panel ever listened on the socket")
                time.sleep(0.05)
            finally:
                probe.close()

    def test_only_one_of_many_simultaneous_panels_survives(self):
        # two browsers opening together each start a panel: that used to race on the stale-socket cleanup
        panels = [self.panel() for _ in range(6)]
        deadline = time.monotonic() + TIMEOUT
        while sum(p.poll() is None for p in panels) > 1 and time.monotonic() < deadline:
            time.sleep(0.05)
        time.sleep(1.0)  # a slow loser would have exited by now
        alive = [p for p in panels if p.poll() is None]
        self.assertEqual(len(alive), 1)
        self.assertEqual({p.returncode for p in panels if p.poll() is not None}, {1})  # refused, not crashed
        self.wait_connectable()  # and the survivor really owns the socket

    def test_a_killed_panel_does_not_block_the_next_one(self):
        first = self.panel()
        self.wait_connectable()
        first.kill()  # no cleanup: a stale socket file and lock file stay behind
        first.wait()
        second = self.panel()
        self.wait_connectable()
        self.assertIsNone(second.poll())  # it took over


class HelpTest(unittest.TestCase):
    def help(self, home):
        env = {**os.environ, "XDG_CONFIG_HOME": home, "XDG_RUNTIME_DIR": home}
        done = subprocess.run([sys.executable, PANEL, "-h"], env=env, capture_output=True, text=True, timeout=TIMEOUT)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def test_help_names_the_command_and_where_its_files_are(self):
        with tempfile.TemporaryDirectory() as home:
            config = os.path.join(home, "tabdock", "config.toml")
            out = self.help(home)
            self.assertTrue(out.startswith("usage: tabdock "), out)
            self.assertIn(f"config  {config}\n", out)
            self.assertIn(os.path.normpath(os.path.join(ROOT, "configs", "config.toml")), out)  # none yet: the example
            self.assertIn(f"log     {os.path.join(home, 'tabdock.log')}\n", out)
            old = os.path.join(home, "openbox-sidepanel", "config.toml")
            os.makedirs(os.path.dirname(old))
            with open(old, "w") as f:
                f.write("")
            out = self.help(home)
            self.assertIn(f"config  {old}\n", out)  # the one in use...
            self.assertIn(f"move it to {config}", out)  # ...and where it belongs now


class FindCommandTest(unittest.TestCase):
    def find(self, path):
        env = {**os.environ, "TABDOCK_SOCKET": path}
        return subprocess.run([sys.executable, PANEL, "--find"], env=env, capture_output=True, text=True, timeout=TIMEOUT)

    def test_no_panel_running_says_so_and_fails(self):
        with tempfile.TemporaryDirectory() as home:
            done = self.find(os.path.join(home, "nobody.sock"))
            self.assertEqual(done.returncode, 1)
            self.assertEqual(done.stderr, "tabdock: not running\n")

    def test_it_sends_a_find_message_to_the_panel(self):
        with tempfile.TemporaryDirectory() as home:
            path = os.path.join(home, "panel.sock")
            srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.addCleanup(srv.close)
            srv.bind(path)
            srv.listen(1)
            srv.settimeout(TIMEOUT)
            done = self.find(path)
            self.assertEqual(done.returncode, 0, done.stderr)
            conn, _ = srv.accept()
            self.addCleanup(conn.close)
            self.assertEqual(conn.recv(100), b'{"type":"find"}\n')


class PanelDebugTest(Base):
    def read_panel_until(self, panel, needle):
        deadline = time.monotonic() + TIMEOUT
        fd = panel.stdout.fileno()
        buf = b""
        while time.monotonic() < deadline:
            if select.select([fd], [], [], 0.2)[0]:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                buf += chunk
                if needle.encode() in buf:
                    return buf.decode()
        self.fail(f"{needle!r} never appeared in panel output: {buf.decode()!r}")

    def test_panel_end_to_end(self):
        panel = self.spawn([sys.executable, PANEL, "--debug"])
        deadline = time.monotonic() + TIMEOUT
        while not os.path.exists(self.sock_path):
            self.assertLess(time.monotonic(), deadline, "panel socket never appeared")
            time.sleep(0.05)

        # a second panel must refuse to start
        second = subprocess.run([sys.executable, PANEL, "--debug"], env=self.env, capture_output=True, timeout=TIMEOUT)
        self.assertEqual(second.returncode, 1)
        self.assertIn(b"already listening", second.stderr)

        # unusable socket directory: clean error, no traceback
        bad_env = {**self.env, "TABDOCK_SOCKET": os.path.join(self.tmp.name, "missing-dir", "sp.sock")}
        bad = subprocess.run([sys.executable, PANEL, "--debug"], env=bad_env, capture_output=True, timeout=TIMEOUT)
        self.assertEqual(bad.returncode, 1)
        self.assertIn(b"tabdock:", bad.stderr)
        self.assertNotIn(b"Traceback", bad.stderr)

        relay = self.spawn([RELAY])
        self.assertEqual(read_frame(relay), {"type": "resync"})
        write_frame(relay, {"type": "hello", "browser": "Firefox", "version": "156.0"})
        write_frame(
            relay,
            {
                "type": "state",
                "focusedWindowId": 5,
                "containers": [{"cookieStoreId": "firefox-container-1", "name": "Personal"}],
                "windows": [
                    {
                        "id": 5,
                        "tabs": [
                            {"id": 21, "title": "hello tab", "cookieStoreId": "firefox-default", "active": True},
                            {"id": 22, "title": "mail tab", "cookieStoreId": "firefox-container-1", "active": False},
                        ],
                    }
                ],
            },
        )
        out = self.read_panel_until(panel, "mail tab [22]")
        self.assertIn(f"pid {os.getpid()}", out)
        self.assertIn("[Personal] (1)", out)
        self.assertIn(" * hello tab [21]", out)

        # reverse path: console command -> panel -> relay -> extension
        panel.stdin.write(b"activate 22\n")
        self.assertEqual(read_frame(relay), {"type": "activate_tab", "tabId": 22, "windowId": 5})


if __name__ == "__main__":
    unittest.main()
