import argparse
import signal
import sys

import gi

gi.require_version("GLibUnix", "2.0")
gi.require_version("GioUnix", "2.0")
from gi.repository import Gio, GioUnix, GLib, GLibUnix  # noqa: E402

from . import config  # noqa: E402
from .ipc import Server  # noqa: E402
from .model import window_of_tab  # noqa: E402
from .ui import ConsoleView  # noqa: E402


class Panel:
    """Routes relay messages to the view and view actions back to the browser."""

    def __init__(self):
        self.view = None
        self.browsers = {}  # Connection -> hello message
        self.latest = None  # (Connection, state) of the last snapshot shown

    def on_message(self, conn, msg):
        kind = msg.get("type")
        if kind == "hello":
            self.browsers[conn] = msg
        elif kind == "state" and conn in self.browsers:
            self.latest = (conn, msg)
            self.view.show(conn, self.browsers[conn], msg)

    def on_close(self, conn):
        self.browsers.pop(conn, None)
        if self.latest and self.latest[0] is conn:
            self.latest = None

    def activate_tab(self, conn, tab_id, window_id):
        conn.send({"type": "activate_tab", "tabId": tab_id, "windowId": window_id})

    def on_stdin_line(self, line):
        """--debug console: 'activate <tabId>' drives the reverse path without a GUI."""
        parts = line.split()
        if len(parts) == 2 and parts[0] == "activate" and parts[1].isdigit() and self.latest:
            conn, state = self.latest
            window_id = window_of_tab(state, int(parts[1]))
            if window_id is not None:
                self.activate_tab(conn, int(parts[1]), window_id)


def _watch_stdin(panel):
    reader = Gio.DataInputStream.new(GioUnix.InputStream.new(0, False))

    def on_line(stream, result):
        try:
            line, _ = stream.read_line_finish_utf8(result)
        except GLib.Error:
            line = None
        if line is not None:
            panel.on_stdin_line(line)
            reader.read_line_async(GLib.PRIORITY_DEFAULT, None, on_line)

    reader.read_line_async(GLib.PRIORITY_DEFAULT, None, on_line)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="sidepanel", description="Desktop side panel for Firefox-family browsers")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="no GUI: print each snapshot to stdout, read 'activate <tabId>' from stdin",
    )
    args = parser.parse_args(argv)

    loop = GLib.MainLoop()
    panel = Panel()
    server = Server(config.socket_path(), panel.on_message, panel.on_close)
    try:
        server.start()
    except (RuntimeError, GLib.Error) as e:  # already running, or socket dir missing/unwritable
        print(f"sidepanel: {e}", file=sys.stderr)
        return 1

    if args.debug:
        panel.view = ConsoleView()
        _watch_stdin(panel)
    else:
        from .ui import TreeView

        panel.view = TreeView(panel.activate_tab, loop.quit)

    for sig in (signal.SIGINT, signal.SIGTERM):
        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, sig, loop.quit)
    try:
        loop.run()
    finally:
        server.stop()
    return 0
