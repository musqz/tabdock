"""Pure logic: config, geometry/strut, autohide state machine, browser matching."""
import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from tabdock import config  # noqa: E402
from tabdock.autohide import Autohide  # noqa: E402
from tabdock.geometry import TRIGGER_PX, dock_rect, outer_monitor, strut  # noqa: E402
from tabdock.model import (  # noqa: E402
    accent,
    accents,
    ancestors,
    browser_theme_key,
    detect_browser,
    match_browser,
    on_accent,
    owns_window,
)


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
        self.assertEqual(config.DEFAULTS["monitor"], "outer")  # layout-independent unless a name is given
        for monitor in ("outer", "primary", "HDMI-1"):
            self.assertEqual(config.validate({"monitor": monitor})["monitor"], monitor)
        self.assertEqual(config.DEFAULTS["view"], "auto")  # the browser in use, as before
        self.assertEqual(config.validate({"view": "all"})["view"], "all")
        # the panel downloads icons itself, from your own address: never without being asked
        self.assertIs(config.DEFAULTS["icons"], False)
        self.assertIs(config.validate({"icons": True})["icons"], True)
        self.assertIs(config.DEFAULTS["badges"], True)  # reads only the title the browser already reports
        self.assertIs(config.validate({"badges": False})["badges"], False)

    def test_rejects_bad_values(self):
        for bad in (
            {"side": "top"},
            {"follow": "sometimes"},
            {"view": "zen"},  # a browser is chosen with its chip, not in the file
            {"icons": "yes"},
            {"icons": 1},
            {"badges": "yes"},
            {"badges": 1},
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
            with open(path, "w") as f:
                f.write('side = "right"\nwidth = 280    not a comment\n')
            with self.assertRaises(ValueError) as ctx:  # a value trailing without "#" before the comment text
                config.load(path)
            self.assertIn("width = 280    not a comment", str(ctx.exception))

    def test_a_config_from_before_the_rename_is_read_until_there_is_a_new_one(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp}):
            new = os.path.join(tmp, "tabdock", "config.toml")
            old = os.path.join(tmp, "openbox-sidepanel", "config.toml")
            self.assertEqual(config.config_path(), new)  # neither exists: where to make one
            os.makedirs(os.path.dirname(old))
            with open(old, "w") as f:
                f.write('side = "right"\n')
            self.assertEqual(config.config_path(), old)
            self.assertEqual(config.load()["side"], "right")
            os.makedirs(os.path.dirname(new))
            with open(new, "w") as f:
                f.write("")
            self.assertEqual(config.config_path(), new)  # once there is a new one, the old one is ignored
            self.assertEqual(config.load()["side"], "left")

    def test_theme(self):
        self.assertEqual(config.DEFAULTS["theme"], {})  # each browser keeps its own colour unless asked
        cfg = config.validate({"theme": {"accent": "#4C9AFF", "firefox": "#0af", "other": "#123456"}})
        self.assertEqual(cfg["theme"], {"accent": "#4c9aff", "firefox": "#00aaff", "other": "#123456"})
        self.assertEqual(config.DEFAULTS["theme"], {})  # (validating one never changes the defaults)
        for bad in (
            {"theme": "blue"},  # a section, not a value
            {"theme": {"accent": "blue"}},  # a name: the colour also names a style class, so only #hex
            {"theme": {"accent": "4c9aff"}},
            {"theme": {"accent": "#4c9af"}},
            {"theme": {"accent": "#4c9aff; color: red"}},
            {"theme": {"firefox": 0x4C9AFF}},
            {"theme": {"chrome": "#4c9aff"}},  # not a browser the panel knows
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                config.validate(bad)

    def test_set_theme_colour_keeps_every_other_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "c.toml")
            with open(path, "w") as f:
                f.write('side = "right"\n\n# comment above [theme]\n[theme]\n# accent = "#4c9aff"\nfirefox = "#111111"\n')
            config.set_theme_colour("firefox", "#4c9aff", path)  # replaces an existing active line in place
            config.set_theme_colour("other", "#8f9bb3", path)  # adds a key that was never there
            with open(path) as f:
                text = f.read()
            self.assertIn('side = "right"\n\n# comment above [theme]\n[theme]\n', text)  # everything above kept
            self.assertIn('# accent = "#4c9aff"', text)  # an unrelated commented line is untouched
            self.assertIn('firefox = "#4c9aff"', text)
            self.assertIn('other = "#8f9bb3"', text)
            self.assertEqual(config.load(path)["theme"], {"firefox": "#4c9aff", "other": "#8f9bb3"})

    def test_set_theme_colour_uncomments_an_example_and_creates_a_missing_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "c.toml")
            with open(path, "w") as f:
                f.write('side = "right"\n[theme]\n# waterfox = "#2ec4b6"\n')
            config.set_theme_colour("waterfox", "#111111", path)
            self.assertEqual(config.load(path)["theme"], {"waterfox": "#111111"})

            path2 = os.path.join(tmp, "c2.toml")
            with open(path2, "w") as f:
                f.write('side = "right"\n')  # no [theme] section at all yet
            config.set_theme_colour("floorp", "#e5b93a", path2)
            self.assertEqual(config.load(path2)["theme"], {"floorp": "#e5b93a"})

            path3 = os.path.join(tmp, "c3.toml")  # the file does not exist yet either
            config.set_theme_colour("zen", "#9d7cd8", path3)
            self.assertEqual(config.load(path3)["theme"], {"zen": "#9d7cd8"})

    def test_an_option_written_below_theme_says_where_it_belongs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "c.toml")
            with open(path, "w") as f:
                f.write('side = "right"\n[theme]\naccent = "#4c9aff"\npinned = true\n')  # TOML: pinned is theme's
            with self.assertRaisesRegex(ValueError, r"in \[theme\]: pinned .*above the \[theme\] line"):
                config.load(path)
            with open(path, "w") as f:
                f.write('side = "right"\npinned = true\n[theme]\naccent = "#4c9aff"\n')
            cfg = config.load(path)
            self.assertEqual((cfg["side"], cfg["pinned"], cfg["theme"]), ("right", True, {"accent": "#4c9aff"}))

    def test_shipped_template_is_valid(self):
        template = os.path.join(os.path.dirname(__file__), "..", "configs", "config.toml")
        self.assertEqual(config.load(template), config.DEFAULTS)

    def test_every_example_in_the_template_works_once_its_hash_is_taken_off(self):
        """The template says to take the # off an example line: what is left must still be a valid config."""
        template = os.path.join(os.path.dirname(__file__), "..", "configs", "config.toml")
        with open(template) as f:
            lines = f.read().split("\n")
        examples = [i for i, line in enumerate(lines) if re.match(r"# [a-z_]+ = ", line)]
        self.assertGreaterEqual(len(examples), 3)  # (the [theme] ones at least)
        for i in examples:
            with self.subTest(line=lines[i]), tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "config.toml")
                with open(path, "w") as f:
                    f.write("\n".join(lines[:i] + [lines[i][2:]] + lines[i + 1:]))
                config.load(path)


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


