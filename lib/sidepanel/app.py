import argparse
import signal
import sys

import gi

gi.require_version("GLibUnix", "2.0")
gi.require_version("GioUnix", "2.0")
from gi.repository import Gio, GioUnix, GLib, GLibUnix  # noqa: E402

from . import config  # noqa: E402
from .ipc import Server  # noqa: E402
from .model import detect_browser, match_browser, window_of_tab  # noqa: E402
from .ui import ConsoleView  # noqa: E402


class Panel:
    """Routes relay messages to the view, picks which browser to show, and sends actions back."""

    def __init__(self, cfg, x=None):
        self.cfg = cfg
        self.x = x  # x11.XConn or None (headless)
        self.view = None
        self.browsers = {}  # Connection -> hello message
        self.states = {}  # Connection -> last state message
        self.current = None  # Connection whose tabs are shown
        self.active = None  # XID of the active window
        self.browser_xid = None  # XID of the last active browser window
        self.on_browser = False  # is the active window a browser window?

    # -- from the relays -----------------------------------------------------------

    def on_message(self, conn, msg):
        kind = msg.get("type")
        if kind == "hello":
            self.browsers[conn] = {**msg, "browser": detect_browser(msg)}
            self.follow(self.active)
            if self.current is None:
                self.current = conn
                self._render()
        elif kind == "state" and conn in self.browsers:
            self.states[conn] = msg
            if conn is self.current:
                self._render()

    def on_close(self, conn):
        self.browsers.pop(conn, None)
        self.states.pop(conn, None)
        if conn is self.current:
            self.current = None
            self.follow(self.active)  # prefer the browser that owns the active window (renders it)...
            if self.current is None:
                self.current = next(iter(self.browsers), None)  # ...else any that is left, or nothing
                self._render()

    # -- from X11 ------------------------------------------------------------------

    def follow(self, xid):
        """The active window changed (or a browser appeared): decide which browser to show."""
        self.active = xid
        if xid is not None and xid in self.view.xids:
            return  # our own windows: the browser stays "active" from the user's point of view
        pid, wm_class = self.x.window_info(xid) if (self.x and xid) else (None, ())
        match = match_browser(self.browsers, pid, wm_class) if xid else None
        if match is not None:
            self.on_browser = True
            self.browser_xid = xid
            self.current = match
            self.view.set_hidden(False)
            self._render()
        else:
            self.on_browser = False
            if self.cfg["follow"] == "hide":
                self.view.set_hidden(True)

    # -- from the view -------------------------------------------------------------

    def activate_tab(self, conn, tab_id, window_id):
        conn.send({"type": "activate_tab", "tabId": tab_id, "windowId": window_id})
        if self.x and self.browser_xid and not self.on_browser:
            self.x.activate(self.browser_xid)  # the browser was not focused: bring it forward

    def reconfigure(self, cfg):
        self.cfg = cfg
        self.view.reconfigure(cfg)
        if cfg["follow"] == "last":
            self.view.set_hidden(False)

    def on_stdin_line(self, line):
        """--debug console: 'activate <tabId>' drives the reverse path without a GUI."""
        parts = line.split()
        if len(parts) == 2 and parts[0] == "activate" and parts[1].isdigit() and self.current in self.states:
            window_id = window_of_tab(self.states[self.current], int(parts[1]))
            if window_id is not None:
                self.activate_tab(self.current, int(parts[1]), window_id)

    def _render(self):
        if self.current in self.states:
            self.view.show(self.current, self.browsers[self.current], self.states[self.current])
        else:  # nothing to show yet: never leave another browser's tabs under this one's header
            self.view.clear()


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

    try:
        cfg = config.load()
    except ValueError as e:
        print(f"sidepanel: {config.config_path()}: {e}", file=sys.stderr)
        return 1

    loop = GLib.MainLoop()
    x = None
    try:
        from . import x11  # python-xlib is only needed to follow the active window

        x = x11.connect()
    except ImportError:
        print("sidepanel: python-xlib not found, the active window will not be followed", file=sys.stderr)
    panel = Panel(cfg, x)
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
        if x is None:
            print("sidepanel: needs an X display and python-xlib (is DISPLAY set?)", file=sys.stderr)
            server.stop()
            return 1
        from .dock import DockView

        panel.view = DockView(cfg, panel.activate_tab, loop.quit, x)

    if x is not None:
        x.watch_active_window(panel.follow, loop.quit)
        panel.follow(x.active_window())

    def reload_config():
        try:
            panel.reconfigure(config.load())
        except ValueError as e:
            print(f"sidepanel: reload failed, keeping the old config: {e}", file=sys.stderr)
        return GLib.SOURCE_CONTINUE

    for sig in (signal.SIGINT, signal.SIGTERM):
        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, sig, loop.quit)
    GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGHUP, reload_config)
    try:
        loop.run()
    finally:
        server.stop()
    return 0
