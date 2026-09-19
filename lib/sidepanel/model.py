"""Pure helpers over the extension's state snapshot (no GTK/GLib, unit-testable)."""

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
