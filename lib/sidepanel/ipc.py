"""Unix-socket server for the native-messaging relays (line-delimited JSON, GLib main loop)."""
import json
import os
import socket

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

    def start(self):
        _claim(self.path)
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

    def _incoming(self, _service, gconn, _source):
        self.conns.add(Connection(self, gconn))
        return True


def _claim(path):
    """Refuse to start if a live panel owns the socket; clear a stale socket file."""
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.connect(path)
    except (FileNotFoundError, ConnectionRefusedError):
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        return
    finally:
        probe.close()
    raise RuntimeError(f"another sidepanel is already listening on {path}")
