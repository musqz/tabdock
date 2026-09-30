"""DockView smoke test. Window show/hide are recorded instead of executed, so nothing is ever
mapped on screen. Skipped when there is no X display."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

from tabdock import favicons, geometry  # noqa: E402
from tabdock.config import DEFAULTS  # noqa: E402

STATE = {
    "focusedWindowId": 2,
    "containers": [
        {"cookieStoreId": "firefox-container-1", "name": "Personal & Co", "colorCode": "#37adff", "icon": "fingerprint"},
        {"cookieStoreId": "firefox-container-2", "name": "Work", "colorCode": "#ff9f00", "icon": "briefcase"},
    ],
    "windows": [
        {
            "id": 2,
            "tabs": [
                {"id": 10, "title": "plain", "url": "https://a.example", "cookieStoreId": "firefox-default", "active": True},
                {"id": 11, "title": "mail", "cookieStoreId": "firefox-container-1", "active": False},
            ],
        }
    ],
}
INFO = {"browser": "Firefox", "version": "156.0", "browserPid": 1,
        "features": ["close_tab", "pin_tab", "containers", "reopen_in_container"]}
OLD_INFO = {"browser": "Firefox", "version": "156.0", "browserPid": 1}  # an extension from before the features list


def label_of(row):
    """The text label of a row. A tab row holds an icon and a label; a section row holds a label and a button."""
    child = row.get_child() if isinstance(row, Gtk.EventBox) else row
    if isinstance(child, Gtk.Box):
        child = next(c for c in child.get_children() if isinstance(c, Gtk.Label))
    return child


def new_tab_button_of(row):
    """A section row's "+" button, the other child of its box alongside the label."""
    child = row.get_child() if isinstance(row, Gtk.EventBox) else row
    return next(c for c in child.get_children() if isinstance(c, Gtk.Button))


def button(widget, kind, signal, x=0.0, y=0.0, which=1):
    event = Gdk.Event.new(kind)
    event.button = which
    event.x = event.x_root = x
    event.y = event.y_root = y
    widget.emit(signal, event)


def press(widget, x=0.0, y=0.0):
    button(widget, Gdk.EventType.BUTTON_PRESS, "button-press-event", x, y)


def release(widget, x=0.0, y=0.0, which=1):
    button(widget, Gdk.EventType.BUTTON_RELEASE, "button-release-event", x, y, which)


def click(widget):
    """A real click: press and release without moving, which is what a row treats as a click."""
    press(widget)
    release(widget)


def motion(widget, x, y):
    event = Gdk.Event.new(Gdk.EventType.MOTION_NOTIFY)
    event.x = event.x_root = x
    event.y = event.y_root = y
    widget.emit("motion-notify-event", event)


DRAG_STATE = {  # one window: p1 mail p2 p3 (the mail tab belongs to the Personal container)
    "focusedWindowId": 2,
    "containers": [
        {"cookieStoreId": "firefox-container-1", "name": "Personal"},
        {"cookieStoreId": "firefox-container-2", "name": "Work"},
    ],
    "windows": [
        {
            "id": 2,
            "tabs": [
                {"id": 1, "index": 0, "title": "p1", "cookieStoreId": "firefox-default", "active": True},
                {"id": 2, "index": 1, "title": "mail", "cookieStoreId": "firefox-container-1"},
                {"id": 3, "index": 2, "title": "p2", "cookieStoreId": "firefox-default"},
                {"id": 4, "index": 3, "title": "p3", "cookieStoreId": "firefox-default"},
            ],
        }
    ],
}

NO_EMPTY_STATE = {**DRAG_STATE, "containers": DRAG_STATE["containers"][:1]}  # no empty container for the arrows to stop on


