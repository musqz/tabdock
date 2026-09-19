"""Pure helpers over the extension's state snapshot (no GTK/GLib, unit-testable)."""
import os

NO_CONTAINER = "firefox-default"


def focused_window(state):
    windows = state.get("windows") or []
    for w in windows:
        if w["id"] == state.get("focusedWindowId"):
            return w
    return windows[0] if windows else None


def window_of_tab(state, tab_id):
    for w in state.get("windows") or []:
        if any(t["id"] == tab_id for t in w["tabs"]):
            return w["id"]
    return None


def group_tabs(state):
    """[(container, [tab, ...])] for the focused window.

    No-container tabs first, then every known container in the browser's order
    (empty ones included, they are targets for "new tab here"), then any
    unknown cookie store.
    """
    win = focused_window(state)
    if win is None:
        return []
    by_store = {}
    for tab in win["tabs"]:
        by_store.setdefault(tab.get("cookieStoreId") or NO_CONTAINER, []).append(tab)

    groups = []
    if NO_CONTAINER in by_store:
        groups.append(({"cookieStoreId": NO_CONTAINER, "name": "No container"}, by_store.pop(NO_CONTAINER)))
    for container in state.get("containers") or []:
        groups.append((container, by_store.pop(container["cookieStoreId"], [])))
    for store, tabs in by_store.items():
        groups.append(({"cookieStoreId": store, "name": store}, tabs))
    return groups


ACCENTS = {"firefox": "#ff7139", "zen": "#9d7cd8", "firedragon": "#e5484d", "librewolf": "#3fa9f5"}
DEFAULT_ACCENT = "#8f9bb3"


def accent(info):
    """Colour identifying a browser, so the active one is recognisable at a glance."""
    name = (info.get("browser") or "").lower()
    for key, colour in ACCENTS.items():
        if key in name:
            return colour
    return DEFAULT_ACCENT


def ancestors(pid):
    """[pid, parent, grandparent, ...] from /proc, stopping at init or on any error."""
    chain = []
    while pid and pid > 1 and pid not in chain:
        chain.append(pid)
        try:
            with open(f"/proc/{pid}/stat") as f:
                # "pid (comm) state ppid ..." and comm may contain spaces or parens
                pid = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
    return chain


def owns_window(browser_pid, window_pid):
    """True if the window belongs to the browser process or one of its children.

    One direction only: the terminal or launcher that started the browser is an
    ancestor of it and must not count as the browser.
    """
    return browser_pid in ancestors(window_pid)


def match_browser(browsers, window_pid, wm_class):
    """Key of the browser owning an X window, or None.

    `browsers` maps key -> hello message. The process tree decides; the window class
    ("firefox", "zen", ...) is only a fallback for a browser or window whose pid is unknown.
    """
    if window_pid:
        chain = ancestors(window_pid)
        for key, info in browsers.items():
            if info.get("browserPid") in chain:
                return key
    for key, info in browsers.items():
        if window_pid and info.get("browserPid"):
            continue  # both pids are known and do not line up: not this browser
        name = (info.get("browser") or "").lower()
        if name and any(part.lower() == name or part.lower().startswith(name + "-") for part in wm_class):
            return key
    return None


KNOWN_BROWSERS = (
    ("zen", "Zen"),
    ("firedragon", "FireDragon"),
    ("librewolf", "LibreWolf"),
    ("floorp", "Floorp"),
    ("waterfox", "Waterfox"),
    ("firefox", "Firefox"),
)


def detect_browser(info):
    """Display name of the browser behind a hello message.

    browser.runtime.getBrowserInfo() cannot be trusted (Zen reports "Firefox"), so look at
    the executable of the process that started the relay first.
    """
    pid = info.get("browserPid")
    if pid:
        try:
            exe = os.readlink(f"/proc/{pid}/exe")
        except OSError:
            exe = ""
        tail = "/".join(exe.lower().split("/")[-2:])  # e.g. "zen-browser-bin/zen-bin"
        for key, name in KNOWN_BROWSERS:
            if key in tail:
                return name
    return info.get("browser") or "browser"


def browser_label(info):
    label = f'{info.get("browser", "?")} {info.get("version", "")}'.strip()
    return f'{label} (pid {info["browserPid"]})' if "browserPid" in info else label


def tab_label(tab):
    return tab.get("title") or tab.get("url") or "(untitled)"


def format_state(info, state):
    win = focused_window(state)
    head = f'== {browser_label(info)}' + (f' window {win["id"]}' if win else " (no windows)") + " =="
    lines = [head]
    for container, tabs in group_tabs(state):
        lines.append(f'[{container["name"]}] ({len(tabs)})')
        for tab in tabs:
            lines.append(f' {"*" if tab.get("active") else " "} {tab_label(tab)} [{tab["id"]}]')
    return "\n".join(lines)
