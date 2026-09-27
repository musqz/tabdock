#!/usr/bin/env python3
"""End-to-end check of the dock panel under a real Openbox (slow, manual; not part of discovery).

Runs the panel inside a nested Xephyr display (a window appears on your desktop while it
runs) with Openbox as window manager. xterm windows stand in for browsers, and this script
plays the extension by talking to the panel socket directly. Needs Xephyr, openbox, xterm,
xdotool, xprop, xwininfo and ImageMagick (`magick`).

Checks: dock type + strip geometry, no strut while autohiding, hover expand/collapse, click on
a tab reaches the browser without stealing focus, the strip colour follows the active browser,
raising the browser when clicking while another app is active, dragging to reorder, closing a tab
(its ✕, a middle click), a container's menu (rename, removal asked first), the chips
and the all-browsers list (folding, raising the right browser), workspaces (switch, the right-click
menu, naming a new one in a window that takes the keyboard, a colour from the chip's submenu), pin ->
strut, side switch, and follow=hide.

    python3 tests/e2e_x11.py [--shots DIR]
"""
import argparse
import base64
import json
import os
import re
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
import zlib

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DISPLAY = ":92"
ENV = {**os.environ, "DISPLAY": DISPLAY}
WIDTH = 300
STRIP = 3
SCREEN = (1280, 800)
COLOURS = {"Firefox": "FF7139", "Zen": "9D7CD8"}


def green_icon():
    """A 16x16 solid green PNG as a data: URL, the way a page can carry its own icon: no network involved."""
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    raw = b"".join(b"\x00" + b"\x00\xff\x00\xff" * 16 for _ in range(16))
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 16, 16, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return "data:image/png;base64," + base64.b64encode(png).decode()


ICON = green_icon()


def run(*cmd, **kw):
    return subprocess.run(cmd, env=ENV, capture_output=True, text=True, **kw)


