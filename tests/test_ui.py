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
