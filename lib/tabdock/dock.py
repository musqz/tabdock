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
from datetime import datetime

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkX11", "3.0")
from gi.repository import Gdk, GdkX11, GLib, Gtk, Pango  # noqa: E402,F401

from . import config, favicons, geometry, launch  # noqa: E402
from .autohide import Autohide  # noqa: E402
from .model import (  # noqa: E402
    DARK_TEXT,
    DEFAULT_ACCENT,
    FEATURES,
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
    window_groups,
    GROUP_COLORS,
    supports,
    focused_window,
    bookmark_rows,
    day_label,
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
.sp-row.kbd {{ background-color: #2a2e38; border-left-color: {accent}; box-shadow: inset 0 0 0 1px {accent}; }}
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
.sp-grouprow {{ padding: 5px 10px 1px 19px; }}
.sp-pill {{ border-radius: 9px; padding: 0 10px; font-weight: bold; }}
.sp-ingroup {{ margin-left: 22px; padding-left: 8px; }}
button.sp-btn.sp-close {{ opacity: 0; padding: 0 4px; }}
.sp-row:hover button.sp-btn.sp-close {{ opacity: 1; }}
button.sp-btn.sp-close:hover {{ color: #ff6b6b; }}
button.sp-btn.sp-view {{ border: 1px solid #454b58; border-radius: 9px; padding: 0 10px; }}
button.sp-btn.sp-view:hover {{ border-color: #7d8594; color: #ffffff; }}
button.sp-btn.sp-view.selected {{ background-color: {accent}; border-color: {accent}; color: {on_accent}; font-weight: bold; }}
.sp-views {{ padding: 5px 8px; background-color: #23262e; }}
.sp-ghost {{ color: #7d8594; }}
button.sp-btn.sp-reopen {{ padding: 0 4px; color: #dfe3ea; }}
button.sp-btn.sp-reopen:hover {{ color: #ffffff; }}
"""


# The rows the find window's keys walk: the tabs, or the bookmark folders and bookmarks or the visits listed while
# one of those views is up, and the Start rows. A row of another kind opts in with `findable`.
FIND_KINDS = ("tab", "bookmark", "bookmark_folder", "history", "offline")

# Rows Enter folds or unfolds, where the rest open something.
FOLD_KINDS = ("bookmark_folder", "browser", "tabgroup")

# Ctrl + one of these switches the view the find window searches: Tabs, Bookmarks, History.
FIND_VIEW_KEYS = {Gdk.KEY_1: "tabs", Gdk.KEY_2: "bookmarks", Gdk.KEY_3: "history"}

# Ctrl + one of these acts on the dock from the find window (methods of DockView), or on the highlighted row (the
# names in a row's `keys`).
FIND_ACTIONS = {Gdk.KEY_p: "toggle_pin", Gdk.KEY_i: "toggle_icons", Gdk.KEY_l: "flip_side", Gdk.KEY_n: "new_workspace"}
FIND_ROW_ACTIONS = {Gdk.KEY_k: "pin", Gdk.KEY_t: "new_tab"}

# Seconds the panel stays open, and a highlighted row stays marked, after the last of those keys.
NAV_IDLE_S = 5

# The faint reminder along the bottom of the find window.
FIND_HINT = (
    "↑↓ pick   Enter open   Del close tab   ^K pin tab   ^T new tab\n"
    "^P pin dock   ^I icons   ^L side   ^N new workspace   ^A auto/all   ^1/2/3 view"
)

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
# Ctrl+Shift+T reopens the closed tab, as in the browser (Super may still be down from the hotkey).
RESTORE_MODS = Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.CONTROL_MASK
# The keys that switch view, or with Ctrl workspace (steps), while the find window's entry is empty.
WORKSPACE_KEYS = {Gdk.KEY_Left: -1, Gdk.KEY_Right: 1, Gdk.KEY_KP_Left: -1, Gdk.KEY_KP_Right: 1}


def group_key(browser, gid):
    """What `collapsed` holds for a Firefox tab group (folded in every container section it shows in)."""
    return (browser, f"group:{gid}")


def group_class(color):
    """The style class of a Firefox tab group colour (an unknown one is drawn grey)."""
    return "gc-" + (color if color in GROUP_COLORS else "gray")


def acc_class(colour):
    """The style class that carries one browser's colour, so several browsers can show at once."""
    return "acc-" + colour.lstrip("#")


# The colours that must differ from row to row (with several browsers listed, "the accent" is no
# longer one colour): the active tab, the drop marker and the chips. Loaded again only when [theme] changes.
def browser_css(colours):
    """The rules for each browser colour in `colours` (a text readable on it where it fills something)."""
    return "".join(
        f".sp-row.active.{acc_class(c)} {{ border-left-color: {c}; }}"
        f".sp-row.kbd.{acc_class(c)} {{ border-left-color: {c}; box-shadow: inset 0 0 0 1px {c}; }}"
        f".sp-row.sp-bhead.kbd.{acc_class(c)} {{ box-shadow: inset 0 0 0 2px #1b1d23; }}"
        f".sp-row.drop-before.{acc_class(c)} {{ box-shadow: inset 0 2px 0 0 {c}; }}"
        f".sp-row.drop-after.{acc_class(c)} {{ box-shadow: inset 0 -2px 0 0 {c}; }}"
        f"button.sp-btn.sp-chip.{acc_class(c)} {{ border-color: {c}; }}"
        f"button.sp-btn.sp-chip.{acc_class(c)}:hover {{ border-color: shade({c}, 1.35); }}"
        f"button.sp-btn.sp-chip.selected.{acc_class(c)} {{ background-color: {c}; border-color: {c}; color: {on_accent(c)}; }}"
        f".sp-bhead.{acc_class(c)} {{ background-color: {c}; }}"
        f".sp-bhead.{acc_class(c)}:hover {{ background-color: shade({c}, 1.15); }}"
        f".sp-bhead.{acc_class(c)} .sp-bandlabel {{ color: {on_accent(c)}; }}"
        f"button.sp-btn.sp-ws.selected.{acc_class(c)} {{ box-shadow: inset 0 -2px 0 0 {c}; }}"
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

# Firefox's tab group colours: the pill that heads a group and the line down the left of its tabs.
GROUP_CSS = "".join(
    f".sp-pill.{group_class(name)} {{ background-color: {c}; color: {on_accent(c)}; }}"
    f".sp-ingroup.{group_class(name)} {{ border-left: 2px solid {c}; }}"
    for name, c in GROUP_COLORS.items()
)

STATIC_CSS = WS_CSS + GROUP_CSS

# Firefox container icon names -> a glyph (best effort; unknown names fall back to a dot)
ICONS = {
    "fingerprint": "☺", "briefcase": "💼", "dollar": "$", "cart": "🛒", "circle": "●",
    "gift": "🎁", "vacation": "🌴", "food": "🍴", "fruit": "🍎", "pet": "🐾",
    "tree": "🌲", "chill": "❄", "fence": "🚧",
}
CONTAINER_ICONS = tuple(ICONS)  # the icons Firefox offers a container, in its order


DRAG_THRESHOLD = 6  # px the pointer must travel with the button down before a click becomes a drag
PRESS_STALE_S = 30  # a press with no release this long is forgotten, so updates cannot stay blocked
GHOST_S = 8  # seconds a tab closed from the panel stays in its place as an undo (see DockView._ghost_row)
GHOST_GUARD_S = 0.5  # a click on it sooner than this is ignored: a double click on the ✕ must not undo itself
GHOST_RESTORING_S = 3  # after the click its row waits this long for the tab to come back, then goes anyway
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
    def __init__(self, cfg, on_activate, on_quit, xconn=None, on_command=None, on_choose=None, on_raise=None):
        self.cfg = dict(cfg)
        self.on_activate = on_activate
        self.on_command = on_command  # on_command(conn, message): what a drop asks the browser to do
        self.on_choose = on_choose  # on_choose("auto" | "all" | conn): a chip was clicked
        self.on_raise = on_raise  # on_raise(conn): bring that browser's window forward (a tab was made or brought back)
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
        self._groups_seen = set()  # (browser, tab group id) met: a group Firefox has collapsed starts folded, once
        self._nav_timer = None  # the idle timeout of the keys that work without the find window
        self._mode = "auto"  # what the chips say: "auto", "all" or a conn
        self._choices = ()  # (conn, label, colour) of the chips built
        self._chip_buttons = []  # (key, button)
        self._ws_buttons = []  # (conn, workspace id or None for "+", button) of the rows built last
        self._close_buttons = []  # (tab id, its ✕ button) of the rows built last
        self._view = "tabs"  # "tabs", "bookmarks" or "history" (those two only while cfg[view] is on and the extension can)
        self._lists = {}  # (view, conn) -> the extension's last "bookmarks" or "history" message
        self._asked = set()  # (view, conn) asked for and not answered yet
        self._scroll_top = False  # the next list starts at the top (a view was switched)
        self._first_url = None  # (conn, url, window) of the first bookmark or visit listed while finding
        self._query = ""  # what the find window has typed: only the tabs that match are listed, from every workspace
        self._first_match = None  # (conn, tab id, window id) of the first tab listed while finding
        self._ghost = None  # the tab just closed from the panel: {conn, id, title, group, position, t}
        self._ghost_timer = None
        self._selected = None  # (conn, row id) of the row the arrow keys have highlighted while finding
        self._find_dialog = None  # the find window, while it is up (self._dialog may be another window)
        self._state = {}  # the state of the browser whose rows are being built
        self._middle = None  # the row a middle button went down on: releasing it there closes that tab
        self._holds = set()  # why the panel must stay open whatever the pointer does: "drag", "menu", "dialog"
        self._menu = None  # the context menu up (kept referenced while it is shown)
        self._dialog = None  # the window asking for a workspace name, while it is up
        self._dialog_finish = None  # finish(accepted) of that window
        self.collapsed = set()  # (browser pid, cookieStoreId) of folded container sections; (pid, None) a folded browser
        self.opened = set()  # (browser pid, "/3/0") of the bookmark folders opened: they all start closed
        self.hidden = False
        self._last = None  # what the last render showed, to skip identical ones
        self._offline = ()  # [(name, executable)] of the browsers that can be started from the panel
        self._starting = set()  # names clicked lately: no row until the browser connects, or 30 s pass
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
        self._per_browser.load_from_data((browser_css(self._colours.values()) + STATIC_CSS).encode())
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
        self.flip_btn.connect("clicked", lambda _b: self.flip_side())
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

        # Tabs / Bookmarks: only shown while a view besides the tabs is on
        self.views = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.views.get_style_context().add_class("sp-views")
        self._view_buttons = []
        self._find_view_buttons = []  # the same buttons in the find window, while it is up
        self._find_switch = None  # the box holding them
        for key, label in (("tabs", "Tabs"), ("bookmarks", "Bookmarks"), ("history", "History")):
            button = self._button(label, f"Show the {label.lower()}", Gtk.Button)
            button.get_style_context().add_class("sp-view")
            button.connect("clicked", lambda _b, key=key: self._set_view(key))
            self.views.pack_start(button, False, False, 0)
            self._view_buttons.append((key, button))

        self.content.pack_start(header, False, False, 0)
        self.content.pack_start(self.chips, False, False, 0)
        self.content.pack_start(self.scroll, True, True, 0)
        self.content.pack_start(self.views, False, False, 0)
        self.win.get_child().add(self.content)
        self.win.get_child().show_all()  # the panel window itself is only shown while expanded
        self.views.set_visible(False)
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

    def show(self, sources, mode="auto", choices=(), focus=None, offline=()):
        """List the browsers in `sources` ([(conn, hello, state)]). `mode` ("auto", "all" or a conn) and
        `choices` ([(conn, label, colour)] of every connected browser) drive the chips; `focus` is the
        hello of the browser whose colour the header and the strip wear (the only one listed, by default).
        `offline`: [(name, executable)] of browsers to offer starting, as dimmed rows."""
        if self._press is not None and not self._pressing():
            self._end_press()  # a press whose release never came: let go of the hold and the drag marks
        if self._pressing():
            self._deferred = (sources, mode, choices, focus, offline)  # rows are being pressed or dragged: redraw after the drop
            return
        self._deferred = None
        self._ws_pending = None
        self.sources = list(sources)
        self._offline = tuple(offline)
        self._names = {conn: label for conn, label, _colour in choices}
        if focus is None and len(self.sources) == 1:
            focus = self.sources[0][1]
        self._focus = focus
        for _conn, info, state in self.sources:  # a group Firefox has collapsed starts folded, once
            browser = info.get("browserPid") or info.get("browser")
            for group in state.get("groups") or []:
                if (browser, group["id"]) not in self._groups_seen:
                    self._groups_seen.add((browser, group["id"]))
                    if group.get("collapsed"):
                        self.collapsed.add(group_key(browser, group["id"]))
        self._mode = mode
        for gone in [k for k in self._lists if k[1] not in self._names]:  # a browser that left: forget its lists
            del self._lists[gone]
        self._asked = {k for k in self._asked if k[1] in self._names}
        if len(self.sources) == 1:
            conn, info, _state = self.sources[0]
            self.browser_name.set_text(self._name(conn, info))
            self.browser_name.set_tooltip_text(f"{browser_label(info)}\nRight-click to set its colour (shared by every browser of its kind)")
            self._current_source = (conn, info)
        else:
            self.browser_name.set_text("All browsers")
            self.browser_name.set_tooltip_text("Choose one browser below, then right-click its name to set its colour")
            self._current_source = None
        # only the strip and the header wear it: no rebuild
        self._set_accent(accent(focus, self._colours) if focus else self._colours["other"])
        listed = self.sources if self._view == "tabs" else [  # bookmarks do not change with the tabs
            (c, i, (focused_window(s) or {}).get("id")) for c, i, s in self.sources]
        snapshot = (listed, frozenset(self.collapsed), mode, tuple(choices), self._offline)
        if snapshot != self._last:
            self._last = snapshot
            self._set_chips(mode, choices)
            self._set_views()
            self._rebuild()

    def clear(self, mode="auto", choices=(), offline=()):
        """Nothing to list (yet). The chips stay when browsers are connected: they lead to another one."""
        self._end_press()
        self._deferred = None
        self._clear_ghost()  # (its timer would rebuild the list over the waiting text)
        self.sources = []
        self._offline = tuple(offline)
        self._mode = mode
        self._names = {}
        self._lists, self._asked = {}, set()
        self._last = None
        self._meta, self._row_order = {}, []
        self._ws_buttons = []
        self._set_chips(mode, choices)
        self.views.set_visible(False)
        self.browser_name.set_text("")
        self.browser_name.set_tooltip_text(None)
        self._current_source = None
        self._set_accent(self._colours["other"])
        self._replace_rows([self._label(waiting_text(), "sp-empty", wrap=True), *self._offline_rows()])

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

    def flip_side(self):
        self.set_side("right" if self.cfg["side"] == "left" else "left")

    def toggle_pin(self):
        self.pin_btn.set_active(not self.pin_btn.get_active())

    def toggle_icons(self):
        self.icons_btn.set_active(not self.icons_btn.get_active())

    def new_workspace(self):
        """As the "+" chip: asks for a name, then makes the workspace in the browser in use. From the find window
        that window closes first."""
        source = self._keyboard_source()
        window = source and offers_workspaces(source[1], source[2]) and focused_window(source[2])
        if not window or self._dialog not in (None, self._find_dialog):
            return
        if self._dialog is not None:
            self._dialog_finish(False)
        self.set_hidden(False)
        self._clear_highlight()

        def make(name):
            self._command(source[0], {"type": "new_workspace", "windowId": window["id"], "name": name})
            self._raise(source[0])  # the new tab is in its window: what is typed next goes there

        self._ask_name("New workspace", f"Workspace {len(workspaces(source[2])) + 1}", make)

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
                 "and DNS, not through the browser's proxy (see docs/USAGE.md)"
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
        was = self._view
        self._lists = {k: v for k, v in self._lists.items() if self.cfg[k[0]]}
        self._set_views()
        self._last = None
        if self._view != was and self.sources:
            self._rebuild()
        self._place()  # side, width or monitor may have changed too
        colours = accents(self.cfg.get("theme"))
        if colours != self._colours:  # new [theme] colours: the next show() rebuilds the rows in them
            self._colours = colours
            self._per_browser.load_from_data((browser_css(colours.values()) + STATIC_CSS).encode())
            self._last = None
            if not self.sources:
                self._set_accent(colours["other"])  # (nothing listed: no show() to come)

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
        self._clear_ghost()
        self._end_nav()
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

    def _view_source(self, view):
        """(conn, hello, state) whose `view` ("bookmarks" or "history") is on offer, or None: the option is off, the
        extension cannot, or several browsers are listed (one browser's list, never a mix)."""
        source = self._keyboard_source() if len(self.sources) == 1 else None
        return source if source and self.cfg[view] and supports(source[1], view) else None

    def _set_views(self):
        """Show the Tabs / Bookmarks / History buttons for the views on offer; fall back to the tabs when the one up is not."""
        offered = {view for view in ("bookmarks", "history") if self._view_source(view) is not None}
        if self._view not in offered:
            self._view = "tabs"
        self.views.set_visible(bool(offered))
        if self._find_switch is not None:
            self._find_switch.set_visible(bool(offered))
        for key, button in (*self._view_buttons, *self._find_view_buttons):
            button.set_visible(key == "tabs" or key in offered)
            ctx = button.get_style_context()
            (ctx.add_class if key == self._view else ctx.remove_class)("selected")

    def _set_view(self, view):
        if view == self._view or (view != "tabs" and self._view_source(view) is None):
            return
        self._view = view
        self._scroll_top = True
        if view != "tabs":
            conn = self._view_source(view)[0]
            if view == "history":
                self._lists.pop((view, conn), None)  # a list of another search must not show meanwhile
            self._ask(view, conn)  # fresh each time: the panel keeps no copy in sync
        self._set_views()
        self._last = None
        self._rebuild()

    def _ask(self, view, conn):
        self._asked.add((view, conn))
        if view == "bookmarks":
            self._command(conn, {"type": "get_bookmarks"})
        else:
            self._command(conn, {"type": "search_history", "query": self._query.strip()})

    def _got(self, view, conn, msg):
        if not self.cfg[view]:
            return  # granted in the browser, but not switched on here: nothing is kept
        if view == "history" and msg.get("granted") and msg.get("query", "") != self._query.strip():
            if not (self._lists.get((view, conn)) or {}).get("granted", True):
                self._ask(view, conn)  # the permission was just granted: the news carries no search
            return  # else the answer to a search typed since
        self._asked.discard((view, conn))
        self._lists[(view, conn)] = msg
        if self._view == view:
            self._last = None
            self._rebuild()

    def show_bookmarks(self, conn, msg):
        """The extension's answer to get_bookmarks (or its news that the permission was just granted)."""
        self._got("bookmarks", conn, msg)

    def show_history(self, conn, msg):
        """The extension's answer to search_history (or its news that the permission was just granted)."""
        self._got("history", conn, msg)

    def _list_message(self, view, conn, colour):
        """(msg, None) once the extension has answered with a list to show, else (None, the rows saying why not)."""
        msg = self._lists.get((view, conn))
        if msg is None:
            if (view, conn) not in self._asked:  # the browser changed under the view, or the panel restarted
                self._ask(view, conn)
            return None, [self._label(f"Loading {view}…", "sp-empty", wrap=True)]
        if msg.get("error"):
            return None, [self._label(f"The browser could not list its {view}", "sp-empty", wrap=True)]
        if not msg.get("granted"):
            text = f"tabdock may not read {view} yet. Click here and tick “Allow tabdock to read {view}”."
            row = self._row(self._label(text, "sp-empty", wrap=True), "view_help", None, None, conn, colour,
                            lambda: (self._command(conn, {"type": "open_options"}), self._raise(conn)),
                            draggable=False)
            return None, [row]
        return msg, None

    def _list_row(self, conn, colour, kind, ident, label, click, indent=0, trailing=None):
        """A row of a bookmarks or history list: `label`, an optional widget at the far end, and `indent` levels in."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.get_style_context().add_class("sp-tabbox")
        box.set_margin_start(12 * indent)
        box.pack_start(label, True, True, 0)
        if trailing is not None:
            box.pack_end(trailing, False, False, 0)
        return self._row(box, kind, ident, None, conn, colour, click, draggable=False)

    def _url_label(self, title, url):
        label = self._label(title, "sp-tab")
        label.set_tooltip_text(f"{title}\n{url}")
        return label

    def _bookmark_list(self, conn, info, state):
        """The rows of the Bookmarks view for one browser. Folders start closed: only what is opened gets built."""
        colour = accent(info, self._colours)
        browser = info.get("browserPid") or info.get("browser")
        msg, rows = self._list_message("bookmarks", conn, colour)
        if msg is None:
            return rows
        window = focused_window(state)
        query = self._query
        opened = {key[1] for key in self.opened if key[0] == browser}
        rows = []
        for depth, node, path in bookmark_rows(msg.get("tree", []), query, opened):
            # the ident is (position, url): the same page in two folders is two rows, and the arrow keys tell them apart
            ident = (len(rows), node.get("url"))
            if path is not None:
                arrow = "▾" if path in opened else "▸"
                label = self._label(f'{arrow} <b>{GLib.markup_escape_text(node["title"] or "folder")}</b>',
                                    "sp-tab", markup=True)
                rows.append(self._list_row(conn, colour, "bookmark_folder", ident, label,
                                           lambda key=(browser, path): self._toggle_folder(key), depth))
            else:
                url = node["url"]
                rows.append(self._list_row(conn, colour, "bookmark", ident, self._url_label(node["title"], url),
                                           lambda url=url: self._open_url(conn, url, window), depth))
                self._note_first(conn, url, window, True)
        if not rows:
            text = f"No bookmark matches “{query.strip()}”" if query.strip() else "No bookmarks"
            rows.append(self._label(text, "sp-empty", wrap=True))
        return rows

    def _history_list(self, conn, info, state):
        """The rows of the History view for one browser: the newest visits, under a heading for each day."""
        colour = accent(info, self._colours)
        msg, rows = self._list_message("history", conn, colour)
        if msg is None:
            return rows
        window = focused_window(state)
        query = self._query.strip()
        rows = []
        day = None
        for item in msg.get("items", []):
            when = datetime.fromtimestamp(item.get("lastVisitTime", 0) / 1000)
            if when.date() != day:
                day = when.date()
                heading = self._label(day_label(day, datetime.now().date()), "sp-section")
                heading.get_style_context().add_class("sp-sectionbox")
                rows.append(heading)
            url = item["url"]
            rows.append(self._list_row(conn, colour, "history", url, self._url_label(item["title"], url),
                                       lambda url=url: self._open_url(conn, url, window),
                                       trailing=self._label(when.strftime("%H:%M"), "sp-where")))
            self._note_first(conn, url, window, msg.get("query", "") == query)  # not an answer to an older search
        if not rows:
            rows.append(self._label(f"No history matches “{query}”" if query else "No history", "sp-empty", wrap=True))
        return rows

    def _note_first(self, conn, url, window, current):
        """The first bookmark or visit listed while finding is what Enter opens when none is highlighted."""
        if self._first_url is None and self._query.strip() and current:
            self._first_url = (conn, url, window)

    def _toggle_folder(self, key):
        self.opened ^= {key}
        self._last = None
        self._rebuild()

    def _open_url(self, conn, url, window):
        self._command(conn, {"type": "open_url", "url": url, "windowId": window["id"] if window else None})
        self._raise(conn)

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
             menu=None, closable=False, findable=False, pick=None, keys=None):
        """A row of the browser `conn`, in its colour. Hover/active styling lives on the EventBox: a
        windowless label gets no prelight.

        A click and a drag share one press, so they never both happen: the click fires on release,
        and moving DRAG_THRESHOLD px with the button down turns the press into a drag instead.
        `menu` ([(label, action)], see _popup) is what a right click offers. `findable` puts the row among the ones
        the find window's arrows stop on, and `pick` is what Enter does there (default: what a click does).
        """
        findable = findable or kind in FIND_KINDS
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
        if findable and (conn, ident) == self._selected:
            box.get_style_context().add_class("kbd")
        box.add(child)
        self._meta[box] = {
            "kind": kind, "id": ident, "group": group, "conn": conn, "click": on_click,
            "pick": pick or on_click, "findable": findable,
            "draggable": draggable, "pinned": pinned, "menu": menu, "closable": closable, "keys": keys or {},
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
        value = 0 if self._scroll_top else adj.get_value()
        self._scroll_top = False
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
        self._first_url = None
        source = self._view_source(self._view) if self._view != "tabs" else None
        if source is not None:
            self._replace_rows((self._bookmark_list if self._view == "bookmarks" else self._history_list)(*source))
            return
        many = len(self.sources) > 1
        rows = []
        finding = bool(self._query.strip())
        for conn, info, state in self.sources:
            # per browser process: two profiles of the same browser fold independently
            browser = info.get("browserPid") or info.get("browser")
            colour = accent(info, self._colours)
            window = focused_window(state)
            self._state = state  # (what a tab row looks its group up in)
            self._check_ghost(conn, state)
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
                    tab_rows = [
                        self._tab_row(tab, window["id"], container["cookieStoreId"], conn, colour, spaces, can,
                                      ordered_containers(state), window.get("workspaceId") if finding else None)
                        for tab in tabs if finding or not self._hidden_by_fold(browser, state, tab)
                    ]
                    ghost = None if finding else self._ghost_row(conn, container["cookieStoreId"], tabs, colour, window)
                    if ghost is not None:
                        tab_rows.insert(min(self._ghost["position"], len(tab_rows)), ghost)
                    rows.extend(tab_rows if finding else self._group_rows(tab_rows, tabs, browser, conn, colour, state,
                                                                          container["cookieStoreId"]))
                if finding and tabs and self._first_match is None:
                    self._first_match = (conn, tabs[0]["id"], window["id"])
        self._row_order = [r for r in rows if r in self._meta]  # (an undo row is made last but sits among the tabs)
        if finding and self._first_match is None:
            rows.append(self._label(f"No tab matches “{self._query.strip()}”", "sp-empty", wrap=True))
        self._replace_rows((rows or [self._label("No browser windows", "sp-empty", wrap=True)]) + self._offline_rows())

    def _offline_rows(self):
        """Dimmed rows that start a browser, after the tab rows. Not draggable. A find query keeps the ones it names."""
        words = self._query.casefold().split()
        rows = []
        for name, binary in self._offline:
            if name in self._starting or not all(w in name.casefold() for w in words):
                continue
            label = self._label(f"Start {name}", "sp-empty")
            label.set_tooltip_text(binary)
            rows.append(self._row(label, "offline", binary, None, None, self._colours["other"],
                                  lambda n=name, b=binary: self._start(n, b), draggable=False))
        return rows

    def _start(self, name, binary):
        launch.launch(binary)
        self._starting.add(name)
        GLib.timeout_add_seconds(30, self._stopped_waiting, name)
        self._redraw_offline()

    def _stopped_waiting(self, name):
        self._starting.discard(name)
        self._redraw_offline()
        return False

    def _redraw_offline(self):
        if self.sources:
            self._last = None
            self._rebuild()
        else:
            self._meta, self._row_order = {}, []
            self._replace_rows([self._label(waiting_text(), "sp-empty", wrap=True), *self._offline_rows()])

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
            lambda: self._toggle(key), draggable=False, findable=self._mode == "all" and not self._query.strip(),
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
        has_new = cid == NO_CONTAINER or cid in known
        new_tab = lambda: self._new_tab(conn, cid, window_id)  # noqa: E731
        empty = has_new and not tabs
        if has_new:
            button = self._button(
                "+", "New tab" if cid == NO_CONTAINER else f"New tab in {container['name']}", Gtk.Button
            )
            button.get_style_context().add_class("sp-newtab")
            button.connect("clicked", lambda _b: new_tab())
            box.pack_start(button, False, False, 0)
        return self._row(
            box, "section", cid, None, conn, browser_colour, (lambda: self._toggle(key)) if tabs else (lambda: None),
            findable=empty, pick=new_tab if empty else None, keys={"new_tab": new_tab} if empty else None,
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

    def _hidden_by_fold(self, browser, state, tab):
        """A tab of a folded Firefox tab group is not listed, except the active one (as Firefox keeps it in view)."""
        group = tab_group(state, tab)
        return group is not None and group_key(browser, group["id"]) in self.collapsed and not tab.get("active")

    def _group_rows(self, rows, tabs, browser, conn, colour, state, store):
        """`rows` (the listed tab rows of the container `store`) with a pill before each run of tabs in a Firefox tab
        group. `tabs`: all of the container's tabs, which the pill counts."""
        index = {t["id"]: i for i, t in enumerate(tabs)}
        runs, run = [], None  # (where a run of one group starts, the group)
        for i, tab in enumerate(tabs):
            group = tab_group(state, tab)
            gid = group["id"] if group else None
            if gid != run:
                run = gid
                if group:
                    runs.append((i, group))
        out = []

        def pill(group):
            size = sum(1 for t in tabs if t.get("groupId") == group["id"])
            key = group_key(browser, group["id"])
            out.append(self._group_row(group, size, key, key in self.collapsed, conn, colour, store))

        for row in rows:
            meta = self._meta[row]
            if meta["kind"] == "tab":  # (an undo row stays where it is)
                while runs and runs[0][0] <= index[meta["id"]]:
                    pill(runs.pop(0)[1])
            out.append(row)
        for _start, group in runs:  # a folded group with no tab listed still has its pill
            pill(group)
        return out

    def _group_row(self, group, size, key, folded, conn, colour, store):
        """The pill that heads a Firefox tab group: its name in its colour, how many tabs, and ▾ or ▸. A group with
        tabs in several containers has a pill in each, so the row's id names the container too."""
        name = GLib.markup_escape_text(group["title"] or "Unnamed group")
        arrow = "▸" if folded else "▾"
        label = self._label(f'{name}  <span alpha="70%">({size})  {arrow}</span>', "sp-pill", markup=True)
        label.get_style_context().add_class(group_class(group["color"]))
        label.set_halign(Gtk.Align.START)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        box.get_style_context().add_class("sp-grouprow")
        box.pack_start(label, False, False, 0)
        return self._row(box, "tabgroup", f"group:{group['id']}:{store}", None, conn, colour,
                         lambda: self._toggle(key), draggable=False, findable=True)

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
        headed = firefox_group is not None and not self._query.strip()  # (a pill heads its tabs, except in a find)
        if headed:
            box.get_style_context().add_class("sp-ingroup")
            box.get_style_context().add_class(group_class(firefox_group["color"]))
        elif firefox_group is not None:  # Firefox's own tab group: its name, in its colour
            title = firefox_group["title"]
            tag = self._label(
                f'<span foreground="{GROUP_COLORS.get(firefox_group["color"], GROUP_COLORS["gray"])}">'
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
        if "tab_groups" in can and not pinned:  # (a pinned tab cannot be in a group)
            current = tab_group(self._state, tab)
            others = [g for g in window_groups(self._state) if current is None or g["id"] != current["id"]]
            items = [
                (Markup(f'<span foreground="{GROUP_COLORS.get(g["color"], GROUP_COLORS["gray"])}">▌</span> '
                        f'{GLib.markup_escape_text(g["title"] or "Unnamed group")}'),
                 lambda gid=g["id"]: self._command(conn, {"type": "group_tab", "tabId": tab["id"], "groupId": gid}))
                for g in others
            ]
            if items:
                items.append((None, None))
            items.append(("New group…", lambda: self._ask_name(
                "New group", "", lambda name: self._command(conn, {"type": "group_tab", "tabId": tab["id"], "title": name}))))
            part = [("Add to group", items)]
            if current is not None:
                part.append(("Remove from group", lambda: self._command(conn, {"type": "ungroup_tab", "tabId": tab["id"]})))
            groups.append(part)
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
        keys = {}  # what the find window's Delete, Ctrl+K and Ctrl+T do on this row
        if "close_tab" in can:
            keys["close"] = lambda: self._close_tab(conn, tab["id"])
        if "pin_tab" in can:
            keys["pin"] = lambda: self._command(conn, {"type": "pin_tab", "tabId": tab["id"], "pinned": not pinned})
        if store == NO_CONTAINER or store in {c["cookieStoreId"] for c in containers}:
            keys["new_tab"] = lambda: self._new_tab(conn, store, window_id)
        return self._row(
            box, "tab", tab["id"], group, conn, colour, lambda: self.on_activate(conn, tab["id"], window_id),
            active=bool(tab.get("active")), pinned=pinned, menu=menu, closable="close_tab" in can, keys=keys,
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
        every word of it, from every workspace. Down and Up highlight a tab, Left and Right switch view and Ctrl+Left and Ctrl+Right workspace (see
        _on_find_key); Enter picks the highlighted tab, or the first one when none is (switching to its workspace),
        Escape gives the whole list back."""
        previous = self._view
        entry = Gtk.Entry(placeholder_text="Title or address")
        entry.set_width_chars(36)
        switch = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        buttons = []
        for key, label in (("tabs", "Tabs"), ("bookmarks", "Bookmarks"), ("history", "History")):
            button = self._button(label, f"{label}  (Ctrl+{'123'[len(buttons)]})", Gtk.Button)
            button.get_style_context().add_class("sp-view")
            button.connect("clicked", lambda _b, key=key: self._find_view(key))
            switch.pack_start(button, False, False, 0)
            buttons.append((key, button))
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content.pack_start(switch, False, False, 0)
        content.pack_start(entry, False, False, 0)

        def narrow(_entry):
            self._query = entry.get_text()
            self._last = None
            source = self._view_source("history") if self._view == "history" else None
            if source is not None:
                self._first_url = None  # what was listed answers an older search
                self._ask("history", source[0])  # the browser searches all of its history; the answer redraws
            else:
                self._rebuild()

        def answer(accepted):
            box = self._highlighted()
            pick = self._meta[box]["pick"] if box is not None else None  # what Enter does on that row
            first = self._first_match
            first_url = self._first_url
            self._find_switch, self._find_view_buttons = None, []
            source = self._view_source("history") if self._view == "history" and self._query.strip() else None
            if source is not None:
                self._lists.pop(("history", source[0]), None)  # the answer to the search: _rebuild asks for the whole list
                self._asked.discard(("history", source[0]))
            self._find_dialog = None
            self._ws_pending = None
            self._query = ""
            self._selected = None
            self._last = None
            if self._view != previous:
                self._set_view(previous)  # a find only changes what is searched, not the view the panel shows
            self._rebuild()
            if accepted and pick is not None:
                pick()
            elif accepted and first is not None:
                self.on_activate(*first)
            elif accepted and first_url is not None:
                conn, url, window = first_url
                self._open_url(conn, url, window)

        finish, _ok = self._small_window("Find", content, "Go", answer, focus=entry, beside=True, hint=FIND_HINT)
        self._find_dialog = self._dialog
        self._find_switch, self._find_view_buttons = switch, buttons
        self._set_views()  # hides the buttons of the views not on offer
        entry.connect("changed", narrow)
        entry.connect("activate", lambda _e: self._find_accept())
        entry.connect("key-press-event", self._on_find_key)
        self._dialog_entry = entry

    def _step_view(self, step):
        """Search the view `step` away (Tabs, Bookmarks, History: those on offer), stopping at the ends."""
        order = [v for v in ("tabs", "bookmarks", "history") if v == "tabs" or self._view_source(v) is not None]
        at = order.index(self._view) + step if self._view in order else -1
        if 0 <= at < len(order):
            self._find_view(order[at])

    def _find_accept(self):
        """Enter in the find window: on a highlighted bookmark folder it opens or closes the folder, and on a browser
        header or a tab group's pill it folds or unfolds it; the window stays either way. Anything else is picked and the window closes."""
        box = self._highlighted()
        if box is not None and self._meta[box]["kind"] in FOLD_KINDS:
            self._meta[box]["click"]()  # the list is rebuilt, and the same row is highlighted again
        else:
            self._dialog_finish(True)

    def _find_view(self, view):
        """Search another view (its buttons in the find window, Ctrl+1/2/3); what is typed stays and filters it."""
        if view == self._view or (view != "tabs" and self._view_source(view) is None):
            return
        self._selected = None
        self._set_view(view)

    def _find_rows(self):
        return [b for b in self._row_order if self._meta[b]["findable"]]

    def _tab_rows(self):
        return [b for b in self._row_order if self._meta[b]["kind"] == "tab"]

    def _tab_key(self, box):
        return self._meta[box]["conn"], self._meta[box]["id"]

    def _on_find_key(self, entry, event):
        """Down, Up, Page Down, Page Up, Home and End walk the tab rows while the find window has the keyboard.
        The arrows are always taken, even with nothing to walk: GTK would move the focus off the entry with them.
        Home and End stay the entry's caret keys when chorded (Shift+Home selects text) or when no tab is listed.
        Left and Right switch view (Tabs, Bookmarks, History), Ctrl+Left and Ctrl+Right switch workspace, but only
        while nothing is typed: they are the caret's after that, and the list spans every workspace then anyway. Ctrl+Shift+T reopens the tab closed last, as in the browser, and
        closes the window.
        The hotkey's Super may still be down, so it changes none of this, and Enter still picks."""
        if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and event.state & Gtk.accelerator_get_default_mod_mask():
            self._find_accept()  # (the entry's own "activate" needs every modifier up)
            return True
        if event.keyval in (Gdk.KEY_t, Gdk.KEY_T) and event.state & CARET_MODS == RESTORE_MODS:
            if self._restore_tab():
                self._dialog_finish(False)  # the tab is back: the keyboard goes on to the browser
            return True
        lower = Gdk.keyval_to_lower(event.keyval)
        if lower == Gdk.KEY_a and event.state & CARET_MODS == Gdk.ModifierType.CONTROL_MASK and len(self._choices) > 1:
            self.toggle_all()
            return True
        if event.state & CARET_MODS == Gdk.ModifierType.CONTROL_MASK and (lower in FIND_ACTIONS or lower in FIND_ROW_ACTIONS):
            if lower in FIND_ACTIONS:
                getattr(self, FIND_ACTIONS[lower])()
            else:
                act = self._row_action(FIND_ROW_ACTIONS[lower])
                if act:
                    act()
                    if lower == Gdk.KEY_t:
                        self._dialog_finish(False)  # the browser is raised: the keyboard goes on to it
            return True
        if event.keyval in (Gdk.KEY_Delete, Gdk.KEY_KP_Delete) and not event.state & CARET_MODS:
            close = self._row_action("close")
            if close and not entry.get_selection_bounds() and entry.get_position() == len(entry.get_text()):
                rows = self._find_rows()  # (elsewhere Delete deletes text)
                at = next(i for i, b in enumerate(rows) if self._tab_key(b) == self._selected)
                close()
                near = [b for b in rows[at + 1:] + rows[:at][::-1] if self._meta[b]["kind"] == "tab"]
                if near:  # the highlight moves to the neighbouring tab, which the rebuild marks
                    self._selected = self._tab_key(near[0])
                return True
            return False
        if event.keyval in FIND_VIEW_KEYS and event.state & CARET_MODS == Gdk.ModifierType.CONTROL_MASK:
            self._find_view(FIND_VIEW_KEYS[event.keyval])
            return True
        if event.keyval in WORKSPACE_KEYS:
            if entry.get_text().strip():  # (as _rebuild counts a query: blanks alone list nothing more)
                return False
            mods = event.state & CARET_MODS
            if mods == Gdk.ModifierType.CONTROL_MASK:
                if self._view == "tabs":  # elsewhere the list would not show the switch
                    self._step_workspace(WORKSPACE_KEYS[event.keyval])
            elif not mods:
                self._step_view(WORKSPACE_KEYS[event.keyval])
            else:
                return False  # Shift and Alt chords are the caret's
            return True
        if event.keyval not in FIND_KEYS:
            return False
        step, from_nothing = FIND_KEYS[event.keyval]
        listed = any(self._meta[b]["kind"] != "offline" for b in self._find_rows())  # Start rows alone leave Home/End to the caret
        if from_nothing and (not listed or event.state & CARET_MODS):
            return False
        self._walk(step, from_nothing)
        return True

    def _walk(self, step, from_nothing=False):
        rows = self._find_rows()
        if rows:
            keys = [self._tab_key(b) for b in rows]
            current = None if from_nothing or self._selected not in keys else keys.index(self._selected)
            self._select(rows[step_index(current, len(rows), step)])

    # -- keys without the find window: `tabdock --next`, `--prev`, `--open`, `--all`, `--ws-next`, `--ws-prev` ------------------------------

    def _nav(self):
        """The panel is shown and stays open while keys move the highlight; it lets go, and the highlight goes, after
        NAV_IDLE_S without one."""
        self.set_hidden(False)
        self._hold("keys", True)
        if self._nav_timer is not None:
            GLib.source_remove(self._nav_timer)
        self._nav_timer = GLib.timeout_add_seconds(NAV_IDLE_S, self._end_nav)

    def _end_nav(self):
        if self._nav_timer is not None:
            GLib.source_remove(self._nav_timer)
            self._nav_timer = None
        self._hold("keys", False)
        self._ws_pending = None  # (a switch that never arrived must not steer the next key)
        if self._dialog is None:
            self._clear_highlight()
        return False

    def _clear_highlight(self):
        self._selected = None
        for row in self._row_order:
            row.get_style_context().remove_class("kbd")

    def nav_next(self):
        self._nav()
        self._walk(1)

    def nav_prev(self):
        self._nav()
        self._walk(-1)

    def nav_open(self):
        """Enter: a browser header folds or unfolds; a tab opens, and the highlight goes."""
        box = self._highlighted()
        if box is None:
            return
        if self._dialog is not None and self._dialog is self._find_dialog:
            self._find_accept()
            return
        if self._meta[box]["kind"] in FOLD_KINDS:
            self._nav()
            self._meta[box]["click"]()
            return
        pick = self._meta[box]["pick"]
        self._end_nav()
        pick()

    def _ws_key(self, step):
        """`--ws-next` and `--ws-prev`: as Ctrl+Left and Ctrl+Right, but with no window up: the panel shows the switch."""
        if self._dialog is None:
            self._nav()
            self._step_workspace(step)

    def ws_next(self):
        self._ws_key(1)

    def ws_prev(self):
        self._ws_key(-1)

    def toggle_all(self):
        """Ctrl+A, or `tabdock --all`: between "all" (the arrows also stop on the browser headers) and "auto". Leaving "all" from a
        highlighted row makes its browser the one in use, and the keyboard goes on to it."""
        if len(self._choices) < 2 or self._dialog not in (None, self._find_dialog):
            return
        if self._dialog is None:
            self._nav()
        if self._mode != "all":
            self._choose("all")
            return
        box = self._highlighted()
        conn = box and self._meta[box]["conn"]  # (choosing rebuilds the rows)
        self._choose("auto")
        if conn is not None:
            self._raise(conn)
            if self._dialog is not None:
                self._dialog_finish(False)
            self._end_nav()

    def _highlighted(self):
        return next((b for b in self._find_rows() if self._tab_key(b) == self._selected), None)

    def _row_action(self, name):
        """What `name` does on the highlighted row, or None."""
        box = self._highlighted()
        return box and self._meta[box]["keys"].get(name)

    def _keyboard_source(self):
        """(conn, hello, state) of the browser the find window's keys act on: the one listed, or of several the one
        in use."""
        return next((s for s in self.sources if len(self.sources) == 1 or s[1] is self._focus), None)

    def _raise(self, conn):
        if self.on_raise is not None:
            self.on_raise(conn)

    def _restore(self, conn):
        self._command(conn, {"type": "restore_tab"})
        self._raise(conn)  # (the tab comes back there, even when asked from the find window in a terminal)

    def _restore_tab(self):
        """Reopen the tab closed last, in the find window's browser. False, and nothing sent, when its extension
        cannot."""
        source = self._keyboard_source()
        if source is None or not supports(source[1], "restore_tab"):
            return False
        self._clear_ghost()  # the tab comes back under a new id: the undo row would name it twice
        self._restore(source[0])
        return True

    def _step_workspace(self, step):
        """Switch the window to the workspace `step` away, stopping at the ends, as a click on its chip does: of the
        browser listed, or of the one in use among several. The tabs listed change, so no tab stays highlighted."""
        source = self._keyboard_source()
        target = source and offers_workspaces(source[1], source[2]) and workspace_step(source[2], step, self._ws_pending)
        if not target:
            return
        self._ws_pending = target[1]  # (keys pressed before the browser reports the switch count from here)
        self._clear_highlight()
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

    def _new_tab(self, conn, store, window_id):
        """A "+". The browser puts the cursor in a new tab's address bar (a tab made without an address does), so
        bring its window forward: what you type next is a search or an address there."""
        self._command(conn, {"type": "new_tab", "cookieStoreId": store, "windowId": window_id})
        self._raise(conn)

    def _close_tab(self, conn, tab_id):
        self._note_closed(conn, tab_id)
        self._command(conn, {"type": "close_tab", "tabId": tab_id})

    # -- undoing a close ---------------------------------------------------------------------

    # A tab closed from the panel leaves its row behind for a few seconds, struck through, with a ↶ where its ✕ was:
    # one click brings it back to that place. The browser restores the tab it closed last, so the row is only kept
    # while that is still this tab: it goes as soon as another one closes.

    def _note_closed(self, conn, tab_id):
        """Remember the tab about to close (its title, place and window), if its browser can restore it."""
        self._clear_ghost()  # whatever was closed before is not the tab closed last any more
        info = next((i for c, i, _s in self.sources if c is conn), None)
        box = next((b for b in self._tab_rows() if self._tab_key(b) == (conn, tab_id)), None)
        state = self._state_of(conn) or {}
        found = next(((w, t) for w in state.get("windows", []) for t in w["tabs"] if t["id"] == tab_id), None)
        if info is None or box is None or found is None or not supports(info, "restore_tab") or self._query.strip():
            return
        window, tab = found
        group = self._meta[box]["group"]
        peers = [b for b in self._tab_rows() if self._meta[b]["conn"] is conn and self._meta[b]["group"] == group]
        self._ghost = {
            "conn": conn, "id": tab_id, "title": tab_label(tab), "group": group, "position": peers.index(box),
            "window": window["id"], "workspace": window.get("workspaceId"),  # (it shows only where it was closed)
            "others": {t["id"] for w in state["windows"] for t in w["tabs"]} - {tab_id},
            "restoring": False, "t": time.monotonic(),
        }
        self._arm_ghost(GHOST_S)

    def _arm_ghost(self, seconds):
        if self._ghost_timer is not None:
            GLib.source_remove(self._ghost_timer)
        self._ghost_timer = _schedule(seconds * 1000, self._drop_ghost)

    def _clear_ghost(self):
        if self._ghost_timer is not None:
            GLib.source_remove(self._ghost_timer)
            self._ghost_timer = None
        self._ghost = None

    def _drop_ghost(self):
        """Its time is up."""
        self._clear_ghost()
        self._rebuild()

    def _check_ghost(self, conn, state):
        """Forget the undo row once it would bring back another tab: one of the others has gone since (closed in the
        browser, by 'Reopen in container' ...), or, after the click, the restored tab is listed."""
        ghost = self._ghost
        if ghost is None or ghost["conn"] is not conn:
            return
        now = {t["id"] for w in state.get("windows", []) for t in w["tabs"]}
        if ghost["others"] - now or (ghost["restoring"] and now - ghost["others"] - {ghost["id"]}):
            self._clear_ghost()

    def _ghost_row(self, conn, group, tabs, colour, window):
        """The closed tab's row for its container `group` (whose listed `tabs` are given, in `window`): its title
        struck through and a ↶. None when it belongs elsewhere (another container, window or workspace), or the
        browser still lists the tab (it has not reported the close)."""
        ghost = self._ghost
        if ghost is None or ghost["conn"] is not conn or ghost["group"] != group:
            return None
        if window["id"] != ghost["window"] or window.get("workspaceId") != ghost["workspace"]:
            return None
        if any(t["id"] == ghost["id"] for t in tabs):
            return None
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.get_style_context().add_class("sp-tabbox")
        if self.cfg["icons"]:
            spacer = Gtk.Image()
            spacer.set_size_request(favicons.ICON_PX, favicons.ICON_PX)  # the titles stay in line
            box.pack_start(spacer, False, False, 0)
        box.pack_start(self._label(f'<s>{GLib.markup_escape_text(ghost["title"])}</s>', "sp-ghost", markup=True),
                       True, True, 0)
        if not ghost["restoring"]:  # (asked already: no second ↶ to click while the tab is on its way)
            undo = self._button("↶", "Reopen this tab", Gtk.Button)
            undo.get_style_context().add_class("sp-reopen")
            undo.connect("clicked", lambda _b: self._reopen_ghost())
            box.pack_end(undo, False, False, 0)
        row = self._row(box, "ghost", ghost["id"], group, conn, colour, self._reopen_ghost, draggable=False)
        row.get_style_context().add_class("ghost")
        return row

    def _reopen_ghost(self):
        ghost = self._ghost
        if ghost is None or ghost["restoring"] or time.monotonic() - ghost["t"] < GHOST_GUARD_S:
            return
        self._restore(ghost["conn"])
        ghost["restoring"] = True  # the row stays until the tab is listed again, so nothing below it moves under a
        self._arm_ghost(GHOST_RESTORING_S)  # second click, and goes anyway if it never comes
        self._rebuild()

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

    def _small_window(self, title, content, accept_label, answer, focus=None, beside=False, hint=None):
        """A small window of its own: `content` above Cancel and `accept_label`. It takes the keyboard, which the dock
        windows never do (a click must not steal it from the browser), and the panel stays open while it is up.
        answer(accepted) is called once, as it goes; Escape or closing it is Cancel. Returns (finish, accept button).
        `beside`: next to the panel instead of at the pointer, where it would cover what the panel shows.
        `hint`: a faint line of text along the bottom."""
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
        if hint:
            box.pack_start(self._label(hint, "sp-where", wrap=True), False, False, 0)
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
