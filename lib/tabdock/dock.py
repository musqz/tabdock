"""The panel: an autohiding dock with the containers and tabs of the browser in use, of one chosen
browser, or of all open browsers (chips under the header choose).

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
import hashlib
import json
import os
import sys
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkX11", "3.0")
from gi.repository import Gdk, GdkX11, GLib, Gtk, Pango  # noqa: E402,F401

from . import config, favicons, geometry  # noqa: E402
from .autohide import Autohide  # noqa: E402
from .model import (  # noqa: E402
    ACCENTS,
    DARK_TEXT,
    DEFAULT_ACCENT,
    FEATURES,
    KNOWN_BROWSERS,
    NO_CONTAINER,
    WS_COLORS,
    accent,
    accents,
    browser_label,
    browser_theme_key,
    colour_name,
    edits_workspaces,
    removal_text,
    reopenable,
    tab_group,
    GROUP_COLORS,
    supports,
    focused_window,
    group_tabs,
    heir,
    matches,
    offers_workspaces,
    on_accent,
    ordered_containers,
    reordered,
    step_index,
    tab_badge,
    tab_label,
    tab_move_index,
    waiting_text,
    workspace_label,
    workspace_step,
    workspaces,
)

CSS = """
.sp-strip {{ background-color: {accent}; }}
.sp-panel {{ background-color: #1b1d23; }}
.sp-content {{ background-color: #1b1d23; color: #dfe3ea; }}
.sp-header {{ background-color: #23262e; border-top: 3px solid {accent}; padding: 5px 8px; }}
.sp-browser {{ font-weight: bold; color: {name}; }}
.sp-sectionbox {{ padding: 6px 8px 3px 6px; }}
.sp-section {{ padding: 0; color: #aab2c0; }}
.sp-row {{ border-left: 3px solid transparent; }}
.sp-row:hover {{ background-color: #2a2e38; }}
.sp-row.active {{ background-color: #2f3542; border-left-color: {accent}; }}
.sp-row.active label {{ font-weight: bold; }}
.sp-row.kbd {{ background-color: #2a2e38; border-left-color: {accent}; }}
.sp-tabbox {{ padding: 4px 10px 4px 19px; }}
.sp-tab {{ padding: 0; }}
.sp-badge {{ background-color: #e64553; color: #ffffff; font-weight: bold; font-size: 0.8em; padding: 0 5px; border-radius: 8px; }}
.sp-empty {{ padding: 16px; color: #7d8594; }}
button.sp-btn {{ padding: 0 6px; min-height: 0; min-width: 0; background: none; border: none; box-shadow: none; color: #aab2c0; }}
button.sp-btn:hover {{ color: #ffffff; }}
button.sp-btn.sp-pin {{ border: 1px solid #454b58; border-radius: 9px; padding: 0 8px; }}
button.sp-btn.sp-pin:hover {{ border-color: #7d8594; }}
button.sp-btn.sp-pin:checked {{ background-color: {accent}; border-color: {accent}; color: {on_accent}; font-weight: bold; }}
button.sp-btn.sp-quit {{ margin-left: 6px; }}
button.sp-btn.sp-quit:hover {{ color: #ff6b6b; }}
button.sp-btn.sp-newtab {{ margin-left: 4px; }}
.sp-row.dragging {{ opacity: 0.45; }}
.sp-row.drop-before {{ box-shadow: inset 0 2px 0 0 {accent}; }}
.sp-row.drop-after {{ box-shadow: inset 0 -2px 0 0 {accent}; }}
.sp-chips {{ padding: 4px 6px 3px 6px; background-color: #1b1d23; }}
button.sp-btn.sp-chip {{ border: 1px solid #454b58; border-radius: 9px; padding: 0 8px; }}
button.sp-btn.sp-chip:hover {{ border-color: #7d8594; color: #ffffff; }}
button.sp-btn.sp-chip.selected {{ background-color: {accent}; border-color: {accent}; color: {on_accent}; font-weight: bold; }}
.sp-row.sp-bhead {{ border-left: none; margin-top: 6px; }}
.sp-bandlabel {{ padding: 5px 8px; color: #1b1d23; font-weight: bold; }}
.sp-wsrow {{ padding: 5px 6px 2px 6px; }}
button.sp-btn.sp-ws {{ border-radius: 4px; padding: 1px 8px; }}
button.sp-btn.sp-ws:hover {{ background-color: #2a2e38; color: #ffffff; }}
button.sp-btn.sp-ws.selected {{ background-color: #2f3542; color: #fff; font-weight: bold; box-shadow: inset 0 -2px 0 0 {accent}; }}
.sp-pinmark {{ font-size: 0.8em; }}
.sp-where {{ color: #7d8594; font-size: 0.85em; }}
.sp-group {{ font-size: 0.85em; font-weight: bold; }}
button.sp-btn.sp-close {{ opacity: 0; padding: 0 4px; }}
.sp-row:hover button.sp-btn.sp-close {{ opacity: 1; }}
button.sp-btn.sp-close:hover {{ color: #ff6b6b; }}
.sp-advanced {{ background-color: #1b1d23; padding: 2px 8px 6px 8px; }}
.sp-advrow {{ padding: 3px 0; }}
button.sp-btn.sp-swatch {{ min-width: 30px; min-height: 14px; border-radius: 4px; border: 1px solid #454b58; padding: 0; }}
button.sp-btn.sp-swatch:hover {{ border-color: #7d8594; }}
"""


# The keys of the find window that walk the tab rows: (rows to step, from nothing). Home and End step from
# nothing, which lands on the first or the last row.
FIND_KEYS = {
    Gdk.KEY_Down: (1, False), Gdk.KEY_Up: (-1, False),
    Gdk.KEY_Page_Down: (10, False), Gdk.KEY_Page_Up: (-10, False),
    Gdk.KEY_Home: (1, True), Gdk.KEY_End: (-1, True),
    Gdk.KEY_KP_Down: (1, False), Gdk.KEY_KP_Up: (-1, False),
    Gdk.KEY_KP_Page_Down: (10, False), Gdk.KEY_KP_Page_Up: (-10, False),
    Gdk.KEY_KP_Home: (1, True), Gdk.KEY_KP_End: (-1, True),
}
# With one of these down, Home and End are the entry's caret keys (Shift+Home selects). Super is not one of them:
# it is still down from the hotkey.
CARET_MODS = Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.MOD1_MASK
# The keys that switch workspace (workspaces to step), while the find window's entry is empty.
WORKSPACE_KEYS = {Gdk.KEY_Left: -1, Gdk.KEY_Right: 1, Gdk.KEY_KP_Left: -1, Gdk.KEY_KP_Right: 1}


def acc_class(colour):
    """The style class that carries one browser's colour, so several browsers can show at once."""
    return "acc-" + colour.lstrip("#")


# The colours that must differ from row to row (with several browsers listed, "the accent" is no
# longer one colour): the active tab, the drop marker and the chips. Loaded again only when [theme] changes.
def browser_css(colours):
    """The rules for each browser colour in `colours` (a text readable on it where it fills something)."""
    return "".join(
        f".sp-row.active.{acc_class(c)} {{ border-left-color: {c}; }}"
        f".sp-row.kbd.{acc_class(c)} {{ border-left-color: {c}; }}"
        f".sp-row.drop-before.{acc_class(c)} {{ box-shadow: inset 0 2px 0 0 {c}; }}"
        f".sp-row.drop-after.{acc_class(c)} {{ box-shadow: inset 0 -2px 0 0 {c}; }}"
        f"button.sp-btn.sp-chip.{acc_class(c)} {{ border-color: {c}; }}"
        f"button.sp-btn.sp-chip.{acc_class(c)}:hover {{ border-color: shade({c}, 1.35); }}"
        f"button.sp-btn.sp-chip.selected.{acc_class(c)} {{ background-color: {c}; border-color: {c}; color: {on_accent(c)}; }}"
        f".sp-bhead.{acc_class(c)} {{ background-color: {c}; }}"
        f".sp-bhead.{acc_class(c)}:hover {{ background-color: shade({c}, 1.15); }}"
        f".sp-bhead.{acc_class(c)} .sp-bandlabel {{ color: {on_accent(c)}; }}"
        f"button.sp-btn.sp-ws.selected.{acc_class(c)} {{ box-shadow: inset 0 -2px 0 0 {c}; }}"
        f"button.sp-btn.sp-swatch.{acc_class(c)} {{ background-color: {c}; }}"
        for c in sorted(set(colours))
    )


def ws_class(color):
    return "ws-" + color


# A workspace's own colour: a bar under its chip, and a full one when it is the workspace shown, where it
# takes the place of the browser's colour (one class more specific than that rule, so it wins).
WS_CSS = "".join(
    f"button.sp-btn.sp-ws.ws-col.{ws_class(name)} {{ box-shadow: inset 0 -2px 0 0 alpha({c}, 0.55); }}"
    f"button.sp-btn.sp-ws.ws-col.selected.{ws_class(name)} {{ box-shadow: inset 0 -3px 0 0 {c}; }}"
    for name, c in WS_COLORS.items()
)

# Firefox container icon names -> a glyph (best effort; unknown names fall back to a dot)
ICONS = {
    "fingerprint": "☺", "briefcase": "💼", "dollar": "$", "cart": "🛒", "circle": "●",
    "gift": "🎁", "vacation": "🌴", "food": "🍴", "fruit": "🍎", "pet": "🐾",
    "tree": "🌲", "chill": "❄", "fence": "🚧",
}
CONTAINER_ICONS = tuple(ICONS)  # the icons Firefox offers a container, in its order


DRAG_THRESHOLD = 6  # px the pointer must travel with the button down before a click becomes a drag
PRESS_STALE_S = 30  # a press with no release this long is forgotten, so updates cannot stay blocked
ICON_RETRY_S = 300  # an icon that could not be fetched (no network, a timeout) is tried again after this long
ICONS_KEPT = 512  # icons (and remembered failures) held in memory
ICONS_PENDING_MAX = 64  # icon downloads queued or running at once
NO_ICON = "No icon: "  # the start of what the empty icon slot says when hovered, followed by why
NOT_DOWNLOADED = "it could not be downloaded (no network, or a problem at the site); it is tried again later"
NAME_MAX = 64  # characters in a workspace name (the extension cuts longer ones too)
ICON_MAX = 8  # characters in a workspace icon: one emoji, even a composed one, or a few letters (as the extension)
# the icons a workspace's menu offers; "Other…" takes any
WS_ICONS = ("🏠", "💼", "📚", "💻", "🎮", "🎵", "🛒", "✈", "🧪", "📰", "💬", "⭐")


class Markup(str):
    """A menu label in Pango markup (a coloured swatch), where a plain str is shown as it is."""


def _schedule(ms, fn):
    return GLib.timeout_add(ms, lambda: fn() or False)


class DockView:
    def __init__(self, cfg, on_activate, on_quit, xconn=None, on_command=None, on_choose=None):
        self.cfg = dict(cfg)
        self.on_activate = on_activate
        self.on_command = on_command  # on_command(conn, message): what a drop asks the browser to do
        self.on_choose = on_choose  # on_choose("auto" | "all" | conn): a chip was clicked
        self.x = xconn
        self._meta = {}  # row widget -> what it stands for (kind, id, group, conn, click handler, draggable)
        self._row_order = []  # row widgets in display order
        self._press = None  # the button-1 press in progress: {box, x, y, t, dragging, target, after}
        self._deferred = None  # a state update that arrived mid-drag, applied after the drop
        self._dump_path = os.environ.get("TABDOCK_LAYOUT_DUMP")  # a test hook: off unless set at start
        self._dump_pending = False
        self.sources = []  # [(conn, hello, state)] of the browsers listed
        self._focus = None  # the hello of the browser in use, when several are listed
        self._ws_pending = None  # the workspace the last Left or Right asked for, until the browser reports its state
        # icons are known by _icon_key(url); all in memory only: nothing about your tabs is written to disk
        self._icons = {}  # -> 16 px pixbuf, least recently used first
        self._failed = {}  # -> when it did not work (tried again after ICON_RETRY_S)
        self._refused = {}  # -> why: it will never be an icon (not https, not an image, 404 ...): never asked again
        self._pending = set()  # being downloaded
        self._waiting = {}  # -> the image widgets of the rows built since, waiting for it
        self._fetcher = None  # started with the first icon wanted: no threads while icons are off
        self._redraw = False  # a redraw was asked for while a row was pressed: done after the release
        self._names = {}  # conn -> how its browser is called (numbered when two share a name)
        self._choices = ()  # (conn, label, colour) of the chips built
        self._chip_buttons = []  # (key, button)
        self._ws_buttons = []  # (conn, workspace id or None for "+", button) of the rows built last
        self._close_buttons = []  # (tab id, its ✕ button) of the rows built last
        self._query = ""  # what the find window has typed: only the tabs that match are listed, from every workspace
        self._first_match = None  # (conn, tab id, window id) of the first tab listed while finding
        self._selected = None  # (conn, tab id) of the tab the arrow keys have highlighted while finding
        self._find_dialog = None  # the find window, while it is up (self._dialog may be another window)
        self._state = {}  # the state of the browser whose rows are being built
        self._middle = None  # the row a middle button went down on: releasing it there closes that tab
        self._holds = set()  # why the panel must stay open whatever the pointer does: "drag", "menu", "dialog"
        self._menu = None  # the context menu up (kept referenced while it is shown)
        self._dialog = None  # the window asking for a workspace name, while it is up
        self._dialog_finish = None  # finish(accepted) of that window
        self.collapsed = set()  # (browser pid, cookieStoreId) of folded container sections; (pid, None) a folded browser
        self.hidden = False
        self._last = None  # what the last render showed, to skip identical ones
        self._accent = None
        self._warned_monitor = False
        self._overlay = False  # pinned, but on an inner edge where no space can be reserved
        self._relayout_id = None
        self._screen_handlers = []
        self._closed = False

        GLib.set_prgname("tabdock")
        self._css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), self._css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        self._colours = accents(cfg.get("theme"))  # each browser's colour, with the config's [theme]
        self._set_accent(self._colours["other"])
        self._per_browser = Gtk.CssProvider()
        self._per_browser.load_from_data((browser_css(self._colours.values()) + WS_CSS).encode())
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), self._per_browser, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        self.strip = self._dock_window("sp-strip", "tabdock-strip")
        self.win = self._dock_window("sp-panel", "tabdock-panel")
        self.win.connect("destroy", lambda _w: on_quit())

        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.content.get_style_context().add_class("sp-content")

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        header.get_style_context().add_class("sp-header")
        self.browser_name = Gtk.Label(label="", xalign=0)
        self.browser_name.set_ellipsize(Pango.EllipsizeMode.END)  # the header never makes the panel wider than `width`
        self.browser_name.get_style_context().add_class("sp-browser")
        self._current_source = None  # (conn, info) of the one browser shown, for the name's right-click menu
        self.browser_name_box = Gtk.EventBox()
        self.browser_name_box.add(self.browser_name)
        self.browser_name_box.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.browser_name_box.connect("button-press-event", self._on_browser_name_press)
        self.quit_btn = self._button("✕", "Quit tabdock", Gtk.Button)
        self.quit_btn.get_style_context().add_class("sp-quit")
        self.quit_btn.connect("clicked", lambda _b: on_quit())
        self.flip_btn = self._button("⇄", "Switch side", Gtk.Button)
        self.flip_btn.connect("clicked", lambda _b: self.set_side("right" if self.cfg["side"] == "left" else "left"))
        self.pin_btn = self._button("pin", "Pin: keep the panel open", Gtk.ToggleButton)
        self.pin_btn.get_style_context().add_class("sp-pin")
        self.pin_btn.connect("toggled", self._on_pin_toggled)
        self.icons_btn = self._button("icons", "", Gtk.ToggleButton)
        self.icons_btn.get_style_context().add_class("sp-pin")  # the same pill: filled while on
        self.icons_btn.set_active(self.cfg["icons"])
        self._refresh_icons_btn()
        self.icons_btn.connect("toggled", self._on_icons_toggled)
        self.find_btn = self._button("🔍", "Find a tab by its title or address, in every workspace", Gtk.Button)
        self.find_btn.get_style_context().add_class("sp-pin")
        self.find_btn.connect("clicked", lambda _b: self._find())
        header.pack_start(self.browser_name_box, True, True, 0)
        header.pack_end(self.quit_btn, False, False, 0)  # rightmost
        header.pack_end(self.flip_btn, False, False, 0)
        header.pack_end(self.pin_btn, False, False, 0)
        header.pack_end(self.icons_btn, False, False, 0)
        header.pack_end(self.find_btn, False, False, 0)

        # which browser(s) to list; wraps onto more lines when many browsers are open, and only
        # shown when there is a choice to make
        self.chips = Gtk.FlowBox()
        self.chips.set_selection_mode(Gtk.SelectionMode.NONE)
        self.chips.set_homogeneous(False)
        self.chips.set_column_spacing(4)
        self.chips.set_row_spacing(3)
        self.chips.get_style_context().add_class("sp-chips")

        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.scroll.add(self.list)

        # every known browser's colour, reachable without depending on a right-click landing on the
        # header (which the config.toml editing story already covers, but a button never misses)
        self.advanced = Gtk.Expander(label="Advanced")
        self.advanced.get_style_context().add_class("sp-advanced")
        adv_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._swatches = {}
        names = dict(KNOWN_BROWSERS)
        for key in (*ACCENTS, "other"):
            name = names.get(key, "Other")
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row.get_style_context().add_class("sp-advrow")
            row.pack_start(Gtk.Label(label=name, xalign=0), True, True, 0)
            swatch = self._button("", f"{name} colour", Gtk.Button)
            swatch.get_style_context().add_class("sp-swatch")
            swatch.connect("clicked", lambda _b, key=key, name=name: self._pick_colour(key, name))
            self._swatches[key] = swatch
            row.pack_end(swatch, False, False, 0)
            adv_box.pack_start(row, False, False, 0)
        self.advanced.add(adv_box)
        self._refresh_swatches()

        self.content.pack_start(header, False, False, 0)
        self.content.pack_start(self.chips, False, False, 0)
        self.content.pack_start(self.scroll, True, True, 0)
        self.content.pack_start(self.advanced, False, False, 0)
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
        windows = (self.strip, self.win, self._dialog)  # (the name window only while it is up)
        return {w.get_window().get_xid() for w in windows if w is not None and w.get_window() is not None}

    def show(self, sources, mode="auto", choices=(), focus=None):
        """List the browsers in `sources` ([(conn, hello, state)]). `mode` ("auto", "all" or a conn) and
        `choices` ([(conn, label, colour)] of every connected browser) drive the chips; `focus` is the
        hello of the browser whose colour the header and the strip wear (the only one listed, by default)."""
        if self._press is not None and not self._pressing():
            self._end_press()  # a press whose release never came: let go of the hold and the drag marks
        if self._pressing():
            self._deferred = (sources, mode, choices, focus)  # rows are being pressed or dragged: redraw after the drop
            return
        self._deferred = None
        self._ws_pending = None
        self.sources = list(sources)
        self._names = {conn: label for conn, label, _colour in choices}
        if focus is None and len(self.sources) == 1:
            focus = self.sources[0][1]
        self._focus = focus
        if len(self.sources) == 1:
            conn, info, _state = self.sources[0]
            self.browser_name.set_text(self._name(conn, info))
            self.browser_name.set_tooltip_text(browser_label(info))
            self._current_source = (conn, info)
        else:
            self.browser_name.set_text("All browsers")
            self.browser_name.set_tooltip_text(None)
            self._current_source = None
        # only the strip and the header wear it: no rebuild
        self._set_accent(accent(focus, self._colours) if focus else self._colours["other"])
        snapshot = (self.sources, frozenset(self.collapsed), mode, tuple(choices))
        if snapshot != self._last:
            self._last = snapshot
            self._set_chips(mode, choices)
            self._rebuild()

    def clear(self, mode="auto", choices=()):
        """Nothing to list (yet). The chips stay when browsers are connected: they lead to another one."""
        self._end_press()
        self._deferred = None
        self.sources = []
        self._names = {}
        self._last = None
        self._meta, self._row_order = {}, []
        self._ws_buttons = []
        self._set_chips(mode, choices)
        self.browser_name.set_text("")
        self._current_source = None
        self._set_accent(self._colours["other"])
        self._replace_rows([self._label(waiting_text(), "sp-empty", wrap=True)])

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

    def _refresh_icons_btn(self):
        on = self.icons_btn.get_active()
        self.icons_btn.set_tooltip_text(
            "Site icons are shown. Click to hide them and stop downloading" if on
            else "Show each tab's site icon. The panel downloads the icons itself, from your own address "
                 "and DNS, not through the browser's proxy (see the README)"
        )

    def _on_icons_toggled(self, button):
        self.cfg["icons"] = button.get_active()
        self._refresh_icons_btn()
        if not self.cfg["icons"] and self._fetcher is not None:
            for url in self._fetcher.drop_queued():  # what has not started yet is not downloaded
                self._pending.discard(self._icon_key(url))
        self._last = None
        if self.sources:
            self._rebuild()

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
        self.icons_btn.set_active(self.cfg["icons"])  # (the toggle handler redraws when it changed)
        self._place()  # side, width or monitor may have changed too
        colours = accents(self.cfg.get("theme"))
        if colours != self._colours:  # new [theme] colours: the next show() rebuilds the rows in them
            self._colours = colours
            self._per_browser.load_from_data((browser_css(colours.values()) + WS_CSS).encode())
            self._last = None
            self._refresh_swatches()
            if not self.sources:
                self._set_accent(colours["other"])  # (nothing listed: no show() to come)

    def _refresh_swatches(self):
        """The Advanced section's colour buttons, in the current [theme] colours."""
        for key, button in self._swatches.items():
            ctx = button.get_style_context()
            for cls in [c for c in ctx.list_classes() if c.startswith("acc-")]:
                ctx.remove_class(cls)
            ctx.add_class(acc_class(self._colours[key]))

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
                print(f"tabdock: no monitor named {name!r}, using the outer screen edge", file=sys.stderr)
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
        if self._dialog is not None:
            self._dialog.destroy()
            self._dialog = None

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

    def _set_chips(self, mode, choices):
        """One chip per browser plus "auto" and "all". The buttons are only rebuilt when a browser
        comes or goes; a click just moves the highlight. Hidden while there is nothing to choose."""
        if tuple(choices) != self._choices:
            self._choices = tuple(choices)
            for child in self.chips.get_children():
                self.chips.remove(child)
            self._chip_buttons = []
            entries = [("auto", "auto", None, "Follow the browser you are using")]
            entries += [(conn, label, colour, f"Show only {label}") for conn, label, colour in choices]
            entries.append(("all", "all", None, "Show every open browser"))
            for key, label, colour, tip in entries:
                button = self._button(label, tip, Gtk.Button)
                button.get_style_context().add_class("sp-chip")
                if colour:
                    button.get_style_context().add_class(acc_class(colour))
                button.connect("clicked", lambda _b, key=key: self._choose(key))
                self.chips.add(button)
                self._chip_buttons.append((key, button))
            self.chips.show_all()
        for key, button in self._chip_buttons:
            ctx = button.get_style_context()
            (ctx.add_class if key == mode else ctx.remove_class)("selected")
        self.chips.set_visible(len(self._choices) > 1)

    def _choose(self, key):
        if self.on_choose is not None:
            self.on_choose(key)

    def _label(self, text, css_class, markup=False, wrap=False):
        label = Gtk.Label(xalign=0)
        (label.set_markup if markup else label.set_text)(text)
        if wrap:
            label.set_line_wrap(True)
        else:
            label.set_ellipsize(Pango.EllipsizeMode.END)
        label.get_style_context().add_class(css_class)
        return label

    def _row(self, child, kind, ident, group, conn, colour, on_click, active=False, draggable=True, pinned=False,
             menu=None, closable=False):
        """A row of the browser `conn`, in its colour. Hover/active styling lives on the EventBox: a
        windowless label gets no prelight.

        A click and a drag share one press, so they never both happen: the click fires on release,
        and moving DRAG_THRESHOLD px with the button down turns the press into a drag instead.
        `menu` ([(label, action)], see _popup) is what a right click offers.
        """
        box = Gtk.EventBox()
        box.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.BUTTON1_MOTION_MASK
            | Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK
        )
        box.connect("enter-notify-event", self._on_row_enter)
        box.connect("leave-notify-event", self._on_row_leave)
        box.connect("button-press-event", self._on_press)
        box.connect("motion-notify-event", self._on_motion)
        box.connect("button-release-event", self._on_release)
        box.get_style_context().add_class("sp-row")
        box.get_style_context().add_class(acc_class(colour))
        if active:
            box.get_style_context().add_class("active")
        if kind == "tab" and (conn, ident) == self._selected:
            box.get_style_context().add_class("kbd")
        box.add(child)
        self._meta[box] = {
            "kind": kind, "id": ident, "group": group, "conn": conn, "click": on_click,
            "draggable": draggable, "pinned": pinned, "menu": menu, "closable": closable,
        }
        self._row_order.append(box)
        return box

    # -- hovering rows ---------------------------------------------------------------

    # An EventBox never marks itself hovered (a GtkButton does, for itself), so a row's :hover style, and the ✕ a
    # hovered tab shows, need it set here. Moving onto the row's own ✕ is still being on the row.
    @staticmethod
    def _on_row_enter(box, _event):
        box.set_state_flags(Gtk.StateFlags.PRELIGHT, False)
        return False

    @staticmethod
    def _on_row_leave(box, event):
        if event.detail != Gdk.NotifyType.INFERIOR:
            box.unset_state_flags(Gtk.StateFlags.PRELIGHT)
        return False

    # -- pressing, clicking and dragging rows ---------------------------------------

    def _pressing(self):
        p = self._press
        return p is not None and time.monotonic() - p["t"] < PRESS_STALE_S

    def _hold(self, why, on):
        """Keep the panel open (a drag, a menu, the name window) whatever the pointer does, until every
        reason is gone."""
        (self._holds.add if on else self._holds.discard)(why)
        self.autohide.set_held(bool(self._holds))

    def _end_press(self):
        p, self._press = self._press, None
        if p is not None and p["dragging"]:
            self._clear_marks(p)
            self._hold("drag", False)

    def _on_press(self, box, event):
        if event.button == 1 and box in self._meta:
            self._press = {"box": box, "x": event.x_root, "y": event.y_root, "t": time.monotonic(),
                           "dragging": False, "target": None, "after": False}
        elif event.button == 2 and self._meta.get(box, {}).get("closable"):
            self._middle = box  # closed on release, as in the browser's tab strip
            return True
        elif event.button == 3 and self._meta.get(box, {}).get("menu"):
            self._popup(self._meta[box]["menu"], event)
            return True
        return False

    def _on_motion(self, box, event):
        p = self._press
        if p is None or p["box"] is not box or not self._meta.get(box, {}).get("draggable"):
            return False
        if not p["dragging"]:
            if max(abs(event.x_root - p["x"]), abs(event.y_root - p["y"])) < DRAG_THRESHOLD:
                return False
            p["dragging"] = True
            self._hold("drag", True)  # the pointer may leave the panel mid-drag: stay open
            box.get_style_context().add_class("dragging")
        self._point_at(p, box, event)
        return True

    def _on_release(self, box, event):
        if event.button == 2:
            middle, self._middle = self._middle, None
            if middle is box and box in self._meta:  # released on the row it went down on
                self._close_tab(self._meta[box]["conn"], self._meta[box]["id"])
            return middle is not None
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
        if self._redraw:
            self._rebuild()  # a redraw (icons switched, config reloaded) that had to wait for the release
        return True

    def _drop_candidates(self, box):
        """The rows the dragged one can be dropped between: same browser and kind; for tabs the same container
        and the same pinned-ness, because Firefox keeps pinned tabs in front and clamps a move across that line."""
        meta = self._meta[box]
        return [
            b for b in self._row_order
            if self._meta[b]["draggable"]
            and self._meta[b]["conn"] is meta["conn"]
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

    def _command(self, conn, message):
        if self.on_command is not None:
            self.on_command(conn, message)

    def _state_of(self, conn):
        return next((state for c, _info, state in self.sources if c is conn), None)

    def _drop(self, p):
        box, target = p["box"], p["target"]
        self._clear_marks(p)
        self._hold("drag", False)
        if target is None or box not in self._meta or target not in self._meta:
            return
        meta = self._meta[box]
        conn, state = meta["conn"], self._state_of(meta["conn"])
        if state is None:
            return  # the browser went away under the drag
        candidates = self._drop_candidates(box)
        at = candidates.index(target) + (1 if p["after"] else 0)
        before = self._meta[candidates[at]]["id"] if at < len(candidates) else None  # lands in front of this
        if meta["kind"] == "section":
            ids = [self._meta[b]["id"] for b in candidates]
            order = reordered(ids, meta["id"], before)
            if order != ids:
                self._command(conn, {"type": "set_container_order", "order": order})
                # show it at once; the browser confirms
                self.sources = [(c, i, {**s, "containerOrder": order} if c is conn else s) for c, i, s in self.sources]
                self._last = None
                self._rebuild()
        else:
            # the tabs it can land among: same container and same pinned-ness (see _drop_candidates)
            group = next((tabs for c, tabs in group_tabs(state) if c["cookieStoreId"] == meta["group"]), [])
            group = [t for t in group if bool(t.get("pinned")) == meta["pinned"]]
            if meta["id"] not in {t["id"] for t in group}:
                return  # the state changed under the drag (browser switched, tab closed): nothing to do
            index = tab_move_index(group, meta["id"], before)
            if index is not None:
                self._command(conn, {"type": "move_tab", "tabId": meta["id"], "index": index})

    # -- test hook ---------------------------------------------------------------------

    def _schedule_dump(self):
        if self._dump_path and not self._dump_pending:
            self._dump_pending = True
            GLib.idle_add(self._dump_layout)

    def _dump_layout(self):
        """TABDOCK_LAYOUT_DUMP=<file> writes where every row is, in screen pixels, so an end-to-end
        test can drag with a real pointer without guessing coordinates."""
        self._dump_pending = False
        path = self._dump_path
        root = self.win.get_child()
        if not path or self._closed or root is None:  # (the window may be gone by the time an idle callback runs)
            return False
        wx, wy = self.win.get_position()

        def spot(widget, kind, ident, group=None):
            a = widget.get_allocation()
            pos = widget.translate_coordinates(root, 0, 0) or (a.x, a.y)  # unmapped: the list-relative fallback
            return {"kind": kind, "id": ident, "group": group,
                    "x": wx + pos[0], "y": wy + pos[1], "w": a.width, "h": a.height}

        rows = [spot(box, self._meta[box]["kind"], self._meta[box]["id"], self._meta[box]["group"])
                for box in self._row_order if box in self._meta]
        if self.chips.get_visible():
            rows += [spot(button, "chip", button.get_label()) for _key, button in self._chip_buttons]
        rows += [spot(button, "workspace", ws_id, button.get_label()) for _conn, ws_id, button in self._ws_buttons]
        rows += [spot(button, "close", tab_id) for tab_id, button in self._close_buttons]
        rows.append(spot(self.find_btn, "button", "find"))
        with open(path + ".tmp", "w") as f:
            json.dump(rows, f)
        os.replace(path + ".tmp", path)
        return False

    def _set_accent(self, colour):
        if colour == self._accent:
            return  # reloading the provider restyles every widget: only do it on a real change
        self._accent = colour
        text = on_accent(colour)
        # the browser's name is written in the accent on the dark header, unless the accent is too dark to read there
        self._css_data = CSS.format(accent=colour, on_accent=text, name=colour if text == DARK_TEXT else "#dfe3ea")
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
        if self._pressing():  # a row is being pressed or dragged: the rows must not be replaced under it
            self._redraw = True
            return
        self._redraw = False
        self._meta, self._row_order = {}, []
        self._ws_buttons = []
        self._close_buttons = []
        self._waiting = {}  # the old rows are about to go: only the rows built below wait for an icon
        self._first_match = None
        many = len(self.sources) > 1
        rows = []
        finding = bool(self._query.strip())
        for conn, info, state in self.sources:
            # per browser process: two profiles of the same browser fold independently
            browser = info.get("browserPid") or info.get("browser")
            colour = accent(info, self._colours)
            window = focused_window(state)
            self._state = state  # (what a tab row looks its group up in)
            groups = group_tabs(state, every_workspace=finding)  # the focused window's tabs, in the workspace it shows
            if finding:  # only what matches, and only the sections that hold some of it
                groups = [(c, [t for t in tabs if matches(t, self._query)]) for c, tabs in groups]
                groups = [(c, tabs) for c, tabs in groups if tabs]
            if many:  # each browser gets its own header, which folds the whole browser away
                folded = (browser, None) in self.collapsed
                count = sum(len(tabs) for _container, tabs in groups)
                rows.append(self._browser_row(conn, colour, self._name(conn, info), count, (browser, None), folded))
                if folded:
                    continue
            if window is None:
                rows.append(self._label("No browser windows", "sp-empty", wrap=True))
                continue
            spaces = workspaces(state) if offers_workspaces(info, state) else []
            can = {feature for feature in FEATURES if supports(info, feature)}
            if spaces:
                rows.append(self._workspace_row(conn, colour, spaces, window, ordered_containers(state)))
            for container, tabs in groups:
                key = (browser, container["cookieStoreId"])
                folded = key in self.collapsed and not finding  # a match is never folded away
                rows.append(self._section(container, tabs, key, folded, conn, colour, state, window["id"], can))
                if not folded:
                    rows.extend(
                        self._tab_row(tab, window["id"], container["cookieStoreId"], conn, colour, spaces, can,
                                      ordered_containers(state), window.get("workspaceId") if finding else None)
                        for tab in tabs
                    )
                if finding and tabs and self._first_match is None:
                    self._first_match = (conn, tabs[0]["id"], window["id"])
        if finding and self._first_match is None:
            rows.append(self._label(f"No tab matches “{self._query.strip()}”", "sp-empty", wrap=True))
        self._replace_rows(rows or [self._label("No browser windows", "sp-empty", wrap=True)])

    def _name(self, conn, info):
        return self._names.get(conn) or info.get("browser") or "browser"

    def _browser_row(self, conn, colour, name, count, key, folded):
        """A browser is a solid band in its colour, so it cannot be mistaken for a container (a small
        coloured bar with an icon) or a tab. `count`: the tabs it lists."""
        markup = (
            f'{GLib.markup_escape_text(name)} <span alpha="70%">({count})</span>'
            f'  <span alpha="70%">{"▸" if folded else "▾"}</span>'
        )
        row = self._row(
            self._label(markup, "sp-bandlabel", markup=True), "browser", None, None, conn, colour,
            lambda: self._toggle(key), draggable=False,
        )
        row.get_style_context().add_class("sp-bhead")
        return row

    def _section(self, container, tabs, key, folded, conn, browser_colour, state, window_id, can=()):
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
        # windows, say) cannot be ordered or offered "new tab here": the next snapshot would put a
        # reordered one straight back, and a new-tab request for a deleted container would just fail
        known = {c["cookieStoreId"] for c in state.get("containers") or []}
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        box.get_style_context().add_class("sp-sectionbox")
        box.pack_start(label, True, True, 0)
        if cid == NO_CONTAINER or cid in known:
            button = self._button(
                "+", "New tab" if cid == NO_CONTAINER else f"New tab in {container['name']}", Gtk.Button
            )
            button.get_style_context().add_class("sp-newtab")
            button.connect(
                "clicked",
                lambda _b: self._command(conn, {"type": "new_tab", "cookieStoreId": cid, "windowId": window_id}),
            )
            box.pack_start(button, False, False, 0)
        return self._row(
            box, "section", cid, None, conn, browser_colour, (lambda: self._toggle(key)) if tabs else (lambda: None),
            draggable=cid != NO_CONTAINER and cid in known,
            menu=(self._container_menu(conn, container, state)
                  if "containers" in can and (cid == NO_CONTAINER or cid in known) else None),
        )

    def _container_menu(self, conn, container, state):
        """A right click on a container section: rename it, its colour and icon, a new container, and removing it
        (after asking: its tabs close and Firefox deletes its cookies). "No container" offers only the new one."""
        new = ("New container…", lambda: self._ask_name(
            "New container", "", lambda name: self._command(conn, {"type": "create_container", "name": name})))
        cid = container["cookieStoreId"]
        if cid == NO_CONTAINER:
            return [new]

        def update(**change):
            self._command(conn, {"type": "update_container", "cookieStoreId": cid, **change})

        tabs = sum(t.get("cookieStoreId") == cid for w in state.get("windows") or [] for t in w["tabs"])
        return [
            ("Rename…", lambda: self._ask_name("Rename container", container["name"], lambda name: update(name=name))),
            ("Colour", [
                (Markup(f'<span foreground="{code}">●</span> {colour_name(name)}'), lambda name=name: update(color=name),
                 container.get("color") == name)
                for name, code in WS_COLORS.items()
            ]),
            ("Icon", [
                (f"{ICONS[icon]} {icon.capitalize()}", lambda icon=icon: update(icon=icon), container.get("icon") == icon)
                for icon in CONTAINER_ICONS
            ]),
            (None, None),
            new,
            (None, None),
            ("Remove container…", lambda: self._confirm(
                "Remove container", removal_text(container["name"], tabs), "Remove",
                lambda: self._command(conn, {"type": "remove_container", "cookieStoreId": cid}))),
        ]

    def _toggle(self, key):
        self.collapsed ^= {key}
        self._last = None
        self._rebuild()

    def _tab_row(self, tab, window_id, group, conn, colour, spaces=(), can=(), containers=(), shown=None):
        """A tab: its site icon (optional), the title, an unread badge, a pin if pinned, and a ✕ that shows while
        the row is hovered. Middle-click closes it too; right-click pins, moves (to another workspace) or closes.
        `can`: what the extension handles ("close_tab", "pin_tab", "reopen_in_container"); the rest is not offered.
        `shown`: while finding, the workspace the window shows; a tab of another one says which it is in."""
        label = self._label(tab_label(tab), "sp-tab")
        label.set_tooltip_text("\n".join(filter(None, (tab.get("title"), tab.get("url")))))
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.get_style_context().add_class("sp-tabbox")
        pinned = bool(tab.get("pinned"))
        if self.cfg["icons"]:
            image = Gtk.Image()
            image.set_size_request(favicons.ICON_PX, favicons.ICON_PX)  # the room is kept until the icon arrives
            self._want_icon(tab.get("favIconUrl"), image)
            box.pack_start(image, False, False, 0)
        box.pack_start(label, True, True, 0)
        badge = self.cfg["badges"] and tab_badge(tab)
        if badge:
            badge_label = self._label(badge, "sp-badge")
            badge_label.set_tooltip_text(f"{badge} unread, from the tab's title")
            box.pack_start(badge_label, False, False, 0)
        other = shown is not None and not pinned and tab.get("workspaceId", shown) != shown
        if other:  # found in a workspace the window does not show: picking it switches there
            where = next((ws for ws in spaces if ws["id"] == tab.get("workspaceId")), None)
            if where is not None:
                box.pack_start(self._label(f"in {workspace_label(where)}", "sp-where"), False, False, 0)
        firefox_group = tab_group(self._state, tab)  # (not `group`: that is the row's container)
        if firefox_group is not None:  # Firefox's own tab group: its name, in its colour
            title = firefox_group["title"]
            tag = self._label(
                f'<span foreground="{GROUP_COLORS.get(firefox_group["color"], DEFAULT_ACCENT)}">'
                f'{GLib.markup_escape_text(title or "group")}</span>', "sp-group", markup=True)
            tag.set_tooltip_text(f"In the tab group “{title}”" if title else "In an unnamed tab group")
            box.pack_start(tag, False, False, 0)
        if pinned:  # after the title, so every title starts in the same place
            mark = self._label("📌", "sp-pinmark")
            mark.set_tooltip_text("Pinned: shows in every workspace" if len(spaces) > 1 else "Pinned")
            box.pack_start(mark, False, False, 0)
        if "close_tab" in can:
            close = self._button("✕", "Close tab (or middle-click it)", Gtk.Button)
            close.get_style_context().add_class("sp-close")
            close.connect("clicked", lambda _b: self._close_tab(conn, tab["id"]))
            box.pack_end(close, False, False, 0)
            self._close_buttons.append((tab["id"], close))
        groups = []  # the menu's parts, with a line between them
        if "pin_tab" in can:
            groups.append([("Unpin tab" if pinned else "Pin tab",
                            lambda: self._command(conn, {"type": "pin_tab", "tabId": tab["id"], "pinned": not pinned}))])
        store = tab.get("cookieStoreId") or NO_CONTAINER
        if "reopen_in_container" in can and store != "firefox-private" and reopenable(tab):
            others = [c for c in ({"cookieStoreId": NO_CONTAINER, "name": "No container"}, *containers)
                      if c["cookieStoreId"] != store]
            if others:
                groups.append([("Reopen in container", [
                    (Markup(f'<span foreground="{c.get("colorCode") or DEFAULT_ACCENT}">▌</span> '
                            f'{GLib.markup_escape_text(c["name"])}'),
                     lambda cid=c["cookieStoreId"]: self._command(
                         conn, {"type": "reopen_in_container", "tabId": tab["id"], "cookieStoreId": cid}))
                    for c in others
                ])])
        if len(spaces) > 1 and not pinned:  # (a pinned tab shows in every workspace)
            groups.append([
                (f"Move to {workspace_label(ws)}", lambda ws_id=ws["id"]: self._command(
                    conn, {"type": "move_tab_to_workspace", "tabId": tab["id"], "workspaceId": ws_id}))
                for ws in spaces if ws["id"] != tab.get("workspaceId")
            ])
        if "close_tab" in can:
            groups.append([("Close tab", lambda: self._close_tab(conn, tab["id"]))])
        menu = [item for i, group in enumerate(groups) for item in ([(None, None)] if i else []) + group] or None
        return self._row(
            box, "tab", tab["id"], group, conn, colour, lambda: self.on_activate(conn, tab["id"], window_id),
            active=bool(tab.get("active")), pinned=pinned, menu=menu, closable="close_tab" in can,
        )

    def find(self):
        """The hotkey (`tabdock --find`): the find window, with the panel shown for it even while it is hidden.
        The same key closes it again."""
        if self._dialog is not None and self._dialog is self._find_dialog:
            self._dialog_finish(False)
            return
        self.set_hidden(False)
        self._find()

    def _find(self):
        """The find window: what is typed there narrows the list at once, to the tabs whose title or address has
        every word of it, from every workspace. Down and Up highlight a tab and Left and Right switch workspace (see
        _on_find_key); Enter picks the highlighted tab, or the first one when none is (switching to its workspace),
        Escape gives the whole list back."""
        entry = Gtk.Entry(placeholder_text="Title or address")
        entry.set_width_chars(28)

        def narrow(_entry):
            self._query = entry.get_text()
            self._last = None
            self._rebuild()

        def answer(accepted):
            box = next((b for b in self._tab_rows() if self._tab_key(b) == self._selected), None)
            pick = self._meta[box]["click"] if box is not None else None  # what a click on that row does
            first = self._first_match
            self._find_dialog = None
            self._ws_pending = None
            self._query = ""
            self._selected = None
            self._last = None
            self._rebuild()
            if accepted and pick is not None:
                pick()
            elif accepted and first is not None:
                self.on_activate(*first)

        finish, _ok = self._small_window("Find tab", entry, "Go", answer, focus=entry, beside=True)
        self._find_dialog = self._dialog
        entry.connect("changed", narrow)
        entry.connect("activate", lambda _e: finish(True))
        entry.connect("key-press-event", self._on_find_key)
        self._dialog_entry = entry

    def _tab_rows(self):
        return [b for b in self._row_order if self._meta[b]["kind"] == "tab"]

    def _tab_key(self, box):
        return self._meta[box]["conn"], self._meta[box]["id"]

    def _on_find_key(self, entry, event):
        """Down, Up, Page Down, Page Up, Home and End walk the tab rows while the find window has the keyboard.
        The arrows are always taken, even with nothing to walk: GTK would move the focus off the entry with them.
        Home and End stay the entry's caret keys when chorded (Shift+Home selects text) or when no tab is listed.
        Left and Right switch workspace, but only while nothing is typed: they are the caret's after that, and the
        list spans every workspace then anyway.
        The hotkey's Super may still be down, so it changes none of this, and Enter still picks."""
        if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and event.state & Gtk.accelerator_get_default_mod_mask():
            self._dialog_finish(True)  # (the entry's own "activate" needs every modifier up)
            return True
        if event.keyval in WORKSPACE_KEYS:
            if entry.get_text().strip():  # (as _rebuild counts a query: blanks alone list nothing more)
                return False
            self._step_workspace(WORKSPACE_KEYS[event.keyval])
            return True
        if event.keyval not in FIND_KEYS:
            return False
        step, from_nothing = FIND_KEYS[event.keyval]
        rows = self._tab_rows()
        if from_nothing and (not rows or event.state & CARET_MODS):
            return False
        if rows:
            keys = [self._tab_key(b) for b in rows]
            current = None if from_nothing or self._selected not in keys else keys.index(self._selected)
            self._select(rows[step_index(current, len(rows), step)])
        return True

    def _step_workspace(self, step):
        """Switch the window to the workspace `step` away, stopping at the ends, as a click on its chip does: of the
        browser listed, or of the one in use among several. The tabs listed change, so no tab stays highlighted."""
        source = next(
            (s for s in self.sources if (len(self.sources) == 1 or s[1] is self._focus) and offers_workspaces(s[1], s[2])),
            None,
        )
        target = source and workspace_step(source[2], step, self._ws_pending)
        if not target:
            return
        self._ws_pending = target[1]  # (keys pressed before the browser reports the switch count from here)
        self._selected = None
        for row in self._row_order:
            row.get_style_context().remove_class("kbd")
        self._command(source[0], {"type": "switch_workspace", "windowId": target[0], "workspaceId": target[1]})

    def _select(self, box):
        """Highlight one tab row, in place: a rebuild would reset the scroll. The row is scrolled into view."""
        self._selected = self._tab_key(box)
        for row in self._row_order:
            context = row.get_style_context()
            (context.add_class if row is box else context.remove_class)("kbd")
        pos = box.translate_coordinates(self.list, 0, 0)
        if pos is None:
            return
        adj = self.scroll.get_vadjustment()
        top, bottom = pos[1], pos[1] + box.get_allocated_height()
        if top < adj.get_value():
            adj.set_value(top)
        elif bottom > adj.get_value() + adj.get_page_size():
            adj.set_value(bottom - adj.get_page_size())

    def _close_tab(self, conn, tab_id):
        self._command(conn, {"type": "close_tab", "tabId": tab_id})

    # -- workspaces ------------------------------------------------------------------------

    def _workspace_row(self, conn, colour, spaces, window, containers=()):
        """The browser's workspaces as chips, the one the window shows marked: a click switches to one, a right
        click changes or removes it, and "+" makes a new one (which the browser then switches to). A chip wears
        the workspace's icon and colour."""
        row = Gtk.FlowBox()
        row.set_selection_mode(Gtk.SelectionMode.NONE)
        row.set_homogeneous(False)
        row.set_column_spacing(4)
        row.set_row_spacing(3)
        row.get_style_context().add_class("sp-wsrow")
        window_id = window["id"]
        names = {c["cookieStoreId"]: c["name"] for c in containers}
        for ws in spaces:
            label = workspace_label(ws)
            opens_in = names.get(ws.get("cookieStoreId"))
            tooltip = f"Switch to {label}" + (f". New tabs open in {opens_in}" if opens_in else "")
            button = self._button(label, tooltip + ". Right-click to change or remove it", Gtk.Button)
            button.get_child().set_ellipsize(Pango.EllipsizeMode.END)
            button.get_child().set_max_width_chars(18)
            ctx = button.get_style_context()
            ctx.add_class("sp-ws")
            ctx.add_class(acc_class(colour))
            if ws.get("color") in WS_COLORS:
                ctx.add_class("ws-col")
                ctx.add_class(ws_class(ws["color"]))
            if ws["id"] == window.get("workspaceId"):
                ctx.add_class("selected")
            button.connect("clicked", lambda _b, ws_id=ws["id"]: self._command(
                conn, {"type": "switch_workspace", "windowId": window_id, "workspaceId": ws_id}))
            button.connect(
                "button-press-event", self._on_workspace_press, self._workspace_menu(conn, spaces, ws, containers)
            )
            row.add(button)
            self._ws_buttons.append((conn, ws["id"], button))
        new = self._button("+", "New workspace", Gtk.Button)
        new.get_style_context().add_class("sp-ws")
        new.connect("clicked", lambda _b: self._ask_name(
            "New workspace", f"Workspace {len(spaces) + 1}",
            lambda name: self._command(conn, {"type": "new_workspace", "windowId": window_id, "name": name})))
        row.add(new)
        self._ws_buttons.append((conn, None, new))
        return row

    def _workspace_menu(self, conn, spaces, ws, containers=()):
        """Rename; its icon, colour and the container its new tabs open in (from an extension that keeps them);
        and remove, which closes nothing: its tabs go to its neighbour (the last one stays)."""
        rename = lambda: self._ask_name(  # noqa: E731
            "Rename workspace", ws["name"],
            lambda name: self._command(conn, {"type": "rename_workspace", "workspaceId": ws["id"], "name": name}))
        items = [("Rename…", rename)]
        if edits_workspaces(spaces):
            def edit(**change):
                self._command(conn, {"type": "edit_workspace", "workspaceId": ws["id"], **change})

            items.append(("Icon", self._icon_items(ws, edit)))
            items.append(("Colour", [("None", lambda: edit(color=None), not ws.get("color"))] + [
                (Markup(f'<span foreground="{code}">●</span> {colour_name(name)}'),
                 lambda name=name: edit(color=name), ws.get("color") == name)
                for name, code in WS_COLORS.items()
            ]))
            if containers:  # (none: containers are switched off in this browser)
                items.append(("New tabs in", [("No container", lambda: edit(cookieStoreId=None),
                                               not ws.get("cookieStoreId"))] + [
                    (Markup(f'<span foreground="{c.get("colorCode") or DEFAULT_ACCENT}">▌</span> '
                            f'{ICONS.get(c.get("icon"), "●")} {GLib.markup_escape_text(c["name"])}'),
                     lambda cid=c["cookieStoreId"]: edit(cookieStoreId=cid), ws.get("cookieStoreId") == c["cookieStoreId"])
                    for c in containers
                ]))
        to = heir(spaces, ws["id"])
        if to is None:
            return items + [("Remove (the last workspace stays)", None)]
        return items + [
            (f"Remove (its tabs go to {workspace_label(to)})",
             lambda: self._command(conn, {"type": "remove_workspace", "workspaceId": ws["id"]})),
        ]

    def _icon_items(self, ws, edit):
        """None, a few icons, and "Other…" for any other one (an emoji typed or pasted, or a few letters)."""
        current = ws.get("icon")
        other = lambda: self._ask_name(  # noqa: E731
            "Workspace icon", current or "", lambda icon: edit(icon=icon), max_length=ICON_MAX)
        return (
            [("None", lambda: edit(icon=None), not current)]
            + [(icon, lambda icon=icon: edit(icon=icon), icon == current) for icon in WS_ICONS]
            + [(f"Other ({current})…" if current and current not in WS_ICONS else "Other…", other,
                bool(current) and current not in WS_ICONS)]
        )

    def _on_workspace_press(self, _button, event, menu):
        if event.button != 3:
            return False  # a left click is the button's own "clicked"
        self._popup(menu, event)
        return True

    def _on_browser_name_press(self, _box, event):
        if event.button != 3 or self._current_source is None:
            return False  # not a right click, or nothing single shown to colour ("All browsers")
        conn, info = self._current_source
        self._popup([("Set colour…", lambda: self._pick_colour(browser_theme_key(info), self._name(conn, info)))], event)
        return True

    def _pick_colour(self, key, title):
        """A [theme] colour for `key` ("firefox", "other", ...), picked with a full colour chooser."""
        chooser = Gtk.ColorChooserWidget()
        chooser.set_use_alpha(False)
        chooser.set_property("show-editor", True)
        rgba = Gdk.RGBA()
        rgba.parse(self._colours[key])
        chooser.set_rgba(rgba)

        def answer(accepted):
            if not accepted:
                return
            picked = chooser.get_rgba()
            value = "#{:02x}{:02x}{:02x}".format(
                round(picked.red * 255), round(picked.green * 255), round(picked.blue * 255)
            )
            config.set_theme_colour(key, value)
            self.reconfigure({**self.cfg, "theme": {**self.cfg.get("theme", {}), key: value}})
            self._rebuild()  # reconfigure() alone only restyles what a following show() rebuilds
            if self._current_source is not None:
                self._set_accent(self._colours[key])

        self._small_window(f"{title} colour", chooser, "Set", answer)
        self._dialog_chooser = chooser

    def _popup(self, items, event):
        """A context menu (see _menu_of). The panel stays open while it is up."""
        menu = self._menu_of(items)
        menu.connect("deactivate", lambda _m: self._hold("menu", False))
        menu.show_all()
        self._menu = menu
        self._hold("menu", True)
        menu.popup_at_pointer(event)
        if not menu.get_visible():  # it could not open: it must not keep the panel open either
            self._hold("menu", False)

    def _menu_of(self, items):
        """A menu of (label, action) or (label, action, chosen) items. An action is a callable, a list of items
        (a submenu), or None (shown greyed out); `chosen` marks the current choice among a submenu's items. A
        None label is a separator."""
        menu = Gtk.Menu()
        for label, action, *chosen in items:
            if label is None:
                menu.append(Gtk.SeparatorMenuItem())
                continue
            if chosen:
                item = Gtk.CheckMenuItem(label=label)
                item.set_draw_as_radio(True)
                item.set_active(chosen[0])  # before "activate" is connected: setting it emits that signal
            else:
                item = Gtk.MenuItem(label=label)
            if isinstance(label, Markup):
                item.get_child().set_markup(label)
            if isinstance(action, list):
                item.set_submenu(self._menu_of(action))
            else:
                item.set_sensitive(action is not None)
                if action is not None:
                    item.connect("activate", lambda _i, action=action: action())
            menu.append(item)
        return menu

    def _small_window(self, title, content, accept_label, answer, focus=None, beside=False):
        """A small window of its own: `content` above Cancel and `accept_label`. It takes the keyboard, which the dock
        windows never do (a click must not steal it from the browser), and the panel stays open while it is up.
        answer(accepted) is called once, as it goes; Escape or closing it is Cancel. Returns (finish, accept button).
        `beside`: next to the panel instead of at the pointer, where it would cover what the panel shows."""
        if self._dialog is not None:
            self._dialog_finish(False)  # replaced is cancelled: its answer undoes what it changed (a find's list)
        dialog = Gtk.Window(type=Gtk.WindowType.TOPLEVEL, title=title)
        dialog.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        dialog.set_keep_above(True)
        dialog.set_resizable(False)
        dialog.set_skip_taskbar_hint(True)
        dialog.set_position(Gtk.WindowPosition.MOUSE)
        ok, cancel = Gtk.Button(label=accept_label), Gtk.Button(label="Cancel")
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        buttons.pack_end(ok, False, False, 0)
        buttons.pack_end(cancel, False, False, 0)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(10)
        box.pack_start(content, False, False, 0)
        box.pack_start(buttons, False, False, 0)
        dialog.add(box)

        def finish(accept):
            if self._dialog is not dialog:
                return  # already answered
            self._dialog = None
            self._dialog_finish = None
            self._hold("dialog", False)
            answer(accept)
            dialog.destroy()

        ok.connect("clicked", lambda _b: finish(True))
        cancel.connect("clicked", lambda _b: finish(False))
        dialog.connect("key-press-event", lambda _w, e: e.keyval == Gdk.KEY_Escape and (finish(False) or True))
        dialog.connect("delete-event", lambda *_a: finish(False) or True)
        self._dialog = dialog
        self._dialog_finish = finish
        self._dialog_ok = ok
        self._hold("dialog", True)
        box.show_all()
        if beside:  # where the panel is, or is about to be: it may still be unmapped, and its position stale
            px, py, pw, _ph = geometry.dock_rect(self._monitor_rect(), self.cfg["side"], self.cfg["width"], True)
            dw = dialog.get_preferred_size()[1].width
            dialog.set_position(Gtk.WindowPosition.NONE)
            dialog.move(px + pw + 8 if self.cfg["side"] == "left" else max(0, px - dw - 8), py + 30)
        dialog.show()
        (focus or cancel).grab_focus()
        return finish, ok

    def _ask_name(self, title, text, done, max_length=NAME_MAX):
        """A small window to type a name (or a workspace icon) in, then done(name); an empty one is no answer."""
        entry = Gtk.Entry(text=text)
        entry.set_max_length(max_length)
        entry.set_width_chars(24)

        def answer(accepted):
            name = entry.get_text().strip()
            if accepted and name:
                done(name)

        finish, _ok = self._small_window(title, entry, "OK", answer, focus=entry)  # the whole text selected: typing replaces it
        entry.connect("activate", lambda _e: finish(True))
        self._dialog_entry = entry

    def _confirm(self, title, text, action_label, done):
        """Asks before what cannot be undone: done() only on `action_label`. Cancel has the keyboard, so a stray
        Enter does not do it."""
        label = Gtk.Label(label=text, xalign=0)
        label.set_line_wrap(True)
        label.set_max_width_chars(44)
        _finish, ok = self._small_window(title, label, action_label, lambda accepted: accepted and done())
        ok.get_style_context().add_class("destructive-action")
        self._dialog_text = label

    @staticmethod
    def _icon_key(url):
        """What an icon is remembered by: its URL, or for a long one (a data: URL can be hundreds of KB) its hash."""
        return url if len(url) <= 256 else "sha256:" + hashlib.sha256(url.encode()).hexdigest()

    @staticmethod
    def _remember(store, key, value):
        """`store[key] = value`, keeping the store to ICONS_KEPT entries: the least recently used goes first."""
        store.pop(key, None)
        store[key] = value
        while len(store) > ICONS_KEPT:
            store.pop(next(iter(store)))

    def _want_icon(self, url, image):
        """Put the icon for `url` into `image`: at once when it is known, else when it has been downloaded."""
        if not isinstance(url, str) or not url:
            image.set_tooltip_text(NO_ICON + "the browser reported no icon address")
            return
        key = self._icon_key(url)
        pixbuf = self._icons.get(key)
        if pixbuf is not None:
            self._remember(self._icons, key, pixbuf)  # used just now
            image.set_from_pixbuf(pixbuf)
            return
        if key in self._refused:  # it will never be an icon: no request, however often the rows are redrawn
            image.set_tooltip_text(NO_ICON + self._refused[key])
            return
        failed = self._failed.get(key)
        if failed is not None and time.monotonic() - failed < ICON_RETRY_S:  # it did not work a moment ago
            image.set_tooltip_text(NO_ICON + NOT_DOWNLOADED)  # no icon rather than a request per redraw
            return
        if key not in self._pending:
            if len(self._pending) >= ICONS_PENDING_MAX:
                return  # a page that keeps changing its icon must not queue downloads without end
            self._pending.add(key)
            if self._fetcher is None:
                self._fetcher = favicons.Fetcher(lambda u, result: GLib.idle_add(self._icon_ready, u, result))
            self._fetcher.submit(url)
        self._waiting.setdefault(key, []).append(image)

    def _icon_ready(self, url, result):
        """A download finished (on the UI thread again): the pixels, None (it did not work this time) or
        REFUSED (it never will). Fill in the rows that wait for it."""
        key = self._icon_key(url)
        self._pending.discard(key)
        waiting = self._waiting.pop(key, [])
        if isinstance(result, favicons.Refused):
            self._remember(self._refused, key, result.why)
            for image in waiting:
                image.set_tooltip_text(NO_ICON + result.why)  # hover the empty slot to see why
        elif not isinstance(result, bytes) or self._closed:
            self._remember(self._failed, key, time.monotonic())
            for image in waiting:
                image.set_tooltip_text(NO_ICON + NOT_DOWNLOADED)
        else:
            pixbuf = favicons.to_pixbuf(result)  # only 16x16 raw pixels: nothing untrusted is parsed here
            self._remember(self._icons, key, pixbuf)
            self._failed.pop(key, None)
            for image in waiting:
                image.set_from_pixbuf(pixbuf)
        return False
