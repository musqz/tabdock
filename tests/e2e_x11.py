#!/usr/bin/env python3
"""End-to-end check of the dock panel under a real Openbox (slow, manual; not part of discovery).

Runs the panel inside a nested Xephyr display (a window appears on your desktop while it
runs) with Openbox as window manager. xterm windows stand in for browsers, and this script
plays the extension by talking to the panel socket directly. Needs Xephyr, openbox, xterm,
xdotool, xprop, xwininfo and ImageMagick (`magick`).

Checks: dock type + strip geometry, no strut while autohiding, hover expand/collapse, click on
a tab reaches the browser without stealing focus, the strip colour follows the active browser,
raising the browser when clicking while another app is active, pin -> strut, side switch,
and follow=hide.

    python3 tests/e2e_x11.py [--shots DIR]
"""
import argparse
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DISPLAY = ":92"
ENV = {**os.environ, "DISPLAY": DISPLAY}
WIDTH = 300
STRIP = 3
SCREEN = (1280, 800)
COLOURS = {"Firefox": "FF7139", "Zen": "9D7CD8"}


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
        self.send(
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
                            {"id": 1, "title": f"{browser}: start page", "cookieStoreId": "firefox-default", "active": True},
                            {"id": 2, "title": f"{browser}: a much longer title that has to be ellipsized nicely", "cookieStoreId": "firefox-default"},
                            {"id": 3, "title": f"{browser}: mail", "cookieStoreId": "firefox-container-1"},
                            {"id": 4, "title": f"{browser}: tickets", "cookieStoreId": "firefox-container-2"},
                        ],
                    }
                ],
            }
        )

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

    tmp = tempfile.mkdtemp(prefix="sidepanel-x11-")
    shots = args.shots or tmp
    os.makedirs(shots, exist_ok=True)
    procs = []
    try:
        xdg = os.path.join(tmp, "xdg")
        os.makedirs(os.path.join(xdg, "openbox-sidepanel"))
        cfg = os.path.join(xdg, "openbox-sidepanel", "config.toml")

        def write_cfg(**opts):
            with open(cfg, "w") as f:
                for key, value in opts.items():
                    f.write(f"{key} = {json.dumps(value)}\n")
            os.kill(panel.pid, signal.SIGHUP)

        sock_path = os.path.join(tmp, "sp.sock")

        procs.append(subprocess.Popen(
            ["Xephyr", DISPLAY, "-screen", f"{SCREEN[0]}x{SCREEN[1]}", "-ac", "-br", "-noreset", "-name", "sidepanel-e2e"],
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
            f.write(f'side = "left"\nwidth = {WIDTH}\n')
        panel_env = {**ENV, "XDG_CONFIG_HOME": xdg, "SIDEPANEL_SOCKET": sock_path}
        panel_log = open(os.path.join(tmp, "panel.log"), "w")
        panel = subprocess.Popen([os.path.join(ROOT, "sidepanel")], env=panel_env, stdout=panel_log, stderr=subprocess.STDOUT)
        procs.append(panel)
        wait_for(lambda: os.path.exists(sock_path), "panel socket")
        strip = wait_for(lambda: find("openbox-sidepanel-strip"), "strip window")
        wait_for(lambda: wininfo(strip)["mapped"], "strip mapped")

        def panel_win():
            return find("openbox-sidepanel-panel")  # not "openbox-sidepanel": GTK's hidden leader window owns that

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
        def click_a_tab():
            for y in range(70, 260, 8):
                run("xdotool", "mousemove", "120", str(y), "click", "1")
                time.sleep(0.15)
                got = [m for m in ff.received() if m.get("type") == "activate_tab"]
                if got:
                    return got
            return []

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
        wait_for(lambda: find("openbox-sidepanel-strip") is None, "the strip window is gone once the panel exited")
        ok("quit button: the panel exits with code 0, removes its socket and its windows")

        # -- a browser start is enough: the relay launches the real panel, which outlives the relay ---
        relay_env = {**panel_env, "SIDEPANEL_SOCKET": os.path.join(tmp, "launched.sock"), "XDG_RUNTIME_DIR": tmp}
        relay_env.pop("SIDEPANEL_NO_LAUNCH", None)
        relay = subprocess.Popen(
            [os.path.join(ROOT, "lib", "native-host", "sidepanel-nmhost")],
            env=relay_env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        )
        procs.append(relay)
        launched_strip = wait_for(lambda: find("openbox-sidepanel-strip"), "the relay never started the panel")
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