class OuterMonitorTest(unittest.TestCase):
    HDMI, DP = (0, 0, 2560, 1440), (2560, 180, 1920, 1080)

    def test_your_layout(self):
        rects = [self.HDMI, self.DP]
        self.assertEqual(outer_monitor(rects, "left", 0), 0)  # HDMI-1 owns the left edge
        self.assertEqual(outer_monitor(rects, "right", 0), 1)  # DP-1 owns the right edge

    def test_mirrored_layout_gives_the_mirrored_answer(self):
        dp, hdmi = (0, 180, 1920, 1080), (1920, 0, 2560, 1440)  # DP-1 left, HDMI-1 right (and primary)
        self.assertEqual(outer_monitor([dp, hdmi], "left", 1), 0)
        self.assertEqual(outer_monitor([dp, hdmi], "right", 1), 1)

    def test_order_of_the_monitor_list_does_not_matter(self):
        self.assertEqual(outer_monitor([self.DP, self.HDMI], "left", 1), 1)
        self.assertEqual(outer_monitor([self.DP, self.HDMI], "right", 1), 0)

    def test_single_monitor_and_three_monitors(self):
        self.assertEqual((outer_monitor([self.HDMI], "left"), outer_monitor([self.HDMI], "right")), (0, 0))
        three = [(0, 0, 1920, 1080), (1920, 0, 2560, 1440), (4480, 0, 1920, 1080)]
        self.assertEqual((outer_monitor(three, "left", 1), outer_monitor(three, "right", 1)), (0, 2))

    def test_vertically_stacked_monitors_prefer_primary_then_tallest_then_first(self):
        stacked = [(0, 0, 1920, 1080), (0, 1080, 2560, 1440)]
        self.assertEqual(outer_monitor(stacked, "left", 0), 0)  # the primary wins
        self.assertEqual(outer_monitor(stacked, "left", None), 1)  # else the tallest
        equal = [(0, 0, 1920, 1080), (0, 1080, 1920, 1080)]
        self.assertEqual(outer_monitor(equal, "left", None), 0)  # else the first

    def test_a_primary_on_an_inner_edge_is_ignored(self):
        self.assertEqual(outer_monitor([self.HDMI, self.DP], "right", 0), 1)  # HDMI-1 is primary but inner


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


class AutohideHoldTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.applied = []
        self.hide = Autohide(self.applied.append, self.clock.schedule, self.clock.cancel, open_ms=100, close_ms=400)
        self.hide.enter()
        self.clock.advance(100)  # open, pointer inside

    def test_a_drag_keeps_the_panel_open_wherever_the_pointer_goes(self):
        self.hide.set_held(True)
        self.hide.leave()  # the pointer left the panel mid-drag
        self.clock.advance(5000)
        self.assertEqual(self.applied, [True])  # never closed

    def test_it_closes_after_the_drop_unless_the_pointer_is_back(self):
        self.hide.set_held(True)
        self.hide.leave()
        self.hide.set_held(False)  # dropped outside the panel
        self.clock.advance(399)
        self.assertEqual(self.applied, [True])
        self.clock.advance(1)
        self.assertEqual(self.applied, [True, False])

    def test_dropping_inside_keeps_it_open(self):
        self.hide.set_held(True)
        self.hide.set_held(False)  # the pointer never left
        self.clock.advance(5000)
        self.assertEqual(self.applied, [True])


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
            with self.subTest(exe=exe), mock.patch("tabdock.model.os.readlink", return_value=exe):
                self.assertEqual(detect_browser(hello), expected)

    def test_detect_browser_without_a_readable_process(self):
        self.assertEqual(detect_browser({"browser": "Zen"}), "Zen")
        self.assertEqual(detect_browser({"browser": "Zen", "browserPid": 2**22 + 5}), "Zen")  # no such process
        self.assertEqual(detect_browser({}), "browser")

    def test_accent(self):
        self.assertEqual(accent({"browser": "Firefox"}), "#ff7139")
        self.assertEqual(accent({"browser": "LibreWolf"}), "#3fa9f5")
        self.assertEqual(accent({"browser": "Zen"}), "#9d7cd8")
        self.assertEqual(accent({"browser": "Waterfox"}), "#2ec4b6")
        self.assertEqual(accent({"browser": "Mystery"}), "#8f9bb3")
        self.assertEqual(accent({}), "#8f9bb3")
        from tabdock.model import KNOWN_BROWSERS

        # every browser the panel recognises has its own colour, so several can be listed together
        browsers = [name for _key, name in KNOWN_BROWSERS]
        self.assertEqual(len({accent({"browser": b}) for b in browsers}), len(browsers))
        self.assertNotIn(accent({"browser": "Floorp"}), ("#8f9bb3", accent({"browser": "Firefox"})))

    def test_browser_theme_key(self):
        self.assertEqual(browser_theme_key({"browser": "Firefox"}), "firefox")
        self.assertEqual(browser_theme_key({"browser": "LibreWolf"}), "librewolf")
        self.assertEqual(browser_theme_key({"browser": "Mystery"}), "other")
        self.assertEqual(browser_theme_key({}), "other")

    def test_theme_colours(self):
        self.assertEqual(accents(), accents({}))
        self.assertEqual(accents()["firefox"], "#ff7139")
        self.assertEqual(accents()["other"], "#8f9bb3")
        one = accents({"accent": "#4c9aff"})  # every browser, and the strip with none connected
        self.assertEqual(set(one.values()), {"#4c9aff"})
        mixed = accents({"accent": "#4c9aff", "zen": "#00ff00"})  # a browser's own key wins over accent
        self.assertEqual((mixed["zen"], mixed["firefox"]), ("#00ff00", "#4c9aff"))
        own = accents({"firefox": "#4c9aff"})  # the other browsers keep theirs
        self.assertEqual((own["firefox"], own["zen"], own["other"]), ("#4c9aff", "#9d7cd8", "#8f9bb3"))
        self.assertEqual(accent({"browser": "Firefox"}, own), "#4c9aff")
        self.assertEqual(accent({"browser": "Zen"}, own), "#9d7cd8")
        self.assertEqual(accent({"browser": "Mystery"}, accents({"other": "#123456"})), "#123456")
        self.assertEqual(accent({}, accents({"other": "#123456"})), "#123456")

    def test_text_on_an_accent_stays_readable(self):
        # every built-in colour keeps the dark text it always had
        for colour in accents().values():
            self.assertEqual(on_accent(colour), "#1b1d23", colour)
        for dark in ("#1e3a8a", "#000000", "#7a1f1f", "#2d2d6e"):
            self.assertEqual(on_accent(dark), "#ffffff", dark)
        for light in ("#ffffff", "#ffcb00", "#4c9aff"):
            self.assertEqual(on_accent(light), "#1b1d23", light)


if __name__ == "__main__":
    unittest.main()
