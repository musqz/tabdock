"""Protocol tests without a browser: this test plays the extension (native-messaging
frames on the relay's stdio) and, in the first class, also the panel (Unix socket).
"""
import json
import os
import select
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
RELAY = os.path.join(ROOT, "lib", "native-host", "sidepanel-nmhost")
PANEL = os.path.join(ROOT, "sidepanel")
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
        self.env = {**os.environ, "SIDEPANEL_SOCKET": self.sock_path}
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

    def spawn(self, cmd, **kw):
        p = subprocess.Popen(cmd, env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0, **kw)
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
        bad_env = {**self.env, "SIDEPANEL_SOCKET": os.path.join(self.tmp.name, "missing-dir", "sp.sock")}
        bad = subprocess.run([sys.executable, PANEL, "--debug"], env=bad_env, capture_output=True, timeout=TIMEOUT)
        self.assertEqual(bad.returncode, 1)
        self.assertIn(b"sidepanel:", bad.stderr)
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
