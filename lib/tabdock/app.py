import argparse
import os
import signal
import socket
import sys

import gi

gi.require_version("GLibUnix", "2.0")
gi.require_version("GioUnix", "2.0")
from gi.repository import Gio, GioUnix, GLib, GLibUnix  # noqa: E402

from . import config, launch  # noqa: E402
from .ipc import Server  # noqa: E402
from .model import (  # noqa: E402
    accent,
    accents,
    choice_labels,
    detect_browser,
    focused_window,
    match_browser,
    offers_workspaces,
    owns_window,
    window_of_tab,
)
from .ui import ConsoleView  # noqa: E402


EDITS = {"wsicon": "icon", "wscolor": "color", "wscontainer": "cookieStoreId"}  # --debug verb -> what it sets
CONTAINER_VERBS = {"cnew": None, "crm": None, "crename": "name", "ccolor": "color", "cicon": "icon"}


class Panel:
    """Routes relay messages to the view, picks which browsers to show, and sends actions back."""

    def __init__(self, cfg, x=None):
        self.cfg = cfg
        self.colours = accents(cfg.get("theme"))  # each browser's colour, with the config's [theme]
        self.x = x  # x11.XConn or None (headless)
        self.view = None
        self.browsers = {}  # Connection -> hello message
        self.states = {}  # Connection -> last state message
        self.current = None  # Connection of the browser in use: the one whose tabs "auto" shows
        self.mode = cfg["view"]  # "auto" (the browser in use), "all", or the Connection chosen with its chip
        self.active = None  # XID of the active window
        self.browser_xids = {}  # Connection -> XID of its window when it was last seen active
        self.installed = launch.installed_browsers() if cfg.get("launch_offline") else []  # scanned at start and on reload

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
        elif kind == "bookmarks" and conn in self.browsers:
            self.view.show_bookmarks(conn, msg)
        elif kind == "history" and conn in self.browsers:
            self.view.show_history(conn, msg)
        elif kind == "find":  # from `tabdock --find`, a key bound in the window manager
            self.view.find()

    def on_close(self, conn):
        if conn not in self.browsers:
            return  # never said hello (`tabdock --find`): nothing to forget, nothing to redraw
        self.browsers.pop(conn)
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
        self.raise_browser(conn)

    def raise_browser(self, conn):
        xid = self._window_of(conn)
        # self.active leaves out our own windows, so a find or rename window holding the keyboard is checked apart
        if self.x and xid and (xid != self.active or self.x.active_window() in self.view.xids):
            self.x.activate(xid)  # the browser is not the focused window: bring it forward

    def choose(self, mode):
        """A chip was clicked: "auto" follows the browser in use, "all" lists every browser, and a
        Connection shows just that browser, whichever window has the focus."""
        if mode in ("auto", "all") or mode in self.browsers:
            self.mode = mode
            self._render()

    def reconfigure(self, cfg):
        self.cfg = cfg
        before = self._offline()
        self.installed = launch.installed_browsers() if cfg.get("launch_offline") else []
        mode, self.mode = self.mode, cfg["view"]  # the file wins over a chip clicked since, like pin and side
        colours, self.colours = self.colours, accents(cfg.get("theme"))
        self.view.reconfigure(cfg)
        if cfg["follow"] == "last":
            self.view.set_hidden(False)
        if self._offline() != before or self.mode != mode or self.colours != colours:
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
        'activate <tabId>', 'move <tabId> <index>', 'order <cookieStoreId>,<cookieStoreId>,...',
        'newtab <cookieStoreId>' (the "+" of a container section), 'close <tabId>', 'pin <tabId>',
        'unpin <tabId>', 'restore' (the tab closed last), 'reopen <tabId> <cookieStoreId>', for containers 'cnew <name>', 'crename <id> <name>', 'ccolor <id> <colour>', 'cicon <id> <icon>',
        'crm <id>', and for workspaces (the focused window's; ids as the console prints them, in braces) 'ws <id>',
        'wsnew <name>', 'wsrename <id> <name>', 'wsrm <id>', 'wsmove <tabId> <id>', and 'wsicon <id> [icon]',
        'wscolor <id> [colour]', 'wscontainer <id> [cookieStoreId]' (without the last word: none)."""
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
        elif len(parts) == 2 and parts[0] == "close" and parts[1].isdigit():
            self.command(self.current, {"type": "close_tab", "tabId": int(parts[1])})
        elif len(parts) == 2 and parts[0] in ("pin", "unpin") and parts[1].isdigit():
            self.command(self.current, {"type": "pin_tab", "tabId": int(parts[1]), "pinned": parts[0] == "pin"})
        elif parts == ["restore"]:
            self.command(self.current, {"type": "restore_tab"})
        elif len(parts) == 3 and parts[0] == "reopen" and parts[1].isdigit():
            self.command(self.current, {"type": "reopen_in_container", "tabId": int(parts[1]), "cookieStoreId": parts[2]})
        elif parts[0] in CONTAINER_VERBS:
            self._container_line(line)
        elif len(parts) == 2 and parts[0] == "newtab" and focused_window(state):
            self.command(self.current, {"type": "new_tab", "cookieStoreId": parts[1], "windowId": focused_window(state)["id"]})
        elif parts[0].startswith("ws") and offers_workspaces(self.browsers[self.current], state):
            self._workspace_line(line, focused_window(state))

    def _container_line(self, line):
        verb, _, rest = line.strip().partition(" ")
        cid, _, value = rest.strip().partition(" ")
        value = value.strip()
        if verb == "cnew" and rest.strip():
            self.command(self.current, {"type": "create_container", "name": rest.strip()})
        elif verb == "crm" and cid and not value:
            self.command(self.current, {"type": "remove_container", "cookieStoreId": cid})
        elif verb in CONTAINER_VERBS and verb not in ("cnew", "crm") and cid and value:
            self.command(self.current, {"type": "update_container", "cookieStoreId": cid, CONTAINER_VERBS[verb]: value})

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
        elif verb in EDITS and 1 <= len(args) <= 2:
            value = args[1] if len(args) == 2 else None
            self.command(self.current, {"type": "edit_workspace", "workspaceId": args[0], EDITS[verb]: value})

    def _shown(self):
        """The browsers to list: all of them, the one chosen, or the one in use. Only those that have
        sent their tabs, so a browser still starting up never shows another browser's tabs instead."""
        if self.mode == "all":
            conns = list(self.browsers)
        else:
            conns = [self.current if self.mode == "auto" else self.mode]
        return [c for c in conns if c in self.states]

    def _offline(self):
        """Installed browsers that are not connected, by kind (not by profile)."""
        running = {info["browser"] for info in self.browsers.values()}
        return [(name, binary) for name, binary in self.installed if name not in running]

    def _render(self):
        shown = self._shown()
        offline = self._offline()
        choices = [(c, label, accent(self.browsers[c], self.colours)) for c, label in choice_labels(self.browsers)]
        if not shown:  # nothing to show yet: never leave another browser's tabs under this one's header
            self.view.clear(self.mode, choices, offline)  # (the chips stay: they are the way to another browser)
            return
        sources = [(c, self.browsers[c], self.states[c]) for c in shown]
        # the header and the strip wear the colour of the browser shown, or, for all of them, of the one in use
        focus = sources[0][1] if len(sources) == 1 else self.browsers.get(self.current)
        self.view.show(sources, self.mode, choices, focus, offline)


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


def _root(*parts):
    """VERSION and configs/ sit two levels above this package, in a checkout and once installed."""
    return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", *parts))


def _version():
    try:
        with open(_root("VERSION")) as f:
            return f.read().strip()
    except OSError:
        return "unknown"


def _help_files():
    """The end of --help: where the files are on this machine, and how the panel usually starts."""
    path, home = config.config_path(), os.path.join(config.config_dir(), "config.toml")
    if not os.path.exists(path):
        note = f"\n          (not there, so the defaults apply; an example to copy: {_root('configs', 'config.toml')})"
    elif path != home:
        note = f"\n          (from before the rename to tabdock: move it to {home})"
    else:
        note = ""
    return (
        "files:\n"
        f"  config  {path}{note}\n"
        f"  log     {config.log_path()}\n"
        "          (the output of a panel the browser started)\n\n"
        "Usually started by the browser when it opens with the Tabdock extension (start_with_browser),\n"
        'from the "Tabdock" menu entry, or an autostart line. https://github.com/musqz/tabdock'
    )


def _send_find():
    """`tabdock --find`: tell the running panel to open its find window."""
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.connect(config.socket_path())
        client.sendall(b'{"type":"find"}\n')
    except OSError:
        print("tabdock: not running", file=sys.stderr)
        return 1
    finally:
        client.close()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="tabdock",
        description="Autohiding X11 side panel with the tabs and containers of Firefox-family browsers.",
        epilog=_help_files(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"tabdock {_version()}")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="no GUI: print each snapshot to stdout, and read 'activate <tabId>', 'move <tabId> <index>' "
        "and 'order <cookieStoreId>,...' from stdin",
    )
    parser.add_argument(
        "--find",
        action="store_true",
        help="show the running panel's find window (bind it to a key in your window manager); "
        "arrows and Enter then pick a tab, Escape closes it",
    )
    args = parser.parse_args(argv)

    if args.find:
        return _send_find()

    try:
        cfg = config.load()
    except ValueError as e:
        print(f"tabdock: {config.config_path()}: {e}", file=sys.stderr)
        return 1

    loop = GLib.MainLoop()
    x = None
    try:
        from . import x11  # python-xlib is only needed to follow the active window

        x = x11.connect()
    except ImportError:
        print("tabdock: python-xlib not found, the active window will not be followed", file=sys.stderr)
    panel = Panel(cfg, x)
    server = Server(config.socket_path(), panel.on_message, panel.on_close)
    try:
        server.start()
    except (RuntimeError, GLib.Error, OSError) as e:  # already running, or socket dir missing/unwritable
        print(f"tabdock: {e}", file=sys.stderr)
        return 1

    if args.debug:
        panel.view = ConsoleView()
        _watch_stdin(panel)
    else:
        if x is None:
            print("tabdock: needs an X display and python-xlib (is DISPLAY set?)", file=sys.stderr)
            server.stop()
            return 1
        from .dock import DockView

        panel.view = DockView(
            cfg, panel.activate_tab, loop.quit, x,
            on_command=panel.command, on_choose=panel.choose, on_raise=panel.raise_browser,
        )

    panel._render()
    if x is not None:
        x.watch_active_window(panel.follow, loop.quit)
        panel.follow(x.active_window())

    def reload_config():
        try:
            panel.reconfigure(config.load())
        except ValueError as e:
            print(f"tabdock: reload failed, keeping the old config: {e}", file=sys.stderr)
        return GLib.SOURCE_CONTINUE

    for sig in (signal.SIGINT, signal.SIGTERM):
        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, sig, loop.quit)
    GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGHUP, reload_config)
    try:
        loop.run()
    finally:
        server.stop()
    return 0
