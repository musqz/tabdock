import itertools
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from tabdock import wl  # noqa: E402


class FakeHandle:
    def __init__(self):
        self.dispatcher = {}
        self.activated_for = []
        self.destroyed = False

    def activate(self, seat):
        self.activated_for.append(seat)

    def destroy(self):
        self.destroyed = True

    def send(self, app_id=None, active=None):
        if app_id is not None:
            self.dispatcher["app_id"](self, app_id)
        if active is not None:
            self.dispatcher["state"](self, [wl.ACTIVATED] if active else [])
        self.dispatcher["done"](self)


class FakeDisplay:
    def flush(self):
        pass


class WlConnTest(unittest.TestCase):
    def setUp(self):
        self.conn = wl.WlConn.__new__(wl.WlConn)
        self.conn.display = FakeDisplay()
        self.conn.seat = "seat"
        self.conn._windows = {}
        self.conn._ids = itertools.count(1)
        self.conn._callback = None
        self.conn._last_active = None
        self.conn._settle_id = None
        self.reported = []

    def window(self, app_id, active=False):
        handle = FakeHandle()
        self.conn._on_toplevel(None, handle)
        handle.send(app_id, active)
        return handle

    def test_window_info_tells_a_browser_by_its_app_id(self):
        self.window("firefox")
        self.window("org.mozilla.firefox")
        self.assertEqual(self.conn.window_info(1), (None, ("firefox", "firefox")))
        self.assertEqual(self.conn.window_info(2), (None, ("org.mozilla.firefox", "firefox")))
        self.assertEqual(self.conn.window_info(99), (None, ()))

    def test_the_active_window_is_the_one_last_activated(self):
        self.window("a", active=True)
        b = self.window("b")
        self.assertEqual(self.conn.active_window(), 1)
        b.send(active=True)
        self.assertEqual(self.conn.active_window(), 2)  # two flagged: the later one wins
        self.assertEqual(self.conn.client_windows(), [1, 2])

    def test_a_switch_is_reported_only_where_it_ends(self):
        a = self.window("a", active=True)
        b = self.window("b")
        self.conn._last_active = self.conn.active_window()
        self.conn._callback = self.reported.append
        a.send(active=False)  # nothing active for a moment
        b.send(active=True)
        self.conn._settle()
        self.assertEqual(self.reported, [2])

    def test_closed_windows_are_forgotten(self):
        self.window("tabdock")
        b = self.window("firefox", active=True)
        b.dispatcher["closed"](b)
        self.assertTrue(b.destroyed)
        self.assertEqual(self.conn.client_windows(), [1])
        self.assertIsNone(self.conn.active_window())

    def test_the_manager_finishing_is_a_lost_compositor(self):
        lost = []
        self.conn._on_lost = lambda: lost.append(1)
        self.conn._on_finished(None)
        self.assertEqual(lost, [1])

    def test_activate_asks_the_compositor_with_the_seat(self):
        a = self.window("a")
        self.conn.activate(1)
        self.assertEqual(a.activated_for, ["seat"])
        self.conn.activate(42)  # gone: nothing happens


if __name__ == "__main__":
    unittest.main()