@unittest.skipUnless(Gtk.init_check()[0], "no X display")
class DockViewTest(unittest.TestCase):
    def setUp(self):
        self.shown = set()
        for name, fn in (("show", self.shown.add), ("hide", self.shown.discard)):
            patcher = mock.patch.object(Gtk.Window, name, lambda w, fn=fn: fn(w))
            patcher.start()
            self.addCleanup(patcher.stop)
        # a context menu opens as shown (nothing is mapped or grabbed), and a right click needs no real window
        patcher = mock.patch.object(Gtk.Menu, "popup_at_pointer", lambda menu, _event: menu.show())
        patcher.start()
        self.addCleanup(patcher.stop)

    def make(self, **cfg):
        from tabdock.dock import DockView

        self.activated = []
        self.quit_calls = []
        self.commands = []
        self.command_conns = []
        self.chosen = []
        self.raised = []
        view = DockView(
            {**DEFAULTS, **cfg},
            lambda *a: self.activated.append(a),
            lambda: self.quit_calls.append(1),
            on_command=lambda conn, message: (self.commands.append(message), self.command_conns.append(conn)),
            on_choose=self.chosen.append,
            on_raise=self.raised.append,
        )
        self.addCleanup(view.win.destroy)
        self.addCleanup(view.strip.destroy)
        return view

    @property
    def restored(self):
        """The browsers asked to reopen the tab they closed last."""
        return [c for m, c in zip(self.commands, self.command_conns) if m["type"] == "restore_tab"]

    def row_texts(self, view):
        return [label_of(r).get_text() for r in view.list.get_children()]

    def bookmark_view(self, **cfg):
        view = self.make(bookmarks=True, **cfg)
        conn = object()
        view.show([(conn, {**INFO, "features": [*INFO["features"], "bookmarks"]}, STATE)])
        return view, conn

    def test_no_view_buttons_without_the_option_or_an_extension_that_can(self):
        view = self.make()
        view.show([(object(), {**INFO, "features": ["bookmarks"]}, STATE)])
        self.assertFalse(view.views.get_visible())
        view = self.make(bookmarks=True)
        view.show([(object(), INFO, STATE)])
        self.assertFalse(view.views.get_visible())

    def test_bookmarks_view_asks_for_them_lists_folders_and_opens_a_bookmark(self):
        view, conn = self.bookmark_view()
        self.assertTrue(view.views.get_visible())
        view._set_view("bookmarks")
        self.assertEqual(self.commands, [{"type": "get_bookmarks"}])
        self.assertIn("Loading", self.row_texts(view)[0])
        tree = [{"title": "Bar", "children": [{"title": "Arch wiki", "url": "https://wiki.archlinux.org"}]}]
        view.show_bookmarks(conn, {"type": "bookmarks", "granted": True, "tree": tree})
        self.assertEqual(self.row_texts(view), ["▸ Bar"])  # folders start closed
        click(view.list.get_children()[0])
        self.assertEqual(self.row_texts(view), ["▾ Bar", "Arch wiki"])
        click(view.list.get_children()[1])
        self.assertEqual(self.commands[-1]["type"], "open_url")
        self.assertEqual(self.commands[-1]["url"], "https://wiki.archlinux.org")
        self.assertEqual(self.raised, [conn])
        click(view.list.get_children()[0])  # closes the folder
        self.assertEqual(len(view.list.get_children()), 1)

    def history_view(self):
        view = self.make(history=True)
        conn = object()
        view.show([(conn, {**INFO, "features": [*INFO["features"], "history"]}, STATE)])
        return view, conn

    def test_history_lists_visits_by_day_and_opens_one(self):
        import time

        view, conn = self.history_view()
        self.assertTrue(view.views.get_visible())
        self.assertEqual([k for k, b in view._view_buttons if b.get_visible()], ["tabs", "history"])
        view._set_view("history")
        self.assertEqual(self.commands, [{"type": "search_history", "query": ""}])
        now = int(time.time() * 1000)
        items = [{"title": "Arch wiki", "url": "https://wiki.archlinux.org", "lastVisitTime": now}]
        view.show_history(conn, {"type": "history", "granted": True, "query": "", "items": items})
        texts = self.row_texts(view)
        self.assertEqual(texts[0], "Today")
        self.assertEqual(texts[1], "Arch wiki")
        click(view.list.get_children()[1])
        self.assertEqual(self.commands[-1]["url"], "https://wiki.archlinux.org")
        self.assertEqual(self.raised, [conn])

    def test_history_ignores_the_answer_to_an_older_search(self):
        view, conn = self.history_view()
        view._set_view("history")
        view._query = "arch"
        view.show_history(conn, {"type": "history", "granted": True, "query": "ar", "items": []})
        self.assertIn("Loading", self.row_texts(view)[0])

    def test_history_enter_never_opens_the_answer_to_an_older_search(self):
        view, conn = self.history_view()
        view._set_view("history")
        view._query = "a"
        item = {"title": "A", "url": "https://a.example", "lastVisitTime": 1}
        view.show_history(conn, {"type": "history", "granted": True, "query": "a", "items": [item]})
        self.assertEqual(view._first_url[1], "https://a.example")
        view._query = "ar"  # typed since: what is listed answers "a"
        view._first_url = None
        view._rebuild()
        self.assertIsNone(view._first_url)

    def test_history_granted_while_a_search_is_typed_asks_again(self):
        view, conn = self.history_view()
        view._set_view("history")
        view.show_history(conn, {"type": "history", "granted": False})
        view._query = "abc"
        self.commands.clear()
        view.show_history(conn, {"type": "history", "granted": True, "query": "", "items": []})
        self.assertEqual(self.commands, [{"type": "search_history", "query": "abc"}])

    def test_history_is_not_kept_while_the_option_is_off(self):
        view, conn = self.bookmark_view()  # history stays off
        view.show_history(conn, {"type": "history", "granted": True, "query": "", "items": []})
        self.assertEqual(view._lists, {})

    def test_bookmarks_without_the_permission_lead_to_the_options(self):
        view, conn = self.bookmark_view()
        view._set_view("bookmarks")
        view.show_bookmarks(conn, {"type": "bookmarks", "granted": False})
        click(view.list.get_children()[0])
        self.assertEqual(self.commands[-1], {"type": "open_options"})

    def test_starts_as_a_strip_with_the_panel_unmapped(self):
        view = self.make()
        self.assertFalse(view.autohide.expanded)
        self.assertEqual(self.shown, {view.strip})
        self.assertEqual(view.strip.get_size()[0], geometry.TRIGGER_PX)
        self.assertEqual(view.win.get_size()[0], view.cfg["width"])  # sized while unmapped
        self.assertIn("Waiting for a browser", self.row_texts(view)[0])

    def test_pinned_starts_with_the_panel_shown_at_configured_width(self):
        view = self.make(pinned=True, width=280)
        self.assertTrue(view.autohide.expanded)
        self.assertEqual(self.shown, {view.strip, view.win})
        self.assertEqual(view.win.get_size()[0], 280)
        self.assertTrue(view.pin_btn.get_active())

    def test_pin_state_is_readable_at_a_glance(self):
        view = self.make()
        self.assertEqual(view.pin_btn.get_label(), "pin")
        self.assertIn("Pin", view.pin_btn.get_tooltip_text())
        self.assertFalse(view.pin_btn.get_active())

        view.pin_btn.set_active(True)  # a click
        self.assertEqual(view.pin_btn.get_label(), "pinned")  # the word changes, not just a colour
        self.assertIn("Unpin", view.pin_btn.get_tooltip_text())  # the tooltip says what a click does now
        self.assertTrue(view.autohide.pinned and view.cfg["pinned"])

        view.set_pinned(False)  # e.g. from a config reload
        self.assertEqual(view.pin_btn.get_label(), "pin")
        self.assertFalse(view.pin_btn.get_active())

    def test_pin_from_config_starts_labelled_pinned(self):
        view = self.make(pinned=True)
        self.assertEqual(view.pin_btn.get_label(), "pinned")

    def test_pin_label_follows_a_config_reload(self):
        view = self.make()
        view.reconfigure({**DEFAULTS, "pinned": True})
        self.assertEqual(view.pin_btn.get_label(), "pinned")
        view.reconfigure({**DEFAULTS, "pinned": False})
        self.assertEqual(view.pin_btn.get_label(), "pin")

    def test_quit_button_quits(self):
        view = self.make()
        self.assertEqual(view.quit_btn.get_tooltip_text(), "Quit tabdock")
        view.quit_btn.clicked()
        self.assertEqual(self.quit_calls, [1])

    def test_header_button_order_is_pin_flip_quit(self):
        view = self.make()
        header = view.content.get_children()[0]

        def position(button):
            return header.child_get_property(button, "position")

        # packed with pack_end: the first one packed is rightmost, so quit is far right, then flip, then pin
        self.assertLess(position(view.quit_btn), position(view.flip_btn))
        self.assertLess(position(view.flip_btn), position(view.pin_btn))

    def test_show_renders_header_sections_and_tabs(self):
        view = self.make()
        view.show([(object(), INFO, STATE)])
        self.assertEqual(view.browser_name.get_text(), "Firefox")  # the active browser is always named
        self.assertIn("#ff7139", view._css_data)  # ...and its accent colours the strip
        texts = self.row_texts(view)
        self.assertEqual(len(texts), 5)  # 3 section headers + 2 tabs
        self.assertIn("plain", texts)
        self.assertIn("mail", texts)
        self.assertIn("Personal & Co", texts[2])  # markup was escaped, not parsed
        active = [r for r in view.list.get_children() if r.get_style_context().has_class("active")]
        self.assertEqual([label_of(r).get_text() for r in active], ["plain"])

    def test_accent_follows_the_browser(self):
        view = self.make()
        view.show([(object(), {**INFO, "browser": "Zen"}, STATE)])
        self.assertIn("#9d7cd8", view._css_data)
        view.clear()
        self.assertIn("#8f9bb3", view._css_data)
        self.assertEqual(view.browser_name.get_text(), "")

    def test_the_header_name_says_in_its_tooltip_that_a_right_click_sets_the_colour(self):
        view = self.make()
        view.show([(object(), INFO, STATE)])
        self.assertEqual(view.browser_name.get_tooltip_text(), "Firefox 156.0 (pid 1)\nRight-click to set its colour (shared by every browser of its kind)")
        view.show([(object(), INFO, STATE), (object(), {**INFO, "browser": "Zen"}, STATE)])
        self.assertIn("Choose one browser", view.browser_name.get_tooltip_text())  # a right-click does nothing here
        view.clear()
        self.assertIsNone(view.browser_name.get_tooltip_text())  # nothing listed: nothing to colour

    def test_theme_colours_the_panel_instead_of_the_browser_colour(self):
        view = self.make(theme={"firefox": "#1e3a8a"})
        self.assertIn("#8f9bb3", view._css_data)  # nothing listed yet: the colour of any other browser
        view.show([(object(), INFO, STATE)])
        self.assertIn("#1e3a8a", view._css_data)  # Firefox's colour from [theme], not its orange
        self.assertNotIn("#ff7139", view._css_data)
        pinned = next(line for line in view._css_data.splitlines() if line.startswith("button.sp-btn.sp-pin:checked"))
        self.assertIn("color: #ffffff", pinned)  # a dark accent: the text on it turns white
        name = next(line for line in view._css_data.splitlines() if line.startswith(".sp-browser"))
        self.assertIn("color: #dfe3ea", name)  # ...and the browser's name, on the dark header, the usual text colour
        self.assertTrue(all(r.get_style_context().has_class("acc-1e3a8a") for r in view.list.get_children()))
        # (as GTK prints the rules back, so they were parsed): white text on a browser band in that colour too
        self.assertIn(".acc-1e3a8a.sp-bhead .sp-bandlabel {\n  color: rgb(255,255,255);", view._per_browser.to_string())

    def test_right_click_on_the_header_name_sets_its_theme_colour(self):
        view = self.make()
        view.show([(object(), INFO, STATE)])
        self.right_click(view.browser_name_box)
        self.assertEqual(self.labels(view), ["Set colour…"])
        with mock.patch("tabdock.dock.config.set_theme_colour") as set_theme_colour:
            self.menu_items(view)["Set colour…"].activate()
            self.assertEqual(view._dialog.get_title(), "Firefox colour")
            rgba = Gdk.RGBA()
            rgba.parse("#4c9aff")
            view._dialog_chooser.set_rgba(rgba)
            view._dialog_ok.clicked()
        set_theme_colour.assert_called_once_with("firefox", "#4c9aff")
        self.assertEqual(view.cfg["theme"]["firefox"], "#4c9aff")
        self.assertIn("#4c9aff", view._css_data)  # applied at once, like a reload (see reconfigure)

    def test_a_colour_set_after_the_browser_went_away_is_still_saved(self):
        view = self.make()  # nothing listed: the chooser may outlive the browser it was opened for
        with mock.patch("tabdock.dock.config.set_theme_colour") as set_theme_colour:
            view._pick_colour("waterfox", "Waterfox")
            self.assertEqual(view._dialog.get_title(), "Waterfox colour")
            rgba = Gdk.RGBA()
            rgba.parse("#2ec4b6")
            view._dialog_chooser.set_rgba(rgba)
            view._dialog_ok.clicked()
        set_theme_colour.assert_called_once_with("waterfox", "#2ec4b6")
        self.assertEqual(view.cfg["theme"]["waterfox"], "#2ec4b6")

    def test_right_click_on_the_header_name_does_nothing_for_all_browsers(self):
        view = self.make()
        view.show([(object(), INFO, STATE), (object(), {**INFO, "browser": "Zen"}, STATE)])
        self.assertEqual(view.browser_name.get_text(), "All browsers")
        self.right_click(view.browser_name_box)
        self.assertIsNone(view._menu)

    def test_a_reload_applies_new_theme_colours(self):
        view = self.make()
        conn = object()
        view.show([(conn, INFO, STATE)])
        self.assertIn(".sp-browser { font-weight: bold; color: #ff7139; }", view._css_data)  # a light accent: in the name
        view.reconfigure({**DEFAULTS, "theme": {"accent": "#4c9aff"}})
        view.show([(conn, INFO, STATE)])  # the same tabs: rebuilt all the same, in the new colour
        self.assertIn("#4c9aff", view._css_data)
        self.assertTrue(all(r.get_style_context().has_class("acc-4c9aff") for r in view.list.get_children()))
        view.clear()
        self.assertIn("#4c9aff", view._css_data)  # with nothing listed, the strip wears it too
        view.reconfigure({**DEFAULTS, "theme": {"other": "#123456"}})  # a reload while nothing is listed
        self.assertIn("#123456", view._css_data)

    def test_click_activates_tab_in_its_window(self):
        view = self.make()
        conn = object()
        view.show([(conn, INFO, STATE)])
        rows = [r for r in view.list.get_children() if isinstance(r, Gtk.EventBox) and label_of(r).get_text() == "mail"]
        click(rows[0])
        self.assertEqual(self.activated, [(conn, 11, 2)])

    def test_section_folds_and_unfolds(self):
        view = self.make()
        view.show([(object(), INFO, STATE)])
        click(view.list.get_children()[0])  # "No container" has a tab, so it is clickable
        self.assertEqual(len(view.list.get_children()), 4)
        click(view.list.get_children()[0])
        self.assertEqual(len(view.list.get_children()), 5)

    def test_new_tab_button_sends_new_tab_for_its_own_container_and_window(self):
        view = self.make()
        conn = object()
        view.show([(conn, INFO, STATE)])
        row = next(r for r in view.list.get_children() if "Personal & Co" in label_of(r).get_text())
        new_tab_button_of(row).clicked()
        self.assertEqual(self.commands, [{"type": "new_tab", "cookieStoreId": "firefox-container-1", "windowId": 2}])
        self.assertEqual(self.command_conns, [conn])
        self.assertEqual(self.raised, [conn])  # the browser comes forward: its address bar is ready for typing

    def test_new_tab_button_is_absent_for_a_container_the_browser_no_longer_lists(self):
        # A deleted container's leftover tabs still get a section (model.group_tabs), but
        # tabs.create({cookieStoreId}) for a store the browser no longer has would just fail.
        state = {**STATE, "windows": [{
            "id": 2,
            "tabs": [{"id": 20, "title": "orphan", "cookieStoreId": "firefox-container-9", "active": False}],
        }]}
        view = self.make()
        view.show([(object(), INFO, state)])
        row = next(r for r in view.list.get_children() if "firefox-container-9" in label_of(r).get_text())
        buttons = [c for c in row.get_child().get_children() if isinstance(c, Gtk.Button)]
        self.assertEqual(buttons, [])

    def test_new_tab_button_names_its_container_in_the_tooltip(self):
        view = self.make()
        view.show([(object(), INFO, STATE)])
        row = next(r for r in view.list.get_children() if "Personal & Co" in label_of(r).get_text())
        self.assertEqual(new_tab_button_of(row).get_tooltip_text(), "New tab in Personal & Co")

    def test_new_tab_button_for_no_container_does_not_name_it(self):
        view = self.make()
        view.show([(object(), INFO, STATE)])
        row = view.list.get_children()[0]  # "No container" stays first
        self.assertEqual(new_tab_button_of(row).get_tooltip_text(), "New tab")

    def test_new_tab_button_does_not_fold_the_section_or_start_a_drag(self):
        # .clicked() only proves the button's own wiring never touches fold/drag state; whether a
        # real click actually lands on the nested Button before the row's EventBox sees it is a
        # GTK3 property (the deepest widget under the pointer wins) not exercised by this harness,
        # which never maps a real window (see the drag tests' note above on tests/e2e_x11.py).
        view = self.make()
        view.show([(object(), INFO, STATE)])
        row = view.list.get_children()[0]  # "No container" has a tab, so a plain click would fold it
        new_tab_button_of(row).clicked()
        self.assertEqual(len(view.list.get_children()), 5)  # still unfolded: the section was not toggled
        self.assertIsNone(view._press)

    def test_identical_state_does_not_rebuild_or_restyle(self):
        view = self.make()
        conn = object()
        view.show([(conn, INFO, STATE)])
        rows = view.list.get_children()
        with mock.patch.object(view._css, "load_from_data") as reload_css:
            view.show([(conn, INFO, {**STATE})])  # equal content, new dict, as a fresh JSON message would be
        self.assertEqual(view.list.get_children(), rows)
        reload_css.assert_not_called()  # reloading the provider restyles the whole panel

    def test_folding_is_per_browser_process(self):
        view = self.make()
        view.show([(object(), {**INFO, "browserPid": 1}, STATE)])
        click(view.list.get_children()[0])  # fold "No container" in the first profile
        self.assertEqual(len(view.list.get_children()), 4)
        view.show([(object(), {**INFO, "browserPid": 2}, STATE)])  # another Firefox profile: not folded
        self.assertEqual(len(view.list.get_children()), 5)

    def test_expanding_shows_the_panel_and_collapsing_hides_it(self):
        view = self.make()
        view.autohide.expanded = True  # what Autohide sets right before calling apply
        view._apply(True)
        self.assertIn(view.win, self.shown)
        view.autohide.expanded = False
        view._apply(False)
        self.assertNotIn(view.win, self.shown)
        self.assertIn(view.strip, self.shown)

    def test_side_change_moves_both_windows(self):
        view = self.make()
        view.set_side("right")
        mon = view._monitor_rect()  # with monitor = "outer" the right side may be another monitor
        self.assertEqual(view.strip.get_position(), geometry.dock_rect(mon, "right", view.cfg["width"], False)[:2])
        self.assertEqual(view.win.get_position(), geometry.dock_rect(mon, "right", view.cfg["width"], True)[:2])

    def test_hide_and_unhide(self):
        view = self.make(pinned=True)
        view.set_hidden(True)
        self.assertEqual(self.shown, set())
        view.set_hidden(False)
        self.assertEqual(self.shown, {view.strip, view.win})  # pinned: panel comes back too

    # -- reordering: click vs drag, and what a drop asks the browser to do ------------------------
    # Mapping pixels to a drop target needs real window allocations (tests/e2e_x11.py drags with a
    # real pointer); here a stand-in picks the target so everything around it can be checked.

    def row(self, view, kind, ident):
        return next(b for b, m in view._meta.items() if m["kind"] == kind and m["id"] == ident)

    def drag(self, view, moved, target, after, distance=40):
        view._point_at = lambda p, box, ev: p.update(target=target, after=after)
        press(moved, 5, 5)
        motion(moved, 5, 5 + distance)
        release(moved, 5, 5 + distance)

    def test_a_click_activates_but_a_drag_does_not(self):
        view = self.make()
        conn = object()
        view.show([(conn, INFO, DRAG_STATE)])
        tab = self.row(view, "tab", 3)
        press(tab, 5, 5)
        motion(tab, 8, 7)  # under the threshold: still a click
        release(tab, 8, 7)
        self.assertEqual(self.activated, [(conn, 3, 2)])
        self.drag(view, tab, self.row(view, "tab", 4), after=False)
        self.assertEqual(len(self.activated), 1)  # the drag did not activate anything

    def test_dragging_a_tab_sends_the_final_index_within_its_own_container(self):
        view = self.make()
        view.show([(object(), INFO, DRAG_STATE)])
        self.drag(view, self.row(view, "tab", 1), self.row(view, "tab", 4), after=False)  # p1 before p3
        self.drag(view, self.row(view, "tab", 4), self.row(view, "tab", 1), after=False)  # p3 before p1
        self.drag(view, self.row(view, "tab", 1), self.row(view, "tab", 4), after=True)  # p1 after the last p
        self.assertEqual(
            self.commands,
            [
                {"type": "move_tab", "tabId": 1, "index": 2},  # strip becomes mail p2 p1 p3
                {"type": "move_tab", "tabId": 4, "index": 0},
                {"type": "move_tab", "tabId": 1, "index": 3},  # after the last p: mail p2 p3 p1
            ],
        )

    def test_tabs_can_only_be_dropped_among_their_own_containers_tabs(self):
        view = self.make()
        view.show([(object(), INFO, DRAG_STATE)])
        plain = self.row(view, "tab", 1)
        candidates = [view._meta[b]["id"] for b in view._drop_candidates(plain)]
        self.assertEqual(candidates, [1, 3, 4])  # not the Personal container's mail tab (2)

    def test_dropping_a_tab_where_it_already_is_sends_nothing(self):
        view = self.make()
        view.show([(object(), INFO, DRAG_STATE)])
        self.drag(view, self.row(view, "tab", 3), self.row(view, "tab", 3), after=False)  # onto itself
        self.drag(view, self.row(view, "tab", 3), self.row(view, "tab", 4), after=False)  # before its neighbour
        self.drag(view, self.row(view, "tab", 4), self.row(view, "tab", 4), after=True)  # already last
        self.assertEqual(self.commands, [])

    def test_dragging_a_section_sends_the_new_order_and_shows_it_at_once(self):
        view = self.make()
        view.show([(object(), INFO, DRAG_STATE)])
        def sections():  # the labels start with the container's colour bar and icon, so match inside
            return [("Personal" if "Personal" in t else "Work") for t in self.row_texts(view) if "Personal" in t or "Work" in t]

        self.assertEqual(sections(), ["Personal", "Work"])
        self.drag(view, self.row(view, "section", "firefox-container-2"), self.row(view, "section", "firefox-container-1"),
                  after=False)  # Work above Personal
        self.assertEqual(self.commands, [{"type": "set_container_order",
                                          "order": ["firefox-container-2", "firefox-container-1"]}])
        self.assertEqual(sections(), ["Work", "Personal"])  # redrawn without waiting for the browser
        self.assertEqual(view.sources[0][2]["containerOrder"], ["firefox-container-2", "firefox-container-1"])

    def test_no_container_stays_first_and_cannot_be_dragged(self):
        view = self.make()
        view.show([(object(), INFO, DRAG_STATE)])
        header = self.row(view, "section", "firefox-default")
        self.assertFalse(view._meta[header]["draggable"])
        press(header, 5, 5)
        motion(header, 5, 60)
        self.assertFalse(view._press["dragging"])  # it never turns into a drag
        release(header, 5, 60)
        candidates = [view._meta[b]["id"] for b in view._drop_candidates(self.row(view, "section", "firefox-container-1"))]
        self.assertNotIn("firefox-default", candidates)  # nothing can be dropped above it either
        self.assertEqual(self.commands, [])

    def test_the_panel_stays_open_while_dragging_and_updates_wait_for_the_drop(self):
        view = self.make()
        conn = object()
        view.show([(conn, INFO, DRAG_STATE)])
        tab = self.row(view, "tab", 3)
        press(tab, 5, 5)
        motion(tab, 5, 60)
        self.assertTrue(view.autohide.held)  # the pointer may leave the panel: it must not close under it
        newer = {**DRAG_STATE, "windows": [{"id": 2, "tabs": DRAG_STATE["windows"][0]["tabs"][:2]}]}
        view.show([(conn, INFO, newer)])  # the browser reports a change mid-drag...
        self.assertIs(self.row(view, "tab", 3), tab)  # ...the rows under the pointer are not rebuilt
        release(tab, 5, 60)
        self.assertFalse(view.autohide.held)
        self.assertEqual({m["id"] for m in view._meta.values() if m["kind"] == "tab"}, {1, 2})  # applied now

    def test_a_stale_drag_lets_go_of_the_hold_when_updates_resume(self):
        view = self.make()
        conn = object()
        view.show([(conn, INFO, DRAG_STATE)])
        tab = self.row(view, "tab", 1)
        press(tab, 5, 5)
        motion(tab, 5, 60)  # a drag is under way and holds the panel open...
        self.assertTrue(view.autohide.held)
        view._press["t"] -= 60  # ...but its release never came
        view.show([(conn, INFO, DRAG_STATE)])
        self.assertIsNone(view._press)
        self.assertFalse(view.autohide.held)  # the panel is not stuck open

    def test_releasing_another_button_does_not_lose_the_press_in_progress(self):
        view = self.make()
        view.show([(object(), INFO, DRAG_STATE)])
        moved, target = self.row(view, "tab", 1), self.row(view, "tab", 4)
        view._point_at = lambda p, box, ev: p.update(target=target, after=False)
        press(moved, 5, 5)
        motion(moved, 5, 60)
        release(moved, 5, 60, which=3)  # a right-click release mid-drag
        self.assertIsNotNone(view._press)
        self.assertTrue(view._press["dragging"])
        self.assertTrue(view.autohide.held)
        release(moved, 5, 60)  # the real end of the drag
        self.assertEqual(self.commands, [{"type": "move_tab", "tabId": 1, "index": 2}])
        self.assertFalse(view.autohide.held)

    def test_only_real_containers_can_be_dragged(self):
        state = {**DRAG_STATE, "windows": [{"id": 2, "tabs": DRAG_STATE["windows"][0]["tabs"]
                                            + [{"id": 9, "index": 4, "title": "x", "cookieStoreId": "firefox-container-9"}]}]}
        view = self.make()
        view.show([(object(), INFO, state)])
        draggable = {m["id"]: m["draggable"] for m in view._meta.values() if m["kind"] == "section"}
        self.assertEqual(draggable, {"firefox-default": False, "firefox-container-1": True,
                                     "firefox-container-2": True, "firefox-container-9": False})

    def test_a_drop_after_the_state_changed_under_the_drag_does_nothing(self):
        view = self.make()
        view.show([(object(), INFO, DRAG_STATE)])
        moved, target = self.row(view, "tab", 1), self.row(view, "tab", 4)
        view._point_at = lambda p, box, ev: p.update(target=target, after=False)
        press(moved, 5, 5)
        motion(moved, 5, 60)
        view.sources = []  # e.g. the browser went away meanwhile
        release(moved, 5, 60)  # must not raise inside the signal handler
        self.assertEqual(self.commands, [])
        self.assertFalse(view.autohide.held)

    def test_tabs_are_not_dragged_across_the_pinned_boundary(self):
        tabs = [
            {"id": 1, "index": 0, "title": "pinned", "cookieStoreId": "firefox-default", "pinned": True},
            {"id": 2, "index": 1, "title": "n1", "cookieStoreId": "firefox-default"},
            {"id": 3, "index": 2, "title": "n2", "cookieStoreId": "firefox-default"},
        ]
        view = self.make()
        view.show([(object(), INFO, {**DRAG_STATE, "windows": [{"id": 2, "tabs": tabs}]})])
        ids = lambda tab: [view._meta[b]["id"] for b in view._drop_candidates(self.row(view, "tab", tab))]  # noqa: E731
        self.assertEqual(ids(2), [2, 3])  # a normal tab cannot be dropped among the pinned ones
        self.assertEqual(ids(1), [1])  # nor a pinned one among the normal ones
        self.drag(view, self.row(view, "tab", 3), self.row(view, "tab", 2), after=False)
        self.assertEqual(self.commands, [{"type": "move_tab", "tabId": 3, "index": 1}])  # never index 0

    def test_a_stale_press_cannot_block_updates_forever(self):
        view = self.make()
        conn = object()
        view.show([(conn, INFO, DRAG_STATE)])
        press(self.row(view, "tab", 1), 5, 5)  # the release never arrives
        view._press["t"] -= 60
        view.show([(conn, INFO, {**DRAG_STATE, "windows": [{"id": 2, "tabs": []}]})])
        self.assertEqual([m for m in view._meta.values() if m["kind"] == "tab"], [])

    def test_layout_dump_hook_reports_every_row(self):
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"TABDOCK_LAYOUT_DUMP": tmp + "/rows.json"}):
            view = self.make()  # the hook is read once, when the panel starts
            view.show([(object(), INFO, DRAG_STATE)])
            view._dump_layout()
            with open(tmp + "/rows.json") as f:
                rows = json.load(f)
        self.assertEqual([(r["kind"], r["id"]) for r in rows if r["kind"] == "section"],
                         [("section", "firefox-default"), ("section", "firefox-container-1"), ("section", "firefox-container-2")])
        self.assertEqual({r["id"] for r in rows if r["kind"] == "tab"}, {1, 2, 3, 4})
        self.assertTrue(all({"x", "y", "w", "h", "group"} <= r.keys() for r in rows))

    # -- site icons before the tab titles ----------------------------------------------------------------
    # Off unless asked for: the panel downloads them itself. The downloads are stubbed, so nothing here
    # touches the network; decoding is real (a short-lived process per icon).

    ICON_URL = "https://example.com/favicon.png"

    def icon_state(self, *urls):
        tabs = [{"id": i + 1, "index": i, "title": f"t{i + 1}", "cookieStoreId": "firefox-default", "favIconUrl": url}
                for i, url in enumerate(urls)]
        return {"focusedWindowId": 2, "containers": [], "windows": [{"id": 2, "tabs": tabs}]}

    def tab_image(self, view, tab_id):
        box = self.row(view, "tab", tab_id).get_child()
        return next(c for c in box.get_children() if isinstance(c, Gtk.Image))

    def tab_widgets(self, view, tab_id):
        """What a tab row shows, left to right, apart from the ✕ every row ends with (see its own tests)."""
        return [type(c) for c in self.row(view, "tab", tab_id).get_child().get_children()
                if not c.get_style_context().has_class("sp-close")]

    def has_icon(self, view, *tab_ids):
        return all(self.tab_image(view, i).get_pixbuf() is not None for i in tab_ids)

    def pump(self, condition, what, timeout=10.0):
        """Run the main loop until `condition()`: icons arrive from worker threads through it."""
        import time
        import warnings

        from gi.repository import GLib

        deadline = time.monotonic() + timeout
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)  # PyGObject's own asyncio glue, not ours
            while not condition():
                if time.monotonic() > deadline:
                    self.fail(f"timed out waiting for: {what}")
                while GLib.MainContext.default().iteration(False):
                    pass
                time.sleep(0.01)

    def data_icon(self, side=2):
        import base64

        from test_favicons import png

        return "data:image/png;base64," + base64.b64encode(png(side, side)).decode()

    def test_icons_are_off_until_asked_for_and_then_nothing_is_downloaded(self):
        from test_favicons import png

        view = self.make()
        self.assertFalse(view.cfg["icons"] or view.icons_btn.get_active())
        with mock.patch("tabdock.favicons.download", return_value=png()) as download:
            view.show([(object(), INFO, self.icon_state(self.ICON_URL))])
            self.assertEqual(self.tab_widgets(view, 1), [Gtk.Label])
            self.assertIsNone(view._fetcher)  # not even the worker threads
            download.assert_not_called()

    def test_a_tab_row_is_an_icon_and_a_title(self):
        view = self.make(icons=True)
        view.show([(object(), INFO, self.icon_state(None))])
        self.assertEqual(self.tab_widgets(view, 1), [Gtk.Image, Gtk.Label])  # the icon comes first
        image = self.tab_image(view, 1)
        self.assertEqual(image.get_size_request(), (16, 16))  # its room is kept, so nothing shifts when it arrives
        self.assertIsNone(image.get_pixbuf())

    def test_a_tab_with_an_unread_count_gets_a_badge(self):
        view = self.make()
        state = {**STATE, "windows": [{"id": 2, "tabs": [
            {"id": 10, "title": "(3) plain", "cookieStoreId": "firefox-default", "active": True},
        ]}]}
        view.show([(object(), INFO, state)])
        self.assertEqual(self.tab_widgets(view, 10), [Gtk.Label, Gtk.Label])
        row = self.row(view, "tab", 10).get_child()
        self.assertEqual(label_of(row).get_text(), "plain")
        self.assertEqual(row.get_children()[-2].get_text(), "3")  # last before the ✕

    def test_an_icon_and_a_badge_together_keep_the_title_first_among_labels(self):
        view = self.make(icons=True)
        state = {**STATE, "windows": [{"id": 2, "tabs": [
            {"id": 10, "title": "(3) plain", "cookieStoreId": "firefox-default", "active": True},
        ]}]}
        view.show([(object(), INFO, state)])
        self.assertEqual(self.tab_widgets(view, 10), [Gtk.Image, Gtk.Label, Gtk.Label])
        row = self.row(view, "tab", 10).get_child()
        self.assertEqual(label_of(row).get_text(), "plain")
        self.assertEqual(row.get_children()[-2].get_text(), "3")  # last before the ✕

    def test_a_tab_without_an_unread_count_has_no_badge(self):
        view = self.make()
        view.show([(object(), INFO, STATE)])
        self.assertEqual(self.tab_widgets(view, 10), [Gtk.Label])

    def test_badges_can_be_turned_off(self):
        view = self.make(badges=False)
        state = {**STATE, "windows": [{"id": 2, "tabs": [
            {"id": 10, "title": "(3) plain", "cookieStoreId": "firefox-default", "active": True},
        ]}]}
        view.show([(object(), INFO, state)])
        self.assertEqual(self.tab_widgets(view, 10), [Gtk.Label])

    def test_an_icon_that_is_in_the_page_as_data_shows_without_any_download(self):
        view = self.make(icons=True)
        with mock.patch("tabdock.favicons.download", side_effect=AssertionError("no network for a data: icon")):
            view.show([(object(), INFO, self.icon_state(self.data_icon(24)))])
            self.pump(lambda: self.has_icon(view, 1), "the icon")
        self.assertEqual(self.tab_image(view, 1).get_pixbuf().get_width(), 16)

    def test_a_downloaded_icon_arrives_in_its_row_once_for_all_tabs_of_a_site(self):
        from test_favicons import png

        view = self.make(icons=True)
        state = self.icon_state(self.ICON_URL, self.ICON_URL, self.ICON_URL)
        with mock.patch("tabdock.favicons.download", return_value=png()) as download:
            view.show([(object(), INFO, state)])
            self.pump(lambda: self.has_icon(view, 1, 2, 3), "three icons")
            view.show([(object(), INFO, {**state})])  # a redraw
            self.assertTrue(self.has_icon(view, 1, 2, 3))  # at once: it is remembered
        self.assertEqual(download.call_count, 1)  # one request for the site

    def test_rows_redrawn_while_an_icon_is_on_its_way_still_get_it(self):
        import threading

        from test_favicons import png

        view = self.make(icons=True)
        release, calls = threading.Event(), []

        def slow(url):
            calls.append(url)
            release.wait(10)
            return png()

        conn = object()
        with mock.patch("tabdock.favicons.download", side_effect=slow):
            view.show([(conn, INFO, self.icon_state(self.ICON_URL))])
            self.pump(lambda: calls, "the download to start")
            view.show([(conn, INFO, self.icon_state(self.ICON_URL, self.ICON_URL))])  # the state changed: new rows
            release.set()
            self.pump(lambda: self.has_icon(view, 1, 2), "the icon in the new rows")
        self.assertEqual(len(calls), 1)

    def test_a_download_that_did_not_work_is_tried_again_later_but_not_on_every_redraw(self):
        view = self.make(icons=True)
        with mock.patch("tabdock.favicons.download", return_value=None) as download:  # no network, say
            view.show([(object(), INFO, self.icon_state(self.ICON_URL))])
            self.pump(lambda: view._failed and not view._pending, "the failure")
            for _ in range(3):
                view._rebuild()
            self.assertEqual(download.call_count, 1)
            self.assertIsNone(self.tab_image(view, 1).get_pixbuf())
            for key in view._failed:
                view._failed[key] -= 1000  # long enough ago
            view._rebuild()
            self.pump(lambda: download.call_count == 2 and not view._pending, "a second try")

    def test_something_that_can_never_be_an_icon_is_not_asked_for_again(self):
        view = self.make(icons=True)
        for answer in (favicons.REFUSED, b"<svg onload='x'/>", b"<html>sign in</html>"):  # 404, svg, a page
            with self.subTest(answer=answer), mock.patch("tabdock.favicons.download", return_value=answer) as download:
                view._refused.clear()
                view.show([(object(), INFO, self.icon_state(self.ICON_URL))])
                self.pump(lambda: view._refused and not view._pending, "the refusal")
                for key in list(view._failed):
                    view._failed[key] -= 1000
                view._rebuild()
                view._rebuild()
                self.assertEqual(download.call_count, 1)  # not now, and not five minutes from now
                self.assertFalse(view._failed)
                self.assertIsNone(self.tab_image(view, 1).get_pixbuf())

    def test_what_a_page_names_as_its_icon_is_never_fetched_unless_it_is_https_or_data(self):
        view = self.make(icons=True)
        urls = ("http://example.com/favicon.ico", "chrome://branding/content/icon32.png", "about:newtab",
                "file:///etc/passwd", "resource://gre/x.png", "", None)
        with mock.patch("tabdock.favicons.download", side_effect=AssertionError("fetched")) as download:
            view.show([(object(), INFO, self.icon_state(*urls))])
            self.pump(lambda: len(view._refused) == 5 and not view._pending, "the refusals")  # '' and None: no request at all
        download.assert_not_called()

    def test_hovering_an_empty_icon_slot_says_why_there_is_no_icon(self):
        view = self.make(icons=True)
        why = lambda tab_id: self.tab_image(view, tab_id).get_tooltip_text()  # noqa: E731
        urls = (self.ICON_URL, "chrome://branding/content/icon32.png", None)
        with mock.patch("tabdock.favicons.download", return_value=favicons.Refused("the site answered 404")) as download:
            view.show([(object(), INFO, self.icon_state(*urls))])
            self.pump(lambda: not view._pending and len(view._refused) == 2, "the answers")
            self.assertEqual(why(1), "No icon: the site answered 404")
            self.assertIn("not an https", why(2))  # never fetched at all, and it says so
            self.assertIn("reported no icon address", why(3))
            download.assert_called_once()
            view._rebuild()  # a redraw keeps the explanations
            self.assertEqual(why(1), "No icon: the site answered 404")

    def test_an_icon_that_could_not_be_downloaded_says_it_will_be_tried_again(self):
        view = self.make(icons=True)
        with mock.patch("tabdock.favicons.download", return_value=None):
            view.show([(object(), INFO, self.icon_state(self.ICON_URL))])
            self.pump(lambda: view._failed and not view._pending, "the failure")
        self.assertIn("could not be downloaded", self.tab_image(view, 1).get_tooltip_text())
        self.assertIn("tried again later", self.tab_image(view, 1).get_tooltip_text())

    def test_a_tab_with_an_icon_has_no_explanation(self):
        view = self.make(icons=True)
        view.show([(object(), INFO, self.icon_state(self.data_icon()))])
        self.pump(lambda: self.has_icon(view, 1), "the icon")
        self.assertIsNone(self.tab_image(view, 1).get_tooltip_text())

    def test_the_icons_button_switches_icons_on_and_off(self):
        from test_favicons import png

        view = self.make()
        with mock.patch("tabdock.favicons.download", return_value=png()) as download:
            view.show([(object(), INFO, self.icon_state(self.ICON_URL))])
            download.assert_not_called()
            view.icons_btn.set_active(True)  # a click
            self.assertTrue(view.cfg["icons"])
            self.pump(lambda: self.has_icon(view, 1), "the icon after switching on")
            view.icons_btn.set_active(False)
            self.assertEqual(self.tab_widgets(view, 1), [Gtk.Label])

    def test_switching_icons_off_drops_the_downloads_that_have_not_started(self):
        import threading

        from test_favicons import png

        view = self.make(icons=True)
        release, started = threading.Event(), []

        def slow(url):
            started.append(url)
            release.wait(10)
            return png()

        urls = [f"https://site{i}.test/favicon.png" for i in range(7)]
        with mock.patch("tabdock.favicons.download", side_effect=slow):
            view.show([(object(), INFO, self.icon_state(*urls))])
            self.pump(lambda: len(started) == 4, "the four workers to be busy")  # the other three are queued
            view.icons_btn.set_active(False)
            release.set()
            self.pump(lambda: not view._pending, "the running downloads to finish")
        self.assertEqual(len(started), 4)  # the three that had not started never were

    def test_a_config_reload_applies_icons(self):
        view = self.make()
        self.assertFalse(view.icons_btn.get_active())
        view.reconfigure({**DEFAULTS, "icons": True})
        self.assertTrue(view.icons_btn.get_active() and view.cfg["icons"])
        view.reconfigure({**DEFAULTS, "icons": False})
        self.assertFalse(view.icons_btn.get_active() or view.cfg["icons"])

    def test_the_icons_button_says_what_a_click_does(self):
        view = self.make(icons=True)
        self.assertIn("Click to hide", view.icons_btn.get_tooltip_text())
        view.icons_btn.set_active(False)
        self.assertIn("downloads", view.icons_btn.get_tooltip_text())
        self.assertIn("proxy", view.icons_btn.get_tooltip_text())  # what switching on means is said before it happens

    def test_the_least_recently_used_icon_goes_when_too_many_are_kept(self):
        view = self.make(icons=True)
        a, b, c = (self.data_icon(side) for side in (2, 3, 4))
        conn = object()
        with mock.patch("tabdock.dock.ICONS_KEPT", 2):
            view.show([(conn, INFO, self.icon_state(a, b))])
            self.pump(lambda: len(view._icons) == 2 and not view._pending, "a and b")
            view.show([(conn, INFO, self.icon_state(a))])  # a is used again: b is now the one not used for longest
            view.show([(conn, INFO, self.icon_state(a, c))])
            self.pump(lambda: len(view._icons) == 2 and not view._pending and view._icon_key(c) in view._icons, "c")
        self.assertIn(view._icon_key(a), view._icons)
        self.assertNotIn(view._icon_key(b), view._icons)

    def test_a_huge_icon_url_is_remembered_by_its_hash_not_kept_whole(self):
        view = self.make(icons=True)
        url = "data:image/png;base64," + "A" * 100_000  # not an icon, but a long URL all the same
        key = view._icon_key(url)
        self.assertTrue(key.startswith("sha256:") and len(key) < 100)
        self.assertEqual(view._icon_key(self.ICON_URL), self.ICON_URL)  # a normal one is its own key
        view.show([(object(), INFO, self.icon_state(url))])
        self.pump(lambda: key in view._refused, "the refusal")
        self.assertNotIn(url, view._refused)

    def test_a_page_that_keeps_changing_its_icon_cannot_queue_downloads_without_end(self):
        import threading

        view = self.make(icons=True)
        release, started = threading.Event(), []

        def slow(url):
            started.append(url)
            release.wait(10)
            return None

        urls = [f"https://site{i}.test/favicon.png" for i in range(10)]
        with mock.patch("tabdock.dock.ICONS_PENDING_MAX", 3), mock.patch("tabdock.favicons.download", side_effect=slow):
            view.show([(object(), INFO, self.icon_state(*urls))])
            self.pump(lambda: len(started) == 3, "three downloads")
            self.assertEqual(len(view._pending), 3)  # the rest is not asked for at all
            release.set()
            self.pump(lambda: not view._pending, "them to finish")
        self.assertEqual(len(started), 3)

    def test_a_redraw_asked_for_during_a_drag_waits_for_the_drop(self):
        view = self.make()
        view.show([(object(), INFO, self.icon_state(None, None))])
        tab = self.row(view, "tab", 1)
        press(tab, 5, 5)
        view.icons_btn.set_active(True)  # e.g. a config reload in the middle of a drag
        self.assertIs(self.row(view, "tab", 1), tab)  # the row under the pointer is still there
        self.assertTrue(view._redraw)
        release(tab, 5, 5)
        self.assertFalse(view._redraw)
        self.assertEqual(self.tab_widgets(view, 1), [Gtk.Image, Gtk.Label])  # done after the release

    def test_nothing_about_the_tabs_is_written_to_disk(self):
        import tempfile

        from test_favicons import png

        view = self.make(icons=True)
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(
            os.environ, {"HOME": home, "XDG_CACHE_HOME": home + "/cache", "XDG_DATA_HOME": home + "/data"}
        ), mock.patch("tabdock.favicons.download", return_value=png()):
            view.show([(object(), INFO, self.icon_state(self.ICON_URL))])
            self.pump(lambda: self.has_icon(view, 1), "the icon")
            self.assertEqual(os.listdir(home), [])

    # -- several browsers at once: chips, one header per browser, and nothing crossing between them ----

    ZEN = {"browser": "Zen", "version": "1.0", "browserPid": 2}

    def two(self, view, mode="all", focus=INFO):
        ff, zen = object(), object()
        choices = [(ff, "Firefox", "#ff7139"), (zen, "Zen", "#9d7cd8")]
        view.show([(ff, INFO, DRAG_STATE), (zen, self.ZEN, DRAG_STATE)], mode, choices, focus)
        return ff, zen

    def row_of(self, view, conn, kind, ident):
        return next(b for b, m in view._meta.items() if m["conn"] is conn and m["kind"] == kind and m["id"] == ident)

    def chips(self, view):
        return {b.get_label(): b for _key, b in view._chip_buttons}

    def test_chips_appear_only_when_there_is_a_choice(self):
        view = self.make()
        view.show([(object(), INFO, STATE)])
        self.assertFalse(view.chips.get_visible())  # one browser: nothing to choose
        self.two(view)
        self.assertTrue(view.chips.get_visible())
        self.assertEqual([b.get_label() for _key, b in view._chip_buttons], ["auto", "Firefox", "Zen", "all"])
        view.clear()
        self.assertFalse(view.chips.get_visible())

    def test_the_selected_chip_is_marked_and_a_click_chooses(self):
        view = self.make()
        ff, zen = self.two(view, mode="all")
        selected = lambda: [label for label, b in self.chips(view).items() if b.get_style_context().has_class("selected")]  # noqa: E731
        self.assertEqual(selected(), ["all"])
        view.show([(ff, INFO, DRAG_STATE)], zen, [(ff, "Firefox", "#ff7139"), (zen, "Zen", "#9d7cd8")], INFO)
        self.assertEqual(selected(), ["Zen"])  # a chosen browser is highlighted, whichever one is in use
        self.chips(view)["Zen"].clicked()
        self.chips(view)["auto"].clicked()
        self.chips(view)["all"].clicked()
        self.assertEqual(self.chosen, [zen, "auto", "all"])

    def test_chips_are_kept_while_the_browsers_stay_the_same(self):
        view = self.make()
        ff, zen = self.two(view)
        buttons = [b for _key, b in view._chip_buttons]
        choices = [(ff, "Firefox", "#ff7139"), (zen, "Zen", "#9d7cd8")]
        both = [(ff, INFO, DRAG_STATE), (zen, self.ZEN, DRAG_STATE)]
        view.show(both, "auto", choices, INFO)  # a chip was clicked, or a tab changed: same browsers, same buttons
        self.assertEqual([b for _key, b in view._chip_buttons], buttons)
        libre = object()  # a third browser opens: a new chip
        view.show(both, "auto", choices + [(libre, "LibreWolf", "#3fa9f5")], INFO)
        self.assertEqual([b.get_label() for _key, b in view._chip_buttons], ["auto", "Firefox", "Zen", "LibreWolf", "all"])

    def test_all_gets_a_named_header_per_browser(self):
        view = self.make()
        ff, zen = self.two(view)
        self.assertEqual(view.browser_name.get_text(), "All browsers")
        headers = [(m["conn"], view._meta[b]["kind"]) for b, m in view._meta.items() if m["kind"] == "browser"]
        self.assertEqual(headers, [(ff, "browser"), (zen, "browser")])
        first = self.row_of(view, ff, "browser", None).get_child().get_text()
        second = self.row_of(view, zen, "browser", None).get_child().get_text()
        self.assertTrue(first.strip("▌ ").startswith("Firefox (4)") and second.strip("▌ ").startswith("Zen (4)"))

    def test_a_single_browser_has_no_browser_header(self):
        view = self.make()
        view.show([(object(), INFO, DRAG_STATE)])
        self.assertEqual([m for m in view._meta.values() if m["kind"] == "browser"], [])

    def test_a_browser_header_folds_that_browser_away_and_back(self):
        view = self.make()
        ff, zen = self.two(view)
        before = len(view.list.get_children())
        click(self.row_of(view, zen, "browser", None))
        tabs = [m["conn"] for m in view._meta.values() if m["kind"] == "tab"]
        self.assertEqual(set(tabs), {ff})  # Zen's sections and tabs are gone, Firefox's stay
        self.assertEqual(len(view.list.get_children()), before - 7)  # 3 sections + 4 tabs
        click(self.row_of(view, zen, "browser", None))
        self.assertEqual(len(view.list.get_children()), before)

    def test_folding_a_browser_does_not_fold_the_same_browser_in_another_profile(self):
        view = self.make()
        ff, zen = self.two(view)
        click(self.row_of(view, zen, "browser", None))
        other = object()  # a second Zen profile: another process
        view.show([(ff, INFO, DRAG_STATE), (other, {**self.ZEN, "browserPid": 3}, DRAG_STATE)], "all",
                  [(ff, "Firefox", "#ff7139"), (other, "Zen", "#9d7cd8")], INFO)
        self.assertIn(other, {m["conn"] for m in view._meta.values() if m["kind"] == "tab"})

    def test_a_tab_click_goes_to_the_browser_it_belongs_to(self):
        view = self.make()
        ff, zen = self.two(view)
        click(self.row_of(view, zen, "tab", 3))
        click(self.row_of(view, ff, "tab", 1))
        self.assertEqual(self.activated, [(zen, 3, 2), (ff, 1, 2)])

    def test_a_drag_cannot_land_in_another_browser(self):
        view = self.make()
        ff, zen = self.two(view)
        for kind, ident in (("tab", 1), ("section", "firefox-container-1")):
            candidates = view._drop_candidates(self.row_of(view, zen, kind, ident))
            self.assertTrue(candidates)
            self.assertEqual({view._meta[b]["conn"] for b in candidates}, {zen})

    def test_a_drop_is_sent_to_the_browser_whose_row_it_was(self):
        view = self.make()
        ff, zen = self.two(view)
        self.drag(view, self.row_of(view, zen, "tab", 1), self.row_of(view, zen, "tab", 4), after=False)
        self.assertEqual(self.commands, [{"type": "move_tab", "tabId": 1, "index": 2}])
        self.assertEqual(self.command_conns, [zen])

    def test_reordering_containers_changes_only_that_browsers_order(self):
        view = self.make()
        ff, zen = self.two(view)
        self.drag(view, self.row_of(view, zen, "section", "firefox-container-2"),
                  self.row_of(view, zen, "section", "firefox-container-1"), after=False)
        self.assertEqual(self.command_conns, [zen])
        orders = {c: s.get("containerOrder") for c, _info, s in view.sources}
        self.assertEqual(orders, {ff: None, zen: ["firefox-container-2", "firefox-container-1"]})

    def test_rows_wear_their_own_browsers_colour(self):
        view = self.make()
        ff, zen = self.two(view)
        has = lambda conn, cls: self.row_of(view, conn, "tab", 1).get_style_context().has_class(cls)  # noqa: E731
        self.assertTrue(has(ff, "acc-ff7139") and not has(ff, "acc-9d7cd8"))
        self.assertTrue(has(zen, "acc-9d7cd8") and not has(zen, "acc-ff7139"))

    def test_the_strip_wears_the_colour_of_the_browser_in_use_when_all_are_listed(self):
        view = self.make()
        self.two(view, focus=INFO)
        self.assertIn("#ff7139", view._css_data)
        self.two(view, focus=self.ZEN)
        self.assertIn("#9d7cd8", view._css_data)
        self.two(view, focus=None)  # nothing in use yet
        self.assertIn("#8f9bb3", view._css_data)

    def test_the_chips_stay_when_there_is_nothing_to_list_but_browsers_are_connected(self):
        view = self.make()
        ff, zen = self.two(view)
        choices = [(ff, "Firefox", "#ff7139"), (zen, "Zen", "#9d7cd8")]
        view.clear(zen, choices)  # the chosen browser has sent no tabs yet
        self.assertTrue(view.chips.get_visible())  # a way to pick auto, all or the other browser
        self.assertEqual([r for r in self.row_texts(view) if "Waiting" in r], self.row_texts(view))
        selected = [label for label, b in self.chips(view).items() if b.get_style_context().has_class("selected")]
        self.assertEqual(selected, ["Zen"])
        view.clear()
        self.assertFalse(view.chips.get_visible())

    def test_switching_the_browser_in_use_restyles_but_does_not_rebuild_the_rows(self):
        view = self.make()
        ff, zen = self.two(view, focus=INFO)
        rows = view.list.get_children()
        both = [(ff, INFO, DRAG_STATE), (zen, self.ZEN, DRAG_STATE)]
        view.show(both, "all", [(ff, "Firefox", "#ff7139"), (zen, "Zen", "#9d7cd8")], self.ZEN)  # alt-tab to Zen
        self.assertEqual(view.list.get_children(), rows)  # rows carry their own browser's colour
        self.assertIn("#9d7cd8", view._css_data)  # the strip and the header change

    def test_hovering_a_browser_chip_changes_its_border_like_the_other_chips(self):
        import warnings

        view = self.make()
        self.two(view)
        for label in ("auto", "Firefox", "Zen"):
            ctx = self.chips(view)[label].get_style_context()
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)  # no other way to ask GTK3 for a state's border
                normal = ctx.get_border_color(Gtk.StateFlags.NORMAL).to_string()
                hover = ctx.get_border_color(Gtk.StateFlags.PRELIGHT).to_string()
            self.assertNotEqual(normal, hover, label)

    def test_a_chosen_browser_is_named_with_its_number_when_two_share_a_name(self):
        view = self.make()
        conn = object()
        view.show([(conn, INFO, STATE)], conn, [(conn, "Firefox 2", "#ff7139"), (object(), "Firefox 1", "#ff7139")], INFO)
        self.assertEqual(view.browser_name.get_text(), "Firefox 2")

    def test_the_layout_hook_survives_a_window_that_is_already_gone(self):
        with mock.patch.dict(os.environ, {"TABDOCK_LAYOUT_DUMP": "/nonexistent/rows.json"}):
            view = self.make()
        view.show([(object(), INFO, DRAG_STATE)])
        view.win.destroy()
        self.assertFalse(view._dump_layout())  # an idle callback that outlived its window: quietly nothing

    # -- workspaces ----------------------------------------------------------------------------------

    WS_STATE = {  # window 2 shows "Work"; tab 3 is pinned, so it shows in every workspace
        "focusedWindowId": 2,
        "containers": [],
        "workspaces": [{"id": "default", "name": "Default"}, {"id": "ws-1", "name": "Work"}, {"id": "ws-2", "name": "Play"}],
        "windows": [{"id": 2, "workspaceId": "ws-1", "tabs": [
            {"id": 1, "index": 1, "title": "home", "cookieStoreId": "firefox-default", "workspaceId": "default"},
            {"id": 2, "index": 2, "title": "ticket", "cookieStoreId": "firefox-default", "workspaceId": "ws-1", "active": True},
            {"id": 3, "index": 0, "title": "music", "cookieStoreId": "firefox-default", "workspaceId": "ws-2", "pinned": True},
        ]}],
    }

    def ws_buttons(self, view):
        return {button.get_label(): button for _conn, _id, button in view._ws_buttons}

    def selected_ws(self, view):
        return [label for label, b in self.ws_buttons(view).items() if b.get_style_context().has_class("selected")]

    def right_click(self, widget):
        button(widget, Gdk.EventType.BUTTON_PRESS, "button-press-event", which=3)

    def menu_items(self, view):
        return {item.get_label(): item for item in view._menu.get_children()}

    def test_workspaces_are_chips_above_the_tabs_with_the_shown_one_marked(self):
        view = self.make()
        view.show([(object(), INFO, self.WS_STATE)])
        self.assertEqual(list(self.ws_buttons(view)), ["Default", "Work", "Play", "+"])
        self.assertEqual(self.selected_ws(view), ["Work"])
        self.assertIsInstance(view.list.get_children()[0], Gtk.FlowBox)  # first, above the containers

    def test_only_the_shown_workspaces_tabs_are_listed_and_pinned_tabs_everywhere(self):
        view = self.make()
        view.show([(object(), INFO, self.WS_STATE)])
        self.assertEqual({m["id"] for m in view._meta.values() if m["kind"] == "tab"}, {2, 3})

    def test_no_workspaces_in_zen_or_from_an_older_extension(self):
        view = self.make()
        view.show([(object(), {**INFO, "browser": "Zen"}, self.WS_STATE)])  # Zen has workspaces of its own
        self.assertEqual(view._ws_buttons, [])
        old = {k: v for k, v in STATE.items() if k != "workspaces"}
        view.show([(object(), INFO, old)])
        self.assertEqual(view._ws_buttons, [])
        self.assertNotIsInstance(view.list.get_children()[0], Gtk.FlowBox)

    def test_one_workspace_is_a_chip_too_with_a_plus_to_make_the_next(self):
        view = self.make()
        view.show([(object(), INFO, {**STATE, "workspaces": [{"id": "default", "name": "Default"}]})])
        self.assertEqual(list(self.ws_buttons(view)), ["Default", "+"])

    def test_a_click_on_a_workspace_switches_the_window_to_it(self):
        view = self.make()
        conn = object()
        view.show([(conn, INFO, self.WS_STATE)])
        self.ws_buttons(view)["Play"].clicked()
        self.assertEqual(self.commands, [{"type": "switch_workspace", "windowId": 2, "workspaceId": "ws-2"}])
        self.assertEqual(self.command_conns, [conn])

    def test_plus_asks_for_a_name_and_makes_the_workspace(self):
        view = self.make()
        view.show([(object(), INFO, self.WS_STATE)])
        self.ws_buttons(view)["+"].clicked()
        self.assertEqual(view._dialog_entry.get_text(), "Workspace 4")  # a name to keep or type over
        self.assertTrue(view.autohide.held)  # the panel stays while you type
        view._dialog.realize()  # (never mapped here)
        self.assertIn(view._dialog.get_window().get_xid(), view.xids)  # typing there is not "another app"
        view._dialog_entry.set_text("  Deep work  ")
        view._dialog_entry.emit("activate")  # Enter
        self.assertEqual(self.commands, [{"type": "new_workspace", "windowId": 2, "name": "Deep work"}])
        self.assertIsNone(view._dialog)
        self.assertFalse(view.autohide.held)

    def test_the_name_window_can_be_cancelled_and_an_empty_name_does_nothing(self):
        view = self.make()
        view.show([(object(), INFO, self.WS_STATE)])
        self.ws_buttons(view)["+"].clicked()
        event = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
        event.keyval = Gdk.KEY_Escape
        view._dialog.emit("key-press-event", event)
        self.ws_buttons(view)["+"].clicked()
        view._dialog_entry.set_text("   ")
        view._dialog_entry.emit("activate")
        self.assertEqual(self.commands, [])
        self.assertIsNone(view._dialog)
        self.assertFalse(view.autohide.held)

    def test_right_click_on_a_workspace_renames_it(self):
        view = self.make()
        view.show([(object(), INFO, self.WS_STATE)])
        self.right_click(self.ws_buttons(view)["Work"])
        self.assertTrue(view.autohide.held)  # the menu is up: the panel stays
        self.menu_items(view)["Rename…"].activate()
        self.assertEqual(view._dialog_entry.get_text(), "Work")
        view._dialog_entry.set_text("Tickets")
        view._dialog_entry.emit("activate")
        # only the rename: a right click on a workspace does not also switch to it
        self.assertEqual(self.commands, [{"type": "rename_workspace", "workspaceId": "ws-1", "name": "Tickets"}])

    def test_removing_a_workspace_says_where_its_tabs_go(self):
        view = self.make()
        view.show([(object(), INFO, self.WS_STATE)])
        self.right_click(self.ws_buttons(view)["Default"])
        self.assertIn("Remove (its tabs go to Work)", self.menu_items(view))  # the first one: to the next
        self.right_click(self.ws_buttons(view)["Play"])
        self.menu_items(view)["Remove (its tabs go to Work)"].activate()  # any other: to the one before it
        self.assertEqual(self.commands, [{"type": "remove_workspace", "workspaceId": "ws-2"}])

    def test_the_last_workspace_cannot_be_removed(self):
        view = self.make()
        view.show([(object(), INFO, {**STATE, "workspaces": [{"id": "default", "name": "Default"}]})])
        self.right_click(self.ws_buttons(view)["Default"])
        self.assertFalse(self.menu_items(view)["Remove (the last workspace stays)"].get_sensitive())

    EDIT_STATE = {  # an extension that keeps an icon, a colour and a container per workspace
        **WS_STATE,
        "containers": [
            {"cookieStoreId": "firefox-container-1", "name": "Personal", "colorCode": "#37adff", "icon": "fingerprint"},
            {"cookieStoreId": "firefox-container-2", "name": "Bank & Co", "colorCode": "#51cd00", "icon": "dollar"},
        ],
        "workspaces": [
            {"id": "default", "name": "Default", "icon": None, "color": None, "cookieStoreId": None},
            {"id": "ws-1", "name": "Work", "icon": "💼", "color": "blue", "cookieStoreId": "firefox-container-1"},
            {"id": "ws-2", "name": "Play", "icon": None, "color": None, "cookieStoreId": None},
        ],
    }

    def submenu(self, view, label):
        """{the text an item shows (markup stripped): item} of one of the menu's submenus."""
        return {item.get_child().get_text(): item for item in self.menu_items(view)[label].get_submenu().get_children()}

    def test_a_workspace_chip_wears_its_icon_and_colour_and_names_its_container(self):
        view = self.make()
        view.show([(object(), INFO, self.EDIT_STATE)])
        self.assertEqual(list(self.ws_buttons(view)), ["Default", "💼 Work", "Play", "+"])
        work, play = self.ws_buttons(view)["💼 Work"], self.ws_buttons(view)["Play"]
        self.assertTrue(work.get_style_context().has_class("ws-blue"))
        self.assertFalse(play.get_style_context().has_class("ws-col"))
        self.assertIn("New tabs open in Personal", work.get_tooltip_text())
        self.assertNotIn("New tabs", play.get_tooltip_text())

    def test_the_workspace_menu_sets_its_icon_colour_and_container(self):
        view = self.make()
        view.show([(object(), INFO, self.EDIT_STATE)])
        self.right_click(self.ws_buttons(view)["Play"])
        self.assertEqual(list(self.menu_items(view)),
                         ["Rename…", "Icon", "Colour", "New tabs in", "Remove (its tabs go to 💼 Work)"])
        self.assertEqual(self.commands, [])  # marking the current choices sends nothing
        self.submenu(view, "Icon")["🎮"].activate()
        self.submenu(view, "Colour")["● Green"].activate()
        self.submenu(view, "New tabs in")["▌ $ Bank & Co"].activate()  # (markup-escaped, shown as it is)
        edit = {"type": "edit_workspace", "workspaceId": "ws-2"}
        self.assertEqual(self.commands, [
            {**edit, "icon": "🎮"}, {**edit, "color": "green"}, {**edit, "cookieStoreId": "firefox-container-2"},
        ])

    def test_the_workspace_menu_marks_what_it_has_and_can_clear_it(self):
        view = self.make()
        view.show([(object(), INFO, self.EDIT_STATE)])
        self.right_click(self.ws_buttons(view)["💼 Work"])
        chosen = lambda label: [t for t, item in self.submenu(view, label).items() if item.get_active()]  # noqa: E731
        self.assertEqual((chosen("Icon"), chosen("Colour"), chosen("New tabs in")), (["💼"], ["● Blue"], ["▌ ☺ Personal"]))
        self.submenu(view, "Icon")["None"].activate()
        self.submenu(view, "Colour")["None"].activate()
        self.submenu(view, "New tabs in")["No container"].activate()
        edit = {"type": "edit_workspace", "workspaceId": "ws-1"}
        self.assertEqual(self.commands, [{**edit, "icon": None}, {**edit, "color": None}, {**edit, "cookieStoreId": None}])

    def test_any_other_icon_can_be_typed(self):
        view = self.make()
        view.show([(object(), INFO, self.EDIT_STATE)])
        self.right_click(self.ws_buttons(view)["Play"])
        self.submenu(view, "Icon")["Other…"].activate()
        self.assertEqual(view._dialog_entry.get_max_length(), 8)  # one emoji, even a composed one, or a few letters
        view._dialog_entry.set_text("🦊")
        view._dialog_entry.emit("activate")
        self.assertEqual(self.commands, [{"type": "edit_workspace", "workspaceId": "ws-2", "icon": "🦊"}])
        spaces = [{**ws, "icon": "🦊"} if ws["id"] == "ws-2" else ws for ws in self.EDIT_STATE["workspaces"]]
        view.show([(object(), INFO, {**self.EDIT_STATE, "workspaces": spaces})])
        self.right_click(self.ws_buttons(view)["🦊 Play"])
        self.assertTrue(self.submenu(view, "Icon")["Other (🦊)…"].get_active())  # the typed one is the choice

    def test_an_older_extension_or_no_containers_offer_less(self):
        view = self.make()
        view.show([(object(), INFO, self.WS_STATE)])  # workspaces with names only
        self.right_click(self.ws_buttons(view)["Work"])
        self.assertEqual(list(self.menu_items(view)), ["Rename…", "Remove (its tabs go to Default)"])
        view.show([(object(), INFO, {**self.EDIT_STATE, "containers": []})])  # containers switched off
        self.right_click(self.ws_buttons(view)["Play"])
        self.assertNotIn("New tabs in", self.menu_items(view))
        self.assertIn("Colour", self.menu_items(view))

    def test_right_click_on_a_tab_moves_it_to_another_workspace(self):
        view = self.make()
        conn = object()
        view.show([(conn, INFO, self.WS_STATE)])
        self.right_click(self.row(view, "tab", 2))
        self.assertEqual([label for label in self.menu_items(view) if label.startswith("Move")],
                         ["Move to Default", "Move to Play"])  # not where it is
        self.menu_items(view)["Move to Play"].activate()
        self.assertEqual(self.commands, [{"type": "move_tab_to_workspace", "tabId": 2, "workspaceId": "ws-2"}])
        self.assertEqual(self.activated, [])  # a right click is not a click

    def test_a_pinned_tab_or_a_single_workspace_offers_no_move(self):
        view = self.make()
        moves = lambda tab_id: [label for label, _action in view._meta[self.row(view, "tab", tab_id)]["menu"]  # noqa: E731
                                if label and label.startswith("Move")]
        view.show([(object(), INFO, self.WS_STATE)])
        self.assertEqual(moves(3), [])  # pinned: in every workspace already
        view.show([(object(), INFO, {**STATE, "workspaces": [{"id": "default", "name": "Default"}]})])
        self.assertEqual(moves(10), [])

    def test_the_menu_lets_go_of_the_panel_when_it_closes(self):
        view = self.make()
        view.show([(object(), INFO, self.WS_STATE)])
        self.right_click(self.row(view, "tab", 2))
        self.assertTrue(view.autohide.held)
        view._menu.emit("deactivate")  # it closes, chosen from or not
        self.assertFalse(view.autohide.held)

    def test_a_menu_that_cannot_open_does_not_keep_the_panel_open(self):
        view = self.make()
        view.show([(object(), INFO, self.WS_STATE)])
        with mock.patch.object(Gtk.Menu, "popup_at_pointer", lambda _menu, _event: None):
            self.right_click(self.row(view, "tab", 2))
        self.assertFalse(view.autohide.held)

    def test_a_drag_ending_while_the_name_window_is_up_keeps_the_panel_open(self):
        view = self.make()
        view.show([(object(), INFO, self.WS_STATE)])
        self.ws_buttons(view)["+"].clicked()
        view._hold("drag", True)
        view._hold("drag", False)
        self.assertTrue(view.autohide.held)  # still typing a name

    def test_a_browser_band_counts_the_tabs_it_lists(self):
        view = self.make()
        zen = {**INFO, "browser": "Zen", "browserPid": 2}
        ff = object()
        view.show([(ff, INFO, self.WS_STATE), (object(), zen, DRAG_STATE)], "all")
        band = next(b for b, m in view._meta.items() if m["kind"] == "browser" and m["conn"] is ff)
        self.assertTrue(band.get_child().get_text().startswith("Firefox (2)"))  # Work's tab and the pinned one

    def test_layout_dump_hook_reports_the_workspace_chips(self):
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"TABDOCK_LAYOUT_DUMP": tmp + "/rows.json"}):
            view = self.make()
            view.show([(object(), INFO, self.WS_STATE)])
            view._dump_layout()
            with open(tmp + "/rows.json") as f:
                rows = json.load(f)
        self.assertEqual([(r["id"], r["group"]) for r in rows if r["kind"] == "workspace"],
                         [("default", "Default"), ("ws-1", "Work"), ("ws-2", "Play"), (None, "+")])
        self.assertEqual([r["id"] for r in rows if r["kind"] == "close"], [2, 3])  # each listed tab's ✕

    # -- editing containers --------------------------------------------------------------------------

    def labels(self, view):
        return [item.get_label() for item in view._menu.get_children() if not isinstance(item, Gtk.SeparatorMenuItem)]

    def texts(self, view, label):
        return {item.get_child().get_text(): item for item in self.menu_items(view)[label].get_submenu().get_children()}

    def test_right_click_on_a_container_renames_recolours_and_reicons_it(self):
        view = self.make()
        conn = object()
        state = {**STATE, "containers": [{**STATE["containers"][0], "color": "blue"}, STATE["containers"][1]]}
        view.show([(conn, INFO, state)])
        self.right_click(self.row(view, "section", "firefox-container-1"))
        self.assertTrue(view.autohide.held)
        self.assertEqual(self.labels(view), ["Rename…", "Colour", "Icon", "New container…", "Remove container…"])
        self.assertTrue(self.texts(view, "Colour")["● Blue"].get_active())  # what it has now is marked
        self.assertTrue(self.texts(view, "Icon")["☺ Fingerprint"].get_active())
        self.assertEqual(len(self.texts(view, "Icon")), 13)  # every icon Firefox offers a container
        self.assertEqual(self.commands, [])
        self.texts(view, "Colour")["● Purple"].activate()
        self.texts(view, "Icon")["🍎 Fruit"].activate()
        self.menu_items(view)["Rename…"].activate()
        self.assertEqual(view._dialog_entry.get_text(), "Personal & Co")
        view._dialog_entry.set_text("Private")
        view._dialog_entry.emit("activate")
        update = {"type": "update_container", "cookieStoreId": "firefox-container-1"}
        self.assertEqual(self.commands, [{**update, "color": "purple"}, {**update, "icon": "fruit"}, {**update, "name": "Private"}])
        self.assertEqual(self.command_conns, [conn] * 3)

    def test_a_new_container_is_named_in_a_window_of_its_own(self):
        view = self.make()
        view.show([(object(), INFO, STATE)])
        self.right_click(self.row(view, "section", "firefox-default"))
        self.assertEqual(self.labels(view), ["New container…"])  # "No container" itself cannot change
        self.menu_items(view)["New container…"].activate()
        self.assertEqual(view._dialog.get_title(), "New container")
        self.assertEqual(view._dialog_entry.get_text(), "")
        view._dialog_entry.set_text("  Travel ")
        view._dialog_entry.emit("activate")
        self.assertEqual(self.commands, [{"type": "create_container", "name": "Travel"}])

    def test_removing_a_container_asks_first_and_says_what_goes(self):
        view = self.make()
        view.show([(object(), INFO, STATE)])  # Personal & Co has one tab open
        self.right_click(self.row(view, "section", "firefox-container-1"))
        self.menu_items(view)["Remove container…"].activate()
        view._menu.emit("deactivate")  # (a real menu closes when an item is picked)
        text = view._dialog_text.get_text()
        self.assertIn('"Personal & Co"', text)
        self.assertIn("Its 1 open tab will close", text)
        self.assertIn("cookies", text)
        self.assertTrue(view._dialog_ok.get_style_context().has_class("destructive-action"))
        self.assertEqual(view._dialog_ok.get_label(), "Remove")
        self.assertTrue(view.autohide.held)
        event = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
        event.keyval = Gdk.KEY_Escape
        view._dialog.emit("key-press-event", event)  # thought better of it
        self.assertEqual(self.commands, [])
        self.assertIsNone(view._dialog)
        self.assertFalse(view.autohide.held)
        self.right_click(self.row(view, "section", "firefox-container-1"))
        self.menu_items(view)["Remove container…"].activate()
        view._dialog_ok.clicked()
        self.assertEqual(self.commands, [{"type": "remove_container", "cookieStoreId": "firefox-container-1"}])

    def test_a_store_the_browser_does_not_list_as_a_container_offers_no_menu(self):
        view = self.make()
        state = {**STATE, "windows": [{"id": 2, "tabs": [
            {"id": 12, "title": "private", "cookieStoreId": "firefox-private", "active": True}]}]}
        view.show([(object(), INFO, state)])
        self.assertIsNone(view._meta[self.row(view, "section", "firefox-private")]["menu"])

    # -- closing and pinning tabs --------------------------------------------------------------------

    def close_button(self, view, tab_id):
        return next(b for i, b in view._close_buttons if i == tab_id)

    def test_every_tab_has_a_close_button_that_shows_on_hover(self):
        view = self.make()
        conn = object()
        view.show([(conn, INFO, STATE)])
        close = self.close_button(view, 10)
        self.assertTrue(close.get_style_context().has_class("sp-close"))  # (hidden until the row is hovered)
        self.assertIn(close, self.row(view, "tab", 10).get_child().get_children())
        close.clicked()
        self.assertEqual(self.commands, [{"type": "close_tab", "tabId": 10}])
        self.assertEqual(self.command_conns, [conn])
        self.assertEqual(self.activated, [])  # closing is not also a click on the tab

    def test_a_row_is_hovered_while_the_pointer_is_on_it_or_on_its_close_button(self):
        view = self.make()
        view.show([(object(), INFO, STATE)])
        row = self.row(view, "tab", 10)
        hovered = lambda: bool(row.get_state_flags() & Gtk.StateFlags.PRELIGHT)  # noqa: E731

        def crossing(kind, signal, detail):
            event = Gdk.Event.new(kind)
            event.detail = detail
            row.emit(signal, event)

        self.assertFalse(hovered())
        crossing(Gdk.EventType.ENTER_NOTIFY, "enter-notify-event", Gdk.NotifyType.NONLINEAR)
        self.assertTrue(hovered())  # what shows its hover background and its ✕
        crossing(Gdk.EventType.LEAVE_NOTIFY, "leave-notify-event", Gdk.NotifyType.INFERIOR)
        self.assertTrue(hovered())  # onto the ✕, which is inside the row
        crossing(Gdk.EventType.LEAVE_NOTIFY, "leave-notify-event", Gdk.NotifyType.NONLINEAR)
        self.assertFalse(hovered())

    def test_an_older_extension_gets_no_close_pin_or_container_editing_it_could_not_do(self):
        view = self.make()
        view.show([(object(), OLD_INFO, STATE)])
        self.assertEqual(view._close_buttons, [])  # no ✕
        self.assertIsNone(view._meta[self.row(view, "tab", 10)]["menu"])  # nothing to pin, move or close
        self.assertIsNone(view._meta[self.row(view, "section", "firefox-container-1")]["menu"])
        row = self.row(view, "tab", 10)
        button(row, Gdk.EventType.BUTTON_PRESS, "button-press-event", which=2)
        button(row, Gdk.EventType.BUTTON_RELEASE, "button-release-event", which=2)
        self.assertEqual(self.commands, [])  # a middle click closes nothing either
        view.show([(object(), OLD_INFO, self.WS_STATE)])  # with workspaces: moving is still offered
        self.right_click(self.row(view, "tab", 2))
        self.assertEqual(self.labels(view), ["Move to Default", "Move to Play"])

    def test_a_tab_reopens_in_another_container(self):
        view = self.make()
        view.show([(object(), INFO, STATE)])  # tab 10 is in no container, on https://a.example
        self.right_click(self.row(view, "tab", 10))
        self.assertEqual(self.labels(view), ["Pin tab", "Reopen in container", "Close tab"])
        choices = self.texts(view, "Reopen in container")
        self.assertEqual(list(choices), ["▌ Personal & Co", "▌ Work"])  # not where it is
        choices["▌ Work"].activate()
        self.assertEqual(self.commands, [{"type": "reopen_in_container", "tabId": 10, "cookieStoreId": "firefox-container-2"}])
        tabs = [STATE["windows"][0]["tabs"][0], {**STATE["windows"][0]["tabs"][1], "url": "https://mail.example"}]
        view.show([(object(), INFO, {**STATE, "windows": [{"id": 2, "tabs": tabs}]})])
        self.right_click(self.row(view, "tab", 11))  # in Personal & Co: "No container" is a choice
        self.assertEqual(list(self.texts(view, "Reopen in container")), ["▌ No container", "▌ Work"])

    def test_a_page_an_extension_may_not_open_is_not_offered_another_container(self):
        view = self.make()
        state = {**STATE, "windows": [{"id": 2, "tabs": [
            {"id": 10, "title": "config", "url": "about:config", "cookieStoreId": "firefox-default", "active": True}]}]}
        view.show([(object(), INFO, state)])
        self.right_click(self.row(view, "tab", 10))
        self.assertNotIn("Reopen in container", self.labels(view))

    # -- finding a tab -------------------------------------------------------------------------------

    def listed_tabs(self, view):
        return [m["id"] for m in view._meta.values() if m["kind"] == "tab"]

    def test_find_narrows_the_list_as_you_type_across_workspaces_and_enter_picks_the_first(self):
        view = self.make()
        conn = object()
        view.show([(conn, INFO, self.WS_STATE)])  # Work shows tabs 2 and 3 (pinned); tab 1 "home" is in Default
        self.assertEqual(sorted(self.listed_tabs(view)), [2, 3])
        view.find_btn.clicked()
        self.assertEqual(view._dialog.get_title(), "Find")
        self.assertTrue(view.autohide.held)
        view._dialog_entry.set_text("HOME")
        self.assertEqual(self.listed_tabs(view), [1])  # from another workspace, whatever the case
        where = [c.get_text() for c in self.row(view, "tab", 1).get_child().get_children()
                 if c.get_style_context().has_class("sp-where")]
        self.assertEqual(where, ["in Default"])  # says where it is
        view._dialog_entry.emit("activate")  # Enter
        self.assertEqual(self.activated, [(conn, 1, 2)])  # the extension switches to its workspace
        self.assertEqual(sorted(self.listed_tabs(view)), [2, 3])  # the whole list back
        self.assertFalse(view.autohide.held)

    def test_find_says_when_nothing_matches_and_escape_gives_the_list_back(self):
        view = self.make()
        view.show([(object(), INFO, STATE)])
        view.collapsed.add((1, "firefox-container-1"))  # a folded section still shows what matches in it
        view.find_btn.clicked()
        view._dialog_entry.set_text("mail")
        self.assertEqual(self.listed_tabs(view), [11])
        view._dialog_entry.set_text("nothing like this")
        self.assertEqual(self.listed_tabs(view), [])
        self.assertTrue(any(isinstance(c, Gtk.Label) and "No tab matches" in c.get_text() for c in view.list.get_children()))
        event = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
        event.keyval = Gdk.KEY_Escape
        view._dialog.emit("key-press-event", event)
        self.assertEqual(self.activated, [])
        self.assertEqual(self.listed_tabs(view), [10])  # everything again, the folded section folded again

    def key(self, view, keyval, state=0):
        """A key for the find window's entry, whether the panel handled it. (Not emitted: a key event with no window
        makes GTK's own handler complain when the panel leaves it alone.)"""
        event = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
        event.keyval = keyval
        event.state = Gdk.ModifierType(state)
        return view._on_find_key(view._dialog_entry, event)

    def highlighted(self, view):
        return [m["id"] for b, m in view._meta.items() if b.get_style_context().has_class("kbd")]

    def test_find_arrow_keys_highlight_a_tab_and_enter_opens_that_one(self):
        view = self.make()
        conn = object()
        view.show([(conn, INFO, DRAG_STATE)])
        order = self.listed_tabs(view)
        view.find_btn.clicked()
        self.assertEqual(self.highlighted(view), [])
        event = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
        event.keyval = Gdk.KEY_Down
        view._dialog_entry.emit("key-press-event", event)  # the entry is wired to it; from nothing: the first tab
        self.assertEqual(self.highlighted(view), [order[0]])
        self.key(view, Gdk.KEY_Down)
        self.key(view, Gdk.KEY_Down)
        self.assertEqual(self.highlighted(view), [order[2]])
        self.key(view, Gdk.KEY_Up)
        self.assertEqual(self.highlighted(view), [order[1]])
        view._dialog_entry.emit("activate")  # Enter
        self.assertEqual(self.activated, [(conn, order[1], 2)])  # what a click on that row does
        self.assertEqual(self.highlighted(view), [])
        self.assertEqual(self.listed_tabs(view), order)

    def test_find_ctrl_a_toggles_all_and_all_lists_the_browser_headers(self):
        view = self.make()
        ff, zen = self.two(view, mode="auto")
        view.find_btn.clicked()
        self.assertEqual([m["kind"] for b, m in view._meta.items() if m["kind"] == "browser"], ["browser", "browser"])
        self.assertFalse(any(m["findable"] for m in view._meta.values() if m["kind"] == "browser"))
        self.assertTrue(self.key(view, Gdk.KEY_a, Gdk.ModifierType.CONTROL_MASK))
        self.assertEqual(self.chosen, ["all"])
        ff, zen = self.two(view, mode="all")
        self.assertEqual([m["conn"] for m in view._meta.values() if m["kind"] == "browser" and m["findable"]], [ff, zen])
        self.key(view, Gdk.KEY_Down)  # the first row is Firefox's header
        self.assertEqual(self.highlighted(view), [None])
        view._dialog_entry.emit("activate")  # Enter
        self.assertEqual(view.collapsed, {(INFO.get("browserPid") or INFO["browser"], None)})
        self.assertIsNotNone(view._dialog)  # the window stays
        view.on_choose = lambda key: (self.chosen.append(key), view._rebuild())  # as the panel does
        self.key(view, Gdk.KEY_a, Gdk.ModifierType.CONTROL_MASK)
        self.assertEqual(self.chosen, ["all", "auto"])
        self.assertEqual(self.raised, [ff])

    def test_next_prev_and_open_work_without_the_find_window(self):
        view = self.make()
        conn = object()
        view.show([(conn, INFO, DRAG_STATE)])
        order = self.listed_tabs(view)
        view.nav_next()
        self.assertEqual(self.highlighted(view), [order[0]])
        view.nav_next()
        view.nav_prev()
        view.nav_next()
        self.assertEqual(self.highlighted(view), [order[1]])
        self.assertIn("keys", view._holds)  # the panel stays open while keys are used
        view.nav_open()
        self.assertEqual(self.activated, [(conn, order[1], 2)])
        self.assertEqual(self.highlighted(view), [])
        self.assertNotIn("keys", view._holds)

    def test_open_on_a_browser_header_folds_it_and_all_toggles(self):
        view = self.make()
        ff, zen = self.two(view, mode="all")
        view.nav_next()
        view.nav_open()
        self.assertEqual(view.collapsed, {(INFO.get("browserPid") or INFO["browser"], None)})
        self.assertEqual(self.highlighted(view), [None])
        view.toggle_all()
        self.assertEqual(self.chosen, ["auto"])
        self.assertEqual(self.raised, [ff])
        self.assertEqual(self.highlighted(view), [])

    def test_ws_next_and_prev_switch_workspace_without_the_find_window(self):
        view = self.make()
        conn = object()
        view.show([(conn, INFO, self.WS_STATE)])
        view.ws_next()
        self.assertEqual([m["type"] for m in self.commands], ["switch_workspace"])
        self.assertEqual(self.command_conns, [conn])
        self.assertIn("keys", view._holds)  # the panel shows the switch
        view.ws_prev()
        self.assertEqual(len(self.commands), 2)
        self.assertNotEqual(self.commands[0]["workspaceId"], self.commands[1]["workspaceId"])
        view.new_workspace()  # a name window is up: the keys wait
        view.ws_next()
        self.assertEqual(len(self.commands), 2)

    def test_find_arrows_reach_an_empty_container_and_a_start_row(self):
        view = self.make()
        conn = object()
        view.show([(conn, INFO, STATE)], offline=[("Zen", "zen-browser"), ("Chromium", "chromium")])
        view.find_btn.clicked()
        rows = [(view._meta[b]["kind"], view._meta[b]["id"]) for b in view._find_rows()]
        self.assertEqual(rows, [("tab", 10), ("tab", 11), ("section", "firefox-container-2"),
                                ("offline", "zen-browser"), ("offline", "chromium")])
        empty = view._find_rows()[2]
        view._meta[empty]["pick"]()
        self.assertEqual(self.commands[-1]["type"], "new_tab")
        view._dialog_entry.set_text("zen")
        self.assertEqual([view._meta[b]["id"] for b in view._find_rows() if view._meta[b]["kind"] == "offline"],
                         ["zen-browser"])

    def test_find_ctrl_p_i_l_toggle_the_dock_and_stay_open(self):
        ctrl = Gdk.ModifierType.CONTROL_MASK
        view = self.make(pinned=False, icons=False, side="left")
        view.show([(object(), INFO, STATE)])
        view.find_btn.clicked()
        self.assertTrue(self.key(view, Gdk.KEY_p, ctrl))
        self.assertEqual((view.cfg["pinned"], view.autohide.pinned, view.pin_btn.get_active()), (True, True, True))
        self.key(view, Gdk.KEY_p, ctrl)
        self.assertEqual((view.cfg["pinned"], view.autohide.pinned), (False, False))
        self.key(view, Gdk.KEY_i, ctrl)
        self.assertTrue(view.cfg["icons"])
        self.key(view, Gdk.KEY_l, ctrl)
        self.assertEqual(view.cfg["side"], "right")
        self.key(view, Gdk.KEY_L, ctrl)  # (Caps Lock)
        self.assertEqual(view.cfg["side"], "left")
        self.assertIsNotNone(view._find_dialog)
        self.assertEqual(view._dialog_entry.get_text(), "")

    def test_find_ctrl_n_asks_for_a_name_and_makes_a_workspace(self):
        view = self.make()
        conn = object()
        view.show([(conn, INFO, self.WS_STATE)])
        view.find_btn.clicked()
        self.assertTrue(self.key(view, Gdk.KEY_n, Gdk.ModifierType.CONTROL_MASK))
        self.assertIsNone(view._find_dialog)  # the find window made way for the name window
        self.assertEqual(view._dialog_entry.get_text(), "Workspace 4")
        view._dialog_entry.set_text("Deep work")
        view._dialog_entry.emit("activate")
        self.assertEqual(self.commands, [{"type": "new_workspace", "windowId": 2, "name": "Deep work"}])
        self.assertEqual(self.command_conns, [conn])
        self.assertEqual(self.raised, [conn])

    def test_new_workspace_key_makes_nothing_when_the_name_window_is_cancelled(self):
        view = self.make()
        view.show([(object(), INFO, self.WS_STATE)])
        view.new_workspace()
        self.assertEqual(view._dialog.get_title(), "New workspace")
        view._dialog_finish(False)
        self.assertEqual(self.commands, [])

    def test_find_delete_ctrl_k_and_ctrl_t_act_on_the_highlighted_tab(self):
        ctrl = Gdk.ModifierType.CONTROL_MASK
        view = self.make()
        view.show([(object(), INFO, STATE)])
        view.find_btn.clicked()
        self.key(view, Gdk.KEY_k, ctrl)  # nothing highlighted
        self.assertEqual(self.commands, [])
        self.key(view, Gdk.KEY_Down)  # tab 10
        self.key(view, Gdk.KEY_k, ctrl)
        self.assertEqual(self.commands, [{"type": "pin_tab", "tabId": 10, "pinned": True}])
        self.assertTrue(self.key(view, Gdk.KEY_Delete))
        self.assertEqual(self.commands[-1], {"type": "close_tab", "tabId": 10})
        self.assertEqual(view._selected[1], 11)  # the neighbour, marked by the rebuild that follows the close
        view._dialog_entry.set_text("mail")
        view._dialog_entry.select_region(0, -1)
        self.assertFalse(self.key(view, Gdk.KEY_Delete))  # a selection is deleted, not the tab
        self.assertEqual(len(self.commands), 2)
        view._dialog_entry.set_text("")
        self.key(view, Gdk.KEY_Down)
        self.key(view, Gdk.KEY_t, ctrl)
        self.assertEqual(self.commands[-1], {"type": "new_tab", "cookieStoreId": "firefox-container-2", "windowId": 2})  # the empty Work row
        self.assertIsNone(view._find_dialog)  # the browser has the keyboard now

    def test_find_delete_is_the_carets_while_it_is_not_at_the_end_of_the_text(self):
        view = self.make()
        view.show([(object(), INFO, STATE)])
        view.find_btn.clicked()
        view._dialog_entry.set_text("plain")
        self.key(view, Gdk.KEY_Down)
        view._dialog_entry.set_position(2)
        self.assertFalse(self.key(view, Gdk.KEY_Delete))
        self.assertEqual(self.commands, [])

    def test_find_arrow_keys_walk_bookmarks_and_enter_opens_the_highlighted_one(self):
        view, conn = self.bookmark_view()
        view._set_view("bookmarks")
        tree = [{"title": "Python docs", "url": "https://docs.python.org"},
                {"title": "Python wiki", "url": "https://wiki.python.org"}]
        view.show_bookmarks(conn, {"type": "bookmarks", "granted": True, "tree": tree})
        view.find_btn.clicked()
        view._dialog_entry.set_text("python")
        self.key(view, Gdk.KEY_Down)
        self.key(view, Gdk.KEY_Down)
        self.assertEqual(self.highlighted(view), [(1, "https://wiki.python.org")])
        self.key(view, Gdk.KEY_Up)
        self.key(view, Gdk.KEY_Down)
        view._dialog_entry.emit("activate")
        self.assertEqual(self.commands[-1]["url"], "https://wiki.python.org")

    def selected_views(self, view):
        return [k for k, b in view._find_view_buttons if b.get_style_context().has_class("selected")]

    def test_find_switches_view_with_ctrl_digits_and_keeps_what_is_typed(self):
        view = self.make(bookmarks=True, history=True)
        conn = object()
        info = {**INFO, "features": [*INFO["features"], "bookmarks", "history"]}
        view.show([(conn, info, STATE)])
        view.find_btn.clicked()
        self.assertEqual(self.selected_views(view), ["tabs"])
        self.assertEqual([k for k, b in view._find_view_buttons if b.get_visible()], ["tabs", "bookmarks", "history"])
        view._dialog_entry.set_text("python")
        ctrl = Gdk.ModifierType.CONTROL_MASK
        self.assertTrue(self.key(view, Gdk.KEY_2, ctrl))
        self.assertEqual((view._view, self.selected_views(view)), ("bookmarks", ["bookmarks"]))
        view.show_bookmarks(conn, {"type": "bookmarks", "granted": True, "tree": [
            {"title": "Python docs", "url": "https://docs.python.org"}, {"title": "Other", "url": "https://o.example"}]})
        self.assertEqual(self.row_texts(view), ["Python docs"])  # the typed word filters the new view
        self.key(view, Gdk.KEY_3, ctrl)
        self.assertEqual(self.commands[-1], {"type": "search_history", "query": "python"})
        self.key(view, Gdk.KEY_1, ctrl)
        self.assertEqual(view._view, "tabs")
        self.assertFalse(self.key(view, Gdk.KEY_2))  # without Ctrl it is just a digit for the entry
        self.key(view, Gdk.KEY_3, ctrl)
        view._dialog_finish(False)  # closing the find window gives the panel back the view it had
        self.assertEqual(view._view, "tabs")

    def test_find_offers_no_switch_without_bookmarks_or_history(self):
        view = self.make()
        view.show([(object(), INFO, STATE)])
        view.find_btn.clicked()
        self.assertFalse(view._find_switch.get_visible())
        self.key(view, Gdk.KEY_2, Gdk.ModifierType.CONTROL_MASK)
        self.assertEqual(view._view, "tabs")

    def test_find_arrow_keys_reach_closed_bookmark_folders_and_enter_opens_them(self):
        view, conn = self.bookmark_view()
        view._set_view("bookmarks")
        tree = [{"title": "Bar", "children": [{"title": "One", "url": "https://one.example"}]},
                {"title": "Loose", "url": "https://loose.example"}]
        view.show_bookmarks(conn, {"type": "bookmarks", "granted": True, "tree": tree})
        view.find_btn.clicked()
        self.key(view, Gdk.KEY_Down)
        self.assertEqual(self.highlighted(view), [(0, None)])  # the closed folder
        view._dialog_entry.emit("activate")  # Enter
        self.assertEqual(self.row_texts(view), ["▾ Bar", "One", "Loose"])
        self.assertIsNotNone(view._dialog)  # the window stays
        self.assertEqual(self.highlighted(view), [(0, None)])  # and the folder is still the highlighted one
        self.key(view, Gdk.KEY_Down)
        view._dialog_entry.emit("activate")
        self.assertEqual(self.commands[-1]["url"], "https://one.example")
        self.assertIsNone(view._dialog)  # a bookmark closes it

    def test_find_arrow_keys_pass_a_bookmark_saved_in_two_folders(self):
        view, conn = self.bookmark_view()
        view._set_view("bookmarks")
        page = {"title": "Docs", "url": "https://docs.python.org"}
        tree = [{"title": "A", "children": [page]}, {"title": "B", "children": [page]},
                {"title": "Last", "url": "https://last.example"}]
        view.opened = {(1, "/0"), (1, "/1")}  # (the browser's pid in INFO, the folder)
        view.show_bookmarks(conn, {"type": "bookmarks", "granted": True, "tree": tree})
        view.find_btn.clicked()
        for _ in range(5):  # A, Docs, B, Docs, Last
            self.key(view, Gdk.KEY_Down)
        self.assertEqual(self.highlighted(view), [(4, "https://last.example")])
        self.key(view, Gdk.KEY_Up)
        self.assertEqual(len(self.highlighted(view)), 1)  # the second copy alone

    def test_find_highlight_stops_at_the_ends_and_pages_and_jumps(self):
        view = self.make()
        view.show([(object(), INFO, NO_EMPTY_STATE)])
        order = self.listed_tabs(view)
        view.find_btn.clicked()
        self.key(view, Gdk.KEY_Up)  # from nothing: the last tab
        self.assertEqual(self.highlighted(view), [order[-1]])
        self.key(view, Gdk.KEY_Down)
        self.assertEqual(self.highlighted(view), [order[-1]])  # no wrapping
        self.key(view, Gdk.KEY_Page_Up)
        self.assertEqual(self.highlighted(view), [order[0]])
        self.key(view, Gdk.KEY_Up)
        self.assertEqual(self.highlighted(view), [order[0]])
        self.key(view, Gdk.KEY_Page_Down)
        self.assertEqual(self.highlighted(view), [order[-1]])
        self.key(view, Gdk.KEY_Home)
        self.assertEqual(self.highlighted(view), [order[0]])
        self.key(view, Gdk.KEY_End)
        self.assertEqual(self.highlighted(view), [order[-1]])

    def test_find_highlight_survives_typing_while_the_tab_still_matches(self):
        view = self.make()
        view.show([(object(), INFO, DRAG_STATE)])
        view.find_btn.clicked()
        self.key(view, Gdk.KEY_Down)
        self.key(view, Gdk.KEY_Down)  # "p2", tab 3 (the tabs of the Personal container come last)
        view._dialog_entry.set_text("p")  # p1, p2, p3 match
        self.assertEqual(self.highlighted(view), [3])
        view._dialog_entry.set_text("mail")  # the highlighted tab is not listed any more
        self.assertEqual(self.highlighted(view), [])
        self.key(view, Gdk.KEY_Down)  # so the arrows start from nothing again
        self.assertEqual(self.highlighted(view), [2])

    def test_find_enter_picks_the_first_match_when_the_highlighted_tab_is_gone(self):
        view = self.make()
        conn = object()
        view.show([(conn, INFO, DRAG_STATE)])
        view.find_btn.clicked()
        self.key(view, Gdk.KEY_Down)
        self.key(view, Gdk.KEY_Down)  # "p2", tab 3
        view._dialog_entry.set_text("mail")
        view._dialog_entry.emit("activate")
        self.assertEqual(self.activated, [(conn, 2, 2)])

    def test_find_leaves_other_keys_alone_and_keeps_the_arrows_from_moving_the_focus(self):
        view = self.make()
        view.show([(object(), INFO, STATE)])
        view.find_btn.clicked()
        self.assertFalse(self.key(view, Gdk.KEY_a))
        self.assertEqual(self.highlighted(view), [])
        view._dialog_entry.set_text("nothing like this")
        self.assertTrue(self.key(view, Gdk.KEY_Down))  # taken, or GTK moves the focus off the entry to a button
        self.assertTrue(self.key(view, Gdk.KEY_Page_Up))
        self.assertFalse(self.key(view, Gdk.KEY_Home))  # nothing to walk: the caret's again
        self.assertEqual(self.highlighted(view), [])
        self.assertIsNone(view._selected)

    def test_find_keys_work_with_super_still_down_from_the_hotkey_and_on_the_keypad(self):
        view = self.make()
        conn = object()
        view.show([(conn, INFO, NO_EMPTY_STATE)])
        order = self.listed_tabs(view)
        super_ = Gdk.ModifierType.SUPER_MASK
        view.find_btn.clicked()
        self.assertTrue(self.key(view, Gdk.KEY_Down, super_))
        self.assertEqual(self.highlighted(view), [order[0]])
        self.key(view, Gdk.KEY_KP_Down)
        self.assertEqual(self.highlighted(view), [order[1]])
        self.key(view, Gdk.KEY_KP_End)
        self.assertEqual(self.highlighted(view), [order[-1]])
        self.key(view, Gdk.KEY_Home, super_)
        self.assertEqual(self.highlighted(view), [order[0]])
        self.key(view, Gdk.KEY_End, super_)
        self.assertEqual(self.highlighted(view), [order[-1]])
        self.assertTrue(self.key(view, Gdk.KEY_Return, super_))  # the entry's own Enter needs every modifier up
        self.assertEqual(self.activated, [(conn, order[-1], 2)])
        self.assertIsNone(view._dialog)

    def test_find_home_and_end_with_shift_or_control_are_the_carets(self):
        view = self.make()
        view.show([(object(), INFO, DRAG_STATE)])
        view.find_btn.clicked()
        self.assertFalse(self.key(view, Gdk.KEY_Home, Gdk.ModifierType.SHIFT_MASK))  # selects text in the entry
        self.assertFalse(self.key(view, Gdk.KEY_End, Gdk.ModifierType.CONTROL_MASK))
        self.assertEqual(self.highlighted(view), [])

    def on_workspace(self, ws_id):
        window = self.WS_STATE["windows"][0]
        return {**self.WS_STATE, "windows": [{**window, "workspaceId": ws_id}]}

    def test_find_ctrl_left_and_right_switch_workspace_while_nothing_is_typed_and_stop_at_the_ends(self):
        view = self.make()
        conn = object()
        view.show([(conn, INFO, self.WS_STATE)])  # default, Work (shown), Play
        view.find_btn.clicked()
        self.key(view, Gdk.KEY_Down)
        self.assertEqual(len(self.highlighted(view)), 1)
        self.assertTrue(self.key(view, Gdk.KEY_Right, Gdk.ModifierType.CONTROL_MASK))
        self.assertEqual(self.commands, [{"type": "switch_workspace", "windowId": 2, "workspaceId": "ws-2"}])
        self.assertEqual(self.command_conns, [conn])
        self.assertEqual(self.highlighted(view), [])  # the tabs listed are about to change
        view.show([(conn, INFO, self.on_workspace("ws-2"))])  # the browser has switched
        self.assertTrue(self.key(view, Gdk.KEY_KP_Right, Gdk.ModifierType.CONTROL_MASK))  # the last one: nowhere to go
        self.assertEqual(len(self.commands), 1)
        self.assertTrue(self.key(view, Gdk.KEY_Left, Gdk.ModifierType.CONTROL_MASK))
        self.assertEqual(self.commands[-1], {"type": "switch_workspace", "windowId": 2, "workspaceId": "ws-1"})
        view.show([(conn, INFO, self.on_workspace("default"))])
        self.key(view, Gdk.KEY_Left, Gdk.ModifierType.CONTROL_MASK)  # the first one
        self.assertEqual(len(self.commands), 2)

    def test_find_keys_pressed_before_the_browser_reports_the_switch_count_from_the_one_asked_for(self):
        view = self.make()
        view.show([(object(), INFO, self.WS_STATE)])  # default, Work (shown), Play
        view.find_btn.clicked()
        for keyval in (Gdk.KEY_Right, Gdk.KEY_Right, Gdk.KEY_Left):  # ...or a held key repeating
            self.key(view, keyval, Gdk.ModifierType.CONTROL_MASK)
        self.assertEqual([m["workspaceId"] for m in self.commands], ["ws-2", "ws-1"])  # no second, useless ws-2

    def test_find_blanks_alone_are_nothing_typed_so_left_and_right_still_switch_workspace(self):
        view = self.make()
        view.show([(object(), INFO, self.WS_STATE)])
        view.find_btn.clicked()
        view._dialog_entry.set_text("  ")
        self.assertTrue(self.key(view, Gdk.KEY_Right, Gdk.ModifierType.CONTROL_MASK))
        self.assertEqual(len(self.commands), 1)

    def test_find_ctrl_left_and_right_are_the_carets_once_something_is_typed(self):
        view = self.make()
        view.show([(object(), INFO, self.WS_STATE)])
        view.find_btn.clicked()
        view._dialog_entry.set_text("home")
        self.assertFalse(self.key(view, Gdk.KEY_Right, Gdk.ModifierType.CONTROL_MASK))
        self.assertFalse(self.key(view, Gdk.KEY_Left, Gdk.ModifierType.CONTROL_MASK))
        self.assertEqual(self.commands, [])
        view._dialog_entry.set_text("")  # emptied again: they switch workspace again
        self.assertTrue(self.key(view, Gdk.KEY_Right, Gdk.ModifierType.CONTROL_MASK))
        self.assertEqual(len(self.commands), 1)

    RESTORING = {**INFO, "features": [*INFO["features"], "restore_tab"]}

    def without(self, state, tab_id):
        window = state["windows"][0]
        return {**state, "windows": [{**window, "tabs": [t for t in window["tabs"] if t["id"] != tab_id]}]}

    def listed(self, view):
        return [(view._meta[b]["kind"], view._meta[b]["id"]) for b in view._row_order
                if view._meta[b]["kind"] in ("tab", "ghost")]

    def undo_of(self, view):
        row = next(b for b, m in view._meta.items() if m["kind"] == "ghost")
        return row, next(c for c in row.get_child().get_children() if isinstance(c, Gtk.Button))

    def test_a_tab_closed_from_the_panel_leaves_its_row_in_place_as_an_undo(self):
        view = self.make()
        conn = object()
        view.show([(conn, self.RESTORING, DRAG_STATE)])
        self.assertEqual(self.listed(view), [("tab", 1), ("tab", 3), ("tab", 4), ("tab", 2)])
        self.close_button(view, 3).clicked()
        self.assertEqual(self.commands, [{"type": "close_tab", "tabId": 3}])
        self.assertEqual(self.listed(view), [("tab", 1), ("tab", 3), ("tab", 4), ("tab", 2)])  # not reported yet: no twin
        view.show([(conn, self.RESTORING, self.without(DRAG_STATE, 3))])
        self.assertEqual(self.listed(view), [("tab", 1), ("ghost", 3), ("tab", 4), ("tab", 2)])  # where it was
        row, undo = self.undo_of(view)
        self.assertEqual(label_of(row).get_text(), "p2")
        self.assertIn("<s>", label_of(row).get_label())  # struck through
        self.assertEqual(undo.get_label(), "↶")
        self.assertFalse(view._meta[row]["draggable"])
        self.assertFalse(view._meta[row]["closable"])

    def test_the_undo_row_of_the_only_tab_of_a_container_sits_in_that_container(self):
        view = self.make()
        conn = object()
        view.show([(conn, self.RESTORING, DRAG_STATE)])
        self.close_button(view, 2).clicked()  # "mail", alone in Personal
        view.show([(conn, self.RESTORING, self.without(DRAG_STATE, 2))])
        self.assertEqual(self.listed(view), [("tab", 1), ("tab", 3), ("tab", 4), ("ghost", 2)])

    def test_the_undo_reopens_the_tab_but_not_at_once_after_the_close(self):
        view = self.make()
        conn = object()
        view.show([(conn, self.RESTORING, DRAG_STATE)])
        self.close_button(view, 3).clicked()
        view.show([(conn, self.RESTORING, self.without(DRAG_STATE, 3))])
        row, undo = self.undo_of(view)
        undo.clicked()  # a double click on the ✕ lands here
        self.assertEqual(self.restored, [])
        self.assertEqual(self.listed(view)[1], ("ghost", 3))
        view._ghost["t"] -= 1
        undo.clicked()
        self.assertEqual(self.restored, [conn])
        self.assertEqual(self.raised, [conn])

    def test_after_the_click_the_row_stays_without_its_arrow_until_the_tab_is_listed_again(self):
        view = self.make()
        conn = object()
        view.show([(conn, self.RESTORING, DRAG_STATE)])
        self.close_button(view, 3).clicked()
        closed = self.without(DRAG_STATE, 3)
        view.show([(conn, self.RESTORING, closed)])
        view._ghost["t"] -= 1
        click(self.undo_of(view)[0])  # a click on the row itself
        self.assertEqual(self.restored, [conn])
        self.assertEqual(self.listed(view), [("tab", 1), ("ghost", 3), ("tab", 4), ("tab", 2)])  # nothing moves up
        row = next(b for b, m in view._meta.items() if m["kind"] == "ghost")
        self.assertEqual([c for c in row.get_child().get_children() if isinstance(c, Gtk.Button)], [])
        click(row)  # a second click: the tab is on its way already
        self.assertEqual(self.restored, [conn])
        window = closed["windows"][0]
        back = {"id": 99, "index": 2, "title": "p2", "cookieStoreId": "firefox-default"}  # it comes back as a new tab
        view.show([(conn, self.RESTORING, {**closed, "windows": [{**window, "tabs": [*window["tabs"], back]}]})])
        self.assertNotIn("ghost", [kind for kind, _id in self.listed(view)])
        self.assertIsNone(view._ghost)

    def test_the_undo_row_goes_when_another_tab_closes_meanwhile(self):
        view = self.make()
        conn = object()
        view.show([(conn, self.RESTORING, DRAG_STATE)])
        self.close_button(view, 3).clicked()
        closed = self.without(DRAG_STATE, 3)
        view.show([(conn, self.RESTORING, closed)])
        self.assertIn(("ghost", 3), self.listed(view))
        view.show([(conn, self.RESTORING, self.without(closed, 4))])  # closed in the browser: the tab closed last is 4
        self.assertNotIn("ghost", [kind for kind, _id in self.listed(view)])
        self.assertIsNone(view._ghost)

    def test_the_undo_row_shows_only_in_the_workspace_it_was_closed_in(self):
        view = self.make()
        conn = object()
        view.show([(conn, self.RESTORING, self.WS_STATE)])  # the window shows Work
        self.close_button(view, 2).clicked()
        closed = self.without(self.WS_STATE, 2)
        elsewhere = {**closed, "windows": [{**closed["windows"][0], "workspaceId": "default"}]}
        view.show([(conn, self.RESTORING, closed)])
        self.assertIn(("ghost", 2), self.listed(view))
        view.show([(conn, self.RESTORING, elsewhere)])
        self.assertNotIn("ghost", [kind for kind, _id in self.listed(view)])
        view.show([(conn, self.RESTORING, closed)])  # back in Work: still there
        self.assertIn(("ghost", 2), self.listed(view))

    def test_closing_another_tab_moves_the_undo_to_it(self):
        view = self.make()
        conn = object()
        view.show([(conn, self.RESTORING, DRAG_STATE)])
        self.close_button(view, 3).clicked()
        state = self.without(DRAG_STATE, 3)
        view.show([(conn, self.RESTORING, state)])
        self.close_button(view, 4).clicked()  # the tab closed last is 4 now, and that is what would come back
        self.assertEqual(view._ghost["id"], 4)
        view.show([(conn, self.RESTORING, self.without(state, 4))])
        self.assertEqual(self.listed(view), [("tab", 1), ("ghost", 4), ("tab", 2)])

    def test_the_undo_row_goes_when_its_time_is_up(self):
        view = self.make()
        conn = object()
        view.show([(conn, self.RESTORING, DRAG_STATE)])
        with mock.patch("tabdock.dock._schedule") as schedule:
            self.close_button(view, 3).clicked()
        self.assertEqual((schedule.call_args.args[0], schedule.call_args.args[1]), (8000, view._drop_ghost))
        view.show([(conn, self.RESTORING, self.without(DRAG_STATE, 3))])
        self.assertIn(("ghost", 3), self.listed(view))
        view._drop_ghost()
        self.assertEqual(self.listed(view), [("tab", 1), ("tab", 4), ("tab", 2)])
        self.assertEqual(self.commands, [{"type": "close_tab", "tabId": 3}])
        self.assertEqual(self.restored, [])  # nothing was restored

    def test_the_browser_going_away_takes_the_undo_row_and_its_timer_with_it(self):
        view = self.make()
        view.show([(object(), self.RESTORING, DRAG_STATE)])
        self.close_button(view, 3).clicked()
        view.clear()
        self.assertIsNone(view._ghost)
        self.assertIsNone(view._ghost_timer)

    def test_no_undo_row_when_the_extension_cannot_restore_or_while_finding(self):
        view = self.make()
        conn = object()
        view.show([(conn, INFO, DRAG_STATE)])  # an extension from before it
        self.close_button(view, 3).clicked()
        view.show([(conn, INFO, self.without(DRAG_STATE, 3))])
        self.assertNotIn("ghost", [kind for kind, _id in self.listed(view)])
        view.show([(conn, self.RESTORING, DRAG_STATE)])
        view.find_btn.clicked()
        view._dialog_entry.set_text("p")
        self.close_button(view, 3).clicked()  # closed from the search results
        self.assertIsNone(view._ghost)

    def test_ctrl_shift_t_in_the_find_window_reopens_the_tab_and_closes_the_window(self):
        view = self.make()
        conn = object()
        view.show([(conn, self.RESTORING, STATE)])
        view.find_btn.clicked()
        ctrl_shift = Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK
        self.assertTrue(self.key(view, Gdk.KEY_T, ctrl_shift | Gdk.ModifierType.SUPER_MASK))  # Super still down
        self.assertEqual(self.restored, [conn])
        self.assertEqual(self.raised, [conn])  # from a terminal, the tab must not come back behind it
        self.assertIsNone(view._dialog)
        self.assertEqual(self.activated, [])
        view.find_btn.clicked()
        self.key(view, Gdk.KEY_t, ctrl_shift)
        self.assertEqual(self.restored, [conn, conn])

    def test_ctrl_shift_t_takes_the_undo_row_away_as_the_tab_comes_back_under_a_new_id(self):
        view = self.make()
        conn = object()
        view.show([(conn, self.RESTORING, DRAG_STATE)])
        self.close_button(view, 3).clicked()
        view.show([(conn, self.RESTORING, self.without(DRAG_STATE, 3))])
        view.find_btn.clicked()
        self.key(view, Gdk.KEY_T, Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK)
        self.assertEqual(self.restored, [conn])
        self.assertIsNone(view._ghost)
        self.assertNotIn("ghost", [kind for kind, _id in self.listed(view)])

    def test_the_find_window_ignores_t_without_ctrl_and_shift_and_when_the_browser_cannot_restore(self):
        view = self.make()
        view.show([(object(), self.RESTORING, STATE)])
        view.find_btn.clicked()
        self.assertFalse(self.key(view, Gdk.KEY_t))  # plain typing
        self.assertTrue(self.key(view, Gdk.KEY_t, Gdk.ModifierType.CONTROL_MASK))  # new tab in a row: nothing highlighted
        self.assertEqual(self.restored, [])
        self.assertIsNotNone(view._dialog)
        view.show([(object(), INFO, STATE)])  # an extension from before it
        self.assertTrue(self.key(view, Gdk.KEY_T, Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK))
        self.assertEqual(self.restored, [])
        self.assertIsNotNone(view._dialog)  # the window stays: nothing came back

    def test_find_left_and_right_switch_view_and_stop_at_the_ends(self):
        view = self.make(bookmarks=True, history=True)
        info = {**INFO, "features": [*INFO["features"], "bookmarks", "history"]}
        view.show([(object(), info, STATE)])
        view.find_btn.clicked()
        self.assertTrue(self.key(view, Gdk.KEY_Left))  # taken, but nothing before Tabs
        self.assertEqual(view._view, "tabs")
        self.key(view, Gdk.KEY_Right)
        self.assertEqual(view._view, "bookmarks")
        self.key(view, Gdk.KEY_KP_Right)
        self.assertEqual(view._view, "history")
        self.key(view, Gdk.KEY_Right)
        self.assertEqual(view._view, "history")
        self.key(view, Gdk.KEY_Left)
        self.assertEqual(view._view, "bookmarks")
        self.assertEqual(self.commands[-1]["type"], "get_bookmarks")
        self.assertFalse(self.key(view, Gdk.KEY_Right, Gdk.ModifierType.SHIFT_MASK))  # a chord: the caret's
        view._dialog_entry.set_text("py")
        self.assertFalse(self.key(view, Gdk.KEY_Right))  # something typed: the caret's
        self.assertEqual(view._view, "bookmarks")

    def test_find_ctrl_left_and_right_leave_the_workspace_alone_outside_the_tabs(self):
        view = self.make(bookmarks=True)
        info = {**INFO, "features": [*INFO["features"], "bookmarks"]}
        view.show([(object(), info, self.WS_STATE)])
        view.find_btn.clicked()
        self.key(view, Gdk.KEY_Right)  # Bookmarks
        self.commands.clear()
        self.assertTrue(self.key(view, Gdk.KEY_Right, Gdk.ModifierType.CONTROL_MASK))
        self.assertEqual(self.commands, [])

    def test_find_left_and_right_skip_views_that_are_off(self):
        view = self.make(history=True)
        view.show([(object(), {**INFO, "features": [*INFO["features"], "history"]}, STATE)])
        view.find_btn.clicked()
        self.key(view, Gdk.KEY_Right)
        self.assertEqual(view._view, "history")  # no bookmarks between

    def test_find_ctrl_left_and_right_do_nothing_where_the_panel_shows_no_workspaces(self):
        view = self.make()
        view.show([(object(), INFO, STATE)])  # an extension without workspaces
        view.find_btn.clicked()
        self.assertTrue(self.key(view, Gdk.KEY_Right, Gdk.ModifierType.CONTROL_MASK))  # taken all the same: nothing typed to move through
        view.show([(object(), {**INFO, "browser": "Zen"}, self.WS_STATE)])  # Zen has workspaces of its own
        self.key(view, Gdk.KEY_Right, Gdk.ModifierType.CONTROL_MASK)
        self.assertEqual(self.commands, [])

    def test_find_ctrl_left_and_right_switch_the_workspace_of_the_browser_in_use_among_several(self):
        view = self.make()
        first, second = object(), object()
        other = {**INFO, "browserPid": 2}
        view.show([(first, INFO, self.WS_STATE), (second, other, self.WS_STATE)], "all", (), other)
        view.find_btn.clicked()
        self.key(view, Gdk.KEY_Right, Gdk.ModifierType.CONTROL_MASK)
        self.assertEqual(self.command_conns, [second])

    def test_a_closed_window_leaves_nothing_of_itself_behind(self):
        view = self.make()
        view.show([(object(), INFO, STATE)])
        view.find_btn.clicked()
        view.find()  # closes it
        self.assertIsNone(view._dialog)
        self.assertIsNone(view._dialog_finish)
        self.assertIsNone(view._find_dialog)

    def test_another_window_replacing_the_find_window_cancels_it(self):
        view = self.make()
        view.show([(object(), INFO, DRAG_STATE)])
        order = self.listed_tabs(view)
        view.find_btn.clicked()
        view._dialog_entry.set_text("p")
        self.key(view, Gdk.KEY_Down)
        self.assertEqual(self.highlighted(view), [order[0]])
        view._ask_name("Rename", "x", lambda name: None)
        self.assertEqual(view._dialog.get_title(), "Rename")
        self.assertEqual(self.highlighted(view), [])
        self.assertEqual(self.listed_tabs(view), order)  # not filtered by what was typed
        self.assertTrue(view.autohide.held)  # the panel stays open for the window that replaced it
        self.assertEqual(self.activated, [])
        view.find()  # the hotkey opens the find window again, not "closes" the rename window
        self.assertEqual(view._dialog.get_title(), "Find")

    def test_the_find_button_again_starts_a_fresh_find(self):
        view = self.make()
        conn = object()
        view.show([(conn, INFO, DRAG_STATE)])
        order = self.listed_tabs(view)
        view.find_btn.clicked()
        view._dialog_entry.set_text("mail")
        self.key(view, Gdk.KEY_Down)
        view.find_btn.clicked()
        self.assertEqual(view._dialog_entry.get_text(), "")
        self.assertEqual(self.listed_tabs(view), order)
        view._dialog_entry.emit("activate")  # nothing typed: the tab highlighted before is not opened
        self.assertEqual(self.activated, [])

    def test_find_from_the_hotkey_shows_a_hidden_panel_and_the_same_key_closes_it(self):
        view = self.make()
        view.show([(object(), INFO, STATE)])
        view.set_hidden(True)
        view.find()
        self.assertFalse(view.hidden)
        self.assertEqual(view._dialog.get_title(), "Find")
        self.assertTrue(view.autohide.held)  # the panel opens and stays for it
        view.find()
        self.assertIsNone(view._dialog)
        self.assertFalse(view.autohide.held)
        self.assertEqual(self.activated, [])

    def test_find_window_sits_beside_the_panel_even_while_it_is_unmapped(self):
        view = self.make(side="left")
        moved = []
        with mock.patch.object(Gtk.Window, "move", lambda w, x, y: moved.append((w, x, y))):
            view.find()
        px, py, pw, _ph = geometry.dock_rect(view._monitor_rect(), "left", view.cfg["width"], True)
        self.assertEqual([(x, y) for w, x, y in moved if w is view._dialog], [(px + pw + 8, py + 30)])

    GROUP_STATE = {**STATE, "groups": [{"id": 7, "title": "Trip & co", "color": "blue", "collapsed": False}],
                   "windows": [{"id": 2, "tabs": [{**STATE["windows"][0]["tabs"][0], "groupId": 7, "active": False},
                                                  STATE["windows"][0]["tabs"][1]]}]}

    def test_a_firefox_tab_group_gets_a_pill_above_its_tabs(self):
        view = self.make()
        view.show([(object(), INFO, self.GROUP_STATE)])
        pill = self.row(view, "tabgroup", "group:7:firefox-default")
        label = pill.get_child().get_children()[0]
        self.assertIn("Trip &amp; co", label.get_label())
        self.assertIn("(1)", label.get_label())
        self.assertTrue(label.get_style_context().has_class("gc-blue"))
        order = [view._meta[b]["id"] for b in view._row_order]
        self.assertLess(order.index("group:7:firefox-default"), order.index(10))  # above its tab
        self.assertTrue(self.row(view, "tab", 10).get_child().get_style_context().has_class("sp-ingroup"))
        self.assertFalse(self.row(view, "tab", 11).get_child().get_style_context().has_class("sp-ingroup"))
        tags = [c for c in self.row(view, "tab", 10).get_child().get_children() if c.get_style_context().has_class("sp-group")]
        self.assertEqual(tags, [])  # the pill says it

    def test_a_click_on_the_pill_folds_its_tabs(self):
        view = self.make()
        view.show([(object(), INFO, self.GROUP_STATE)])
        view._meta[self.row(view, "tabgroup", "group:7:firefox-default")]["click"]()
        self.assertEqual(self.listed_tabs(view), [11])
        self.assertIn("▸", self.row(view, "tabgroup", "group:7:firefox-default").get_child().get_children()[0].get_label())
        view._meta[self.row(view, "tabgroup", "group:7:firefox-default")]["click"]()
        self.assertEqual(sorted(self.listed_tabs(view)), [10, 11])

    def test_a_group_firefox_has_collapsed_starts_folded(self):
        view = self.make()
        state = {**self.GROUP_STATE, "groups": [{"id": 7, "title": "Trip", "color": "blue", "collapsed": True}]}
        view.show([(object(), INFO, state)])
        self.assertEqual(self.listed_tabs(view), [11])

    def test_a_folded_group_keeps_its_active_tab_listed(self):
        view = self.make()
        tabs = [{**t, "active": t["id"] == 10} for t in self.GROUP_STATE["windows"][0]["tabs"]]
        view.show([(object(), INFO, {**self.GROUP_STATE, "windows": [{"id": 2, "tabs": tabs}],
                                     "groups": [{"id": 7, "title": "Trip", "color": "blue", "collapsed": True}]})])
        self.assertEqual(sorted(self.listed_tabs(view)), [10, 11])

    def test_a_group_in_two_containers_has_a_pill_with_its_own_id_in_each(self):
        view = self.make()
        tabs = [{**STATE["windows"][0]["tabs"][0], "groupId": 7, "active": False},
                {**STATE["windows"][0]["tabs"][1], "groupId": 7, "cookieStoreId": "firefox-container-1"}]
        state = {**STATE, "groups": [{"id": 7, "title": "Trip", "color": "blue", "collapsed": False}],
                 "windows": [{"id": 2, "tabs": tabs}]}
        view.show([(object(), INFO, state)])
        ids = [view._meta[b]["id"] for b in view._row_order if view._meta[b]["kind"] == "tabgroup"]
        self.assertEqual(len(ids), 2)
        self.assertEqual(len(set(ids)), 2)

    def test_a_find_lists_the_tab_with_its_group_name_and_no_pill(self):
        view = self.make()
        view.show([(object(), INFO, self.GROUP_STATE)])
        view.find_btn.clicked()
        view._dialog_entry.set_text("plain")
        with self.assertRaises(StopIteration):
            self.row(view, "tabgroup", "group:7:firefox-default")
        tag = next(c for c in self.row(view, "tab", 10).get_child().get_children() if c.get_style_context().has_class("sp-group"))
        self.assertEqual(tag.get_text(), "Trip & co")

    def test_enter_on_a_highlighted_pill_folds_it_in_find(self):
        view = self.make()
        view.show([(object(), INFO, self.GROUP_STATE)])
        view.find_btn.clicked()
        rows = [view._meta[b]["id"] for b in view._find_rows()]
        self.assertIn("group:7:firefox-default", rows)
        for _ in range(rows.index("group:7:firefox-default") + 1):
            self.key(view, Gdk.KEY_Down)
        self.assertEqual(self.highlighted(view), ["group:7:firefox-default"])
        view._dialog_entry.emit("activate")
        self.assertEqual(self.listed_tabs(view), [11])
        self.assertIsNotNone(view._dialog)  # the window stays

    def test_a_middle_click_closes_the_tab_it_was_released_on(self):
        view = self.make()
        view.show([(object(), INFO, DRAG_STATE)])
        middle = lambda widget, kind, signal: button(widget, kind, signal, which=2)  # noqa: E731
        row = self.row(view, "tab", 1)
        middle(row, Gdk.EventType.BUTTON_PRESS, "button-press-event")
        middle(row, Gdk.EventType.BUTTON_RELEASE, "button-release-event")
        self.assertEqual(self.commands, [{"type": "close_tab", "tabId": 1}])
        middle(row, Gdk.EventType.BUTTON_PRESS, "button-press-event")
        middle(self.row(view, "tab", 2), Gdk.EventType.BUTTON_RELEASE, "button-release-event")  # moved off it
        self.assertEqual(len(self.commands), 1)  # as in the browser: let go elsewhere and nothing closes
        self.assertEqual(self.activated, [])
        middle(self.row(view, "section", "firefox-default"), Gdk.EventType.BUTTON_PRESS, "button-press-event")
        middle(self.row(view, "section", "firefox-default"), Gdk.EventType.BUTTON_RELEASE, "button-release-event")
        self.assertEqual(len(self.commands), 1)  # only tabs close

    def test_right_click_on_a_tab_pins_or_unpins_and_closes_it(self):
        view = self.make()
        view.show([(object(), INFO, self.WS_STATE)])
        self.right_click(self.row(view, "tab", 2))
        labels = [item.get_label() for item in view._menu.get_children()]
        self.assertEqual([labels[0], labels[-1]], ["Pin tab", "Close tab"])  # pin first, close last, as Firefox
        self.assertEqual(sum(isinstance(i, Gtk.SeparatorMenuItem) for i in view._menu.get_children()), 2)
        self.menu_items(view)["Pin tab"].activate()
        self.right_click(self.row(view, "tab", 3))  # pinned
        self.menu_items(view)["Unpin tab"].activate()
        self.menu_items(view)["Close tab"].activate()
        self.assertEqual(self.commands, [
            {"type": "pin_tab", "tabId": 2, "pinned": True},
            {"type": "pin_tab", "tabId": 3, "pinned": False},
            {"type": "close_tab", "tabId": 3},
        ])

    def test_a_pinned_tab_wears_a_pin(self):
        view = self.make()
        pin = lambda tab_id: next((c for c in self.row(view, "tab", tab_id).get_child().get_children()  # noqa: E731
                                   if c.get_style_context().has_class("sp-pinmark")), None)
        view.show([(object(), INFO, self.WS_STATE)])
        self.assertEqual(pin(3).get_text(), "📌")
        self.assertEqual(pin(3).get_tooltip_text(), "Pinned: shows in every workspace")
        self.assertIsNone(pin(2))
        one = {**self.WS_STATE, "workspaces": [{"id": "default", "name": "Default"}]}
        view.show([(object(), INFO, one)])
        self.assertEqual(pin(3).get_tooltip_text(), "Pinned")
        self.assertEqual(label_of(self.row(view, "tab", 3).get_child()).get_text(), "music")  # the title stays the title

    def test_quitting_closes_the_name_window(self):
        view = self.make()
        view.show([(object(), INFO, self.WS_STATE)])
        self.ws_buttons(view)["+"].clicked()
        dialog = view._dialog
        view.win.destroy()
        self.assertIsNone(view._dialog)
        self.assertIsNone(dialog.get_window())  # destroyed with the panel

    # -- which monitor: fake layouts stand in for real hardware -------------------------------

    HDMI, DP = (0, 0, 2560, 1440), (2560, 180, 1920, 1080)
    YOURS = ([HDMI, DP], ["HDMI-1", "DP-1"], 0)  # primary HDMI-1 on the left
    MIRRORED = ([(0, 180, 1920, 1080), (1920, 0, 2560, 1440)], ["DP-1", "HDMI-1"], 1)  # primary on the right

    def with_layout(self, view, layout, **cfg):
        view._layout = lambda: layout
        view.cfg.update(cfg)
        return view._monitor_rect()

    def test_outer_follows_the_layout_whatever_its_shape(self):
        view = self.make()  # default: monitor = "outer"
        rects, _, _ = self.YOURS
        self.assertEqual(self.with_layout(view, self.YOURS, side="left"), rects[0])
        self.assertEqual(self.with_layout(view, self.YOURS, side="right"), rects[1])
        rects, _, _ = self.MIRRORED
        self.assertEqual(self.with_layout(view, self.MIRRORED, side="left"), rects[0])  # DP-1 now
        self.assertEqual(self.with_layout(view, self.MIRRORED, side="right"), rects[1])  # HDMI-1 now

    def test_primary_and_named_monitors_are_still_available(self):
        view = self.make()
        rects, _, _ = self.MIRRORED
        self.assertEqual(self.with_layout(view, self.MIRRORED, side="left", monitor="primary"), rects[1])
        self.assertEqual(self.with_layout(view, self.MIRRORED, side="right", monitor="DP-1"), rects[0])

    def test_unknown_monitor_warns_once_and_uses_the_outer_edge(self):
        rects, _, _ = self.MIRRORED
        with mock.patch("sys.stderr") as err:
            view = self.make(monitor="NOPE-9")  # building it already measures the monitors: one warning
            first = self.with_layout(view, self.MIRRORED, side="left")
            second = view._monitor_rect()
        self.assertEqual((first, second), (rects[0], rects[0]))
        warnings = [c for c in err.write.call_args_list if "NOPE-9" in str(c)]
        self.assertEqual(len(warnings), 1)

    def test_pin_says_so_when_the_edge_cannot_reserve_space(self):
        view = self.make(monitor="primary", pinned=True)
        view._layout = lambda: self.MIRRORED  # primary is HDMI-1 on the right: its left edge is inner
        view._place()
        self.assertEqual(view.pin_btn.get_label(), "pinned (overlay)")
        self.assertIn('"outer"', view.pin_btn.get_tooltip_text())  # and says what to do about it
        view.cfg["monitor"] = "outer"  # the panel moves to the real outer edge: it can reserve space
        view._place()
        self.assertEqual(view.pin_btn.get_label(), "pinned")
        view.set_pinned(False)
        self.assertEqual(view.pin_btn.get_label(), "pin")

    def test_a_layout_change_moves_the_panel(self):
        from tabdock import geometry

        view = self.make()
        view.cfg["side"] = "left"
        view._layout = lambda: self.YOURS
        view._relayout()
        self.assertEqual(view.strip.get_position(), geometry.dock_rect(self.HDMI, "left", view.cfg["width"], False)[:2])
        view._layout = lambda: self.MIRRORED  # monitors swapped (or another one plugged in)
        view._relayout()
        left = self.MIRRORED[0][0]
        self.assertEqual(view.strip.get_position(), geometry.dock_rect(left, "left", view.cfg["width"], False)[:2])

    def test_no_monitors_at_all_falls_back_to_the_whole_screen(self):
        view = self.make()
        with mock.patch.object(Gdk.Display, "get_n_monitors", return_value=0):  # mid-xrandr moment
            rects, names, primary = view._layout()
            view._relayout()  # must not raise inside a timer callback
        self.assertEqual((len(rects), names, primary), (1, [None], 0))
        self.assertEqual(rects[0][:2], (0, 0))
        self.assertGreater(rects[0][2], 0)

    def test_missing_monitor_warns_again_only_after_it_was_seen_again(self):
        dp_only = ([(0, 0, 1920, 1080)], ["HDMI-1"], 0)
        with mock.patch("sys.stderr") as err:
            view = self.make(monitor="DP-1")
            view._layout = lambda: dp_only  # DP-1 absent
            for _ in range(3):
                view._relayout()  # layout changes that do not bring it back are not news
            once = len([c for c in err.write.call_args_list if "DP-1" in str(c)])
            view._layout = lambda: self.MIRRORED  # DP-1 is back...
            view._relayout()
            view._layout = lambda: dp_only  # ...and gone again
            view._relayout()
            twice = len([c for c in err.write.call_args_list if "DP-1" in str(c)])
        self.assertEqual((once, twice), (1, 2))

    def test_closing_the_panel_stops_it_reacting_to_monitor_changes(self):
        view = self.make()
        view._on_monitors_changed()  # a re-place is pending...
        self.assertIsNotNone(view._relayout_id)
        view.win.destroy()  # ...and the panel window goes away
        self.assertIsNone(view._relayout_id)
        self.assertEqual(view._screen_handlers, [])
        moved = []
        view._place = lambda: moved.append(1)
        view._relayout()  # a late callback does nothing on a dead view
        self.assertEqual(moved, [])

    def test_a_burst_of_monitor_signals_re_places_once(self):
        from gi.repository import GLib

        view = self.make()
        view._on_monitors_changed()
        first = view._relayout_id
        view._on_monitors_changed()
        view._on_monitors_changed()
        self.assertIsNotNone(first)
        self.assertEqual(view._relayout_id, first)  # debounced: one pending re-place, not three
        GLib.source_remove(first)
        view._relayout_id = None


if __name__ == "__main__":
    unittest.main()
