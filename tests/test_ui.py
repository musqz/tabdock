"""DockView smoke test. Window show/hide are recorded instead of executed, so nothing is ever
mapped on screen. Skipped when there is no X display."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

from sidepanel import geometry  # noqa: E402
from sidepanel.config import DEFAULTS  # noqa: E402

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
INFO = {"browser": "Firefox", "version": "156.0", "browserPid": 1}


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


@unittest.skipUnless(Gtk.init_check()[0], "no X display")
class DockViewTest(unittest.TestCase):
    def setUp(self):
        self.shown = set()
        for name, fn in (("show", self.shown.add), ("hide", self.shown.discard)):
            patcher = mock.patch.object(Gtk.Window, name, lambda w, fn=fn: fn(w))
            patcher.start()
            self.addCleanup(patcher.stop)

    def make(self, **cfg):
        from sidepanel.dock import DockView

        self.activated = []
        self.quit_calls = []
        self.commands = []
        self.command_conns = []
        self.chosen = []
        view = DockView(
            {**DEFAULTS, **cfg},
            lambda *a: self.activated.append(a),
            lambda: self.quit_calls.append(1),
            on_command=lambda conn, message: (self.commands.append(message), self.command_conns.append(conn)),
            on_choose=self.chosen.append,
        )
        self.addCleanup(view.win.destroy)
        self.addCleanup(view.strip.destroy)
        return view

    def row_texts(self, view):
        return [(r.get_child() if isinstance(r, Gtk.EventBox) else r).get_text() for r in view.list.get_children()]

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
        self.assertEqual(view.quit_btn.get_tooltip_text(), "Quit sidepanel")
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
        self.assertEqual([r.get_child().get_text() for r in active], ["plain"])

    def test_accent_follows_the_browser(self):
        view = self.make()
        view.show([(object(), {**INFO, "browser": "Zen"}, STATE)])
        self.assertIn("#9d7cd8", view._css_data)
        view.clear()
        self.assertIn("#8f9bb3", view._css_data)
        self.assertEqual(view.browser_name.get_text(), "")

    def test_click_activates_tab_in_its_window(self):
        view = self.make()
        conn = object()
        view.show([(conn, INFO, STATE)])
        rows = [r for r in view.list.get_children() if isinstance(r, Gtk.EventBox) and r.get_child().get_text() == "mail"]
        click(rows[0])
        self.assertEqual(self.activated, [(conn, 11, 2)])

    def test_section_folds_and_unfolds(self):
        view = self.make()
        view.show([(object(), INFO, STATE)])
        click(view.list.get_children()[0])  # "No container" has a tab, so it is clickable
        self.assertEqual(len(view.list.get_children()), 4)
        click(view.list.get_children()[0])
        self.assertEqual(len(view.list.get_children()), 5)

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

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"SIDEPANEL_LAYOUT_DUMP": tmp + "/rows.json"}):
            view = self.make()  # the hook is read once, when the panel starts
            view.show([(object(), INFO, DRAG_STATE)])
            view._dump_layout()
            with open(tmp + "/rows.json") as f:
                rows = json.load(f)
        self.assertEqual([(r["kind"], r["id"]) for r in rows if r["kind"] == "section"],
                         [("section", "firefox-default"), ("section", "firefox-container-1"), ("section", "firefox-container-2")])
        self.assertEqual({r["id"] for r in rows if r["kind"] == "tab"}, {1, 2, 3, 4})
        self.assertTrue(all({"x", "y", "w", "h", "group"} <= r.keys() for r in rows))

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
        from sidepanel import geometry

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
