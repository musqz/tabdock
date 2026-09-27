import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from tabdock.model import (  # noqa: E402
    colour_name,
    edits_workspaces,
    format_state,
    group_tabs,
    heir,
    in_workspace,
    offers_workspaces,
    ordered_containers,
    reordered,
    tab_badge,
    tab_label,
    tab_move_index,
    waiting_text,
    window_of_tab,
    workspace_label,
)


def tab(id, title, store="firefox-default", active=False):
    return {"id": id, "title": title, "cookieStoreId": store, "active": active}


STATE = {
    "focusedWindowId": 2,
    "containers": [
        {"cookieStoreId": "firefox-container-1", "name": "Personal"},
        {"cookieStoreId": "firefox-container-2", "name": "Work"},
    ],
    "windows": [
        {"id": 1, "tabs": [tab(1, "other window")]},
        {
            "id": 2,
            "tabs": [
                tab(10, "plain", active=True),
                tab(11, "mail", "firefox-container-1"),
                tab(12, "private-ish", "firefox-container-9"),
                tab(13, "plain 2"),
            ],
        },
    ],
}


class ModelTest(unittest.TestCase):
    def test_groups_follow_focused_window_and_container_order(self):
        groups = group_tabs(STATE)
        self.assertEqual(
            [(c["name"], [t["id"] for t in tabs]) for c, tabs in groups],
            [
                ("No container", [10, 13]),
                ("Personal", [11]),
                ("Work", []),  # empty containers stay (targets for "new tab here")
                ("firefox-container-9", [12]),  # unknown store goes last
            ],
        )

    def test_unknown_focused_window_falls_back_to_first(self):
        groups = group_tabs({**STATE, "focusedWindowId": 99})
        self.assertEqual([t["id"] for t in groups[0][1]], [1])

    def test_no_windows(self):
        self.assertEqual(group_tabs({"windows": []}), [])

    def test_no_container_group_stays_even_when_empty(self):
        # every tab is in a container: no default-context tab exists, but "No container" is still
        # a target for "new tab here", same as an empty known container
        state = {
            "containers": [{"cookieStoreId": "firefox-container-1", "name": "Personal"}],
            "windows": [{"id": 1, "tabs": [tab(1, "mail", "firefox-container-1")]}],
        }
        groups = group_tabs(state)
        self.assertEqual([(c["name"], [t["id"] for t in tabs]) for c, tabs in groups], [("No container", []), ("Personal", [1])])

    def test_custom_container_order_is_applied_and_no_container_stays_first(self):
        state = {**STATE, "containerOrder": ["firefox-container-2", "firefox-container-1"]}
        names = [c["name"] for c, _ in group_tabs(state)]
        self.assertEqual(names, ["No container", "Work", "Personal", "firefox-container-9"])

    def test_container_order_ignores_unknown_and_repeated_ids_and_keeps_unnamed_after(self):
        containers = [{"cookieStoreId": f"c{n}", "name": f"C{n}"} for n in (1, 2, 3, 4)]
        state = {"containers": containers, "containerOrder": ["c3", "gone", "c3", "c1"]}
        self.assertEqual([c["cookieStoreId"] for c in ordered_containers(state)], ["c3", "c1", "c2", "c4"])
        self.assertEqual([c["cookieStoreId"] for c in ordered_containers({"containers": containers})],
                         ["c1", "c2", "c3", "c4"])  # no custom order: the browser's

    def test_reordered(self):
        ids = ["a", "b", "c", "d"]
        self.assertEqual(reordered(ids, "d", "b"), ["a", "d", "b", "c"])  # before b
        self.assertEqual(reordered(ids, "a", "d"), ["b", "c", "a", "d"])  # forward, before d
        self.assertEqual(reordered(ids, "a"), ["b", "c", "d", "a"])  # to the end
        self.assertEqual(reordered(ids, "b", "b"), ids)  # dropped on itself
        self.assertEqual(reordered(ids, "b", "zzz"), ["a", "c", "d", "b"])  # unknown target: the end

    def test_tab_move_index_matches_what_tabs_move_does(self):
        # one window: A0 B1 C2 (a container) and D3 (another container's tab)
        group = [{"id": "A", "index": 0}, {"id": "B", "index": 1}, {"id": "C", "index": 2}]

        def apply(order, moved, index):  # what browser.tabs.move(moved, {index}) does to the tab strip
            rest = [t for t in order if t != moved]
            return rest[:index] + [moved] + rest[index:]

        strip = ["A", "B", "C", "D"]
        self.assertEqual(tab_move_index(group, "A", "C"), 1)  # A before C: forward, lands one earlier
        self.assertEqual(apply(strip, "A", 1), ["B", "A", "C", "D"])
        self.assertEqual(tab_move_index(group, "C", "A"), 0)  # backward: lands on the target's slot
        self.assertEqual(apply(strip, "C", 0), ["C", "A", "B", "D"])
        self.assertEqual(tab_move_index(group, "A"), 2)  # last in the container, before the other one's D
        self.assertEqual(apply(strip, "A", 2), ["B", "C", "A", "D"])

    def test_tab_move_index_is_none_when_nothing_changes(self):
        group = [{"id": "A", "index": 4}, {"id": "B", "index": 5}, {"id": "C", "index": 6}]
        self.assertIsNone(tab_move_index(group, "B", "B"))  # onto itself
        self.assertIsNone(tab_move_index(group, "A", "B"))  # before its own next neighbour
        self.assertIsNone(tab_move_index(group, "C"))  # already last

    def test_window_of_tab(self):
        self.assertEqual(window_of_tab(STATE, 11), 2)
        self.assertIsNone(window_of_tab(STATE, 999))

    def test_tab_badge_reads_a_leading_unread_count(self):
        self.assertEqual(tab_badge(tab(1, "(3) Inbox")), "3")
        self.assertEqual(tab_badge(tab(1, " (3) Inbox")), "3")  # a leading space still counts
        self.assertEqual(tab_badge(tab(1, "(99+) Inbox")), "99+")  # Gmail/Slack-style overflow
        self.assertIsNone(tab_badge(tab(1, "Inbox")))
        self.assertIsNone(tab_badge(tab(1, "(Draft) Inbox")))
        self.assertIsNone(tab_badge(tab(1, "(0) Inbox")))  # nothing unread is not a badge
        self.assertIsNone(tab_badge(tab(1, "(00) Inbox")))  # however padded
        self.assertIsNone(tab_badge(tab(1, "(2024) Annual Report")))  # a year, not a count
        self.assertIsNone(tab_badge({}))

    def test_tab_label_drops_the_badge_prefix(self):
        self.assertEqual(tab_label(tab(1, "(3) Inbox")), "Inbox")
        self.assertEqual(tab_label(tab(1, "(3)")), "(untitled)")  # nothing left to show otherwise
        self.assertEqual(tab_label(tab(1, "Inbox")), "Inbox")
        self.assertEqual(tab_label(tab(1, "(2024) Annual Report")), "(2024) Annual Report")

    def test_format_state_shows_the_unread_count_alongside_the_stripped_title(self):
        state = {**STATE, "windows": [{"id": 2, "tabs": [tab(10, "(3) Inbox")]}]}
        text = format_state({"browser": "Firefox", "version": "156.0", "browserPid": 42}, state)
        self.assertIn(" Inbox (3) [10]", text)

    def test_format_state(self):
        text = format_state({"browser": "Firefox", "version": "156.0", "browserPid": 42}, STATE)
        self.assertEqual(text.splitlines()[0], "== Firefox 156.0 (pid 42) window 2 ==")
        self.assertIn(" * plain [10]", text)
        self.assertIn("[Work] (0)", text)

    WS_STATE = {
        "focusedWindowId": 2,
        "containers": [{"cookieStoreId": "firefox-container-1", "name": "Personal"}],
        "workspaces": [{"id": "default", "name": "Default"}, {"id": "ws-1", "name": "Work"}],
        "windows": [{"id": 2, "workspaceId": "ws-1", "tabs": [
            {**tab(10, "home"), "workspaceId": "default"},
            {**tab(11, "ticket", "firefox-container-1", active=True), "workspaceId": "ws-1"},
            {**tab(12, "music"), "workspaceId": "default", "pinned": True},
        ]}],
    }

    def test_groups_hold_only_the_workspace_the_window_shows_and_pinned_tabs(self):
        groups = group_tabs(self.WS_STATE)
        self.assertEqual([(c["name"], [t["id"] for t in tabs]) for c, tabs in groups],
                         [("No container", [12]), ("Personal", [11])])  # not "home": it is in Default

    def test_an_extension_without_workspaces_shows_every_tab(self):
        self.assertTrue(in_workspace(tab(1, "x"), None))
        self.assertTrue(in_workspace(tab(1, "x"), "ws-1"))  # a tab that does not say shows wherever
        self.assertEqual([t["id"] for _c, tabs in group_tabs(STATE) for t in tabs], [10, 13, 11, 12])

    def test_workspaces_are_offered_except_in_zen_and_by_an_older_extension(self):
        self.assertTrue(offers_workspaces({"browser": "Firefox"}, self.WS_STATE))
        self.assertTrue(offers_workspaces({"browser": "LibreWolf"}, self.WS_STATE))
        self.assertFalse(offers_workspaces({"browser": "Zen"}, self.WS_STATE))  # it has workspaces of its own
        self.assertFalse(offers_workspaces({"browser": "Firefox"}, STATE))  # 0.3.x sends none

    def test_the_heir_of_a_removed_workspace_is_its_neighbour(self):
        spaces = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        self.assertEqual(heir(spaces, "b"), {"id": "a"})  # the one before it
        self.assertEqual(heir(spaces, "c"), {"id": "b"})
        self.assertEqual(heir(spaces, "a"), {"id": "b"})  # the first: the one after it
        self.assertIsNone(heir(spaces[:1], "a"))  # the last workspace stays
        self.assertIsNone(heir(spaces, "gone"))

    def test_format_state_lists_the_workspaces_and_marks_the_shown_one(self):
        lines = format_state({"browser": "Firefox", "version": "156.0"}, self.WS_STATE).splitlines()
        self.assertEqual(lines[1:3], ["workspace  Default {default}", "workspace* Work {ws-1}"])
        self.assertNotIn(" home [10]", lines)  # another workspace's tab is not listed

    def test_format_state_adds_what_else_a_workspace_has(self):
        spaces = [{"id": "default", "name": "Default", "icon": None, "color": None, "cookieStoreId": None},
                  {"id": "ws-1", "name": "Work", "icon": "💼", "color": "blue", "cookieStoreId": "firefox-container-1"}]
        lines = format_state({"browser": "Firefox", "version": "156.0"}, {**self.WS_STATE, "workspaces": spaces}).splitlines()
        self.assertEqual(lines[1:3], ["workspace  Default {default}",
                                      "workspace* Work {ws-1} icon=💼 color=blue cookieStoreId=firefox-container-1"])

    def test_a_workspace_is_named_with_its_icon_and_only_newer_extensions_edit_one(self):
        self.assertEqual(workspace_label({"name": "Work", "icon": "💼"}), "💼 Work")
        self.assertEqual(workspace_label({"name": "Work", "icon": None}), "Work")
        self.assertEqual(workspace_label({"name": "Work"}), "Work")
        self.assertTrue(edits_workspaces([{"id": "default", "name": "Default", "icon": None}]))  # empty, but kept
        self.assertFalse(edits_workspaces([{"id": "default", "name": "Default"}]))  # an extension with names only
        self.assertFalse(edits_workspaces([]))
        self.assertEqual((colour_name("blue"), colour_name("toolbar")), ("Blue", "Grey"))

    def test_waiting_text_without_a_packaged_extension(self):
        self.assertEqual(waiting_text("/nonexistent/tabdock.xpi"), "Waiting for a browser with the Tabdock extension")

    def test_waiting_text_says_where_the_packaged_extension_is(self):
        with tempfile.NamedTemporaryFile(suffix=".xpi") as xpi:
            text = waiting_text(xpi.name)
        self.assertTrue(text.startswith("Waiting for a browser with the Tabdock extension"))
        self.assertIn("about:addons", text)
        self.assertTrue(text.endswith(xpi.name))


if __name__ == "__main__":
    unittest.main()
