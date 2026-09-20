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
import json
import os
import sys
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkX11", "3.0")
from gi.repository import Gdk, GdkX11, GLib, Gtk, Pango  # noqa: E402,F401

from . import geometry  # noqa: E402
from .autohide import Autohide  # noqa: E402
from .model import (  # noqa: E402
    DEFAULT_ACCENT,
    NO_CONTAINER,
    accent,
    browser_label,
    focused_window,
    group_tabs,
    reordered,
    tab_label,
    tab_move_index,
)

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
.sp-row.dragging {{ opacity: 0.45; }}
.sp-row.drop-before {{ box-shadow: inset 0 2px 0 0 {accent}; }}
.sp-row.drop-after {{ box-shadow: inset 0 -2px 0 0 {accent}; }}
"""

# Firefox container icon names -> a glyph (best effort; unknown names fall back to a dot)
ICONS = {
    "fingerprint": "☺", "briefcase": "💼", "dollar": "$", "cart": "🛒", "circle": "●",
    "gift": "🎁", "vacation": "🌴", "food": "🍴", "fruit": "🍎", "pet": "🐾",
    "tree": "🌲", "chill": "❄",
}


DRAG_THRESHOLD = 6  # px the pointer must travel with the button down before a click becomes a drag
PRESS_STALE_S = 30  # a press with no release this long is forgotten, so updates cannot stay blocked


def _schedule(ms, fn):
    return GLib.timeout_add(ms, lambda: fn() or False)


class DockView:
    def __init__(self, cfg, on_activate, on_quit, xconn=None, on_command=None):
        self.cfg = dict(cfg)
        self.on_activate = on_activate
        self.on_command = on_command  # on_command(conn, message): what a drop asks the browser to do
        self.x = xconn
        self._meta = {}  # row widget -> what it stands for (kind, id, group, click handler, draggable)
        self._row_order = []  # row widgets in display order
        self._press = None  # the button-1 press in progress: {box, x, y, t, dragging, target, after}
        self._deferred = None  # a state update that arrived mid-drag, applied after the drop
        self._dump_path = os.environ.get("SIDEPANEL_LAYOUT_DUMP")  # a test hook: off unless set at start
        self._dump_pending = False
        self.conn = None
        self.info = {}
        self.state = {}
        self.collapsed = set()  # (browser pid, cookieStoreId) of folded container sections
        self.hidden = False
        self._last = None  # (conn, state, folds, accent) of the last render, to skip identical ones
        self._accent = None
        self._warned_monitor = False
        self._overlay = False  # pinned, but on an inner edge where no space can be reserved
        self._relayout_id = None
        self._screen_handlers = []
        self._closed = False

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
        screen = Gdk.Screen.get_default()
        for signal in ("monitors-changed", "size-changed"):  # docking, xrandr: follow the new layout
            self._screen_handlers.append((screen, screen.connect(signal, self._on_monitors_changed)))
        self.win.connect("destroy", self._teardown)
        if self._dump_path:  # test hook, see _dump_layout: costs nothing in normal use
            self.win.connect("size-allocate", lambda *_a: self._schedule_dump())

    # -- view API used by app.Panel ------------------------------------------------

    @property
    def xids(self):
        """XIDs of our own windows (so the panel can ignore them as 'active window')."""
        return {w.get_window().get_xid() for w in (self.strip, self.win) if w.get_window() is not None}

    def show(self, conn, info, state):
        if self._press is not None and not self._pressing():
            self._end_press()  # a press whose release never came: let go of the hold and the drag marks
        if self._pressing():
            self._deferred = (conn, info, state)  # rows are being pressed or dragged: redraw after the drop
            return
        self._deferred = None
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
        self._end_press()
        self._deferred = None
        self.conn = None
        self.info = {}
        self.state = {}
        self._last = None
        self._meta, self._row_order = {}, []
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

    def _refresh_pin(self):
        # the state must be readable at a glance: the words, the filled pill and the tooltip all change
        pinned = self.pin_btn.get_active()
        if pinned and self._overlay:
            label = "pinned (overlay)"
            tip = (
                "Unpin. This screen edge borders another monitor, so windows are not resized to make "
                'room. An outer screen edge can reserve space: set monitor = "outer".'
            )
        elif pinned:
            label, tip = "pinned", "Unpin: let the panel hide again"
        else:
            label, tip = "pin", "Pin: keep the panel open"
        self.pin_btn.set_label(label)
        self.pin_btn.set_tooltip_text(tip)

    def _on_pin_toggled(self, button):
        self._refresh_pin()
        self.set_pinned(button.get_active())

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

    def _layout(self):
        """([(x, y, w, h)], [output names], primary index or None) of the connected monitors."""
        display = Gdk.Display.get_default()
        monitors = [display.get_monitor(i) for i in range(display.get_n_monitors())]
        if not monitors:  # a moment in the middle of an xrandr change: treat the screen as one monitor
            root = Gdk.Screen.get_default().get_root_window()
            return [(0, 0, root.get_width(), root.get_height())], [None], 0
        rects = []
        for m in monitors:
            r = m.get_geometry()
            rects.append((r.x, r.y, r.width, r.height))
        primary = display.get_primary_monitor()
        return rects, [m.get_model() for m in monitors], (monitors.index(primary) if primary in monitors else None)

    def _monitor_rect(self):
        """The monitor the panel sits on: "outer" (the screen-edge monitor for the side), "primary",
        or an output name. A name that is not connected falls back to "outer"."""
        rects, names, primary = self._layout()
        name = self.cfg["monitor"]
        if name == "primary":
            index = primary if primary is not None else 0
        elif name != "outer" and name in names:
            self._warned_monitor = False  # seen again: warn once more if it goes missing later
            index = names.index(name)
        else:  # "outer", or an output name that is not connected
            if name != "outer" and not self._warned_monitor:
                self._warned_monitor = True
                print(f"sidepanel: no monitor named {name!r}, using the outer screen edge", file=sys.stderr)
            index = geometry.outer_monitor(rects, self.cfg["side"], primary)
        return rects[index]

    def _place(self):
        mon = self._monitor_rect()
        for win, expanded in ((self.strip, False), (self.win, True)):
            x, y, w, h = geometry.dock_rect(mon, self.cfg["side"], self.cfg["width"], expanded)
            win.set_default_size(w, h)
            win.resize(w, h)
            win.move(x, y)
        self._sync_strut(mon)

    def _sync_strut(self, mon):
        values = None
        if self.cfg["pinned"] and not self.hidden:
            screen_w = max(x + w for x, _, w, _ in self._layout()[0])
            values = geometry.strut(mon, screen_w, self.cfg["side"], self.cfg["width"])
        # pinned on an inner edge cannot reserve space: the pin says so instead of silently overlaying
        self._set_overlay(self.cfg["pinned"] and not self.hidden and values is None)
        if self.x is not None and self.win.get_realized():
            self.x.set_strut(self.win.get_window().get_xid(), values)

    def _set_overlay(self, overlay):
        if overlay != self._overlay:
            self._overlay = overlay
            self._refresh_pin()

    def _on_monitors_changed(self, *_args):
        # plugging a screen or an xrandr change emits several signals in a burst: re-place once, after
        if self._relayout_id is None:
            self._relayout_id = GLib.timeout_add(300, self._relayout)

    def _relayout(self):
        self._relayout_id = None
        if not self._closed:
            self._place()
        return False

    def _teardown(self, *_args):
        """The panel window is gone: stop reacting to monitor changes."""
        self._closed = True
        if self._relayout_id is not None:
            GLib.source_remove(self._relayout_id)
            self._relayout_id = None
        for screen, handler in self._screen_handlers:
            screen.disconnect(handler)
        self._screen_handlers = []

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

    def _row(self, child, kind, ident, group, on_click, active=False, draggable=True, pinned=False):
        """A row. Hover/active styling lives on the EventBox: a windowless label gets no prelight.

        A click and a drag share one press, so they never both happen: the click fires on release,
        and moving DRAG_THRESHOLD px with the button down turns the press into a drag instead.
        """
        box = Gtk.EventBox()
        box.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.BUTTON1_MOTION_MASK
        )
        box.connect("button-press-event", self._on_press)
        box.connect("motion-notify-event", self._on_motion)
        box.connect("button-release-event", self._on_release)
        box.get_style_context().add_class("sp-row")
        if active:
            box.get_style_context().add_class("active")
        box.add(child)
        self._meta[box] = {
            "kind": kind, "id": ident, "group": group, "click": on_click, "draggable": draggable, "pinned": pinned,
        }
        self._row_order.append(box)
        return box

    # -- pressing, clicking and dragging rows ---------------------------------------

    def _pressing(self):
        p = self._press
        return p is not None and time.monotonic() - p["t"] < PRESS_STALE_S

    def _end_press(self):
        p, self._press = self._press, None
        if p is not None and p["dragging"]:
            self._clear_marks(p)
            self.autohide.set_held(False)

    def _on_press(self, box, event):
        if event.button == 1 and box in self._meta:
            self._press = {"box": box, "x": event.x_root, "y": event.y_root, "t": time.monotonic(),
                           "dragging": False, "target": None, "after": False}
        return False

    def _on_motion(self, box, event):
        p = self._press
        if p is None or p["box"] is not box or not self._meta.get(box, {}).get("draggable"):
            return False
        if not p["dragging"]:
            if max(abs(event.x_root - p["x"]), abs(event.y_root - p["y"])) < DRAG_THRESHOLD:
                return False
            p["dragging"] = True
            self.autohide.set_held(True)  # the pointer may leave the panel mid-drag: stay open
            box.get_style_context().add_class("dragging")
        self._point_at(p, box, event)
        return True

    def _on_release(self, box, event):
        p = self._press
        if event.button != 1 or p is None or p["box"] is not box:
            return False  # another button, or not our press: a button-1 press in progress carries on
        self._press = None
        if p["dragging"]:
            self._drop(p)
        elif box in self._meta:
            self._meta[box]["click"]()
        d, self._deferred = self._deferred, None
        if d is not None:
            self.show(*d)  # what the browser reported while the rows were being dragged
        return True

    def _drop_candidates(self, box):
        """The rows the dragged one can be dropped between: same kind; for tabs the same container and the
        same pinned-ness, because Firefox keeps pinned tabs in front and clamps a move across that line."""
        meta = self._meta[box]
        return [
            b for b in self._row_order
            if self._meta[b]["draggable"]
            and self._meta[b]["kind"] == meta["kind"]
            and (
                meta["kind"] == "section"
                or (self._meta[b]["group"] == meta["group"] and self._meta[b]["pinned"] == meta["pinned"])
            )
        ]

    def _point_at(self, p, box, event):
        """Mark where a drop would land: before the first candidate whose middle is below the pointer."""
        pos = box.translate_coordinates(self.list, int(event.x), int(event.y))
        candidates = self._drop_candidates(box)
        if pos is None or not candidates:
            return
        if self._meta[box]["kind"] == "tab":
            # A tab only moves within its own container: pointing well outside that group's rows
            # (one row of slack) cancels the drop instead of snapping the tab to the group's end.
            rects = [c.get_allocation() for c in candidates]
            slack = max(a.height for a in rects)
            if pos[1] < min(a.y for a in rects) - slack or pos[1] > max(a.y + a.height for a in rects) + slack:
                if p["target"] is not None:
                    self._unmark(p["target"])
                p["target"] = None
                return
        target, after = candidates[-1], True
        for c in candidates:
            a = c.get_allocation()
            if pos[1] < a.y + a.height / 2:
                target, after = c, False
                break
        old = p["target"]
        if old is not None and (old is not target or p["after"] != after):
            self._unmark(old)
        p["target"], p["after"] = target, after
        ctx = target.get_style_context()
        ctx.remove_class("drop-before" if after else "drop-after")
        ctx.add_class("drop-after" if after else "drop-before")

    def _unmark(self, row):
        ctx = row.get_style_context()
        ctx.remove_class("drop-before")
        ctx.remove_class("drop-after")

    def _clear_marks(self, p):
        p["box"].get_style_context().remove_class("dragging")
        if p["target"] is not None:
            self._unmark(p["target"])

    def _command(self, message):
        if self.on_command is not None and self.conn is not None:
            self.on_command(self.conn, message)

    def _drop(self, p):
        box, target = p["box"], p["target"]
        self._clear_marks(p)
        self.autohide.set_held(False)
        if target is None or box not in self._meta or target not in self._meta:
            return
        candidates = self._drop_candidates(box)
        at = candidates.index(target) + (1 if p["after"] else 0)
        before = self._meta[candidates[at]]["id"] if at < len(candidates) else None  # lands in front of this
        meta = self._meta[box]
        if meta["kind"] == "section":
            ids = [self._meta[b]["id"] for b in candidates]
            order = reordered(ids, meta["id"], before)
            if order != ids:
                self._command({"type": "set_container_order", "order": order})
                self.state = {**self.state, "containerOrder": order}  # show it at once; the browser confirms
                self._last = None
                self._rebuild()
        else:
            # the tabs it can land among: same container and same pinned-ness (see _drop_candidates)
            group = next((tabs for c, tabs in group_tabs(self.state) if c["cookieStoreId"] == meta["group"]), [])
            group = [t for t in group if bool(t.get("pinned")) == meta["pinned"]]
            if meta["id"] not in {t["id"] for t in group}:
                return  # the state changed under the drag (browser switched, tab closed): nothing to do
            index = tab_move_index(group, meta["id"], before)
            if index is not None:
                self._command({"type": "move_tab", "tabId": meta["id"], "index": index})

    # -- test hook ---------------------------------------------------------------------

    def _schedule_dump(self):
        if self._dump_path and not self._dump_pending:
            self._dump_pending = True
            GLib.idle_add(self._dump_layout)

    def _dump_layout(self):
        """SIDEPANEL_LAYOUT_DUMP=<file> writes where every row is, in screen pixels, so an end-to-end
        test can drag with a real pointer without guessing coordinates."""
        self._dump_pending = False
        path = self._dump_path
        if not path:
            return False
        wx, wy = self.win.get_position()
        root = self.win.get_child()
        rows = []
        for box in self._row_order:
            meta = self._meta.get(box)
            if meta is None:
                continue
            a = box.get_allocation()
            pos = box.translate_coordinates(root, 0, 0) or (a.x, a.y)  # unmapped: the list-relative fallback
            rows.append({"kind": meta["kind"], "id": meta["id"], "group": meta["group"],
                         "x": wx + pos[0], "y": wy + pos[1], "w": a.width, "h": a.height})
        with open(path + ".tmp", "w") as f:
            json.dump(rows, f)
        os.replace(path + ".tmp", path)
        return False

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
        self._schedule_dump()

    def _rebuild(self):
        self._meta, self._row_order = {}, []
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
                rows.extend(self._tab_row(tab, window["id"], container["cookieStoreId"]) for tab in tabs)
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
        cid = container["cookieStoreId"]
        # "No container" stays first, and a store the browser does not list as a container (private
        # windows, say) cannot be ordered: the next snapshot would put it straight back
        known = {c["cookieStoreId"] for c in self.state.get("containers") or []}
        return self._row(
            label, "section", cid, None, (lambda: self._toggle(key)) if tabs else (lambda: None),
            draggable=cid != NO_CONTAINER and cid in known,
        )

    def _toggle(self, key):
        self.collapsed ^= {key}
        self._last = None
        self._rebuild()

    def _tab_row(self, tab, window_id, group):
        label = self._label(tab_label(tab), "sp-tab")
        label.set_tooltip_text("\n".join(filter(None, (tab.get("title"), tab.get("url")))))
        return self._row(
            label, "tab", tab["id"], group, lambda: self.on_activate(self.conn, tab["id"], window_id),
            active=bool(tab.get("active")), pinned=bool(tab.get("pinned")),
        )
