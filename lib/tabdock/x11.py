"""X11 plumbing over python-xlib: active-window tracking, struts, raising windows.

Uses its own connection, separate from GDK's, and plugs into the GLib main loop
through the connection's file descriptor (no polling).
"""
from Xlib import X, Xatom, display, error, protocol
from Xlib.error import DisplayError
from gi.repository import GLib


def connect():
    """An XConn, or None when there is no usable X display (headless tests)."""
    try:
        return XConn(display.Display())
    except (DisplayError, OSError):
        return None


class XConn:
    def __init__(self, disp):
        self.d = disp
        self.root = disp.screen().root
        self.a_active = disp.intern_atom("_NET_ACTIVE_WINDOW")
        self.a_pid = disp.intern_atom("_NET_WM_PID")
        self.a_stacking = disp.intern_atom("_NET_CLIENT_LIST_STACKING")
        self.a_strut = disp.intern_atom("_NET_WM_STRUT")
        self.a_strut_partial = disp.intern_atom("_NET_WM_STRUT_PARTIAL")
        self._callback = None
        self._on_lost = None
        self._kick_pending = False

    def active_window(self):
        """XID of the active window, or None."""
        try:
            prop = self.root.get_full_property(self.a_active, X.AnyPropertyType)
        except error.XError:
            return None
        finally:
            self._kick()
        return prop.value[0] if prop is not None and len(prop.value) and prop.value[0] else None

    def _pid(self, win):
        prop = win.get_full_property(self.a_pid, X.AnyPropertyType)
        return int(prop.value[0]) if prop is not None and len(prop.value) else None

    def window_info(self, xid):
        """(pid or None, (WM_CLASS instance, class) or ()) for a window."""
        try:
            win = self.d.create_resource_object("window", xid)
            return self._pid(win), tuple(win.get_wm_class() or ())
        except error.XError:  # window vanished meanwhile
            return None, ()
        finally:
            self._kick()

    def window_pid(self, xid):
        """The pid behind a window, or None."""
        try:
            return self._pid(self.d.create_resource_object("window", xid))
        except error.XError:  # window vanished meanwhile
            return None
        finally:
            self._kick()

    def client_windows(self):
        """XIDs of every window the window manager manages, bottom to top."""
        try:
            prop = self.root.get_full_property(self.a_stacking, X.AnyPropertyType)
        except error.XError:
            return []
        finally:
            self._kick()
        return list(prop.value) if prop is not None else []

    def watch_active_window(self, callback, on_lost):
        """Call callback(xid or None) whenever the active window changes; on_lost() if X goes away."""
        self._callback = callback
        self._on_lost = on_lost
        self.root.change_attributes(event_mask=X.PropertyChangeMask)
        self.d.flush()
        GLib.io_add_watch(
            self.d.fileno(), GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, self._pump
        )

    def _active_changed(self):
        changed = False
        while self.d.pending_events():
            ev = self.d.next_event()
            if ev.type == X.PropertyNotify and ev.atom == self.a_active:
                changed = True
        return changed

    def _pump(self, _fd=None, cond=GLib.IO_IN):
        if cond & (GLib.IO_HUP | GLib.IO_ERR):
            self._on_lost()
            return False
        try:
            while self._active_changed():
                self._callback(self.active_window())  # its requests may queue more events: loop again
        except (error.ConnectionClosedError, OSError):
            self._on_lost()
            return False
        return True

    def _kick(self):
        """A request that waited for a reply may have queued events without the socket
        becoming readable again, so the fd watch would never fire for them: drain later."""
        if self._callback is not None and not self._kick_pending and self.d.pending_events():
            self._kick_pending = True
            GLib.idle_add(self._kick_run)

    def _kick_run(self):
        self._kick_pending = False
        self._pump()
        return False

    def set_strut(self, xid, values):
        """Reserve screen space for a docked window; values=None removes the reservation."""
        win = self.d.create_resource_object("window", xid)
        if values is None:
            win.delete_property(self.a_strut_partial)
            win.delete_property(self.a_strut)
        else:
            win.change_property(self.a_strut_partial, Xatom.CARDINAL, 32, values)
            win.change_property(self.a_strut, Xatom.CARDINAL, 32, values[:4])
        self.d.flush()

    def activate(self, xid):
        """Ask the window manager to focus and raise a window (EWMH, as a pager would)."""
        win = self.d.create_resource_object("window", xid)
        event = protocol.event.ClientMessage(
            window=win, client_type=self.a_active, data=(32, [2, X.CurrentTime, 0, 0, 0])
        )
        self.root.send_event(event, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
        self.d.flush()