def wait_for(fn, what, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = fn()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for: {what}")


def ok(msg):
    print(f"OK {msg}")


def wininfo(wid):
    out = run("xwininfo", "-id", str(wid)).stdout
    grab = lambda label: int(re.search(rf"{label}:\s+(-?\d+)", out).group(1))  # noqa: E731
    return {
        "x": grab("Absolute upper-left X"),
        "y": grab("Absolute upper-left Y"),
        "w": grab("Width"),
        "h": grab("Height"),
        "mapped": "IsViewable" in out,
    }


def find(title):
    ids = run("xdotool", "search", "--name", f"^{title}$").stdout.split()
    return int(ids[0]) if ids else None


def prop(wid, name):
    return run("xprop", "-id", str(wid), name).stdout.strip()


def has_strut(wid):
    return "not found" not in prop(wid, "_NET_WM_STRUT_PARTIAL")


def screenshot(path):
    run("magick", "import", "-display", DISPLAY, "-window", "root", path)


def colours(x, y, w, h, shots):
    """The distinct colours (hex) in a rectangle of the screen."""
    png = os.path.join(shots, "probe.png")
    screenshot(png)
    out = run("magick", png, "-crop", f"{w}x{h}+{x}+{y}", "+repage", "-unique-colors", "-depth", "8", "txt:-").stdout
    return {c.upper() for c in re.findall(r"#([0-9A-Fa-f]{6})", out)}


def pixel(x, y, shots):
    png = os.path.join(shots, "probe.png")
    screenshot(png)
    out = run("magick", png, "-crop", "1x1+%d+%d" % (x, y), "+repage", "-format", "%[hex:p{0,0}]", "info:").stdout
    return out.strip().upper()


class FakeExtension:
    def __init__(self, path, browser, pid):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(path)
        self.sock.setblocking(False)
        self.buf = b""
        self.send({"type": "hello", "browser": browser, "version": "1", "browserPid": pid})
        self.state = (
            {
                "type": "state",
                "focusedWindowId": 1,
                "containers": [
                    {"cookieStoreId": "firefox-container-1", "name": "Personal", "colorCode": "#37adff", "icon": "fingerprint"},
                    {"cookieStoreId": "firefox-container-2", "name": "Work", "colorCode": "#ff9f00", "icon": "briefcase"},
                ],
                "windows": [
                    {
                        "id": 1,
                        "tabs": [
                            {"id": 1, "index": 0, "title": f"{browser}: start page", "cookieStoreId": "firefox-default", "active": True, "favIconUrl": ICON},
                            {"id": 2, "index": 1, "title": f"{browser}: a much longer title that has to be ellipsized nicely", "cookieStoreId": "firefox-default", "favIconUrl": ICON},
                            {"id": 3, "index": 2, "title": f"{browser}: mail", "cookieStoreId": "firefox-container-1", "favIconUrl": ICON},
                            {"id": 4, "index": 3, "title": f"{browser}: tickets", "cookieStoreId": "firefox-container-2", "favIconUrl": ICON},
                        ],
                    }
                ],
            }
        )
        self.send(self.state)

    def send(self, obj):
        self.sock.sendall(json.dumps(obj).encode() + b"\n")

    def received(self):
        try:
            self.buf += self.sock.recv(65536)
        except BlockingIOError:
            pass
        head, _, self.buf = self.buf.rpartition(b"\n")
        return [json.loads(line) for line in head.split(b"\n") if line]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", help="keep screenshots here")
    args = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="tabdock-x11-")
    shots = args.shots or tmp
    os.makedirs(shots, exist_ok=True)
    procs = []
    try:
        xdg = os.path.join(tmp, "xdg")
        os.makedirs(os.path.join(xdg, "tabdock"))
        cfg = os.path.join(xdg, "tabdock", "config.toml")

        def write_cfg(**opts):
            opts = {"icons": True, **opts}  # icons are off by default; this test wants to see them drawn
            with open(cfg, "w") as f:
                for key, value in opts.items():
                    f.write(f"{key} = {json.dumps(value)}\n")
            os.kill(panel.pid, signal.SIGHUP)

        sock_path = os.path.join(tmp, "sp.sock")

        procs.append(subprocess.Popen(
            ["Xephyr", DISPLAY, "-screen", f"{SCREEN[0]}x{SCREEN[1]}", "-ac", "-br", "-noreset", "-name", "tabdock-e2e"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ))
        wait_for(lambda: run("xdpyinfo").returncode == 0, "Xephyr")
        procs.append(subprocess.Popen(["openbox", "--config-file", "/etc/xdg/openbox/rc.xml"], env=ENV,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        wait_for(lambda: "window id" in run("xprop", "-root", "_NET_SUPPORTING_WM_CHECK").stdout, "openbox")

        def xterm(name, cls, x):
            p = subprocess.Popen(["xterm", "-name", name, "-class", cls, "-title", cls, "-geometry", f"50x12+{x}+100"],
                                 env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            procs.append(p)
            wid = wait_for(lambda: run("xdotool", "search", "--class", f"^{cls}$").stdout.split() or None, f"xterm {cls}")[0]
            return p, int(wid)

        ff_proc, ff_win = xterm("Navigator", "firefox", 500)
        zen_proc, zen_win = xterm("zen", "zen", 700)
        term_proc, term_win = xterm("xterm", "plainterm", 900)
        ok("fake browsers (firefox, zen) and a plain terminal are running")

        with open(cfg, "w") as f:
            f.write(f'side = "left"\nwidth = {WIDTH}\nicons = true\n')
        layout_dump = os.path.join(tmp, "rows.json")
        panel_env = {**ENV, "XDG_CONFIG_HOME": xdg, "TABDOCK_SOCKET": sock_path, "TABDOCK_LAYOUT_DUMP": layout_dump}
        panel_log = open(os.path.join(tmp, "panel.log"), "w")
        panel = subprocess.Popen([os.path.join(ROOT, "tabdock")], env=panel_env, stdout=panel_log, stderr=subprocess.STDOUT)
        procs.append(panel)
        wait_for(lambda: os.path.exists(sock_path), "panel socket")
        strip = wait_for(lambda: find("tabdock-strip"), "strip window")
        wait_for(lambda: wininfo(strip)["mapped"], "strip mapped")

        def panel_win():
            return find("tabdock-panel")  # not "tabdock": GTK's hidden leader window owns that

        def panel_mapped():
            wid = panel_win()
            return wid is not None and wininfo(wid)["mapped"]

        def expand():
            run("xdotool", "mousemove", "0", "400")
            wait_for(panel_mapped, "panel expanded on hover")
            wait_for(lambda: wininfo(panel_win())["w"] == WIDTH, "panel at full width")

        def collapse(x=900):
            run("xdotool", "mousemove", str(x), "600")
            wait_for(lambda: not panel_mapped(), "panel collapsed after leaving")

        # -- dock type, strip geometry, no strut while autohiding -------------------------
        assert "_NET_WM_WINDOW_TYPE_DOCK" in prop(strip, "_NET_WM_WINDOW_TYPE"), prop(strip, "_NET_WM_WINDOW_TYPE")
        info = wininfo(strip)
        assert (info["x"], info["y"], info["w"], info["h"]) == (0, 0, STRIP, SCREEN[1]), info
        assert not has_strut(strip)
        assert not panel_mapped(), "panel must stay unmapped until hovered"
        ok(f"dock strip: {STRIP}px wide at the left edge, full height, no strut, panel unmapped")

        ff = FakeExtension(sock_path, "Firefox", ff_proc.pid)
        zen = FakeExtension(sock_path, "Zen", zen_proc.pid)  # keep a reference: closing the socket = browser gone

        # -- the collapsed strip shows which browser is active ------------------------------
        run("xdotool", "windowactivate", "--sync", str(ff_win))
        wait_for(lambda: pixel(1, 400, shots) == COLOURS["Firefox"], "strip tinted like Firefox")
        run("xdotool", "windowactivate", "--sync", str(zen_win))
        wait_for(lambda: pixel(1, 400, shots) == COLOURS["Zen"], "strip tinted like Zen")
        ok("collapsed strip colour follows the active browser (Firefox orange <-> Zen purple)")
        run("xdotool", "windowactivate", "--sync", str(ff_win))
        wait_for(lambda: pixel(1, 400, shots) == COLOURS["Firefox"], "strip back to Firefox")

        # -- hover expands, leaving collapses -------------------------------------------------
        expand()
        assert not has_strut(panel_win()), "autohide overlay must not reserve space"
        screenshot(os.path.join(shots, "expanded-firefox.png"))
        collapse()
        ok("hover expands to the configured width (no strut), leaving collapses it")

        # -- clicking a tab reaches the browser; focus is not stolen from it -------------------
        def layout():
            with open(layout_dump) as f:
                return {(r["kind"], r["id"]): r for r in json.load(f)}

        def settled_layout():
            """The row positions once the expanded panel has been laid out (header taller than nothing)."""
            try:
                rows = layout()
                return rows if rows[("section", "firefox-default")]["y"] > 10 else None
            except (OSError, ValueError, KeyError):
                return None

        def click_a_tab():
            # where the rows really are (the layout dump), not a guess that depends on fonts and theme
            tab = wait_for(settled_layout, "row positions of the expanded panel")[("tab", 3)]
            run("xdotool", "mousemove", str(tab["x"] + 60), str(int(tab["y"] + tab["h"] / 2)))
            time.sleep(0.3)  # like a hand: a tooltip from a row passed over goes away before the click
            run("xdotool", "click", "1")
            time.sleep(0.4)
            return [m for m in ff.received() if m.get("type") == "activate_tab"]

        expand()
        got = click_a_tab()
        assert got, "no click on the panel produced activate_tab"
        assert got[0]["windowId"] == 1 and got[0]["tabId"] in (1, 2, 3, 4), got
        active = int(run("xdotool", "getactivewindow").stdout)
        assert active == ff_win, f"panel click stole focus (active={active}, browser={ff_win})"
        ok(f"click on a tab sends activate_tab (tab {got[0]['tabId']}) and the browser keeps focus")
        collapse()

        # -- other app active + follow=last: clicking a tab raises the browser -----------------
        run("xdotool", "windowactivate", "--sync", str(term_win))
        time.sleep(0.4)
        assert pixel(1, 400, shots) == COLOURS["Firefox"], "follow=last should keep the last browser's colour"
        expand()
        assert click_a_tab(), "no activate_tab while terminal active"
        wait_for(lambda: int(run("xdotool", "getactivewindow").stdout) == ff_win, "browser raised by the panel")
        ok("clicking a tab while another app is active brings the browser forward")
        collapse()

        # -- reordering with a real pointer: drag container sections and tabs -------------------------
        def messages(kind):
            time.sleep(0.4)
            return [m for m in ff.received() if m.get("type") == kind]

        def press_and_move(src, x1, y1):
            x0, y0 = src["x"] + 60, int(src["y"] + src["h"] / 2)
            run("xdotool", "mousemove", str(x0), str(y0))
            time.sleep(0.1)
            run("xdotool", "mousedown", "1")
            time.sleep(0.1)
            run("xdotool", "mousemove", str(x0), str(y0 + 12))  # past the drag threshold
            time.sleep(0.15)
            run("xdotool", "mousemove", str(x1), str(y1))
            time.sleep(0.2)

        ff.received()  # drop anything left over
        expand()
        rows = wait_for(settled_layout, "row positions of the expanded panel")
        work, personal = rows[("section", "firefox-container-2")], rows[("section", "firefox-container-1")]
        assert work["y"] > personal["y"], "the fake browser lists Personal before Work"
        # Work onto the top half of Personal, with the pointer OUTSIDE the panel
        press_and_move(work, WIDTH + 200, int(personal["y"] + 3))
        time.sleep(0.7)  # longer than the 400 ms close delay: a drag must keep the panel open
        assert panel_mapped(), "the panel closed while a drag was in progress"
        screenshot(os.path.join(shots, "dragging-section.png"))  # for a look at the drop marker
        run("xdotool", "mouseup", "1")
        got = messages("set_container_order")
        assert got and got[-1]["order"] == ["firefox-container-2", "firefox-container-1"], got
        wait_for(lambda: not panel_mapped(), "the panel closes after the drop outside it")
        expand()
        rows = wait_for(lambda: (l := settled_layout()) and l[("section", "firefox-container-2")]["y"]
                        < l[("section", "firefox-container-1")]["y"] and l, "Work redrawn above Personal at once")
        ok("dragging a container section: the new order is sent, the panel stays open during the drag and closes after it")

        first, second = rows[("tab", 1)], rows[("tab", 2)]
        press_and_move(second, second["x"] + 60, int(first["y"] + 2))  # tab 2 onto the top half of tab 1
        run("xdotool", "mouseup", "1")
        got = messages("move_tab")
        assert got and got[-1] == {"type": "move_tab", "tabId": 2, "index": 0}, got
        ok("dragging a tab above another in its container sends move_tab with the final index")

        rows = wait_for(settled_layout, "row positions again")
        elsewhere = rows[("tab", 4)]  # a tab of the Work container, far from tab 1's own group
        press_and_move(rows[("tab", 1)], elsewhere["x"] + 60, int(elsewhere["y"] + elsewhere["h"] / 2))
        run("xdotool", "mouseup", "1")
        assert messages("move_tab") == [], "a tab dropped outside its own container must not move"
        assert messages("activate_tab") == [], "a drag must not also count as a click"
        ok("a tab dragged outside its container is cancelled, and a drag is never also a click")

        rows = wait_for(settled_layout, "row positions once more")
        target = rows[("tab", 3)]
        run("xdotool", "mousemove", str(target["x"] + 60), str(int(target["y"] + target["h"] / 2)))
        # The row we just dragged over shows a tooltip that can sit right on top of this one. A hand
        # moves continuously, and the first motion hides the tooltip; a teleporting test pointer
        # would click the tooltip window instead, so give the move a moment like a person would.
        time.sleep(0.3)
        run("xdotool", "click", "1")
        got = messages("activate_tab")
        assert got and got[-1]["tabId"] == 3, got
        ok("a plain click still activates a tab after all the dragging")

        # closing a tab: the ✕ a hovered tab shows, and a middle click, as in the browser's tab strip
        rows = wait_for(settled_layout, "row positions with the close buttons")
        tab, cross = rows[("tab", 3)], rows[("close", 2)]
        run("xdotool", "mousemove", str(tab["x"] + 60), str(int(tab["y"] + tab["h"] / 2)))
        time.sleep(0.4)
        screenshot(os.path.join(shots, "row-hover.png"))
        assert pixel(tab["x"] + 8, tab["y"] + 2, shots) == "2A2E38", "the tab under the pointer is not highlighted"
        other, mine = rows[("close", 2)], rows[("close", 3)]
        assert colours(other["x"], other["y"], other["w"], other["h"], shots) == {"1B1D23"}, "another tab's ✕ shows"
        assert len(colours(mine["x"], mine["y"], mine["w"], mine["h"], shots)) > 1, "no ✕ on the hovered tab"
        run("xdotool", "mousemove", str(cross["x"] + cross["w"] // 2), str(cross["y"] + cross["h"] // 2))
        time.sleep(0.3)
        screenshot(os.path.join(shots, "close-hover.png"))
        run("xdotool", "click", "1")
        time.sleep(0.4)
        got = ff.received()
        assert [m for m in got if m["type"] == "close_tab"] == [{"type": "close_tab", "tabId": 2}], got
        assert not [m for m in got if m["type"] == "activate_tab"], "the ✕ also activated the tab"
        tab = rows[("tab", 3)]
        run("xdotool", "mousemove", str(tab["x"] + 60), str(int(tab["y"] + tab["h"] / 2)))
        time.sleep(0.3)
        run("xdotool", "click", "2")
        got = messages("close_tab")
        assert got == [{"type": "close_tab", "tabId": 3}], got
        assert int(run("xdotool", "getactivewindow").stdout) == ff_win, "closing took the focus from the browser"
        ok("close: the ✕ of a hovered tab and a middle click send close_tab, and the browser keeps the focus")

        # a container's own menu: rename it in the name window, and removing asks first, Cancel being the default
        def container_menu(*keys):
            # where it is now: the sections dragged into another order earlier go back to the fake browser's order
            # on any redraw, since it never stores an order
            section = wait_for(settled_layout, "row positions")[("section", "firefox-container-1")]
            run("xdotool", "mousemove", str(section["x"] + 60), str(int(section["y"] + section["h"] / 2)))
            time.sleep(0.3)
            run("xdotool", "click", "3")
            time.sleep(0.6)
            assert panel_mapped(), "the panel closed under the container's menu"
            run("xdotool", "key", *keys)

        def active_title():
            return run("xdotool", "getactivewindow", "getwindowname").stdout.strip()

        ff.received()
        container_menu("Down", "Return")  # Rename…
        wait_for(lambda: active_title() == "Rename container", "the rename window, with the keyboard")
        run("xdotool", "type", "--delay", "30", "Private")
        run("xdotool", "key", "Return")
        got = messages("update_container")
        assert got == [{"type": "update_container", "cookieStoreId": "firefox-container-1", "name": "Private"}], got
        wait_for(lambda: int(run("xdotool", "getactivewindow").stdout) == ff_win, "the keyboard back in the browser")
        container_menu("Up", "Return")  # Remove container…, the last item
        wait_for(lambda: active_title() == "Remove container", "the window asking before the removal")
        screenshot(os.path.join(shots, "remove-container.png"))
        run("xdotool", "key", "Return")  # Cancel has the focus: a stray Enter removes nothing
        wait_for(lambda: int(run("xdotool", "getactivewindow").stdout) == ff_win, "the keyboard back in the browser")
        assert messages("remove_container") == [], "Enter removed the container"
        container_menu("Up", "Return")
        wait_for(lambda: active_title() == "Remove container", "the window asking before the removal, again")
        run("xdotool", "key", "Tab", "Return")  # to Remove, then press it
        got = messages("remove_container")
        assert got == [{"type": "remove_container", "cookieStoreId": "firefox-container-1"}], got
        ok("containers: a right click renames one in a window of its own; removing asks first, and Enter means Cancel")
        collapse()

        # -- several browsers: chips choose what is listed, "all" gives each browser a foldable section -----
        def rows_now():
            try:
                with open(layout_dump) as f:
                    return json.load(f)
            except (OSError, ValueError):
                return []

        def count(kind):
            return len([r for r in rows_now() if r["kind"] == kind])

        def of_kind(kind):
            return [r for r in rows_now() if r["kind"] == kind]

        def chip(label):
            return wait_for(lambda: next((r for r in of_kind("chip") if r["id"] == label), None), f"chip {label}")

        def click_row(row):
            run("xdotool", "mousemove", str(row["x"] + row["w"] // 2), str(row["y"] + row["h"] // 2))
            time.sleep(0.3)  # like a hand: a tooltip from the row passed over goes away before the click
            run("xdotool", "click", "1")

        def received(ext, kind):
            time.sleep(0.4)
            return [m for m in ext.received() if m.get("type") == kind]

        expand()
        wait_for(lambda: count("chip") == 4, "chips: auto, Firefox, Zen, all")
        assert count("browser") == 0, "one browser listed: no browser header"
        screenshot(os.path.join(shots, "chips.png"))
        ok("two browsers are open: the panel offers the chips auto, Firefox, Zen and all")

        # -- site icons: drawn before the tab title from the icon the browser reported, off with icons = false
        def icon_green():
            row = of_kind("tab")[0]  # the icon sits in the first 16 px after the row's indent
            return pixel(row["x"] + 30, row["y"] + row["h"] // 2, shots) == "00FF00"

        wait_for(icon_green, "the site icon drawn before the first tab title")
        screenshot(os.path.join(shots, "icons.png"))
        write_cfg(side="left", width=WIDTH, icons=False)
        wait_for(lambda: not icon_green(), "icons switched off by the config")
        write_cfg(side="left", width=WIDTH)
        wait_for(icon_green, "icons back after reloading without the option")
        ok("site icons: drawn before the tab title from the icon the browser reported, and switched by icons = false")

        click_row(chip("all"))
        wait_for(lambda: count("browser") == 2 and count("tab") == 8, "both browsers listed")
        screenshot(os.path.join(shots, "all-browsers.png"))
        ff.received()
        zen.received()
        run("xdotool", "windowactivate", "--sync", str(ff_win))  # Firefox is the browser in use
        click_row(of_kind("tab")[4])  # the first tab of the second browser, Zen
        got = received(zen, "activate_tab")
        assert got and got[0]["tabId"] == 1, got
        assert not received(ff, "activate_tab"), "Firefox was told to activate one of Zen's tabs"
        wait_for(lambda: int(run("xdotool", "getactivewindow").stdout) == zen_win, "Zen raised by the panel")
        ok("all: a click on a tab of the browser not in use reaches that browser and brings its window forward")

        click_row(of_kind("browser")[1])  # the Zen header
        wait_for(lambda: count("tab") == 4 and count("browser") == 2, "Zen folded away")
        screenshot(os.path.join(shots, "all-folded.png"))
        click_row(of_kind("browser")[1])
        wait_for(lambda: count("tab") == 8, "Zen unfolded")
        ok("all: clicking a browser header folds that browser's sections away and back")

        run("xdotool", "windowactivate", "--sync", str(ff_win))
        click_row(chip("Zen"))
        wait_for(lambda: count("browser") == 0 and count("tab") == 4, "only Zen listed")
        collapse()
        wait_for(lambda: pixel(1, 400, shots) == COLOURS["Zen"], "the strip wears the listed browser's colour")
        expand()
        click_row(chip("auto"))
        collapse()
        wait_for(lambda: pixel(1, 400, shots) == COLOURS["Firefox"], "auto follows the browser in use again")
        ok("a chosen browser stays listed while another has the focus; auto follows the focus again")

        write_cfg(side="left", width=WIDTH, view="all")
        wait_for(lambda: count("browser") == 2, "view = all lists every browser")
        write_cfg(side="left", width=WIDTH)
        wait_for(lambda: count("browser") == 0, "back to the browser in use")
        ok('config: view = "all" lists every browser, and reloading without it goes back to auto')

        # a browser that has not been in use since the panel started is found by its process, not remembered:
        # its window took the focus when it opened, but its extension only connects afterwards
        libre_proc, libre_win = xterm("librewolf", "librewolf", 1000)
        run("xdotool", "windowactivate", "--sync", str(ff_win))
        libre = FakeExtension(sock_path, "LibreWolf", libre_proc.pid)
        write_cfg(side="left", width=WIDTH, view="all")
        wait_for(lambda: count("browser") == 3 and count("tab") == 12, "three browsers listed")
        libre.received()
        expand()  # the pointer is out on the desktop after the last step: hover the edge like a person
        click_row(of_kind("tab")[8])  # the first tab of the third browser, LibreWolf
        got = received(libre, "activate_tab")
        assert got and got[0]["tabId"] == 1, got
        wait_for(lambda: int(run("xdotool", "getactivewindow").stdout) == libre_win, "LibreWolf raised by process")
        ok("all: the window of a browser never seen in use is found by its process and raised")
        libre.sock.close()  # the browser goes away
        wait_for(lambda: count("browser") == 2, "two browsers left after LibreWolf closed")
        write_cfg(side="left", width=WIDTH)
        wait_for(lambda: count("browser") == 0, "back to the browser in use")
        libre_proc.terminate()
        collapse()

        # -- workspaces: a chip switches, a right click moves a tab, "+" asks for a name ------------------
        def active_name():
            return run("xdotool", "getactivewindow", "getwindowname").stdout.strip()

        def workspace_chip(name):
            return wait_for(lambda: next((r for r in of_kind("workspace") if r["group"] == name), None), f"chip {name}")

        in_work = ("ws-1", "ws-1", "default", "ws-1")  # tabs 1-4: Work shows 1, 2 and 4; Default has 3
        ws_state = {**ff.state, "workspaces": [{"id": "default", "name": "Default"}, {"id": "ws-1", "name": "Work"}],
                    "windows": [{**ff.state["windows"][0], "workspaceId": "ws-1", "tabs": [
                        {**t, "workspaceId": ws} for t, ws in zip(ff.state["windows"][0]["tabs"], in_work)]}]}
        ff.send(ws_state)
        run("xdotool", "windowactivate", "--sync", str(ff_win))
        expand()
        wait_for(lambda: count("workspace") == 3 and count("tab") == 3, "chips Default, Work and +, and Work's 3 tabs")
        screenshot(os.path.join(shots, "workspaces.png"))
        ff.received()
        click_row(workspace_chip("Default"))
        assert received(ff, "switch_workspace") == [{"type": "switch_workspace", "windowId": 1, "workspaceId": "default"}]
        ok("workspaces: chips above the tabs, only the shown workspace's tabs listed, a click switches")

        row = next(r for r in of_kind("tab") if r["id"] == 2)
        run("xdotool", "mousemove", str(row["x"] + 60), str(row["y"] + row["h"] // 2))
        time.sleep(0.3)
        run("xdotool", "click", "3")
        time.sleep(0.6)  # longer than the close delay: the menu keeps the panel open
        assert panel_mapped(), "the panel closed under its own menu"
        screenshot(os.path.join(shots, "workspace-menu.png"))
        run("xdotool", "key", "Down", "Down", "Return")  # the menu has the keyboard: past "Pin tab" to the move
        moved = received(ff, "move_tab_to_workspace")
        assert moved == [{"type": "move_tab_to_workspace", "tabId": 2, "workspaceId": "default"}], moved
        assert int(run("xdotool", "getactivewindow").stdout) == ff_win, "the menu took the focus from the browser"
        ok("workspaces: a right click on a tab offers the other workspace and moves it there")

        click_row(workspace_chip("+"))
        wait_for(lambda: active_name() == "New workspace", "the name window, with the keyboard")
        screenshot(os.path.join(shots, "workspace-name.png"))
        run("xdotool", "type", "--delay", "30", "Deep work")  # the proposed name is selected: typing replaces it
        run("xdotool", "key", "Return")
        assert received(ff, "new_workspace") == [{"type": "new_workspace", "windowId": 1, "name": "Deep work"}]
        wait_for(lambda: int(run("xdotool", "getactivewindow").stdout) == ff_win, "the keyboard back in the browser")
        ok("workspaces: + asks for a name in a window of its own, then gives the keyboard back to the browser")

        spaces = [{"id": "default", "name": "Default", "icon": None, "color": None, "cookieStoreId": None},
                  {"id": "ws-1", "name": "Work", "icon": None, "color": None, "cookieStoreId": None}]
        ff.send({**ws_state, "workspaces": spaces})  # an extension that keeps an icon, colour and container
        wait_for(lambda: int(run("xdotool", "getactivewindow").stdout) == ff_win, "the browser active")
        expand()
        chip = workspace_chip("Work")
        run("xdotool", "mousemove", str(chip["x"] + chip["w"] // 2), str(chip["y"] + chip["h"] // 2))
        time.sleep(0.3)
        run("xdotool", "click", "3")
        time.sleep(0.6)
        assert panel_mapped(), "the panel closed under the chip's menu"
        screenshot(os.path.join(shots, "workspace-chip-menu.png"))
        # Rename…, Icon, Colour: into its submenu, past None, to Blue
        run("xdotool", "key", "Down", "Down", "Down", "Right", "Down", "Return")
        edits = received(ff, "edit_workspace")
        assert edits == [{"type": "edit_workspace", "workspaceId": "ws-1", "color": "blue"}], edits
        assert int(run("xdotool", "getactivewindow").stdout) == ff_win, "the menu took the focus from the browser"
        ff.send({**ws_state, "workspaces": [spaces[0], {**spaces[1], "icon": "💼", "color": "blue"}]})
        chip = workspace_chip("💼 Work")
        time.sleep(0.3)
        screenshot(os.path.join(shots, "workspace-chip-colour.png"))
        bottom = [pixel(chip["x"] + chip["w"] // 2, chip["y"] + chip["h"] - dy, shots) for dy in (1, 2, 3)]
        assert "37ADFF" in bottom, f"no blue bar under the chip of the workspace shown: {bottom}"
        ok("workspaces: a colour picked in the chip's submenu (the browser keeps the keyboard), worn with its icon")
        ff.send(ff.state)  # the browser without workspaces again, for the steps below
        collapse()

        # -- pin -> strut on the outer edge; unpin removes it -----------------------------------
        write_cfg(side="left", width=WIDTH, pinned=True)
        wait_for(panel_mapped, "pinned panel shown")
        strut = wait_for(lambda: has_strut(panel_win()) and prop(panel_win(), "_NET_WM_STRUT_PARTIAL"), "strut appears when pinned")
        assert f"= {WIDTH}, 0, 0, 0" in strut, strut
        area = run("xprop", "-root", "_NET_WORKAREA").stdout
        assert f"= {WIDTH}, " in area, area  # windows are laid out beside the panel
        screenshot(os.path.join(shots, "pinned.png"))
        write_cfg(side="left", width=WIDTH, pinned=False)
        wait_for(lambda: not has_strut(panel_win()), "strut removed")
        wait_for(lambda: not panel_mapped(), "unpinned panel collapses")
        ok("pinned: panel stays open and reserves work area; unpinned: strut gone, autohide back")

        # -- the pin button itself (header: pin, flip and quit buttons, right-aligned) --------------
        HEADER_Y = 20

        def click_pin_until(condition, what):
            # Sweep clicks across where the pin can be (left of the side-switch button) instead of
            # trusting one pixel offset that depends on fonts and theme padding.
            for x in range(WIDTH - 125, WIDTH - 70, 5):
                run("xdotool", "mousemove", str(x), str(HEADER_Y), "click", "1")
                time.sleep(0.15)
                if condition():
                    return
            raise AssertionError(f"no click on the header's pin region: {what}")

        expand()
        click_pin_until(lambda: has_strut(panel_win()), "strut after clicking the pin button")
        time.sleep(0.3)
        screenshot(os.path.join(shots, "pinned-by-click.png"))
        click_pin_until(lambda: not has_strut(panel_win()), "strut removed after clicking pin again")
        collapse()
        ok("pin button: one click pins (reserves space), the next unpins (autohide again)")

        # -- side switch --------------------------------------------------------------------------
        write_cfg(side="right", width=WIDTH)
        wait_for(lambda: wininfo(strip)["x"] == SCREEN[0] - STRIP, "strip moved to the right edge")
        run("xdotool", "mousemove", str(SCREEN[0] - 1), "400")
        wait_for(panel_mapped, "panel expanded on the right")
        info = wininfo(panel_win())
        assert (info["w"], info["x"]) == (WIDTH, SCREEN[0] - WIDTH), info
        collapse(x=300)
        ok("side = right: strip and expanded panel sit on the right edge")

        # -- follow = hide -------------------------------------------------------------------------
        write_cfg(side="left", width=WIDTH, follow="hide")
        wait_for(lambda: wininfo(strip)["x"] == 0, "back on the left")
        run("xdotool", "windowactivate", "--sync", str(term_win))
        wait_for(lambda: not wininfo(strip)["mapped"], "hidden while a non-browser window is active")
        run("xdotool", "windowactivate", "--sync", str(zen_win))
        wait_for(lambda: wininfo(strip)["mapped"], "visible again for a browser")
        ok("follow = hide: panel disappears over other apps and returns for a browser")

        assert panel.poll() is None, "panel crashed"

        # -- the quit button ends the panel cleanly -----------------------------------------------
        write_cfg(side="left", width=WIDTH)
        expand()
        assert os.path.exists(sock_path)
        for x in (WIDTH - 14, WIDTH - 20, WIDTH - 26):  # the quit button is the rightmost header element
            run("xdotool", "mousemove", str(x), str(HEADER_Y), "click", "1")
            time.sleep(0.2)
            if panel.poll() is not None:
                break
        wait_for(lambda: panel.poll() is not None, "panel exits after the quit button")
        assert panel.returncode == 0, f"panel exit code {panel.returncode}"
        assert not os.path.exists(sock_path), "the panel left its socket behind"
        wait_for(lambda: find("tabdock-strip") is None, "the strip window is gone once the panel exited")
        ok("quit button: the panel exits with code 0, removes its socket and its windows")

        # -- a browser start is enough: the relay launches the real panel, which outlives the relay ---
        relay_env = {**panel_env, "TABDOCK_SOCKET": os.path.join(tmp, "launched.sock"), "XDG_RUNTIME_DIR": tmp}
        relay_env.pop("TABDOCK_NO_LAUNCH", None)
        relay = subprocess.Popen(
            [os.path.join(ROOT, "lib", "native-host", "tabdock-nmhost")],
            env=relay_env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        )
        procs.append(relay)
        launched_strip = wait_for(lambda: find("tabdock-strip"), "the relay never started the panel")
        panel_pid = int(re.search(r"= (\d+)", prop(launched_strip, "_NET_WM_PID")).group(1))
        relay.stdin.close()  # the browser goes away
        relay.wait(timeout=10)
        time.sleep(0.5)
        assert os.path.exists(f"/proc/{panel_pid}"), "the launched panel died together with the relay"
        assert wininfo(launched_strip)["mapped"], "the launched panel lost its strip"
        os.kill(panel_pid, signal.SIGTERM)
        wait_for(lambda: not os.path.exists(f"/proc/{panel_pid}"), "launched panel stops on SIGTERM")
        ok("relay start: opening a browser starts the panel, and it keeps running after the relay exits")

        panel_log.flush()
        log = open(os.path.join(tmp, "panel.log")).read()
        assert "Traceback" not in log and "WARNING" not in log, log
        print("ALL OK")
        return 0
    finally:
        if sys.exc_info()[0] is not None:
            try:
                print("--- panel log ---\n" + open(os.path.join(tmp, "panel.log")).read())
            except OSError:
                pass
        for p in reversed(procs):
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        if not args.shots:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
