"""Wayland plumbing over pywayland and wlr-foreign-toplevel: active-window tracking and raising windows.

Same calls as x11.XConn. A "window id" is a counter number, since a Wayland toplevel has no XID or pid.
"""
import itertools
import sys

from gi.repository import GLib
from pywayland.client import Display
from pywayland.protocol.wayland import WlSeat

from .wlr_foreign_toplevel import ZwlrForeignToplevelHandleV1, ZwlrForeignToplevelManagerV1

ACTIVATED = ZwlrForeignToplevelHandleV1.state.activated


def connect():
    """A WlConn, or None when the compositor has no wlr-foreign-toplevel (or no Wayland display)."""
    try:
        display = Display()
        display.connect()
    except Exception as e:  # pywayland raises plain exceptions for a missing socket
        print(f"tabdock: no Wayland display ({e}), the active window will not be followed", file=sys.stderr)
        return None
    conn = WlConn(display)
    if conn.manager is None:
        print("tabdock: the compositor lacks wlr-foreign-toplevel, the active window will not be followed", file=sys.stderr)
        display.disconnect()
        return None
    return conn


class WlConn:
    uses_pids = False  # a toplevel has no pid: windows are matched by app id

    def __init__(self, display):
        self.display = display
        self.manager = self.seat = None
        self._windows = {}  # id -> {"handle", "app_id", "title", "active"}
        self._ids = itertools.count(1)
        self._callback = self._on_lost = None
        self._last_active = None
        self._settle_id = None
        registry = display.get_registry()
        registry.dispatcher["global"] = self._on_global
        self._registry = registry
        display.roundtrip()
        if self.manager is not None:
            display.roundtrip()  # the toplevels announced on bind

    def _on_global(self, registry, name, interface, version):
        if interface == "zwlr_foreign_toplevel_manager_v1":
            self.manager = registry.bind(name, ZwlrForeignToplevelManagerV1, min(version, 3))
            self.manager.dispatcher["toplevel"] = self._on_toplevel
            self.manager.dispatcher["finished"] = self._on_finished
        elif interface == "wl_seat" and self.seat is None:
            self.seat = registry.bind(name, WlSeat, min(version, 1))

    def _on_finished(self, _manager):
        """The compositor dropped the manager: no more news, the same as losing the connection."""
        if self._on_lost is not None:
            self._on_lost()

    def _on_toplevel(self, _manager, handle):
        wid = next(self._ids)
        win = {"handle": handle, "app_id": "", "active": False, "pending": False}
        self._windows[wid] = win

        def app_id(_h, value):
            win["app_id"] = value

        def state(_h, states):
            win["pending"] = ACTIVATED in list(states)

        def done(_h):
            win["active"] = win["pending"]
            if win["active"] and wid in self._windows:  # last activated last: client_windows() is then a stacking guess
                self._windows[wid] = self._windows.pop(wid)
            self._changed()

        def closed(_h):
            self._windows.pop(wid, None)
            handle.destroy()
            self._changed()

        handle.dispatcher["app_id"] = app_id
        handle.dispatcher["state"] = state
        handle.dispatcher["done"] = done
        handle.dispatcher["closed"] = closed

    def _changed(self):
        if self._settle_id is None:  # a switch is "none active", then the new one: report only where it ends
            self._settle_id = GLib.timeout_add(40, self._settle)

    def _settle(self):
        self._settle_id = None
        active = self.active_window()
        if active != self._last_active:
            self._last_active = active
            if self._callback is not None:
                self._callback(active)
        return False

    def active_window(self):
        return next((wid for wid, w in reversed(self._windows.items()) if w["active"]), None)

    def window_info(self, wid):
        """(None, (app_id, its last dotted part)): there is no pid, so a browser is told by its app id."""
        win = self._windows.get(wid)
        if win is None or not win["app_id"]:
            return None, ()
        app_id = win["app_id"]
        return None, (app_id, app_id.rsplit(".", 1)[-1])

    def client_windows(self):
        """Ids, the one activated longest ago first (the compositor does not say how windows are stacked)."""
        return list(self._windows)

    def activate(self, wid):
        win = self._windows.get(wid)
        if win is not None and self.seat is not None:
            win["handle"].activate(self.seat)
            self.display.flush()

    def watch_active_window(self, callback, on_lost):
        """Call callback(id or None) whenever the active window changes; on_lost() if the compositor goes away."""
        self._callback = callback
        self._on_lost = on_lost
        self._last_active = self.active_window()
        GLib.io_add_watch(self.display.get_fd(), GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, self._pump)

    def _pump(self, _fd, cond):
        if cond & (GLib.IO_HUP | GLib.IO_ERR):
            self._on_lost()
            return False
        try:
            self.display.dispatch(block=True)  # the fd is readable: this reads it and does not wait
            self.display.flush()
        except Exception:  # the connection broke: the compositor is gone
            self._on_lost()
            return False
        return True
