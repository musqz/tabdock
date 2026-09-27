# Plan: tabdock — autohide desktop side panel driven by a Firefox extension

## Context

Zen's sidebar (containers, workspaces, active section, autohide) is what the user relies on, but Zen is
buggy and the sidebar is locked into Zen. Goal: an external desktop panel for Openbox/X11 that shows the
tab/container sidebar of whichever supported browser is focused (Firefox now; FireDragon/Zen/others later),
kept in two-way sync with the browser through a WebExtension. Change something in the browser -> the
panel updates; click/create/close in the panel -> the browser does it.

Verified on this machine (2026-09-19):
- Openbox 3.6.1, X11 (no Wayland). python 3.14, PyGObject/GTK 3.24, python-xlib 0.33, xdotool, wmctrl,
  xprop all installed. Go is installed too. No libwnck needed.
- Firefox 156.0 native (`/usr/bin/firefox`). Zen 1.22.2b native (`/opt/zen-browser-bin`, running now).
  Both are Gecko -> the same extension works in both, useful as a second test target.
- FireDragon and LibreWolf are currently system Flatpaks, only to avoid AUR build time (user). Flatpak
  sandboxes can't spawn a host-side native-messaging helper and use a different PID namespace, so the
  extension would not work there. Prebuilt native packages exist: `firedragon-bin` 13.5.1 (AUR, same
  version as the Flatpak) and `librewolf` (official `extra` repo). Switching to those removes the problem
  (see M5). No plan work is needed for Flatpak support.
- Two monitors: HDMI-1 2560x1440 at +0+0 (primary), DP-1 1920x1080 at +2560+180. Only the far-left edge
  of HDMI-1 (x=0) and the far-right edge of DP-1 (x=4480) are true outer screen edges, where the pointer
  stops. That is where an autohide hover trigger works well. HDMI-1's right edge is an inner edge (the
  pointer just moves on to DP-1), so a hover trigger there is poor.

## Non-goals

- **Flatpak/Snap browsers are not supported.** Native installs only (Firefox, Zen, `firedragon-bin`,
  `librewolf` from pacman/AUR). No portal code, no `flatpak-spawn`, no PID-namespace workarounds. The
  README states this; `install.sh` only writes native-messaging manifests to native profile dirs.
- No Wayland support (X11/Openbox only), no tree tabs in v1.

## Architecture

```
 Firefox ── WebExtension (MV2, persistent background)
              │  runtime.connectNative("openbox_sidepanel")   stdio, 4-byte length + JSON
              ▼
        native-host relay (tiny python, spawned by the browser, one per browser instance)
              │  Unix socket  $XDG_RUNTIME_DIR/tabdock.sock   (JSON lines)
              ▼
        panel process (python + GTK3)  ── X11: dock window, strut, _NET_ACTIVE_WINDOW watch
```

Why this shape: the browser can only talk to a program it spawns (native messaging), so the relay is
a dumb pipe and the panel is the long-lived server that owns all UI and X11 logic. The panel can start
before or after the browser; the extension reconnects with backoff.

### Extension (`extension/`)
- MV2 with a persistent background page (KISS; Firefox keeps supporting MV2 and it avoids event-page
  lifetime issues). Permissions: `tabs`, `cookies`, `contextualIdentities`, `nativeMessaging`
  (+ `tabHide`, `tabGroups`, `storage` in later milestones).
- On connect: send `hello {browser, version, hostPid}`, then a full `state` snapshot:
  `{windows:[{id, focused, tabs:[{id,index,title,url,favIconUrl,cookieStoreId,active,pinned,audible,discarded}]}],
  containers:[{cookieStoreId,name,color,colorCode,icon}], focusedWindowId}`.
- Re-send the snapshot (debounced ~50 ms) on any of: `tabs.onCreated/Removed/Updated/Moved/Activated/
  Attached/Detached`, `windows.onCreated/Removed/FocusChanged`, `contextualIdentities.onCreated/
  Updated/Removed`. Full snapshots, not deltas: simplest, self-healing, and small even for hundreds of
  tabs. Deltas only if it ever proves slow.
- Handle commands from the panel: `activate_tab`, `close_tab`, `new_tab {cookieStoreId?, windowId}`,
  `move_tab`, `pin_tab`, `reopen_in_container`, `create/update/remove_container` (docs/PROTOCOL.md has them all).
  `focus_window` was dropped: `activate_tab` focuses the tab's window, and the panel raises a browser window
  itself over X11 when that one is not in use.
