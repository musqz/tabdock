"""Panel routing (which browser is shown, follow modes, actions) with fake view/X/connections."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from tabdock.app import Panel  # noqa: E402

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

    def show(self, sources, mode, choices, focus):
        self.calls.append(("show", "+".join(info["browser"] for _conn, info, _state in sources)))
        self.last = {"sources": [conn for conn, _info, _state in sources], "mode": mode,
                     "choices": [(label, colour) for _conn, label, colour in choices], "focus": focus}

    def clear(self, mode="auto", choices=()):
        self.calls.append(("clear",))
        self.cleared = {"mode": mode, "choices": [label for _conn, label, _colour in choices]}

    def set_hidden(self, hidden):
        self.calls.append(("hidden", hidden))

    def find(self):
        self.calls.append(("find",))

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
        self.clients = []  # XIDs bottom to top, as _NET_CLIENT_LIST_STACKING gives them
        self.pids = {}  # xid -> pid, asked for lazily
        self.focused = None  # the window that really has the keyboard (the panel only remembers browsers and apps)

    def active_window(self):
        return self.focused

    def window_info(self, xid):
        return self.WINDOWS[xid]

    def client_windows(self):
        return self.clients

    def window_pid(self, xid):
        return self.pids.get(xid)

    def activate(self, xid):
        self.activated.append(xid)


def state(*tabs):
    return {"type": "state", "focusedWindowId": 1, "containers": [], "windows": [{"id": 1, "tabs": list(tabs)}]}


TAB = {"id": 7, "title": "t", "cookieStoreId": "firefox-default", "active": True}


class PanelTest(unittest.TestCase):
    def setUp(self):
        self.x = FakeX()
        self.view = FakeView()
        self.panel = Panel({"follow": "last", "view": "auto"}, self.x)
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
        panel = Panel({"follow": "last", "view": "auto"}, self.x)
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
        self.view.calls.clear()  # (the hello redraws the browser still shown: it has a new chip now)
        self.panel.follow(LIBRE_XID)
        self.assertIs(self.panel.current, libre)
        self.assertEqual(self.view.calls[-1], ("clear",))  # placeholder, not the previous browser's tabs
        self.assertEqual(self.shown(), [])
        self.panel.on_message(libre, state(TAB))  # state arrives: now it renders
        self.assertEqual(self.shown(), ["LibreWolf"])

    def test_hello_name_comes_from_the_process_not_the_reported_name(self):
        zen = FakeConn()
        with mock.patch("tabdock.model.os.readlink", return_value="/opt/zen-browser-bin/zen-bin"):
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

    # -- which browsers are listed: the one in use, one chosen with its chip, or all of them ----------------

    def test_every_browser_is_a_choice_in_its_own_colour(self):
        self.assertEqual(self.view.last["mode"], "auto")
        self.assertEqual(self.view.last["choices"], [("Firefox", "#ff7139"), ("Zen", "#9d7cd8")])

    def test_two_profiles_of_one_browser_are_told_apart(self):
        second = FakeConn()
        self.panel.on_message(second, {"type": "hello", "browser": "Firefox"})
        labels = [label for label, _colour in self.view.last["choices"]]
        self.assertEqual(labels, ["Firefox 1", "Zen", "Firefox 2"])

    def test_choosing_a_browser_keeps_showing_it_whichever_window_has_the_focus(self):
        self.panel.choose(self.zen)
        self.assertEqual(self.view.calls[-1], ("show", "Zen"))
        self.panel.follow(FIREFOX_XID)  # working in Firefox does not change what the panel lists...
        self.assertEqual(self.view.calls[-1], ("show", "Zen"))
        self.assertIs(self.panel.current, self.ff)  # ...but "auto" knows where you are
        self.panel.choose("auto")
        self.assertEqual(self.view.calls[-1], ("show", "Firefox"))

    def test_all_lists_every_browser_that_has_sent_its_tabs(self):
        libre = FakeConn()
        self.panel.on_message(libre, {"type": "hello", "browser": "LibreWolf"})  # still starting: no tabs yet
        self.panel.choose("all")
        self.assertEqual(self.view.calls[-1], ("show", "Firefox+Zen"))
        self.panel.on_message(libre, state(TAB))
        self.assertEqual(self.view.calls[-1], ("show", "Firefox+Zen+LibreWolf"))

    def test_in_all_any_browser_updates_the_list_and_the_one_in_use_sets_the_colour(self):
        self.panel.choose("all")
        self.panel.follow(ZEN_XID)
        self.assertEqual(self.view.last["focus"]["browser"], "Zen")
        self.view.calls.clear()
        self.panel.on_message(self.ff, state(TAB))  # not the browser in use, but it is listed
        self.assertEqual(self.shown(), ["Firefox+Zen"])

    def test_the_configured_view_is_the_starting_mode_and_a_reload_applies_it(self):
        panel = Panel({"follow": "last", "view": "all"}, self.x)
        panel.view = FakeView()
        panel.on_message(self.ff, {"type": "hello", "browser": "Firefox"})
        panel.on_message(self.ff, state(TAB))
        panel.on_message(self.zen, {"type": "hello", "browser": "Zen"})
        panel.on_message(self.zen, state(TAB))
        self.assertEqual(panel.view.calls[-1], ("show", "Firefox+Zen"))
        panel.choose(self.zen)
        panel.reconfigure({"follow": "last", "view": "all"})  # the file wins over a chip clicked since
        self.assertEqual(panel.view.calls[-1], ("show", "Firefox+Zen"))

    def test_a_reload_with_new_theme_colours_redraws_in_them(self):
        self.assertEqual(self.panel.colours["firefox"], "#ff7139")
        self.panel.reconfigure({"follow": "last", "view": "auto", "theme": {"firefox": "#4c9aff"}})
        self.assertEqual(self.shown(), ["Firefox"])
        self.assertEqual(self.view.last["choices"], [("Firefox", "#4c9aff"), ("Zen", "#9d7cd8")])
        self.view.calls.clear()
        self.panel.reconfigure({"follow": "last", "view": "auto", "theme": {"firefox": "#4c9aff"}})
        self.assertEqual(self.shown(), [])  # the same colours: nothing to redraw

    def test_the_chosen_browser_closing_goes_back_to_auto(self):
        self.panel.choose(self.zen)
        self.panel.on_close(self.zen)
        self.assertEqual(self.panel.mode, "auto")
        self.assertEqual(self.view.calls[-1], ("show", "Firefox"))

    def test_a_browser_closing_leaves_all_without_it(self):
        self.panel.choose("all")
        self.panel.on_close(self.zen)  # not the one in use
        self.assertEqual(self.panel.mode, "all")
        self.assertEqual(self.view.calls[-1], ("show", "Firefox"))
        self.assertEqual(self.view.last["choices"], [("Firefox", "#ff7139")])

    def test_choosing_an_unknown_browser_is_ignored(self):
        self.panel.choose(FakeConn())
        self.assertEqual(self.panel.mode, "auto")

    def test_raise_browser_brings_it_forward_only_when_it_was_not_focused(self):
        self.panel.follow(FIREFOX_XID)
        self.panel.raise_browser(self.ff)
        self.assertEqual(self.x.activated, [])  # a "+" in the panel: the browser has the focus already
        self.panel.follow(TERM_XID)  # the find window, from a terminal
        self.panel.raise_browser(self.ff)
        self.assertEqual(self.x.activated, [FIREFOX_XID])

    def test_raise_browser_also_when_our_own_window_has_the_keyboard(self):
        self.panel.follow(FIREFOX_XID)  # the browser was in use, then the find window took the keyboard
        self.x.focused = PANEL_XID
        self.panel.raise_browser(self.ff)
        self.assertEqual(self.x.activated, [FIREFOX_XID])

    def test_debug_console_restores_the_tab_closed_last(self):
        self.panel.on_stdin_line("restore")
        self.panel.on_stdin_line("restore 7")  # (malformed: ignored)
        self.assertEqual(self.ff.sent, [{"type": "restore_tab"}])

    def test_activate_raises_the_browser_that_owns_the_tab_when_listing_several(self):
        self.panel.follow(ZEN_XID)
        self.panel.follow(FIREFOX_XID)  # Firefox is in use; Zen was in use before
        self.panel.choose("all")
        self.panel.activate_tab(self.ff, 7, 1)
        self.assertEqual(self.x.activated, [])  # already the focused window
        self.panel.activate_tab(self.zen, 7, 1)
        self.assertEqual(self.zen.sent[-1], {"type": "activate_tab", "tabId": 7, "windowId": 1})
        self.assertEqual(self.x.activated, [ZEN_XID])

    def test_a_browser_not_yet_in_use_is_found_by_its_process_and_never_by_our_own_window(self):
        libre = FakeConn()
        self.panel.on_message(libre, {"type": "hello", "browser": "LibreWolf", "browserPid": 4242})
        self.x.clients = [300, 301, PANEL_XID]  # the panel is on top, and a child of the browser
        self.x.pids = {300: 5000, 301: 5001, PANEL_XID: 5002}
        with mock.patch("tabdock.app.owns_window", side_effect=lambda browser, window: window >= 5001):
            self.panel.activate_tab(libre, 7, 1)
        self.assertEqual(self.x.activated, [301])  # topmost window of the browser, not the panel's own

    def test_a_remembered_window_that_was_closed_is_replaced_by_one_still_open(self):
        self.panel.on_message(self.zen, {"type": "hello", "browser": "Zen", "browserPid": 4242})
        self.panel.follow(ZEN_XID)  # seen active...
        self.panel.follow(TERM_XID)
        self.x.clients = [300, TERM_XID]  # ...but ZEN_XID has since been closed; another Zen window is open
        self.x.pids = {300: 5000, TERM_XID: 9}
        with mock.patch("tabdock.app.owns_window", side_effect=lambda browser, window: window == 5000):
            self.panel.activate_tab(self.zen, 7, 1)
        self.assertEqual(self.x.activated, [300])
        self.assertNotIn(ZEN_XID, self.panel.browser_xids.values())

    def test_a_remembered_window_that_is_still_open_is_used_without_asking_for_pids(self):
        self.panel.follow(ZEN_XID)
        self.panel.follow(TERM_XID)
        self.x.clients = [ZEN_XID, TERM_XID]
        self.x.window_pid = mock.Mock(side_effect=AssertionError("no need to look at any process"))
        self.panel.activate_tab(self.zen, 7, 1)
        self.assertEqual(self.x.activated, [ZEN_XID])

    def test_the_panels_own_window_being_active_does_not_raise_the_browser_again(self):
        self.panel.follow(FIREFOX_XID)
        self.panel.follow(PANEL_XID)  # e.g. the pointer is on the panel: still "Firefox in use"
        self.panel.activate_tab(self.ff, 7, 1)
        self.assertEqual(self.x.activated, [])

    def test_the_chips_stay_while_a_chosen_browser_has_no_tabs_yet(self):
        libre = FakeConn()
        self.panel.on_message(libre, {"type": "hello", "browser": "LibreWolf"})  # no state yet
        self.panel.choose(libre)
        self.assertEqual(self.view.calls[-1], ("clear",))
        self.assertEqual(self.view.cleared, {"mode": libre, "choices": ["Firefox", "Zen", "LibreWolf"]})  # a way out

    def test_a_browser_with_no_window_at_all_is_just_told(self):
        libre = FakeConn()
        self.panel.on_message(libre, {"type": "hello", "browser": "LibreWolf", "browserPid": 4242})
        with mock.patch("tabdock.app.owns_window", return_value=False):
            self.panel.activate_tab(libre, 7, 1)
        self.assertEqual(libre.sent[-1]["type"], "activate_tab")
        self.assertEqual(self.x.activated, [])

    def test_reconfigure_to_last_unhides(self):
        self.panel.reconfigure({"follow": "last", "view": "auto"})
        self.assertEqual(self.view.calls, [("reconfigure",), ("hidden", False)])

    def test_debug_console_can_reorder_tabs_and_containers(self):
        self.panel.on_stdin_line("move 7 0")
        self.panel.on_stdin_line("order firefox-container-2,firefox-container-1")
        self.assertEqual(
            self.ff.sent,
            [
                {"type": "move_tab", "tabId": 7, "index": 0},
                {"type": "set_container_order", "order": ["firefox-container-2", "firefox-container-1"]},
            ],
        )
        for junk in ("move x 1", "move 7", "order", "order a b", ""):
            self.panel.on_stdin_line(junk)
        self.assertEqual(len(self.ff.sent), 2)  # malformed lines are ignored

    def test_debug_console_drives_workspaces_in_the_focused_window(self):
        spaces = [{"id": "default", "name": "Default"}, {"id": "ws-1", "name": "Work"}]
        self.panel.on_message(self.ff, {**state(TAB), "workspaces": spaces})
        for line in ("ws ws-1", "wsnew Deep work", "wsrename ws-1 Tickets and bugs", "wsrm ws-1", "wsmove 7 default"):
            self.panel.on_stdin_line(line)
        self.assertEqual(self.ff.sent, [
            {"type": "switch_workspace", "windowId": 1, "workspaceId": "ws-1"},
            {"type": "new_workspace", "windowId": 1, "name": "Deep work"},
            {"type": "rename_workspace", "workspaceId": "ws-1", "name": "Tickets and bugs"},
            {"type": "remove_workspace", "workspaceId": "ws-1"},
            {"type": "move_tab_to_workspace", "tabId": 7, "workspaceId": "default"},
        ])
        for junk in ("ws", "ws a b", "wsrename ws-1", "wsrm", "wsmove x default", "wsmove 7"):
            self.panel.on_stdin_line(junk)
        self.assertEqual(len(self.ff.sent), 5)  # malformed lines are ignored

    def test_debug_console_edits_a_workspace_and_opens_a_tab_in_a_container(self):
        spaces = [{"id": "default", "name": "Default"}, {"id": "ws-1", "name": "Work"}]
        self.panel.on_message(self.ff, {**state(TAB), "workspaces": spaces})
        for line in ("wsicon ws-1 💼", "wscolor ws-1 blue", "wscontainer ws-1 firefox-container-1", "wsicon ws-1",
                     "newtab firefox-default"):
            self.panel.on_stdin_line(line)
        edit = {"type": "edit_workspace", "workspaceId": "ws-1"}
        self.assertEqual(self.ff.sent, [
            {**edit, "icon": "💼"}, {**edit, "color": "blue"}, {**edit, "cookieStoreId": "firefox-container-1"},
            {**edit, "icon": None},  # without a value: none
            {"type": "new_tab", "cookieStoreId": "firefox-default", "windowId": 1},
        ])
        for junk in ("wsicon", "wscolor ws-1 blue green", "newtab", "newtab a b"):
            self.panel.on_stdin_line(junk)
        self.assertEqual(len(self.ff.sent), 5)  # malformed lines are ignored

    def test_debug_console_closes_pins_and_unpins(self):
        for line in ("close 7", "pin 7", "unpin 7", "close x", "pin", "unpin 7 8"):
            self.panel.on_stdin_line(line)
        self.assertEqual(self.ff.sent, [
            {"type": "close_tab", "tabId": 7},
            {"type": "pin_tab", "tabId": 7, "pinned": True},
            {"type": "pin_tab", "tabId": 7, "pinned": False},
        ])  # (the malformed lines are ignored)

    def test_debug_console_reopens_a_tab_in_a_container(self):
        for line in ("reopen 7 firefox-container-2", "reopen x firefox-container-2", "reopen 7"):
            self.panel.on_stdin_line(line)
        self.assertEqual(self.ff.sent, [{"type": "reopen_in_container", "tabId": 7, "cookieStoreId": "firefox-container-2"}])

    def test_debug_console_edits_containers(self):
        for line in ("cnew Travel plans", "crename firefox-container-1 Private life", "ccolor firefox-container-1 red",
                     "cicon firefox-container-1 fruit", "crm firefox-container-1"):
            self.panel.on_stdin_line(line)
        update = {"type": "update_container", "cookieStoreId": "firefox-container-1"}
        self.assertEqual(self.ff.sent, [
            {"type": "create_container", "name": "Travel plans"},
            {**update, "name": "Private life"}, {**update, "color": "red"}, {**update, "icon": "fruit"},
            {"type": "remove_container", "cookieStoreId": "firefox-container-1"},
        ])
        for junk in ("cnew", "crename firefox-container-1", "ccolor", "crm", "crm a b"):
            self.panel.on_stdin_line(junk)
        self.assertEqual(len(self.ff.sent), 5)  # malformed lines are ignored

    def test_debug_console_offers_no_workspaces_in_zen_or_without_them(self):
        self.panel.on_stdin_line("wsnew Work")  # this extension sent no workspaces
        self.panel.follow(ZEN_XID)
        self.panel.on_message(self.zen, {**state(TAB), "workspaces": [{"id": "default", "name": "Default"}]})
        self.panel.on_stdin_line("wsnew Work")  # Zen has its own
        self.assertEqual((self.ff.sent, self.zen.sent), ([], []))

    def test_command_goes_to_the_given_browser(self):
        self.panel.command(self.zen, {"type": "move_tab", "tabId": 1, "index": 2})
        self.assertEqual(self.zen.sent, [{"type": "move_tab", "tabId": 1, "index": 2}])
        self.assertEqual(self.ff.sent, [])

    def test_a_find_message_opens_the_find_window(self):
        self.panel.on_message(FakeConn(), {"type": "find"})
        self.assertEqual(self.view.calls, [("find",)])

    def test_a_client_that_never_said_hello_closing_redraws_nothing(self):
        self.panel.on_message(FakeConn(), {"type": "find"})  # what `tabdock --find` sends
        self.view.calls.clear()
        self.panel.on_close(FakeConn())
        self.assertEqual(self.view.calls, [])
        self.assertIs(self.panel.current, self.ff)

    def test_debug_console_activate(self):
        self.panel.on_stdin_line("activate 7")
        self.assertEqual(self.ff.sent[-1], {"type": "activate_tab", "tabId": 7, "windowId": 1})
        self.panel.on_stdin_line("activate 999")  # unknown tab
        self.panel.on_stdin_line("garbage")
        self.assertEqual(len(self.ff.sent), 1)


if __name__ == "__main__":
    unittest.main()
