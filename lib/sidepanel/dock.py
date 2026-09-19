"""The panel: an autohiding dock with the focused browser's containers and tabs.

Two dock windows on the same screen edge:
  * the strip: a thin, always-mapped window. It is the hover target and is tinted in the
    active browser's colour, so the active browser is recognisable even while collapsed;
  * the panel: the full-width window with the tab list, mapped only while expanded. Its
    header always names the browser, so it stays clear which browser is active even when
    window borders are hidden.
The panel is only ever resized while unmapped and then shown or hidden. Resizing a mapped
GTK window while its content appears makes GTK fight the size request (it snaps back to
the content's minimum width).
"""
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkX11", "3.0")
from gi.repository import Gdk, GdkX11, GLib, Gtk, Pango  # noqa: E402,F401

from . import geometry  # noqa: E402
from .autohide import Autohide  # noqa: E402
from .model import DEFAULT_ACCENT, accent, browser_label, focused_window, group_tabs, tab_label  # noqa: E402

CSS = """
.sp-strip {{ background-color: {accent}; }}
.sp-panel {{ background-color: #1b1d23; }}
.sp-content {{ background-color: #1b1d23; color: #dfe3ea; }}
.sp-header {{ background-color: #23262e; border-top: 3px solid {accent}; padding: 5px 8px; }}
.sp-browser {{ font-weight: bold; color: {accent}; }}
.sp-section {{ padding: 6px 8px 3px 6px; color: #aab2c0; }}
.sp-row {{ border-left: 3px solid transparent; }}
.sp-row:hover {{ background-color: #2a2e38; }}
.sp-row.active {{ background-color: #2f3542; border-left-color: {accent}; }}
.sp-row.active label {{ font-weight: bold; }}
.sp-tab {{ padding: 4px 10px 4px 19px; }}
.sp-empty {{ padding: 16px; color: #7d8594; }}
button.sp-btn {{ padding: 0 6px; min-height: 0; min-width: 0; background: none; border: none; box-shadow: none; color: #aab2c0; }}
button.sp-btn:hover {{ color: #ffffff; }}
button.sp-btn.sp-pin {{ border: 1px solid #454b58; border-radius: 9px; padding: 0 8px; }}
button.sp-btn.sp-pin:hover {{ border-color: #7d8594; }}
button.sp-btn.sp-pin:checked {{ background-color: {accent}; border-color: {accent}; color: #1b1d23; font-weight: bold; }}
button.sp-btn.sp-quit {{ margin-left: 6px; }}
button.sp-btn.sp-quit:hover {{ color: #ff6b6b; }}
"""

# Firefox container icon names -> a glyph (best effort; unknown names fall back to a dot)
ICONS = {
    "fingerprint": "☺", "briefcase": "💼", "dollar": "$", "cart": "🛒", "circle": "●",
    "gift": "🎁", "vacation": "🌴", "food": "🍴", "fruit": "🍎", "pet": "🐾",
    "tree": "🌲", "chill": "❄",
}


def _schedule(ms, fn):
    return GLib.timeout_add(ms, lambda: fn() or False)


