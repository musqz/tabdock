import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from sidepanel.model import (  # noqa: E402
    format_state,
    group_tabs,
    ordered_containers,
    reordered,
    tab_move_index,
    window_of_tab,
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

    def test_format_state(self):
        text = format_state({"browser": "Firefox", "version": "156.0", "browserPid": 42}, STATE)
        self.assertEqual(text.splitlines()[0], "== Firefox 156.0 (pid 42) window 2 ==")
        self.assertIn(" * plain [10]", text)
        self.assertIn("[Work] (0)", text)


if __name__ == "__main__":
    unittest.main()
