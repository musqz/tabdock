"""Pure helpers over the extension's state snapshot (no GTK/GLib, unit-testable)."""
import os
import re

NO_CONTAINER = "firefox-default"

# Many sites (forums, mail, chat) prepend an unread count to their tab title, e.g. "(3) Inbox".
# Capped at 3 digits (plus an optional "+", as in "99+") so a year or a numbered list ("(2024) Report")
# is not mistaken for one; a leading "(0)" is excluded separately in `tab_badge`, below.
_BADGE_RE = re.compile(r"^\s*\((\d{1,3}\+?)\)\s*")


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


def workspaces(state):
    """[{id, name, icon, color, cookieStoreId}] of the browser profile; empty from an extension older than
    workspaces, and only {id, name} from one older than the icon, colour and container."""
    return state.get("workspaces") or []


def edits_workspaces(spaces):
    """Whether the extension keeps an icon, a colour and a container for each workspace: it reports all three,
    empty or not. An older one only knows names."""
    return bool(spaces) and all("icon" in ws for ws in spaces)


# Firefox's container colours, as its colorCode gives them: a workspace takes its colour from the same set.
WS_COLORS = {
    "blue": "#37adff", "turquoise": "#00c79a", "green": "#51cd00", "yellow": "#ffcb00", "orange": "#ff9f00",
    "red": "#ff613d", "pink": "#ff4bda", "purple": "#af51f5", "toolbar": "#7c7c7d",
}


def colour_name(color):
    return "Grey" if color == "toolbar" else color.capitalize()  # "toolbar": Firefox's grey


# Firefox's tab group colours, near what its tab strip draws for them.
GROUP_COLORS = {
    "blue": "#3f8cf2", "purple": "#a15fe8", "cyan": "#0cb8c7", "orange": "#f07a1a", "yellow": "#e0b000",
    "pink": "#e553b3", "green": "#3fae48", "gray": "#8f8f9d", "grey": "#8f8f9d", "red": "#e24650",
}


def tab_group(state, tab):
    """The Firefox tab group `tab` is in ({id, title, color, collapsed}), or None."""
    gid = tab.get("groupId")
    return next((g for g in state.get("groups") or [] if g["id"] == gid), None) if gid is not None else None


def removal_text(name, tabs):
    """What the panel asks before removing a container that has `tabs` open tabs (in any window or workspace)."""
    closes = "It has no open tabs" if not tabs else f"Its {tabs} open tab{'s' * (tabs != 1)} will close"
    return (f'Remove the container "{name}"? {closes}, and Firefox deletes its cookies, so you are logged out '
            "of the sites you used in it. This cannot be undone.")


def workspace_label(ws):
    """A workspace as its chip names it: the icon, when it has one, before the name."""
    return f'{ws["icon"]} {ws["name"]}' if ws.get("icon") else ws["name"]


def reopenable(tab):
    """Whether an extension may open this tab's page in another container: web pages and the new-tab page, not
    about:config, file: and the like (Firefox refuses to open those for an extension)."""
    url = tab.get("url") or ""
    return url.startswith(("http:", "https:")) or url in ("about:newtab", "about:home", "about:blank")


# What an extension may say it handles (`features` in its hello), beyond what every version did.
FEATURES = ("close_tab", "pin_tab", "containers", "reopen_in_container", "restore_tab", "bookmarks")


def supports(info, feature):
    """Whether the browser's extension handles `feature` ("close_tab", "pin_tab", "containers"): it lists them in its
    hello. An older one lists none, and the panel then offers only what it can do, never a button that does nothing."""
    return feature in (info.get("features") or ())


def offers_workspaces(info, state):
    """Whether the panel shows workspaces for this browser. Not in Zen, which has workspaces of its own
    (the extension then never hides a tab: nothing there starts using them)."""
    return bool(workspaces(state)) and info.get("browser") != "Zen"


def heir(spaces, ws_id):
    """The workspace that takes over the tabs of a removed one: the one before it, or after it if it is the
    first (the extension does the same). None when it is the only one: the last workspace cannot go."""
    ids = [ws["id"] for ws in spaces]
    if len(ids) < 2 or ws_id not in ids:
        return None
    at = ids.index(ws_id)
    return spaces[at - 1 if at else 1]


def in_workspace(tab, workspace):
    """Whether a tab shows in `workspace` (None: an extension without workspaces, every tab shows).
    Pinned tabs cannot be hidden, so they show in every workspace."""
    return workspace is None or bool(tab.get("pinned")) or tab.get("workspaceId", workspace) == workspace


def matches(tab, query):
    """Whether every word of `query` is in the tab's title or address, whatever the case."""
    text = f'{tab.get("title") or ""} {tab.get("url") or ""}'.casefold()
    return all(word in text for word in query.casefold().split())


