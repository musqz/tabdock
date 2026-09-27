import argparse
import os
import signal
import sys

import gi

gi.require_version("GLibUnix", "2.0")
gi.require_version("GioUnix", "2.0")
from gi.repository import Gio, GioUnix, GLib, GLibUnix  # noqa: E402

from . import config  # noqa: E402
from .ipc import Server  # noqa: E402
from .model import (  # noqa: E402
    accent,
    choice_labels,
    detect_browser,
    focused_window,
    match_browser,
    offers_workspaces,
    owns_window,
    window_of_tab,
)
from .ui import ConsoleView  # noqa: E402


class Panel:
    """Routes relay messages to the view, picks which browsers to show, and sends actions back."""

    def __init__(self, cfg, x=None):
        self.cfg = cfg
        self.x = x  # x11.XConn or None (headless)
        self.view = None
        self.browsers = {}  # Connection -> hello message
        self.states = {}  # Connection -> last state message
        self.current = None  # Connection of the browser in use: the one whose tabs "auto" shows
        self.mode = cfg["view"]  # "auto" (the browser in use), "all", or the Connection chosen with its chip
        self.active = None  # XID of the active window
        self.browser_xids = {}  # Connection -> XID of its window when it was last seen active

    # -- from the relays -----------------------------------------------------------

    def on_message(self, conn, msg):
        kind = msg.get("type")
        if kind == "hello":
            self.browsers[conn] = {**msg, "browser": detect_browser(msg)}
            self.follow(self.active)
            if self.current is None:
                self.current = conn
            self._render()  # a new browser is a new choice, whichever one is showing
        elif kind == "state" and conn in self.browsers:
            self.states[conn] = msg
            if conn in self._shown():
                self._render()

    def on_close(self, conn):
        self.browsers.pop(conn, None)
        self.states.pop(conn, None)
        self.browser_xids.pop(conn, None)
        if self.mode is conn:
            self.mode = "auto"  # the browser you had chosen is gone
        if conn is self.current:
            self.current = None
            self.follow(self.active)  # prefer the browser that owns the active window (renders it)...
            if self.current is not None:
                return
            self.current = next(iter(self.browsers), None)  # ...else any that is left, or nothing
        self._render()

    # -- from X11 ------------------------------------------------------------------

    def follow(self, xid):
        """The active window changed (or a browser appeared): decide which browser to show."""
        if xid is not None and xid in self.view.xids:
            return  # our own windows: what was active stays "active" from the user's point of view
        self.active = xid
        pid, wm_class = self.x.window_info(xid) if (self.x and xid) else (None, ())
        match = match_browser(self.browsers, pid, wm_class) if xid else None
        if match is not None:
            self.browser_xids[match] = xid
            self.current = match
            self.view.set_hidden(False)
            self._render()
        elif self.cfg["follow"] == "hide":
            self.view.set_hidden(True)

    # -- from the view -------------------------------------------------------------

    def activate_tab(self, conn, tab_id, window_id):
        conn.send({"type": "activate_tab", "tabId": tab_id, "windowId": window_id})
        xid = self._window_of(conn)
        if self.x and xid and xid != self.active:
            self.x.activate(xid)  # that browser is not the focused window: bring it forward

    def choose(self, mode):
        """A chip was clicked: "auto" follows the browser in use, "all" lists every browser, and a
        Connection shows just that browser, whichever window has the focus."""
        if mode in ("auto", "all") or mode in self.browsers:
            self.mode = mode
            self._render()

    def reconfigure(self, cfg):
        self.cfg = cfg
        mode, self.mode = self.mode, cfg["view"]  # the file wins over a chip clicked since, like pin and side
        self.view.reconfigure(cfg)
        if cfg["follow"] == "last":
            self.view.set_hidden(False)
        if self.mode != mode:
            self._render()

    def _window_of(self, conn):
        """XID of a browser's window: the one last seen active if it still exists, else its topmost
        window (found by process: the browser has not been in use since the panel started, or that
        window was closed)."""
        if not self.x:
            return None
        windows = self.x.client_windows()
        xid = self.browser_xids.get(conn)
        if xid is not None and (not windows or xid in windows):
            return xid  # (no window list at all: a window manager without it, so trust what we saw)
        self.browser_xids.pop(conn, None)
        pid = self.browsers.get(conn, {}).get("browserPid")
        if not pid:
            return None
        ours = self.view.xids
        for w in reversed(windows):  # topmost first
            wpid = None if w in ours else self.x.window_pid(w)
            if wpid and owns_window(pid, wpid):
                return w
        return None

    def command(self, conn, message):
        """Anything else the panel asks the browser to do (reordering, ...)."""
        conn.send(message)

    def on_stdin_line(self, line):
        """--debug console, to drive the reverse path without a GUI:
        'activate <tabId>', 'move <tabId> <index>', 'order <cookieStoreId>,<cookieStoreId>,...', and for
        workspaces (the focused window's; ids as the console prints them, in braces) 'ws <id>',
        'wsnew <name>', 'wsrename <id> <name>', 'wsrm <id>', 'wsmove <tabId> <id>'."""
        parts = line.split()
        if not parts or self.current not in self.states:
            return
        state = self.states[self.current]
        if len(parts) == 2 and parts[0] == "activate" and parts[1].isdigit():
            window_id = window_of_tab(state, int(parts[1]))
            if window_id is not None:
                self.activate_tab(self.current, int(parts[1]), window_id)
        elif len(parts) == 3 and parts[0] == "move" and parts[1].isdigit() and parts[2].isdigit():
            self.command(self.current, {"type": "move_tab", "tabId": int(parts[1]), "index": int(parts[2])})
        elif len(parts) == 2 and parts[0] == "order":
            self.command(self.current, {"type": "set_container_order", "order": parts[1].split(",")})
        elif parts[0].startswith("ws") and offers_workspaces(self.browsers[self.current], state):
            self._workspace_line(line, focused_window(state))

    def _workspace_line(self, line, window):
        verb, _, rest = line.strip().partition(" ")
        args = rest.split()
        if verb == "ws" and len(args) == 1 and window:
            self.command(self.current, {"type": "switch_workspace", "windowId": window["id"], "workspaceId": args[0]})
        elif verb == "wsnew" and window:
            self.command(self.current, {"type": "new_workspace", "windowId": window["id"], "name": rest.strip()})
        elif verb == "wsrename" and len(args) >= 2:
            ws_id, name = rest.split(None, 1)
            self.command(self.current, {"type": "rename_workspace", "workspaceId": ws_id, "name": name.strip()})
        elif verb == "wsrm" and len(args) == 1:
            self.command(self.current, {"type": "remove_workspace", "workspaceId": args[0]})
        elif verb == "wsmove" and len(args) == 2 and args[0].isdigit():
            self.command(self.current, {"type": "move_tab_to_workspace", "tabId": int(args[0]), "workspaceId": args[1]})

    def _shown(self):
        """The browsers to list: all of them, the one chosen, or the one in use. Only those that have
        sent their tabs, so a browser still starting up never shows another browser's tabs instead."""
        if self.mode == "all":
            conns = list(self.browsers)
        else:
            conns = [self.current if self.mode == "auto" else self.mode]
        return [c for c in conns if c in self.states]

    def _render(self):
        shown = self._shown()
        choices = [(c, label, accent(self.browsers[c])) for c, label in choice_labels(self.browsers)]
        if not shown:  # nothing to show yet: never leave another browser's tabs under this one's header
            self.view.clear(self.mode, choices)  # (the chips stay: they are the way to another browser)
            return
        sources = [(c, self.browsers[c], self.states[c]) for c in shown]
        # the header and the strip wear the colour of the browser shown, or, for all of them, of the one in use
        focus = sources[0][1] if len(sources) == 1 else self.browsers.get(self.current)
        self.view.show(sources, self.mode, choices, focus)


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


def _version():
    """The VERSION file sits two levels above this package, in a checkout and once installed."""
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "VERSION")) as f:
            return f.read().strip()
    except OSError:
        return "unknown"


def main(argv=None):
    parser = argparse.ArgumentParser(prog="sidepanel", description="Desktop side panel for Firefox-family browsers")
    parser.add_argument("--version", action="version", version=f"sidepanel {_version()}")
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
    except (RuntimeError, GLib.Error, OSError) as e:  # already running, or socket dir missing/unwritable
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

        panel.view = DockView(cfg, panel.activate_tab, loop.quit, x, on_command=panel.command, on_choose=panel.choose)

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
