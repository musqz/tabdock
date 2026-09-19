"""Unix-socket server for the native-messaging relays (line-delimited JSON, GLib main loop)."""
import fcntl
import json
import os

from gi.repository import Gio, GLib


class Connection:
    def __init__(self, server, gconn):
        self.server = server
        self.gconn = gconn
        self.closed = False
        self.reader = Gio.DataInputStream.new(gconn.get_input_stream())
        self._read()

    def send(self, msg):
        data = (json.dumps(msg, separators=(",", ":")) + "\n").encode()
        try:
            self.gconn.get_output_stream().write_all(data, None)
        except GLib.Error:
            self.close()

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.gconn.close(None)
        except GLib.Error:
            pass
        self.server.conns.discard(self)
        self.server.on_close(self)

    def _read(self):
        self.reader.read_line_async(GLib.PRIORITY_DEFAULT, None, self._on_line)

    def _on_line(self, stream, result):
        try:
            line, _ = stream.read_line_finish_utf8(result)
        except GLib.Error:
            line = None
        if line is None:  # EOF or error
            self.close()
            return
        try:
            msg = json.loads(line)
        except ValueError:
            msg = None
        if isinstance(msg, dict):
            self.server.on_message(self, msg)
        if not self.closed:
            self._read()


class Server:
    def __init__(self, path, on_message, on_close):
        self.path = path
        self.on_message = on_message
        self.on_close = on_close
        self.conns = set()
        self.service = None
        self._lock = None

    def start(self):
        self._lock = _claim(self.path)  # held for the life of the process
        self.service = Gio.SocketService.new()
        self.service.add_address(
            Gio.UnixSocketAddress.new(self.path), Gio.SocketType.STREAM, Gio.SocketProtocol.DEFAULT, None
        )
        os.chmod(self.path, 0o600)
        self.service.connect("incoming", self._incoming)
        self.service.start()

    def stop(self):
        if self.service is not None:
            self.service.stop()
            self.service.close()
            self.service = None
            try:
                os.unlink(self.path)
            except FileNotFoundError:
                pass
            self._lock.close()  # the lock file itself stays: removing it would race a starting panel

    def _incoming(self, _service, gconn, _source):
        self.conns.add(Connection(self, gconn))
        return True


def _claim(path):
    """Take the single-instance lock, then clear any stale socket file. Returns the lock file.

    An exclusive lock, which the kernel drops when the process dies however it dies, replaces
    probing the socket. Probing raced: two panels starting together (two browsers opening at once
    both start one) could each see the other's not-yet-listening socket as stale and delete it,
    leaving an orphaned panel nobody can reach.
    """
    lock = open(path + ".lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise RuntimeError(f"another sidepanel is already listening on {path}") from None
    try:
        os.unlink(path)  # only ever a leftover of a dead panel: we hold the lock
    except FileNotFoundError:
        pass
    return lock
