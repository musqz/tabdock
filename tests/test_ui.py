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


def click(widget):
    event = Gdk.Event.new(Gdk.EventType.BUTTON_PRESS)
    event.button = 1
    widget.emit("button-press-event", event)


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
        view = DockView({**DEFAULTS, **cfg}, lambda *a: self.activated.append(a), lambda: self.quit_calls.append(1))
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
        view.show(object(), INFO, STATE)
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
        view.show(object(), {**INFO, "browser": "Zen"}, STATE)
        self.assertIn("#9d7cd8", view._css_data)
        view.clear()
        self.assertIn("#8f9bb3", view._css_data)
        self.assertEqual(view.browser_name.get_text(), "")

    def test_click_activates_tab_in_its_window(self):
        view = self.make()
        conn = object()
        view.show(conn, INFO, STATE)
        rows = [r for r in view.list.get_children() if isinstance(r, Gtk.EventBox) and r.get_child().get_text() == "mail"]
        click(rows[0])
        self.assertEqual(self.activated, [(conn, 11, 2)])

    def test_section_folds_and_unfolds(self):
        view = self.make()
        view.show(object(), INFO, STATE)
        click(view.list.get_children()[0])  # "No container" has a tab, so it is clickable
        self.assertEqual(len(view.list.get_children()), 4)
        click(view.list.get_children()[0])
        self.assertEqual(len(view.list.get_children()), 5)

    def test_identical_state_does_not_rebuild_or_restyle(self):
        view = self.make()
        conn = object()
        view.show(conn, INFO, STATE)
        rows = view.list.get_children()
        with mock.patch.object(view._css, "load_from_data") as reload_css:
            view.show(conn, INFO, {**STATE})  # equal content, new dict, as a fresh JSON message would be
        self.assertEqual(view.list.get_children(), rows)
        reload_css.assert_not_called()  # reloading the provider restyles the whole panel

    def test_folding_is_per_browser_process(self):
        view = self.make()
        view.show(object(), {**INFO, "browserPid": 1}, STATE)
        click(view.list.get_children()[0])  # fold "No container" in the first profile
        self.assertEqual(len(view.list.get_children()), 4)
        view.show(object(), {**INFO, "browserPid": 2}, STATE)  # another Firefox profile: not folded
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
        mon = view._monitor_rect()
        view.set_side("right")
        self.assertEqual(view.strip.get_position(), geometry.dock_rect(mon, "right", view.cfg["width"], False)[:2])
        self.assertEqual(view.win.get_position(), geometry.dock_rect(mon, "right", view.cfg["width"], True)[:2])

    def test_hide_and_unhide(self):
        view = self.make(pinned=True)
        view.set_hidden(True)
        self.assertEqual(self.shown, set())
        view.set_hidden(False)
        self.assertEqual(self.shown, {view.strip, view.win})  # pinned: panel comes back too

    def test_unknown_monitor_falls_back_to_primary(self):
        with mock.patch("sys.stderr"):
            view = self.make(monitor="NOPE-9")
            rect = view._monitor_rect()
        self.assertEqual(rect, self.make(monitor="primary")._monitor_rect())


if __name__ == "__main__":
    unittest.main()
