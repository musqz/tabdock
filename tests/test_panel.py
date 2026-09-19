"""Panel routing (which browser is shown, follow modes, actions) with fake view/X/connections."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from sidepanel.app import Panel  # noqa: E402

FIREFOX_XID, ZEN_XID, TERM_XID, PANEL_XID, LIBRE_XID = 101, 102, 103, 104, 105


class FakeConn:
    def __init__(self):
        self.sent = []

    def send(self, msg):
        self.sent.append(msg)


class FakeView:
    xids = {PANEL_XID}

    def __init__(self):
        self.calls = []

    def show(self, conn, info, state):
        self.calls.append(("show", info["browser"]))

    def clear(self):
        self.calls.append(("clear",))

    def set_hidden(self, hidden):
        self.calls.append(("hidden", hidden))

    def reconfigure(self, cfg):
        self.calls.append(("reconfigure",))


class FakeX:
    """window_info by xid; pids are made up so matching goes through the class fallback."""

    WINDOWS = {
        FIREFOX_XID: (None, ("Navigator", "firefox")),
        ZEN_XID: (None, ("zen", "zen")),
        TERM_XID: (None, ("xterm", "XTerm")),
        LIBRE_XID: (None, ("librewolf", "LibreWolf")),
    }

    def __init__(self):
        self.activated = []

    def window_info(self, xid):
        return self.WINDOWS[xid]

    def activate(self, xid):
        self.activated.append(xid)


def state(*tabs):
    return {"type": "state", "focusedWindowId": 1, "containers": [], "windows": [{"id": 1, "tabs": list(tabs)}]}


TAB = {"id": 7, "title": "t", "cookieStoreId": "firefox-default", "active": True}


class PanelTest(unittest.TestCase):
    def setUp(self):
        self.x = FakeX()
        self.view = FakeView()
        self.panel = Panel({"follow": "last"}, self.x)
        self.panel.view = self.view
        self.ff, self.zen = FakeConn(), FakeConn()
        self.panel.on_message(self.ff, {"type": "hello", "browser": "Firefox"})
        self.panel.on_message(self.ff, state(TAB))
        self.panel.on_message(self.zen, {"type": "hello", "browser": "Zen"})
        self.panel.on_message(self.zen, state(TAB))
        self.view.calls.clear()

    def shown(self):
        return [c[1] for c in self.view.calls if c[0] == "show"]

    def test_first_browser_is_shown_and_updates_only_for_current(self):
        self.panel.on_message(self.zen, state())  # not the current browser: no redraw
        self.assertEqual(self.shown(), [])
        self.panel.on_message(self.ff, state(TAB))
        self.assertEqual(self.shown(), ["Firefox"])

    def test_follows_the_active_browser_window(self):
        self.panel.follow(ZEN_XID)
        self.assertEqual(self.shown(), ["Zen"])
        self.panel.follow(FIREFOX_XID)
        self.assertEqual(self.shown(), ["Zen", "Firefox"])

    def test_follow_last_keeps_showing_the_last_browser_over_other_windows(self):
        self.panel.follow(ZEN_XID)
        self.view.calls.clear()
        self.panel.follow(TERM_XID)
        self.assertEqual(self.view.calls, [])
        self.assertIs(self.panel.current, self.zen)

    def test_follow_hide_hides_over_other_windows_and_returns(self):
        self.panel.cfg = {"follow": "hide"}
        self.panel.follow(TERM_XID)
        self.assertIn(("hidden", True), self.view.calls)
        self.panel.follow(FIREFOX_XID)
        self.assertIn(("hidden", False), self.view.calls)

    def test_own_panel_window_is_ignored(self):
        self.panel.follow(ZEN_XID)
        self.view.calls.clear()
        self.panel.cfg = {"follow": "hide"}
        self.panel.follow(PANEL_XID)  # clicking the panel must not count as "not a browser"
        self.assertEqual(self.view.calls, [])
        self.assertIs(self.panel.current, self.zen)

    def test_late_hello_matches_the_already_active_window(self):
        panel = Panel({"follow": "last"}, self.x)
        panel.view = FakeView()
        panel.follow(ZEN_XID)  # zen is active before its extension connects
        first, second = FakeConn(), FakeConn()
        panel.on_message(first, {"type": "hello", "browser": "Firefox"})
        panel.on_message(second, {"type": "hello", "browser": "Zen"})
        self.assertIs(panel.current, second)

    def test_closing_the_current_browser_falls_back_then_clears(self):
        self.panel.on_close(self.ff)
        self.assertEqual(self.shown(), ["Zen"])
        self.panel.on_close(self.zen)
        self.assertEqual(self.view.calls[-1], ("clear",))
        self.assertIsNone(self.panel.current)

    def test_closing_the_current_browser_prefers_the_one_owning_the_active_window(self):
        libre = FakeConn()
        self.panel.on_message(libre, {"type": "hello", "browser": "LibreWolf"})
        self.panel.on_message(libre, state(TAB))
        self.panel.current = self.ff  # e.g. last shown while a terminal was active...
        self.panel.active = LIBRE_XID  # ...and LibreWolf has since been focused
        self.view.calls.clear()
        self.panel.on_close(self.ff)
        self.assertIs(self.panel.current, libre)  # not simply the first one left (Zen)
        self.assertEqual(self.shown(), ["LibreWolf"])

    def test_browser_without_state_yet_never_shows_another_browsers_tabs(self):
        libre = FakeConn()
        self.panel.on_message(libre, {"type": "hello", "browser": "LibreWolf"})  # hello, state not yet arrived
        self.panel.follow(LIBRE_XID)
        self.assertIs(self.panel.current, libre)
        self.assertEqual(self.view.calls[-1], ("clear",))  # placeholder, not the previous browser's tabs
        self.assertEqual(self.shown(), [])
        self.panel.on_message(libre, state(TAB))  # state arrives: now it renders
        self.assertEqual(self.shown(), ["LibreWolf"])

    def test_hello_name_comes_from_the_process_not_the_reported_name(self):
        zen = FakeConn()
        with mock.patch("sidepanel.model.os.readlink", return_value="/opt/zen-browser-bin/zen-bin"):
            self.panel.on_message(zen, {"type": "hello", "browser": "Firefox", "browserPid": 4242})
        self.assertEqual(self.panel.browsers[zen]["browser"], "Zen")  # Zen reports itself as Firefox

    def test_state_before_hello_is_ignored(self):
        stray = FakeConn()
        self.panel.on_message(stray, state(TAB))
        self.assertNotIn(stray, self.panel.states)

    def test_activate_raises_the_browser_only_when_it_was_not_focused(self):
        self.panel.follow(FIREFOX_XID)
        self.panel.activate_tab(self.ff, 7, 1)
        self.assertEqual(self.ff.sent[-1], {"type": "activate_tab", "tabId": 7, "windowId": 1})
        self.assertEqual(self.x.activated, [])  # browser already active

        self.panel.follow(TERM_XID)  # user is in a terminal, panel still shows Firefox
        self.panel.activate_tab(self.ff, 7, 1)
        self.assertEqual(self.x.activated, [FIREFOX_XID])

    def test_reconfigure_to_last_unhides(self):
        self.panel.reconfigure({"follow": "last"})
        self.assertEqual(self.view.calls, [("reconfigure",), ("hidden", False)])

    def test_debug_console_activate(self):
        self.panel.on_stdin_line("activate 7")
        self.assertEqual(self.ff.sent[-1], {"type": "activate_tab", "tabId": 7, "windowId": 1})
        self.panel.on_stdin_line("activate 999")  # unknown tab
        self.panel.on_stdin_line("garbage")
        self.assertEqual(len(self.ff.sent), 1)


if __name__ == "__main__":
    unittest.main()
