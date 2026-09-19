"""GTK tree view smoke test. Widgets are built but never mapped (show_all is patched out),
so nothing appears on screen. Skipped when there is no X display."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from sidepanel.ui import TreeView  # noqa: E402

STATE = {
    "focusedWindowId": 2,
    "containers": [{"cookieStoreId": "firefox-container-1", "name": "Personal"}],
    "windows": [
        {
            "id": 2,
            "tabs": [
                {"id": 10, "title": "plain", "cookieStoreId": "firefox-default", "active": True},
                {"id": 11, "title": "mail", "cookieStoreId": "firefox-container-1", "active": False},
            ],
        }
    ],
}


@unittest.skipUnless(Gtk.init_check()[0], "no X display")
class TreeViewTest(unittest.TestCase):
    def setUp(self):
        self.activated = []
        with mock.patch.object(Gtk.Widget, "show_all", lambda self: None):
            self.view = TreeView(lambda *args: self.activated.append(args), lambda: None)
        self.conn = object()
        self.view.show(self.conn, {"browser": "Firefox", "version": "156.0"}, STATE)

    def test_tree_contents(self):
        rows = [(r[0], [c[0] for c in r.iterchildren()]) for r in self.view.store]
        self.assertEqual(
            rows,
            [("No container (1)", ["● plain"]), ("Personal (1)", ["   mail"])],
        )
        self.assertEqual(self.view.win.get_title(), "Firefox 156.0")

    def test_row_activation_sends_tab_and_window(self):
        self.view._row_activated(self.view.view, Gtk.TreePath.new_from_string("1:0"), None)
        self.assertEqual(self.activated, [(self.conn, 11, 2)])

    def test_header_row_does_nothing(self):
        self.view._row_activated(self.view.view, Gtk.TreePath.new_from_string("1"), None)
        self.assertEqual(self.activated, [])


if __name__ == "__main__":
    unittest.main()