def bookmark_rows(tree, query="", folded=()):
    """[(depth, node, path)] of the bookmark tree ({"title", "url"} or {"title", "children"} nodes) in display order.
    `path` names a folder (its indexes joined with "/") for `folded`. With a query only the bookmarks that match
    are listed, flat: a search never hides a match inside a folded folder."""
    rows = []
    if query.strip():
        def walk(nodes):
            for node in nodes:
                if "children" in node:
                    walk(node["children"])
                elif matches(node, query):
                    rows.append((0, node, None))
        walk(tree)
        return rows

    def walk(nodes, depth, parent):
        for at, node in enumerate(nodes):
            if "children" in node:
                path = f"{parent}/{at}"
                rows.append((depth, node, path))
                if path not in folded:
                    walk(node["children"], depth + 1, path)
            else:
                rows.append((depth, node, None))
    walk(tree, 0, "")
    return rows


def group_tabs(state, every_workspace=False):
    """[(container, [tab, ...])] for the focused window, in the workspace it shows (with `every_workspace`: in all
    of them, as a search lists them).

    No-container first, then every known container in the browser's order, then any unknown
    cookie store. No-container and known containers stay even when empty: they are targets for
    "new tab here".
    """
    win = focused_window(state)
    if win is None:
        return []
    by_store = {}
    for tab in win["tabs"]:
        if every_workspace or in_workspace(tab, win.get("workspaceId")):
            by_store.setdefault(tab.get("cookieStoreId") or NO_CONTAINER, []).append(tab)

    groups = [({"cookieStoreId": NO_CONTAINER, "name": "No container"}, by_store.pop(NO_CONTAINER, []))]
    for container in ordered_containers(state):
        groups.append((container, by_store.pop(container["cookieStoreId"], [])))
    for store, tabs in by_store.items():
        groups.append(({"cookieStoreId": store, "name": store}, tabs))
    return groups


def ordered_containers(state):
    """The containers in the user's own order.

    Firefox cannot reorder containers, so the order lives in the extension (`containerOrder`, a
    list of cookieStoreIds). Ids named there come first in that order (ids that no longer exist
    are ignored); containers not named keep the browser's order after them.
    """
    containers = state.get("containers") or []
    by_id = {c["cookieStoreId"]: c for c in containers}
    first = [by_id[i] for i in dict.fromkeys(state.get("containerOrder") or []) if i in by_id]
    named = {c["cookieStoreId"] for c in first}
    return first + [c for c in containers if c["cookieStoreId"] not in named]


def reordered(ids, moved, before=None):
    """`ids` with `moved` placed just before `before`, or last when `before` is None."""
    if before == moved:
        return list(ids)
    rest = [i for i in ids if i != moved]
    at = rest.index(before) if before in rest else len(rest)
    return rest[:at] + [moved] + rest[at:]


def tab_move_index(group, moved_id, before_id=None):
    """The `tabs.move` index for dropping a tab just before another, or last in its container group.

    `group` is the container's tabs, each with its absolute window `index`. The index is the tab's
    final position: the tab leaves its old place first, so moving forward lands one earlier.
    Returns None when the drop would not change anything.
    """
    by_id = {t["id"]: t for t in group}
    moved = by_id[moved_id]
    target = by_id[before_id]["index"] if before_id is not None else max(t["index"] for t in group) + 1
    if moved["index"] < target:
        target -= 1
    return None if target == moved["index"] else target


def step_index(current, count, step):
    """Where the keyboard highlight goes from row `current` (None: nothing yet) after `step` rows of `count`.
    It stops at the ends. From nothing, a step down lands on the first row and a step up on the last."""
    if current is None:
        return 0 if step > 0 else count - 1
    return max(0, min(count - 1, current + step))


def workspace_step(state, step, here=None):
    """(window id, workspace id) to switch the focused window to, `step` workspaces away from `here` (default: the
    one it shows), stopping at the ends. None without such a window or workspace, or with nowhere to go."""
    window = focused_window(state)
    ids = [ws["id"] for ws in workspaces(state)]
    here = here or (window or {}).get("workspaceId")
    if window is None or here not in ids:
        return None
    index = step_index(ids.index(here), len(ids), step)
    return None if ids[index] == here else (window["id"], ids[index])


ACCENTS = {
    "firefox": "#ff7139",
    "zen": "#9d7cd8",
    "firedragon": "#e5484d",
    "librewolf": "#3fa9f5",
    "waterfox": "#2ec4b6",
    "floorp": "#e5b93a",
    "midori": "#8bc34a",
}
DEFAULT_ACCENT = "#8f9bb3"
DARK_TEXT = "#1b1d23"  # the panel's background: the text on a filled accent (a pinned button, a chip picked)


