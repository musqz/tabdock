#!/usr/bin/env python3
"""End-to-end check with a real headless Firefox (slow, needs /usr/bin/firefox; not part of discovery).

Scratch profile + throwaway $HOME, so your real profile, ~/.local and native-messaging dir are
untouched. It exercises what ships: install.sh puts the program into the scratch $HOME and the
panel runs from that installed copy; packaging/build-extension.sh builds the .xpi, which is
installed as a temporary add-on through Marionette. Then, against a real `tabdock --debug`:
  browser -> panel : tabs appear, new tabs show up, panel restart triggers a resync
  panel -> browser : `activate <id>` switches the active tab, tabs move, containers reorder, a tab is
                     pinned, unpinned and closed, a container is made, renamed, recoloured, given another
                     icon and removed (its tab closed, its cookies gone)
  workspaces       : create, switch, move a tab, rename, close a workspace's last tab, remove, and an
                     extension restart, each checked against the browser's own tab strip too
                     (skipped in Zen, which has workspaces of its own); an icon and a colour, a container
                     that Ctrl+T's new tab opens in, and the keyboard shortcuts, pressed for real

    python3 tests/e2e_firefox.py [--firefox /usr/bin/firefox]
"""
import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TIMEOUT = 60


class Output:
    """Collects a process's stdout in the background so we can wait for text."""

    def __init__(self, proc):
        self.text = ""
        self.lock = threading.Lock()
        threading.Thread(target=self._pump, args=(proc,), daemon=True).start()

    def _pump(self, proc):
        for line in proc.stdout:
            with self.lock:
                self.text += line

    def wait_for(self, pattern, since=0, timeout=TIMEOUT):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.lock:
                m = re.search(pattern, self.text[since:])
                if m:
                    return m
            time.sleep(0.1)
        with self.lock:
            raise AssertionError(f"timed out waiting for {pattern!r}; output was:\n{self.text[since:]}")

    def mark(self):
        with self.lock:
            return len(self.text)


def last_snapshot(text):
    """The last snapshot in the panel's console output (from its final '== ' header)."""
    return text[text.rfind("== "):]


def tab_order(snapshot):
    """Tab ids in the order the console prints them (tab lines end with ' [id]')."""
    return [int(i) for i in re.findall(r"\[(\d+)\]$", snapshot, re.M)]


def sections(snapshot):
    """[(name, cookieStoreId)] in display order; section lines read '[name] (count) cookieStoreId'."""
    return re.findall(r"^\[(.+?)\] \(\d+\) (\S+)$", snapshot, re.M)


def section_order(snapshot):
    return [name for name, _ in sections(snapshot)]


WS_LINE = r"^workspace(\*| ) (.+?) \{(\S+)\}((?: \S+=\S+)*)$"


def workspace_lines(snapshot):
    """[(shown, name, id)]; workspace lines read 'workspace* Name {id}', the star on the one the window shows,
    and then what else it has ('icon=… color=… cookieStoreId=…')."""
    return [(star == "*", name, i) for star, name, i, _extra in re.findall(WS_LINE, snapshot, re.M)]


def workspace_extras(snapshot):
    """{workspace id: {"icon": …, "color": …, "cookieStoreId": …}}, with only what each one has."""
    return {i: dict(kv.split("=", 1) for kv in extra.split())
            for _star, _name, i, extra in re.findall(WS_LINE, snapshot, re.M)}


def section_tabs(snapshot):
    """{cookieStoreId: [title, ...]} of the tabs the console lists, by container section."""
    tabs, store = {}, None
    for line in snapshot.splitlines():
        head = re.match(r"^\[.+?\] \(\d+\) (\S+)$", line)
        if head:
            store = head.group(1)
            tabs[store] = []
        elif store is not None and re.match(r"^ [ *] .* \[\d+\]$", line):
            tabs[store].append(re.sub(r" \[\d+\]$", "", line[3:]))
    return tabs


def shown_workspace(snapshot):
    return next(((name, i) for shown, name, i in workspace_lines(snapshot) if shown), None)


