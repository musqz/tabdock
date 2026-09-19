"""Pure logic: config, geometry/strut, autohide state machine, browser matching."""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from sidepanel import config  # noqa: E402
from sidepanel.autohide import Autohide  # noqa: E402
from sidepanel.geometry import TRIGGER_PX, dock_rect, strut  # noqa: E402
from sidepanel.model import accent, ancestors, detect_browser, match_browser, owns_window  # noqa: E402


class ConfigTest(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(config.validate({}), config.DEFAULTS)

    def test_override(self):
        cfg = config.validate(
            {"side": "right", "width": 400, "pinned": True, "monitor": "DP-1", "start_with_browser": False}
        )
        self.assertEqual(
            (cfg["side"], cfg["width"], cfg["pinned"], cfg["monitor"], cfg["start_with_browser"]),
            ("right", 400, True, "DP-1", False),
        )
        self.assertTrue(config.DEFAULTS["start_with_browser"])  # on unless the user opts out

    def test_rejects_bad_values(self):
        for bad in (
            {"side": "top"},
            {"follow": "sometimes"},
            {"width": 50},
            {"width": "wide"},
            {"width": True},
            {"pinned": "yes"},
            {"start_with_browser": "yes"},
            {"start_with_browser": 1},
            {"monitor": ""},
            {"sdie": "left"},  # typo in a key
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                config.validate(bad)

    def test_load_missing_file_and_toml(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(config.load(os.path.join(tmp, "nope.toml")), config.DEFAULTS)
            path = os.path.join(tmp, "c.toml")
            with open(path, "w") as f:
                f.write('side = "right"\nwidth = 280\n')
            self.assertEqual(config.load(path)["side"], "right")
            with open(path, "w") as f:
                f.write("side = [")
            with self.assertRaises(ValueError):  # TOMLDecodeError is a ValueError
                config.load(path)

    def test_shipped_template_is_valid(self):
        template = os.path.join(os.path.dirname(__file__), "..", "configs", "config.toml")
        self.assertEqual(config.load(template), config.DEFAULTS)


class GeometryTest(unittest.TestCase):
    HDMI = (0, 0, 2560, 1440)
    DP = (2560, 180, 1920, 1080)
    SCREEN_W = 4480

    def test_dock_rect(self):
        self.assertEqual(dock_rect(self.HDMI, "left", 320, True), (0, 0, 320, 1440))
        self.assertEqual(dock_rect(self.HDMI, "left", 320, False), (0, 0, TRIGGER_PX, 1440))
        self.assertEqual(dock_rect(self.DP, "right", 320, True), (4160, 180, 320, 1080))
        self.assertEqual(dock_rect(self.DP, "right", 320, False), (4480 - TRIGGER_PX, 180, TRIGGER_PX, 1080))

    def test_strut_on_outer_edges(self):
        self.assertEqual(strut(self.HDMI, self.SCREEN_W, "left", 320), [320, 0, 0, 0, 0, 1439, 0, 0, 0, 0, 0, 0])
        self.assertEqual(strut(self.DP, self.SCREEN_W, "right", 320), [0, 320, 0, 0, 0, 0, 180, 1259, 0, 0, 0, 0])

    def test_no_strut_on_inner_edges(self):
        # HDMI-1's right edge and DP-1's left edge face each other
        self.assertIsNone(strut(self.HDMI, self.SCREEN_W, "right", 320))
        self.assertIsNone(strut(self.DP, self.SCREEN_W, "left", 320))

    def test_single_monitor_both_sides(self):
        mon = (0, 0, 1920, 1080)
        self.assertIsNotNone(strut(mon, 1920, "left", 300))
        self.assertIsNotNone(strut(mon, 1920, "right", 300))


class FakeClock:
    def __init__(self):
        self.now = 0
        self.timers = {}
        self.next_id = 1

    def schedule(self, ms, fn):
        self.timers[self.next_id] = (self.now + ms, fn)
        self.next_id += 1
        return self.next_id - 1

    def cancel(self, handle):
        self.timers.pop(handle, None)

    def advance(self, ms):
        self.now += ms
        for handle, (due, fn) in sorted(self.timers.items(), key=lambda kv: kv[1][0]):
            if due <= self.now and handle in self.timers:
                del self.timers[handle]
                fn()


class AutohideTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.applied = []
        self.hide = Autohide(self.applied.append, self.clock.schedule, self.clock.cancel, open_ms=100, close_ms=400)

    def test_opens_after_delay_and_closes_after_leave(self):
        self.hide.enter()
        self.clock.advance(99)
        self.assertEqual(self.applied, [])
        self.clock.advance(1)
        self.assertEqual(self.applied, [True])
        self.hide.leave()
        self.clock.advance(399)
        self.assertEqual(self.applied, [True])
        self.clock.advance(1)
        self.assertEqual(self.applied, [True, False])

    def test_pointer_flyby_does_not_open(self):
        self.hide.enter()
        self.clock.advance(50)
        self.hide.leave()
        self.clock.advance(1000)
        self.assertEqual(self.applied, [])

    def test_reentering_cancels_pending_close(self):
        self.hide.enter()
        self.clock.advance(100)
        self.hide.leave()
        self.clock.advance(300)
        self.hide.enter()
        self.clock.advance(1000)
        self.assertEqual(self.applied, [True])

    def test_pin_opens_immediately_and_blocks_close(self):
        self.hide.set_pinned(True)
        self.assertEqual(self.applied, [True])
        self.hide.enter()
        self.hide.leave()
        self.clock.advance(1000)
        self.assertEqual(self.applied, [True])

    def test_unpin_closes_after_delay_unless_hovering(self):
        self.hide.set_pinned(True)
        self.hide.set_pinned(False)
        self.clock.advance(399)
        self.assertEqual(self.applied, [True])
        self.clock.advance(1)
        self.assertEqual(self.applied, [True, False])

        self.hide.set_pinned(True)
        self.hide.enter()
        self.hide.set_pinned(False)
        self.clock.advance(1000)
        self.assertEqual(self.applied[-1], True)  # pointer still inside: stays open


class MatchTest(unittest.TestCase):
    def test_ancestors_of_self_include_parent(self):
        chain = ancestors(os.getpid())
        self.assertEqual(chain[0], os.getpid())
        self.assertIn(os.getppid(), chain)

    def test_ancestors_of_garbage(self):
        self.assertEqual(ancestors(0), [])
        self.assertEqual(ancestors(2**22 + 12345), [2**22 + 12345])  # no such process: just itself

    def test_owns_window_is_one_directional(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        sibling = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.addCleanup(lambda: [p.kill() or p.wait() for p in (child, sibling)])
        me = os.getpid()
        self.assertTrue(owns_window(me, me))  # the browser process itself
        self.assertTrue(owns_window(me, child.pid))  # a helper process of the browser
        # the terminal/launcher that started the browser is an ancestor of it, not the browser:
        self.assertFalse(owns_window(child.pid, me))
        self.assertFalse(owns_window(child.pid, sibling.pid))

    def test_match_prefers_pid_over_class(self):
        me = os.getpid()
        browsers = {
            "a": {"browser": "Firefox", "browserPid": 2**22 + 1},  # class would match, pid does not
            "b": {"browser": "Zen", "browserPid": me},
        }
        self.assertEqual(match_browser(browsers, me, ("Navigator", "firefox")), "b")

    def test_terminal_that_launched_the_browser_is_not_the_browser(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.addCleanup(lambda: child.kill() or child.wait())
        browsers = {"ff": {"browser": "Firefox", "browserPid": child.pid}}  # started by this process
        self.assertIsNone(match_browser(browsers, os.getpid(), ("kitty", "kitty")))
        self.assertIsNone(match_browser(browsers, os.getpid(), ("Navigator", "firefox")))  # pids known: no class guess

    def test_match_class_fallback_and_miss(self):
        browsers = {"a": {"browser": "Firefox"}, "z": {"browser": "Zen"}}
        self.assertEqual(match_browser(browsers, None, ("zen", "zen")), "z")
        self.assertEqual(match_browser(browsers, 4242, ("Navigator", "firefox")), "a")
        self.assertEqual(match_browser(browsers, None, ("Navigator", "firefox-developer-edition")), "a")
        self.assertIsNone(match_browser(browsers, None, ("xterm", "XTerm")))
        self.assertIsNone(match_browser({}, os.getpid(), ("firefox",)))

    def test_class_fallback_is_not_a_substring_match(self):
        self.assertIsNone(match_browser({"z": {"browser": "Zen"}}, None, ("zenity", "Zenity")))
        self.assertIsNone(match_browser({"f": {"browser": "Firefox"}}, None, ("notfirefox", "NotFirefox")))

    def test_detect_browser_uses_the_process_not_the_reported_name(self):
        hello = {"browser": "Firefox", "browserPid": 1234}  # Zen reports itself as "Firefox"
        for exe, expected in (
            ("/opt/zen-browser-bin/zen-bin", "Zen"),
            ("/usr/lib/firefox/firefox", "Firefox"),
            ("/usr/lib/firedragon/firedragon", "FireDragon"),
            ("/opt/librewolf/librewolf", "LibreWolf"),
            ("/usr/lib/firefox-developer-edition/firefox", "Firefox"),
            ("/usr/bin/somethingelse", "Firefox"),  # unknown executable: keep the reported name
        ):
            with self.subTest(exe=exe), mock.patch("sidepanel.model.os.readlink", return_value=exe):
                self.assertEqual(detect_browser(hello), expected)

    def test_detect_browser_without_a_readable_process(self):
        self.assertEqual(detect_browser({"browser": "Zen"}), "Zen")
        self.assertEqual(detect_browser({"browser": "Zen", "browserPid": 2**22 + 5}), "Zen")  # no such process
        self.assertEqual(detect_browser({}), "browser")

    def test_accent(self):
        self.assertEqual(accent({"browser": "Firefox"}), "#ff7139")
        self.assertEqual(accent({"browser": "LibreWolf"}), "#3fa9f5")
        self.assertEqual(accent({"browser": "Zen"}), "#9d7cd8")
        self.assertEqual(accent({"browser": "Mystery"}), "#8f9bb3")
        self.assertEqual(accent({}), "#8f9bb3")
        self.assertEqual(len({accent({"browser": b}) for b in ("Firefox", "Zen", "FireDragon", "LibreWolf")}), 4)


if __name__ == "__main__":
    unittest.main()