- `windows.onFocusChanged` tells the panel which browser window is focused, so the panel never has to
  map individual X windows to browser windows (multi-window solved without title hacks).

### Native host (`lib/native-host/tabdock-nmhost`)
- ~170 lines of python: read/write native-messaging frames on stdio <-> line-JSON on the Unix socket.
  Adds its parent PID (the browser process) to `hello`. Exits when either side closes.
- Manifest template in `configs/` -> installed to `~/.mozilla/native-messaging-hosts/` (Firefox) and
  `~/.zen/native-messaging-hosts/` (Zen); `allowed_extensions` holds the extension ID.

### Panel (`tabdock` + `lib/tabdock/`)
- Python + GTK3 (PyGObject) + python-xlib. Modules: `app.py` (main loop), `ipc.py` (socket server,
  one connection per browser), `model.py` (state per browser), `x11.py` (props, strut, active window),
  `config.py`, `dock.py` (the GTK window, CSS, rows), `autohide.py` (hover open/close timing),
  `favicons.py` (site-icon fetch/decode), `geometry.py` (strut/monitor math), `ui.py` (headless
  console view for `--debug`).
- **Browser follow logic:** watch `_NET_ACTIVE_WINDOW` on the root window through python-xlib
  PropertyNotify wired into the GLib main loop (no polling). Resolve the active window's
  `_NET_WM_PID` -> walk to the browser PID reported in `hello`; fall back to `WM_CLASS`
  (`firefox`, `zen`, `firedragon`...). Panel shows that browser's model.
- **Non-browser window active:** keep showing the last browser's panel (default); config option
  `follow = last | hide` (see open question).