class DockView:
    def __init__(self, cfg, on_activate, on_quit, xconn=None):
        self.cfg = dict(cfg)
        self.on_activate = on_activate
        self.x = xconn
        self.conn = None
        self.info = {}
        self.state = {}
        self.collapsed = set()  # (browser pid, cookieStoreId) of folded container sections
        self.hidden = False
        self._last = None  # (conn, state, folds, accent) of the last render, to skip identical ones
        self._accent = None
        self._warned_monitor = False

        GLib.set_prgname("openbox-sidepanel")
        self._css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), self._css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        self._set_accent(DEFAULT_ACCENT)

        self.strip = self._dock_window("sp-strip", "openbox-sidepanel-strip")
        self.win = self._dock_window("sp-panel", "openbox-sidepanel-panel")
        self.win.connect("destroy", lambda _w: on_quit())

        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.content.get_style_context().add_class("sp-content")

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        header.get_style_context().add_class("sp-header")
        self.browser_name = Gtk.Label(label="", xalign=0)
        self.browser_name.get_style_context().add_class("sp-browser")
        self.quit_btn = self._button("✕", "Quit sidepanel", Gtk.Button)
        self.quit_btn.get_style_context().add_class("sp-quit")
        self.quit_btn.connect("clicked", lambda _b: on_quit())
        self.flip_btn = self._button("⇄", "Switch side", Gtk.Button)
        self.flip_btn.connect("clicked", lambda _b: self.set_side("right" if self.cfg["side"] == "left" else "left"))
        self.pin_btn = self._button("pin", "Pin: keep the panel open", Gtk.ToggleButton)
        self.pin_btn.get_style_context().add_class("sp-pin")
        self.pin_btn.connect("toggled", self._on_pin_toggled)
        header.pack_start(self.browser_name, True, True, 0)
        header.pack_end(self.quit_btn, False, False, 0)  # rightmost
        header.pack_end(self.flip_btn, False, False, 0)
        header.pack_end(self.pin_btn, False, False, 0)

        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.scroll.add(self.list)

        self.content.pack_start(header, False, False, 0)
        self.content.pack_start(self.scroll, True, True, 0)
        self.win.get_child().add(self.content)
        self.win.get_child().show_all()  # the panel window itself is only shown while expanded
        self.strip.get_child().show()
        self.clear()

        self.autohide = Autohide(self._apply, _schedule, GLib.source_remove)
        self.pin_btn.set_active(self.cfg["pinned"])
        self._place()
        self.strip.show()
        self.autohide.set_pinned(self.cfg["pinned"])  # pinned: expands (and shows the panel) right away
        self._place()  # the strut needs the panel window realized

    # -- view API used by app.Panel ------------------------------------------------

    @property
    def xids(self):
        """XIDs of our own windows (so the panel can ignore them as 'active window')."""
        return {w.get_window().get_xid() for w in (self.strip, self.win) if w.get_window() is not None}

    def show(self, conn, info, state):
        self.conn = conn
        self.info = info
        self.state = state
        self.browser_name.set_text(info.get("browser") or "browser")
        self.browser_name.set_tooltip_text(browser_label(info))
        colour = accent(info)
        snapshot = (conn, state, frozenset(self.collapsed), colour)
        self._set_accent(colour)
        if snapshot != self._last:
            self._last = snapshot
            self._rebuild()

    def clear(self):
        self.conn = None
        self.info = {}
        self.state = {}
        self._last = None
        self.browser_name.set_text("")
        self._set_accent(DEFAULT_ACCENT)
        self._replace_rows([self._label("Waiting for a browser with the Sidepanel extension", "sp-empty", wrap=True)])

    def set_hidden(self, hidden):
        if hidden == self.hidden:
            return
        self.hidden = hidden
        if hidden:
            self._sync_strut(self._monitor_rect())  # drop the reservation before unmapping
            self.strip.hide()
            self.win.hide()
        else:
            self._place()
            self.strip.show()
            if self.autohide.expanded:
                self.win.show()
            self._place()

    def set_side(self, side):
        self.cfg["side"] = side
        self._place()

    def _on_pin_toggled(self, button):
        # the state must be readable at a glance: the word, the filled pill and the tooltip all change
        pinned = button.get_active()
        button.set_label("pinned" if pinned else "pin")
        button.set_tooltip_text("Unpin: let the panel hide again" if pinned else "Pin: keep the panel open")
        self.set_pinned(pinned)

    def set_pinned(self, pinned):
        if pinned == self.cfg["pinned"] and pinned == self.autohide.pinned:
            return
        self.cfg["pinned"] = pinned
        self.pin_btn.set_active(pinned)
        self.autohide.set_pinned(pinned)
        self._place()  # the strut depends on pinned even when the expanded state did not change

    def reconfigure(self, cfg):
        """Apply a reloaded config (SIGHUP). The file wins over runtime pin/side changes."""
        self.cfg = dict(cfg)
        self._warned_monitor = False
        self.set_pinned(self.cfg["pinned"])  # syncs the button, autohide and strut in one place
        self._place()  # side, width or monitor may have changed too

    # -- windows -------------------------------------------------------------------

    def _dock_window(self, css_class, title):
        win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        win.set_title(title)
        win.set_type_hint(Gdk.WindowTypeHint.DOCK)
        win.set_decorated(False)
        win.set_keep_above(True)
        win.set_skip_taskbar_hint(True)
        win.set_skip_pager_hint(True)
        win.set_accept_focus(False)  # clicks must not steal focus from the browser
        win.set_focus_on_map(False)
        win.stick()
        win.get_style_context().add_class(css_class)
        # An EventBox child owns the hover events: a childless GTK toplevel never selects
        # Enter/LeaveWindow, so the bare strip would not see the pointer.
        box = Gtk.EventBox()
        box.get_style_context().add_class(css_class)
        box.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        box.connect("enter-notify-event", lambda _w, _e: self.autohide.enter())
        box.connect("leave-notify-event", self._on_leave)
        win.add(box)
        return win

    def _monitors(self):
        display = Gdk.Display.get_default()
        return display, [display.get_monitor(i) for i in range(display.get_n_monitors())]

    def _monitor_rect(self):
        display, monitors = self._monitors()
        name = self.cfg["monitor"]
        mon = None
        if name != "primary":
            mon = next((m for m in monitors if m.get_model() == name), None)
            if mon is None and not self._warned_monitor:
                self._warned_monitor = True
                print(f"sidepanel: no monitor named {name!r}, using the primary one", file=sys.stderr)
        mon = mon or display.get_primary_monitor() or monitors[0]
        r = mon.get_geometry()
        return (r.x, r.y, r.width, r.height)

    def _place(self):
        mon = self._monitor_rect()
        for win, expanded in ((self.strip, False), (self.win, True)):
            x, y, w, h = geometry.dock_rect(mon, self.cfg["side"], self.cfg["width"], expanded)
            win.set_default_size(w, h)
            win.resize(w, h)
            win.move(x, y)
        self._sync_strut(mon)

    def _sync_strut(self, mon):
        if self.x is None or not self.win.get_realized():
            return
        values = None
        if self.cfg["pinned"] and not self.hidden:
            screen_w = max(m.get_geometry().x + m.get_geometry().width for m in self._monitors()[1])
            values = geometry.strut(mon, screen_w, self.cfg["side"], self.cfg["width"])
        self.x.set_strut(self.win.get_window().get_xid(), values)

    def _apply(self, expanded):
        if self.hidden:
            return
        if expanded:
            self._place()  # sized while still unmapped
            self.win.show()
        else:
            self.win.hide()

    def _on_leave(self, _win, event):
        if event.detail != Gdk.NotifyType.INFERIOR:  # moving onto a child widget is not leaving
            self.autohide.leave()

    # -- content -------------------------------------------------------------------

    def _button(self, label, tooltip, kind):
        button = kind(label=label)
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.set_can_focus(False)
        button.set_tooltip_text(tooltip)
        button.get_style_context().add_class("sp-btn")
        return button

    def _label(self, text, css_class, markup=False, wrap=False):
        label = Gtk.Label(xalign=0)
        (label.set_markup if markup else label.set_text)(text)
        if wrap:
            label.set_line_wrap(True)
        else:
            label.set_ellipsize(Pango.EllipsizeMode.END)
        label.get_style_context().add_class(css_class)
        return label

    def _clickable(self, child, handler, active=False):
        # hover/active styling lives on the EventBox: a windowless label gets no prelight
        box = Gtk.EventBox()
        box.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        box.connect("button-press-event", lambda _b, ev: handler(ev) if ev.button == 1 else None)
        box.get_style_context().add_class("sp-row")
        if active:
            box.get_style_context().add_class("active")
        box.add(child)
        return box

    def _set_accent(self, colour):
        if colour == self._accent:
            return  # reloading the provider restyles every widget: only do it on a real change
        self._accent = colour
        self._css_data = CSS.format(accent=colour)
        self._css.load_from_data(self._css_data.encode())

    def _replace_rows(self, rows):
        adj = self.scroll.get_vadjustment()
        value = adj.get_value()
        for child in self.list.get_children():
            self.list.remove(child)
        for row in rows:
            self.list.pack_start(row, False, False, 0)
        self.list.show_all()
        GLib.idle_add(lambda: adj.set_value(value) or False)  # keep the scroll position across refreshes

    def _rebuild(self):
        window = focused_window(self.state)
        if window is None:
            self._replace_rows([self._label("No browser windows", "sp-empty", wrap=True)])
            return
        rows = []
        for container, tabs in group_tabs(self.state):
            # per browser process: two profiles of the same browser fold independently
            key = (self.info.get("browserPid") or self.info.get("browser"), container["cookieStoreId"])
            folded = key in self.collapsed
            rows.append(self._section(container, tabs, key, folded))
            if not folded:
                rows.extend(self._tab_row(tab, window["id"]) for tab in tabs)
        self._replace_rows(rows)

    def _section(self, container, tabs, key, folded):
        colour = container.get("colorCode") or DEFAULT_ACCENT
        icon = ICONS.get(container.get("icon"), "●")
        name = GLib.markup_escape_text(container["name"])
        arrow = "▸" if folded else "▾"
        markup = (
            f'<span foreground="{colour}">▌</span> {icon} <b>{name}</b> '
            f'<span alpha="60%">({len(tabs)})</span>'
            + (f'  <span alpha="50%">{arrow}</span>' if tabs else "")
        )
        label = self._label(markup, "sp-section", markup=True)
        return self._clickable(label, lambda _ev: self._toggle(key)) if tabs else label

    def _toggle(self, key):
        self.collapsed ^= {key}
        self._last = None
        self._rebuild()

    def _tab_row(self, tab, window_id):
        label = self._label(tab_label(tab), "sp-tab")
        label.set_tooltip_text("\n".join(filter(None, (tab.get("title"), tab.get("url")))))
        return self._clickable(
            label, lambda _ev: self.on_activate(self.conn, tab["id"], window_id), active=bool(tab.get("active"))
        )
