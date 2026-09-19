import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from sidepanel.model import format_state, group_tabs, window_of_tab  # noqa: E402


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