def accents(theme=None):
    """The colour of each browser ACCENTS knows and of any "other" one (and of the strip while none is
    connected), with the config's [theme]: a browser's own key wins over `accent`, which wins over the
    built-in colour."""
    theme = theme or {}
    return {key: theme.get(key) or theme.get("accent") or colour
            for key, colour in {**ACCENTS, "other": DEFAULT_ACCENT}.items()}


def browser_theme_key(info):
    """Which [theme] key (config.THEME_KEYS) a browser's own colour lives under, or "other" for one
    ACCENTS does not know."""
    name = (info.get("browser") or "").lower()
    return next((key for key in ACCENTS if key in name), "other")


def accent(info, colours=None):
    """Colour identifying a browser, so the active one is recognisable at a glance. `colours`: accents()."""
    return (colours or accents())[browser_theme_key(info)]


def _luminance(colour):
    """WCAG relative luminance of "#rrggbb"."""
    channels = (int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    r, g, b = (c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def on_accent(colour):
    """The text colour that reads best on a fill of `colour`: the panel's dark one on the built-in accents
    (all light), white on a dark accent chosen in [theme]."""
    lum, dark = _luminance(colour), _luminance(DARK_TEXT)
    return DARK_TEXT if (lum + 0.05) / (dark + 0.05) >= 1.05 / (lum + 0.05) else "#ffffff"


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
    ("midori", "Midori"),
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


def choice_labels(browsers):
    """[(key, label)] for `browsers` (key -> hello message): the browser's name, numbered
    ("Waterfox 1", "Waterfox 2") only when a name repeats, e.g. two profiles running at once."""
    names = {key: info.get("browser") or "browser" for key, info in browsers.items()}
    seen, labels = {}, []
    for key, name in names.items():
        seen[name] = seen.get(name, 0) + 1
        labels.append((key, name if list(names.values()).count(name) == 1 else f"{name} {seen[name]}"))
    return labels


def browser_label(info):
    label = f'{info.get("browser", "?")} {info.get("version", "")}'.strip()
    return f'{label} (pid {info["browserPid"]})' if "browserPid" in info else label


def tab_label(tab):
    title = tab.get("title")
    if not title:
        return tab.get("url") or "(untitled)"
    return _BADGE_RE.sub("", title, count=1) or tab.get("url") or "(untitled)"


def tab_badge(tab):
    """The leading unread count in the tab's title (see `_BADGE_RE`), or None. A zero count
    (however padded, "0", "00", ...) means nothing is unread, so it is not a badge."""
    m = _BADGE_RE.match(tab.get("title") or "")
    return m.group(1) if m and int(m.group(1).rstrip("+")) != 0 else None


# The Arch package ships the signed extension next to VERSION, two levels above this package
# (packaging/PKGBUILD); a checkout or an install.sh install has none there.
PACKAGED_XPI = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tabdock.xpi"))


def waiting_text(xpi=PACKAGED_XPI):
    """What the panel says while no browser is connected: with the packaged extension, where to find it."""
    text = "Waiting for a browser with the Tabdock extension"
    if not os.path.isfile(xpi):
        return text
    return f"{text}.\n\nInstall it once in each browser: about:addons → gear icon → Install Add-on From File… → {xpi}"


def format_state(info, state):
    win = focused_window(state)
    head = f'== {browser_label(info)}' + (f' window {win["id"]}' if win else " (no windows)") + " =="
    lines = [head]
    for ws in workspaces(state):  # "workspace* Name {id}": the star marks the one the window shows
        mark = "*" if win and ws["id"] == win.get("workspaceId") else " "
        extra = "".join(f" {key}={ws[key]}" for key in ("icon", "color", "cookieStoreId") if ws.get(key))
        lines.append(f'workspace{mark} {ws["name"]} {{{ws["id"]}}}{extra}')
    for group in state.get("groups") or []:  # "tabgroup Title (color): 3,7", the tab ids in it
        ids = ",".join(str(t["id"]) for t in (win or {}).get("tabs", []) if t.get("groupId") == group["id"])
        lines.append(f'tabgroup {group["title"] or "(unnamed)"} ({group["color"]}): {ids}')
    for container, tabs in group_tabs(state):
        lines.append(f'[{container["name"]}] ({len(tabs)}) {container["cookieStoreId"]}')  # the id: for `order`
        for tab in tabs:
            badge = tab_badge(tab)
            mark = f" ({badge})" if badge else ""
            lines.append(f' {"*" if tab.get("active") else " "} {tab_label(tab)}{mark} [{tab["id"]}]')
    return "\n".join(lines)