def listed(snapshot):
    """{title: (id, active)} of the tabs the console lists (the window's workspace only)."""
    return {title: (int(i), star == "*") for star, title, i in re.findall(r"^ ([ *]) (.*) \[(\d+)\]$", snapshot, re.M)}


def eventually(fn, what, timeout=TIMEOUT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if fn():
            return
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for: {what}")


def say(panel, line):
    panel.stdin.write(line + "\n")
    panel.stdin.flush()


class Marionette:
    def __init__(self, port):
        deadline = time.monotonic() + TIMEOUT
        while True:
            try:
                self.sock = socket.create_connection(("127.0.0.1", port))
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.5)
        self.buf = b""
        self.msg_id = 0
        self._recv()  # handshake

    def _recv(self):
        while b":" not in self.buf:
            self.buf += self.sock.recv(65536)
        head, rest = self.buf.split(b":", 1)
        size = int(head)
        while len(rest) < size:
            rest += self.sock.recv(65536)
        self.buf = rest[size:]
        return json.loads(rest[:size])

    def call(self, command, params=None):
        self.msg_id += 1
        data = json.dumps([0, self.msg_id, command, params or {}]).encode()
        self.sock.sendall(str(len(data)).encode() + b":" + data)
        while True:
            msg = self._recv()
            if msg[0] == 1 and msg[1] == self.msg_id:
                if msg[2]:
                    raise RuntimeError(f"{command}: {msg[2]}")
                return msg[3]

    def chrome(self, script):
        """Run privileged browser code (Marionette's chrome context) and return its value."""
        self.call("Marionette:SetContext", {"value": "chrome"})
        try:
            return self.call("WebDriver:ExecuteScript", {"script": script, "args": []})["value"]
        finally:
            self.call("Marionette:SetContext", {"value": "content"})

    def tab_rows(self):
        """The browser's own tab strip: [(title, hidden, pinned, selected)]."""
        rows = self.chrome("return gBrowser.tabs.map(t => [t.label, t.hidden, t.pinned, t.selected])")
        return [tuple(row) for row in rows]

    def strip(self):
        """{title: (hidden, pinned, selected)}, for titles that occur once."""
        return {title: (hidden, pinned, selected) for title, hidden, pinned, selected in self.tab_rows()}

    def visible(self):
        return sorted(title for title, hidden, _pinned, _selected in self.tab_rows() if not hidden)

    def press(self, key):
        """Ctrl+Alt+key, as real key events in the browser window (where extension shortcuts are handled)."""
        held = ["\ue009", "\ue00a"]  # Control, Alt
        steps = ([{"type": "keyDown", "value": k} for k in (*held, key)]
                 + [{"type": "keyUp", "value": k} for k in (key, *reversed(held))])
        self.call("Marionette:SetContext", {"value": "chrome"})
        try:
            self.call("WebDriver:PerformActions", {"actions": [{"type": "key", "id": "keyboard", "actions": steps}]})
            self.call("WebDriver:ReleaseActions", {})
        finally:
            self.call("Marionette:SetContext", {"value": "content"})


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_panel(env):
    installed = os.path.join(env["HOME"], ".local", "bin", "tabdock")  # the copy install.sh made
    proc = subprocess.Popen(
        [installed, "--debug"],
        env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1,
    )
    return proc, Output(proc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--firefox", default="/usr/bin/firefox")
    args = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="tabdock-e2e-")
    procs = []
    try:
        home = os.path.join(tmp, "home")
        profile = os.path.join(tmp, "profile")
        os.makedirs(home)
        os.makedirs(profile)
        env = {**os.environ, "HOME": home, "TABDOCK_SOCKET": os.path.join(tmp, "sp.sock")}
        subprocess.run([os.path.join(ROOT, "install.sh")], env=env, check=True, capture_output=True)

        port = free_port()
        with open(os.path.join(profile, "user.js"), "w") as f:
            f.write(
                f'user_pref("marionette.port", {port});\n'
                'user_pref("privacy.userContext.enabled", true);\n'
                'user_pref("browser.shell.checkDefaultBrowser", false);\n'
                'user_pref("datareporting.policy.dataSubmissionEnabled", false);\n'
                'user_pref("browser.aboutwelcome.enabled", false);\n'
                # as the README asks for workspaces: Firefox closes the window when its last *visible* tab
                # closes, the hidden tabs of the other workspaces with it
                'user_pref("browser.tabs.closeWindowWithLastTab", false);\n'
                # the browser restart in the workspace checks: restore the session, and keep the temporary
                # add-on's storage (Firefox removes a temporary add-on when it quits)
                'user_pref("browser.startup.page", 3);\n'
                'user_pref("extensions.webextensions.keepStorageOnUninstall", true);\n'
            )

        with open(os.path.join(ROOT, "VERSION")) as f:
            version = f.read().strip()
        subprocess.run([os.path.join(ROOT, "packaging", "build-extension.sh")], env={**env, "OUT_DIR": tmp},
                       check=True, capture_output=True)
        xpi = os.path.join(tmp, f"tabdock-{version}.xpi")

        panel, out = start_panel(env)
        procs.append(panel)
        deadline = time.monotonic() + TIMEOUT
        while not os.path.exists(env["TABDOCK_SOCKET"]):
            assert time.monotonic() < deadline, "panel socket never appeared"
            time.sleep(0.1)

        browser = []  # the running browser process: the last one launched

        def launch(*urls):
            ff = subprocess.Popen(
                # system access: the workspace checks read the real tab strip (ignored by browsers that predate it)
                [args.firefox, "--headless", "--no-remote", "--marionette", "--remote-allow-system-access", "--profile",
                 profile, *urls],
                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            procs.append(ff)
            browser[:] = [ff]
            m = Marionette(port)
            m.call("WebDriver:NewSession", {"capabilities": {}})
            m.call("Addon:Install", {"path": xpi, "temporary": True})
            return ff, m

        def restart(m):
            """Quit the browser the way a user does (the session is saved) and start it again."""
            try:
                m.call("Marionette:Quit", {"flags": ["eAttemptQuit"]})
            except (OSError, RuntimeError):
                pass  # the connection may go before the reply
            browser[0].wait(timeout=TIMEOUT)
            return launch()[1]

        ff, m = launch("about:blank")
        print("extension installed; waiting for first snapshot ...")

        first = out.wait_for(r"== (\S+) (\S+) \(pid (\d+)\) window \d+ ==")
        assert int(first.group(3)) == ff.pid, f"browserPid {first.group(3)} != browser pid {ff.pid}"
        out.wait_for(r"New Tab \[(\d+)\]")
        print(f"OK browser->panel: hello ({first.group(1)} {first.group(2)}, pid matches) + snapshot")
        out.wait_for(r"\[Personal\]")
        print("OK containers listed")

        mark = out.mark()
        handle = m.call("WebDriver:NewWindow", {"type": "tab", "focus": True})["handle"]
        m.call("WebDriver:SwitchToWindow", {"handle": handle})
        m.call("WebDriver:Navigate", {"url": "data:text/html,<title>marionette-tab</title>"})
        out.wait_for(r"\* marionette-tab \[\d+\]", since=mark)
        print("OK new tab appears, marked active")

        blank_id = re.findall(r"New Tab \[(\d+)\]", out.text[mark:])[-1]
        mark = out.mark()
        panel.stdin.write(f"activate {blank_id}\n")
        panel.stdin.flush()
        out.wait_for(rf"\* New Tab \[{blank_id}\]", since=mark)
        print("OK panel->browser: activate_tab switched the active tab")

        # -- reordering, in the real browser: tabs.move and the stored container order --------------
        for title in ("tab-c", "tab-d"):
            handle = m.call("WebDriver:NewWindow", {"type": "tab", "focus": True})["handle"]
            m.call("WebDriver:SwitchToWindow", {"handle": handle})
            m.call("WebDriver:Navigate", {"url": f"data:text/html,<title>{title}</title>"})
        eventually(lambda: "tab-d [" in out.text, "the extra tabs")
        time.sleep(0.5)
        before = tab_order(last_snapshot(out.text))
        assert len(before) >= 4, before
        last = before[-1]  # whichever tab this browser puts last (Zen opens new tabs at the front)

        panel.stdin.write(f"move {last} 0\n")
        panel.stdin.flush()
        eventually(lambda: tab_order(last_snapshot(out.text))[0] == last, "the last tab moved to the front")
        assert tab_order(last_snapshot(out.text)) == [last] + before[:-1], tab_order(last_snapshot(out.text))
        print("OK move_tab: tabs.move put the tab first in the real tab strip")

        # The containers this browser really has (FireDragon and Waterfox ship other defaults than Firefox).
        original = sections(last_snapshot(out.text))
        containers = [s for s in original if s[1] != "firefox-default"]
        assert len(containers) >= 2, f"need two containers to reorder, got {original}"
        first_id, last_id = containers[0][1], containers[-1][1]
        wanted_ids = [last_id, first_id] + [i for _, i in containers if i not in (first_id, last_id)]
        by_id = dict((i, n) for n, i in original)
        wanted = [n for n, i in original if i == "firefox-default"] + [by_id[i] for i in wanted_ids]
        panel.stdin.write(f"order {last_id},{first_id}\n")  # the last container first, then the first
        panel.stdin.flush()
        eventually(lambda: section_order(last_snapshot(out.text)) == wanted, f"the container order {wanted}")
        print(f"OK set_container_order: {by_id[last_id]} now precedes {by_id[first_id]}, stored by the extension")

        home_handle = m.call("WebDriver:GetWindowHandle")["value"]
        handle = m.call("WebDriver:NewWindow", {"type": "tab", "focus": False})["handle"]
        m.call("WebDriver:SwitchToWindow", {"handle": handle})
        m.call("WebDriver:Navigate", {"url": "data:text/html,<title>pin-me</title>"})
        m.call("WebDriver:SwitchToWindow", {"handle": home_handle})  # (the tab to close must not be Marionette's)
        eventually(lambda: "pin-me" in listed(last_snapshot(out.text)), "pin-me listed")
        pin_me = listed(last_snapshot(out.text))["pin-me"][0]
        say(panel, f"pin {pin_me}")
        eventually(lambda: m.strip()["pin-me"][1], "pin-me pinned in the browser")
        say(panel, f"unpin {pin_me}")
        eventually(lambda: not m.strip()["pin-me"][1], "pin-me unpinned")
        say(panel, f"close {pin_me}")
        eventually(lambda: "pin-me" not in m.strip() and "pin-me" not in listed(last_snapshot(out.text)), "pin-me gone")
        print("OK pin_tab, close_tab: the panel pins, unpins and closes a tab in the browser")

        say(panel, "cnew e2e box")
        eventually(lambda: "e2e box" in dict(sections(last_snapshot(out.text))), "the new container listed")
        box = dict(sections(last_snapshot(out.text)))["e2e box"]
        user_context = int(box.rsplit("-", 1)[1])
        identity = lambda: m.chrome(  # noqa: E731
            f"const i = ContextualIdentityService.getPublicIdentityFromId({user_context}); return i && [i.name, i.color, i.icon]")
        assert identity()[2] == "circle", identity()
        say(panel, f"crename {box} e2e renamed")
        say(panel, f"ccolor {box} purple")
        say(panel, f"cicon {box} fruit")
        eventually(lambda: identity() == ["e2e renamed", "purple", "fruit"], "renamed, recoloured and re-iconed")
        eventually(lambda: "e2e renamed" in dict(sections(last_snapshot(out.text))), "the new name listed")
        print("OK create_container, update_container: made, renamed, recoloured and given another icon in the browser")

        say(panel, f"newtab {box}")
        eventually(lambda: section_tabs(last_snapshot(out.text)).get(box) == ["New Tab"], "a tab in the container")
        cookies = lambda: m.chrome(  # noqa: E731
            f"return Services.cookies.cookies.filter(c => c.originAttributes.userContextId == {user_context}).length")
        m.chrome(f"""Services.cookies.add("example.com", "/", "e2e", "1", true, false, false, Date.now() + 3600e3,
                     {{ userContextId: {user_context} }}, Ci.nsICookie.SAMESITE_NONE, Ci.nsICookie.SCHEME_HTTPS, false)""")
        assert cookies() == 1, "the test cookie was not stored"
        say(panel, f"crm {box}")
        eventually(lambda: box not in [i for _n, i in sections(last_snapshot(out.text))], "the container gone from the panel")
        eventually(lambda: identity() is None, "the container gone from the browser")
        assert m.chrome(f"return gBrowser.tabs.filter(t => t.userContextId == {user_context}).length") == 0, "its tab stayed"
        assert cookies() == 0, "its cookies stayed"
        print("OK remove_container: its tab closed, the container and its cookies gone")
        before = m.chrome("return gBrowser.tabs.length")
        say(panel, "crm firefox-default")  # "No container" is no container: nothing may close
        time.sleep(1.5)
        assert m.chrome("return gBrowser.tabs.length") == before, "removing 'No container' closed tabs"
        print("OK remove_container refuses what is not a container, and closes nothing")
        m.call("WebDriver:SwitchToWindow", {"handle": home_handle})  # the tab in use before, as the checks below expect

        panel.terminate()
        panel.wait(timeout=TIMEOUT)
        panel, out = start_panel(env)
        procs.append(panel)
        out.wait_for(r"== \S+ .* window \d+ ==")
        out.wait_for(r"marionette-tab \[\d+\]")
        eventually(lambda: section_order(last_snapshot(out.text)) == wanted, "the order after a panel restart")
        print("OK panel restart: relay reconnected, extension resynced, and the container order survived")

        if first.group(1) == "Zen" or "Zen" in last_snapshot(out.text).splitlines()[0]:
            print("SKIP workspaces: Zen has workspaces of its own, the panel offers none there")
        else:
            check_workspaces(m, panel, out, restart)
        print("ALL OK")
        return 0
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
        shutil.rmtree(tmp, ignore_errors=True)


def check_workspaces(m, panel, out, restart):
    snap = lambda: last_snapshot(out.text)  # noqa: E731
    assert workspace_lines(snap()) == [(True, "Default", "default")], workspace_lines(snap())
    home = listed(snap())
    assert {"marionette-tab", "tab-c", "tab-d"} <= set(home), home
    assert not any(hidden for _t, hidden, _p, _s in m.tab_rows()), "a tab was hidden before any workspace existed"
    home_active = next(title for title, (_i, active) in home.items() if active)
    print("OK one Default workspace until you make another, and nothing hidden")

    say(panel, "wsnew Work")
    eventually(lambda: (shown_workspace(snap()) or ("",))[0] == "Work", "the new workspace shown")
    work = shown_workspace(snap())[1]
    eventually(lambda: list(listed(snap())) == ["New Tab"], "only the new workspace's own new tab listed")
    eventually(lambda: m.visible() == ["New Tab"], "the other tabs hidden in the real tab strip")
    print("OK wsnew: a new workspace with a new tab; the Default tabs are hidden in the browser too")

    handle = m.call("WebDriver:NewWindow", {"type": "tab", "focus": True})["handle"]
    m.call("WebDriver:SwitchToWindow", {"handle": handle})
    m.call("WebDriver:Navigate", {"url": "data:text/html,<title>work-tab</title>"})
    eventually(lambda: "work-tab" in listed(snap()), "a tab opened in Work listed")
    assert "marionette-tab" not in listed(snap())
    print("OK a tab opened while Work shows joins Work")

    say(panel, "ws default")
    eventually(lambda: shown_workspace(snap()) == ("Default", "default"), "Default shown again")
    eventually(lambda: set(listed(snap())) == set(home), "exactly the Default tabs listed again")
    eventually(lambda: listed(snap())[home_active][1], f"{home_active} active again, the tab last used in Default")
    eventually(lambda: m.strip()["work-tab"][0] and not m.strip()["tab-c"][0], "Work hidden, Default shown")
    print(f"OK ws: back in Default, on {home_active} again; Work's tabs are hidden in the browser")

    tab_c = listed(snap())["tab-c"][0]
    say(panel, f"wsmove {tab_c} {work}")
    eventually(lambda: "tab-c" not in listed(snap()) and m.strip()["tab-c"][0], "tab-c gone to Work")
    say(panel, f"ws {work}")
    eventually(lambda: set(listed(snap())) == {"New Tab", "work-tab", "tab-c"}, "Work with tab-c")
    eventually(lambda: listed(snap())["work-tab"][1], "work-tab active, the tab last used in Work")
    print("OK wsmove: a tab moved to Work shows there, and not in Default")

    say(panel, "ws default")
    eventually(lambda: shown_workspace(snap()) == ("Default", "default") and m.strip()["tab-c"][0], "Default shown")
    m.chrome("gBrowser.selectedTab = gBrowser.tabs.find(t => t.label == 'tab-c')")  # as from "List all tabs"
    eventually(lambda: shown_workspace(snap()) == ("Work", work), "the window follows the hidden tab picked")
    eventually(lambda: not m.strip()["tab-c"][0] and m.strip()["tab-d"][0], "Work shown, Default hidden")
    print("OK picking a hidden tab (the browser's list of all tabs) switches to its workspace")

    say(panel, f"wsrename {work} Deep work")
    eventually(lambda: shown_workspace(snap()) == ("Deep work", work), "the rename")
    print("OK wsrename")

    check_workspace_extras(m, panel, out, work)

    m.chrome("gBrowser.pinTab(gBrowser.tabs.find(t => t.label == 'work-tab'))")
    say(panel, "ws default")
    eventually(lambda: shown_workspace(snap()) == ("Default", "default"), "Default shown")
    eventually(lambda: "work-tab" in listed(snap()) and not m.strip()["work-tab"][0], "the pinned tab in Default")
    m.chrome("gBrowser.unpinTab(gBrowser.tabs.find(t => t.label == 'work-tab'))")
    say(panel, f"ws {work}")
    eventually(lambda: shown_workspace(snap()) == ("Deep work", work), "Work shown")
    eventually(lambda: "work-tab" not in listed(snap()) and m.strip()["work-tab"][0], "unpinned in Default: stays there")
    say(panel, f"wsmove {listed_or_hidden_id(m, out, 'work-tab')} {work}")
    print("OK a pinned tab shows in every workspace; unpinned, it belongs to the one it was unpinned in")

    say(panel, "wsnew Scratch")
    eventually(lambda: (shown_workspace(snap()) or ("",))[0] == "Scratch", "Scratch shown")
    scratch = shown_workspace(snap())[1]
    eventually(lambda: len(listed(snap())) == 1, "Scratch's one new tab")
    only = next(iter(listed(snap()).values()))[0]
    store = next(i for _name, i in sections(snap()) if i != "firefox-default")
    say(panel, f"wscontainer {scratch} {store}")  # its new tab then opens in this container
    eventually(lambda: workspace_extras(snap()).get(scratch, {}).get("cookieStoreId") == store, "Scratch's container")
    m.chrome("gBrowser.removeTab(gBrowser.selectedTab)")
    eventually(lambda: shown_workspace(snap()) == ("Scratch", scratch) and len(listed(snap())) == 1
               and next(iter(listed(snap()).values()))[0] != only, "Scratch kept, with a new tab")
    eventually(lambda: m.visible() == ["New Tab"], "only Scratch's new tab visible in the browser")
    eventually(lambda: section_tabs(snap()).get(store) == ["New Tab"], "that new tab in Scratch's container")
    print("OK closing a workspace's last tab keeps the workspace, with a new tab (in its container, if it has one)")

    # Firefox's default: closing a window's last visible tab closes the window, the hidden tabs with it
    m.chrome('Services.prefs.setBoolPref("browser.tabs.closeWindowWithLastTab", true)')
    hidden = sorted(title for title, is_hidden, _p, _s in m.tab_rows() if is_hidden)
    only = next(iter(listed(snap()).values()))[0]
    say(panel, f"close {only}")
    eventually(lambda: len(listed(snap())) == 1 and next(iter(listed(snap()).values()))[0] != only,
               "Scratch's tab closed by the panel, and a new one in its place")
    assert sorted(title for title, is_hidden, _p, _s in m.tab_rows() if is_hidden) == hidden, "the window kept its tabs"
    assert shown_workspace(snap()) == ("Scratch", scratch), shown_workspace(snap())
    print("OK closing a workspace's only tab from the panel keeps the window, whatever closeWindowWithLastTab says")

    temp = m.chrome('return ContextualIdentityService.create("e2e-scratch", "circle", "red").userContextId')
    doomed = f"firefox-container-{temp}"
    say(panel, f"wscontainer {scratch} {doomed}")
    eventually(lambda: workspace_extras(snap()).get(scratch, {}).get("cookieStoreId") == doomed, "Scratch's new container")
    say(panel, f"close {next(iter(listed(snap()).values()))[0]}")  # the new tab in its place opens in e2e-scratch
    eventually(lambda: section_tabs(snap()).get(doomed) == ["New Tab"], "Scratch's only tab, in e2e-scratch")
    say(panel, f"crm {doomed}")  # still at Firefox's default closeWindowWithLastTab
    eventually(lambda: doomed not in [i for _n, i in sections(snap())], "e2e-scratch removed")
    eventually(lambda: section_tabs(snap())["firefox-default"] == ["New Tab"] and len(listed(snap())) == 1,
               "Scratch's new tab, in no container")
    assert sorted(title for title, is_hidden, _p, _s in m.tab_rows() if is_hidden) == hidden, "the window kept its tabs"
    assert "cookieStoreId" not in workspace_extras(snap())[scratch], workspace_extras(snap())
    m.chrome('Services.prefs.setBoolPref("browser.tabs.closeWindowWithLastTab", false)')
    print("OK removing the container of a workspace's only tab keeps the window, the new tab in no container")

    say(panel, f"wsrm {scratch}")
    eventually(lambda: shown_workspace(snap()) == ("Deep work", work), "its neighbour shown after the removal")
    eventually(lambda: {"work-tab", "tab-c"} <= set(listed(snap())) and len(workspace_lines(snap())) == 2,
               "Scratch's tab moved to its neighbour, nothing closed")
    print("OK wsrm: the tabs of a removed workspace go to its neighbour, nothing is closed")

    before = m.tab_rows()
    mark = out.mark()
    m.chrome("""return (async () => {
        const { AddonManager } = ChromeUtils.importESModule("resource://gre/modules/AddonManager.sys.mjs");
        await (await AddonManager.getAddonByID("openbox-sidepanel@musqz.local")).reload();
    })()""")
    out.wait_for(r"== \S+ .* window \d+ ==", since=mark)
    eventually(lambda: shown_workspace(snap()) == ("Deep work", work), "the workspace after an extension restart")
    eventually(lambda: m.tab_rows() == before, "the same tabs hidden after an extension restart")
    print("OK extension restart: workspaces, membership and hidden tabs come back from storage and the session")

    before = sorted(m.tab_rows())
    listed_before = set(listed(snap()))
    mark = out.mark()
    m = restart(m)
    out.wait_for(r"== \S+ .* window \d+ ==", since=mark)
    eventually(lambda: shown_workspace(snap()) == ("Deep work", work), "the workspace after a browser restart")
    assert workspace_extras(snap())[work] == {"icon": "💼", "color": "blue"}, workspace_extras(snap())
    eventually(lambda: set(listed(snap())) == listed_before, "the same tabs listed after a browser restart")
    eventually(lambda: sorted(m.tab_rows()) == before, "the same tabs hidden after a browser restart")
    print("OK browser restart: the same workspaces, the same tabs in each, the others hidden again")

    say(panel, f"wsrm {work}")
    eventually(lambda: workspace_lines(snap()) == [(True, "Default", "default")], "only Default left")
    eventually(lambda: not any(hidden for _t, hidden, _p, _s in m.tab_rows()), "every tab visible again")
    print("OK removing all but one workspace shows every tab again")


def check_workspace_extras(m, panel, out, work):
    """Work shows, next to Default. Its icon and colour; the container its new tabs open in; the shortcuts."""
    snap = lambda: last_snapshot(out.text)  # noqa: E731
    say(panel, f"wsicon {work} 💼")
    say(panel, f"wscolor {work} blue")
    eventually(lambda: workspace_extras(snap()).get(work) == {"icon": "💼", "color": "blue"}, "Work's icon and colour")
    say(panel, f"wscolor {work} plaid")
    eventually(lambda: workspace_extras(snap()).get(work) == {"icon": "💼"}, "a colour containers do not have: none")
    say(panel, f"wscolor {work} blue")
    eventually(lambda: workspace_extras(snap()).get(work) == {"icon": "💼", "color": "blue"}, "blue again")
    print("OK wsicon, wscolor: kept by the extension and reported with the workspace; an unknown colour clears it")

    store = next(i for _name, i in sections(snap()) if i != "firefox-default")  # this browser's first container
    user_context = int(store.rsplit("-", 1)[1])
    say(panel, f"wscontainer {work} {store}")
    eventually(lambda: workspace_extras(snap()).get(work, {}).get("cookieStoreId") == store, "Work's container")
    in_store, no_container = len(section_tabs(snap()).get(store, [])), len(section_tabs(snap())["firefox-default"])
    m.chrome("BrowserCommands.openTab()")  # Ctrl+T: a new tab, in no container
    eventually(lambda: len(section_tabs(snap()).get(store, [])) == in_store + 1, "Ctrl+T's tab listed in the container")
    eventually(lambda: m.chrome("return gBrowser.selectedTab.userContextId") == user_context,
               "the browser's selected tab is that container's")
    assert len(section_tabs(snap())["firefox-default"]) == no_container, "the no-container original is gone"
    print("OK wscontainer: a new tab (Ctrl+T) in a workspace with a container reopens in that container")

    no_container = len(section_tabs(snap())["firefox-default"])
    say(panel, "newtab firefox-default")  # the panel's "+" of "No container": asked for, so it stays there
    eventually(lambda: len(section_tabs(snap())["firefox-default"]) == no_container + 1, "the panel's no-container tab")
    time.sleep(1)
    assert len(section_tabs(snap())["firefox-default"]) == no_container + 1, section_tabs(snap())
    print("OK a tab the panel opens in no container stays there, whatever the workspace's container")

    temp = m.chrome('return ContextualIdentityService.create("e2e-temp", "circle", "red").userContextId')
    say(panel, f"wscontainer {work} firefox-container-{temp}")
    eventually(lambda: workspace_extras(snap()).get(work, {}).get("cookieStoreId") == f"firefox-container-{temp}",
               "Work's container, the temporary one")
    m.chrome(f"ContextualIdentityService.remove({temp})")
    eventually(lambda: "cookieStoreId" not in workspace_extras(snap()).get(work, {}), "a removed container forgotten")
    print("OK a removed container is no longer a workspace's container")

    default_tab = next(title for title, hidden, pinned, _s in m.tab_rows() if hidden and not pinned)
    m.press("\ue00f")  # Ctrl+Alt+PageDown: the next workspace, round the list (Work is the last)
    eventually(lambda: shown_workspace(snap()) == ("Default", "default"), "Ctrl+Alt+PageDown: Default")
    eventually(lambda: not m.strip()[default_tab][0], "Default's tabs shown in the browser")
    m.press("\ue00e")  # Ctrl+Alt+PageUp: the previous one, round the list
    eventually(lambda: shown_workspace(snap()) == ("Deep work", work), "Ctrl+Alt+PageUp: Work")
    m.press("1")
    eventually(lambda: shown_workspace(snap()) == ("Default", "default"), "Ctrl+Alt+1: Default")
    m.press("2")
    eventually(lambda: shown_workspace(snap()) == ("Deep work", work), "Ctrl+Alt+2: Work")
    m.press("3")  # there is no third workspace
    time.sleep(1)
    assert shown_workspace(snap()) == ("Deep work", work), shown_workspace(snap())
    print("OK keyboard shortcuts: Ctrl+Alt+PageDown/PageUp go round the workspaces, Ctrl+Alt+N picks the Nth")


def listed_or_hidden_id(m, out, title):
    """A tab's id from the panel's latest listing, whichever workspace shows it."""
    ids = re.findall(rf"^ [ *] {re.escape(title)} \[(\d+)\]$", out.text, re.M)
    return ids[-1]


if __name__ == "__main__":
    sys.exit(main())
