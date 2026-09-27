#!/usr/bin/env python3
"""Two monitors under a real Openbox: does a pinned panel make maximising and tiling respect it on
the right monitor? (slow, manual; a Xephyr window appears on your desktop while it runs)

Xephyr gives Openbox two Xinerama heads side by side, the same thing Openbox uses on real hardware.
GTK sees one wide monitor in this nested display, so which monitor the panel picks is covered by the
unit tests (tests/test_ui.py, tests/test_pure.py) instead. What this checks is the part only a real
window manager can answer: a reservation on the outer LEFT edge shrinks the maximised area of the
left head only, and one on the outer RIGHT edge shrinks the right head only.

    python3 tests/e2e_multihead.py
"""
import json
import os
import signal
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import e2e_x11 as x  # noqa: E402  (its helpers and its nested display)

HEAD = 800  # width of each of the two heads
WIDTH = 300


def maximised_geometry(head_x):
    """Open an xterm on the head starting at head_x, maximise it, return (x, width) of its client area."""
    p = subprocess.Popen(["xterm", "-name", "probe", "-class", "probe", "-geometry", f"40x10+{head_x + 60}+80"],
                         env=x.ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wid = int(x.wait_for(lambda: x.run("xdotool", "search", "--class", "^probe$").stdout.split() or None, "probe xterm")[0])
        time.sleep(0.4)
        x.run("wmctrl", "-i", "-r", str(wid), "-b", "add,maximized_vert,maximized_horz")
        time.sleep(0.6)
        info = x.wininfo(wid)
        return info["x"], info["w"]
    finally:
        p.terminate()
        p.wait(timeout=5)
        time.sleep(0.3)


def main():
    tmp = tempfile.mkdtemp(prefix="tabdock-multi-")
    procs = []
    try:
        cfg_dir = os.path.join(tmp, "xdg", "tabdock")
        os.makedirs(cfg_dir)
        cfg = os.path.join(cfg_dir, "config.toml")

        def write_cfg(**opts):
            with open(cfg, "w") as f:
                for key, value in opts.items():
                    f.write(f"{key} = {json.dumps(value)}\n")

        procs.append(subprocess.Popen(
            ["Xephyr", x.DISPLAY, "-screen", f"{HEAD}x600", "-screen", f"{HEAD}x600", "+xinerama", "-ac", "-br", "-noreset"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        x.wait_for(lambda: x.run("xdpyinfo").returncode == 0, "Xephyr")
        heads = x.run("xdpyinfo", "-ext", "XINERAMA").stdout
        assert f"head #0: {HEAD}x600 @ 0,0" in heads and f"head #1: {HEAD}x600 @ {HEAD},0" in heads, heads
        procs.append(subprocess.Popen(["openbox", "--config-file", "/etc/xdg/openbox/rc.xml"], env=x.ENV,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        x.wait_for(lambda: "window id" in x.run("xprop", "-root", "_NET_SUPPORTING_WM_CHECK").stdout, "openbox")
        x.ok("two Xinerama heads under Openbox")

        base_left = maximised_geometry(0)
        base_right = maximised_geometry(HEAD)
        assert base_right[0] > base_left[0] + HEAD - 50, (base_left, base_right)  # really on different heads
        print(f"   baseline maximised (x, width): left head {base_left}, right head {base_right}")

        # -- outer LEFT edge, pinned: only the left head shrinks ---------------------------------
        write_cfg(side="left", width=WIDTH, pinned=True)
        panel_env = {**x.ENV, "XDG_CONFIG_HOME": os.path.join(tmp, "xdg"), "TABDOCK_SOCKET": os.path.join(tmp, "sp.sock"),
                     "TABDOCK_NO_LAUNCH": "1"}
        panel = subprocess.Popen([os.path.join(x.ROOT, "tabdock")], env=panel_env,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        procs.append(panel)
        panel_win = x.wait_for(lambda: x.find("tabdock-panel"), "panel window")
        x.wait_for(lambda: x.has_strut(panel_win), "the pinned panel reserves space")
        left, right = maximised_geometry(0), maximised_geometry(HEAD)
        assert (left[0] - base_left[0], base_left[1] - left[1]) == (WIDTH, WIDTH), (left, base_left)
        assert right == base_right, f"the right head must be untouched: {right} vs {base_right}"
        x.ok(f"pinned on the outer left edge: the LEFT head's maximised windows start {WIDTH}px in, the right head is unchanged")

        # -- outer RIGHT edge, pinned: only the right head shrinks -------------------------------
        write_cfg(side="right", width=WIDTH, pinned=True)
        os.kill(panel.pid, signal.SIGHUP)
        x.wait_for(lambda: "= 0, %d," % WIDTH in x.prop(panel_win, "_NET_WM_STRUT_PARTIAL"), "strut moves to the right edge")
        left, right = maximised_geometry(0), maximised_geometry(HEAD)
        assert left == base_left, f"the left head must be untouched: {left} vs {base_left}"
        assert (right[0] - base_right[0], base_right[1] - right[1]) == (0, WIDTH), (right, base_right)
        x.ok(f"pinned on the outer right edge: the RIGHT head's maximised windows are {WIDTH}px narrower, the left head is unchanged")

        # -- unpinned: nothing reserved anywhere -------------------------------------------------
        write_cfg(side="right", width=WIDTH, pinned=False)
        os.kill(panel.pid, signal.SIGHUP)
        x.wait_for(lambda: not x.has_strut(panel_win), "strut removed")
        assert (maximised_geometry(0), maximised_geometry(HEAD)) == (base_left, base_right)
        x.ok("unpinned: both heads are back to their full size")
        print("ALL OK")
        return 0
    finally:
        for p in reversed(procs):
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()


if __name__ == "__main__":
    sys.exit(main())