- **Autohide (as built):** two `_NET_WM_WINDOW_TYPE_DOCK` windows, undecorated, keep-above, on the
  configured monitor + side. The *strip* (3 px, always mapped) is the hover target and is tinted in
  the active browser's colour; the *panel* (full width) is mapped only while expanded and is only ever
  resized while unmapped (resizing a mapped GTK window while its content appears makes GTK snap it
  back to the content's minimum width). Pointer enter -> panel after ~120 ms; leave -> hidden after
  ~400 ms. Overlay by default (no strut). Fullscreen windows sit above the dock layer in Openbox,
  so the panel stays out of the way during fullscreen video.
- **Animation:** none built in. The panel only maps/unmaps, so any compositor the user runs applies
  its own open/close animation; no rule file is shipped, set one up in the compositor directly if wanted.
- **Active browser always visible:** the panel header names the browser in its accent colour (Firefox
  orange, Zen purple, FireDragon red, Waterfox teal, LibreWolf blue, Floorp gold) and the collapsed
  strip carries the same colour, so it is clear which browser is active even with window borders
  hidden. A `[theme]` section in `config.toml` (as built) overrides the accent globally or per
  browser; on a dark custom accent the text switches to white by a WCAG luminance check
  (`model.on_accent`) so it stays readable.
- **Pin toggle:** header button / hotkey sets `_NET_WM_STRUT_PARTIAL` so the panel stays open and
  windows are laid out beside it; unpin removes the strut and returns to autohide.
- **Left/right:** `side = left | right` and `monitor = outer | primary | <output name>` in
  `~/.config/tabdock/config.toml`; changing it reloads on SIGHUP or `tabdock --reload`.
- **Content:** header (browser name + pin + side flip); pinned row; one collapsible section per
  container (colored bar, icon, name, `+` for a new tab in that container); a "no container" section;
  window switcher when the browser has >1 window; active tab highlighted; search/filter box.
  Site icons (as built, off by default): fetched by the panel (no cookies, no referrer, public `https:`
  addresses only), decoded in a limited child process and kept in memory only; nothing is written to disk.
  Trade-off: a cookie-less favicon fetch outside the container. The alternative is converting them
  inside the extension, which needs `<all_urls>`.
- Click tab -> `activate_tab` + raise/focus the browser window (extension `windows.update`
  `focused:true`; fallback sends an EWMH `_NET_ACTIVE_WINDOW` `ClientMessage` directly via
  python-xlib, `lib/tabdock/x11.py:activate()`, if Openbox declines focus).

### Workspaces (M4, as built)
Firefox has no native workspaces, so they are exclusive workspaces in the extension with `tabs.hide()`
(permissions `tabHide`, `sessions`). The list lives in `storage.local`; which workspace a tab is in and which one a
window shows live in the session (`sessions.setTabValue` / `setWindowValue`), so they survive restarts although
ids change. Each window shows one workspace; switching activates its tab used last and hides the others. All
workspace bookkeeping runs one event at a time (a promise queue), and one `reconcile(window)` hides and shows
from that state, self-healing like the full snapshots. The active tab can't be hidden, so a window always shows
its active tab's workspace (picking a hidden tab from "List all tabs" switches). Nothing is stored or hidden until
a second workspace exists, and the panel offers none in Zen (its own workspaces), so neither is ever touched.
Panel: workspace chips above the tabs (click switches, right-click renames/removes, `+` asks for a name in a small
window that takes the keyboard, which the dock windows never do); right-click a tab to move it. Each workspace can
have an icon, a colour (the container colours) and a container for its new tabs: a new-tab-page tab in no container
is reopened in it (a tab cannot change containers), tabs the panel opens in a given container are left alone.
Keyboard shortcuts are the extension's `commands` (Ctrl+Alt+PageDown/PageUp, Ctrl+Alt+1…9; Ctrl+Alt+arrows are
Openbox's desktop keys), changeable in `about:addons`.
Firefox's native tab groups (`tabGroups`) don't hide each other, so they don't behave like Zen workspaces; the
panel shows them as they are: a grouped tab wears its group's name in the group's colour.

## Repo layout (agreed before commit 1, per global CLAUDE.md)

```
tabdock  VERSION           main executable (python) and the version it reports
install.sh  README.md  CHANGELOG.md  LICENSE
lib/tabdock/              panel python package
lib/native-host/          tabdock-nmhost
extension/                manifest.json, background.js, icons/
configs/                  config.toml default, nm manifest template, tabdock.desktop (autostart)
docs/                     PLAN.md, PROTOCOL.md, RELEASE.md
tests/                    unit tests (pytest) + manual e2e_*.py scripts
packaging/                PKGBUILD, build-extension.sh, sign-extension.sh, tabdock.install
.gitignore                includes CLAUDE.md, claude.md, __pycache__, web-ext-artifacts/
```
Git repo is initialised on a `feat/` branch; nothing on `main` except README updates.

## Milestones

- **M0 skeleton (done):** dirs, `.gitignore`, git init, config loader, README stub. Write `docs/PROTOCOL.md`.
- **M1 tracer bullet (done, verified with headless Firefox 156):** extension connects, sends snapshot; relay + socket;
  panel prints the tab list in a plain GTK list. Proves the whole pipe end to end in Firefox 156.
- **M2 real panel (done, verified under Openbox in Xephyr: `tests/e2e_x11.py`):** dock window, autohide strip, left/right + monitor from config, container sections,
  colors/icons, click-to-activate + focus, follow `_NET_ACTIVE_WINDOW`, pin/strut.
- **M2.5 permanent install (done, pulled forward from M3 because it makes the tool usable daily):**
  copy-install with receipt and `--uninstall`, autostart line for the phased Openbox autostart,
  lint-clean extension with icons and AMO metadata, reproducible `.xpi`, `docs/RELEASE.md`. Signing
  the extension (AMO unlisted) is a step only the user can do; installing the signed `.xpi` makes it survive
  browser restarts.
- **M3 two-way editing:** first slice done (0.3.0): **reordering**, i.e. drag container sections (order kept
  in the extension's `storage.local`, since Firefox cannot reorder containers) and drag tabs within their
  container (`tabs.move`). Second slice done: **new tab in container**, a `+` button per section
  (`tabs.create({cookieStoreId})`). Third slice done: **close and pin** (a `✕` on the hovered tab,
  middle-click, and the tab's right-click menu; `tabs.remove`, `tabs.update({pinned})`), where closing a
  workspace's only visible tab never closes the window. Fourth slice done: **edit containers**, a
  container section's right-click menu to create, rename, recolour, re-icon and remove one (removal asks first:
  its tabs close and Firefox deletes its cookies). Fifth slice done: **reopen in container**
  (Firefox cannot change a tab's container, so the page opens anew there and the original closes, its history
  left behind) and a **search** (a find window beside the panel, over every workspace). M3 is complete.
- **M4 workspaces (done):** exclusive, via `tabs.hide()`, verified with the real-browser test
  (`tests/e2e_firefox.py`: create, switch, move, rename, pin/unpin, last tab, remove, extension and browser
  restart, each checked against Firefox's own tab strip) and under Openbox (`tests/e2e_x11.py`: the chips, the
  right-click menu, the name window). Since then: an icon, a colour and a container per workspace, and keyboard
  shortcuts (also verified in real Firefox 156, the shortcuts pressed as real keys, and under Openbox). Still open:
  nothing: Firefox's own tab groups are shown too (each grouped tab wears its group's name in its colour).
- **M5 more browsers (done, pulled forward):** verified with `tests/e2e_firefox.py --firefox <browser>` on
  Firefox, Zen, FireDragon (`firedragon-bin`), Waterfox (`waterfox-bin`) and LibreWolf (`librewolf`), all
  native packages. Floorp is supported the same way (own accent colour, `KNOWN_BROWSERS` entry, same
  manifest) but has not been run through `e2e_firefox.py` yet. Every one reads
  `~/.mozilla/native-messaging-hosts`, so the single manifest from `install.sh` covers them and no
  per-browser directories (`~/.zen`, `~/.firedragon`, `~/.librewolf`) are needed. Process-based
  identification tells them apart (Zen even reports itself as "Firefox"); Waterfox has its own accent
  colour. The signed `.xpi` is installed once per browser.
- **Later, only if wanted:** tree tabs, Zen-workspace import, publishing `packaging/PKGBUILD` on the AUR.

## Risks

1. **Flatpak browsers (FireDragon, LibreWolf):** not supported, and not needed. Native
   `firedragon-bin` / `librewolf` packages replace them in M5. Firefox and Zen are unaffected.
2. **Extension signing:** release Firefox needs signed add-ons. Use an unlisted AMO self-signed XPI
   (free) or `web-ext run` / `about:debugging` temporary load during development. FireDragon/LibreWolf
   may allow unsigned installs.
3. **Focus stealing:** Openbox may refuse focus changes from the browser; fallback sends an EWMH
   `_NET_ACTIVE_WINDOW` `ClientMessage` directly via python-xlib (`lib/tabdock/x11.py`).
4. **Hover strip vs. other edge users:** on a right-edge panel the browser scrollbar shares the edge on a
   maximised window. Keep the strip at 3 px and prefer outer monitor edges (see Context).
5. **Firefox still shows its own tab strip:** the panel replaces it visually only if the user hides the
   strip (a userChrome.css snippet to do that is planned but not yet written; not shipped as an install
   step).
6. **Closing a workspace's last tab closes the window:** Firefox ignores hidden tabs when deciding whether a tab
   is the window's last (`Tabbrowser.#isLastTabInWindow`), so with `browser.tabs.closeWindowWithLastTab = true`
   (the default) the window goes, and the other workspaces' tabs with it (restorable from recently closed
   windows). An extension can't read or change that pref or stop the close; the README asks workspace users to
   set it to `false`, and Firefox then leaves a new tab in the workspace.

## Verification

- M1: `web-ext run` (or `about:debugging`) with Firefox 156 and a scratch profile; open tabs in 2
  containers; `tabdock --debug` prints the snapshot; open/close/switch tabs and see the snapshot
  update within ~100 ms; kill the panel and confirm the extension reconnects when it comes back.
- M2: `xprop` on the panel window shows `_NET_WM_WINDOW_TYPE_DOCK` (and `_NET_WM_STRUT_PARTIAL` only when
  pinned); pointer at the screen edge expands it; switching focus between Firefox and Zen swaps content;
  fullscreen a video and confirm the panel stays hidden; test `side=right` on DP-1.
- M3: each panel action (new tab in container, close, rename container) appears in the browser, and
  browser-side changes appear in the panel. `tests/` fake-extension script drives protocol tests without
  a browser. Shell-style checks per global CLAUDE.md (known-good/known-bad inputs, exit codes).
- Pre-commit: `/code-review` on the diff before the first commit; `git status` before staging.

## Decisions (confirmed by user)

- Default `side = left`, `monitor = outer` (the monitor at the screen's outer edge for the side, HDMI-1
  on the user's layout, and DP-1's edge for `right`); switchable in config.
- `follow = last`: when a non-browser window is active, keep showing the last browser's panel.
- Workspaces (M4) are exclusive, Zen-style, via `tabs.hide()`.

## Assumptions (change if wrong)

- v1 target is native Firefox 156; Zen is the cheap second target; FireDragon/LibreWolf come in M5 as
  native (non-Flatpak) installs.
- Python + GTK3 (already installed, no build step). Go/C not needed.
- Width 320 px, overlay autohide, 3 px hover strip.
