# Plan: openbox-sidepanel — autohide desktop side panel driven by a Firefox extension

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
- No Wayland support (X11/Openbox only), no drag-and-drop or tree tabs in v1.

## Architecture

```
 Firefox ── WebExtension (MV2, persistent background)
              │  runtime.connectNative("openbox_sidepanel")   stdio, 4-byte length + JSON
              ▼
        native-host relay (tiny python, spawned by the browser, one per browser instance)
              │  Unix socket  $XDG_RUNTIME_DIR/openbox-sidepanel.sock   (JSON lines)
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
  `move_tab`, `pin_tab`, `container_create/update/remove`, `focus_window`.
- `windows.onFocusChanged` tells the panel which browser window is focused, so the panel never has to
  map individual X windows to browser windows (multi-window solved without title hacks).

### Native host (`lib/native-host/sidepanel-nmhost`)
- ~40 lines of python: read/write native-messaging frames on stdio <-> line-JSON on the Unix socket.
  Adds its parent PID (the browser process) to `hello`. Exits when either side closes.
- Manifest template in `configs/` -> installed to `~/.mozilla/native-messaging-hosts/` (Firefox) and
  `~/.zen/native-messaging-hosts/` (Zen); `allowed_extensions` holds the extension ID.

### Panel (`sidepanel` + `lib/sidepanel/`)
- Python + GTK3 (PyGObject) + python-xlib. Modules: `app.py` (main loop), `ipc.py` (socket server,
  one connection per browser), `model.py` (state per browser), `x11.py` (props, strut, active window),
  `config.py`, `ui/` (widgets).
- **Browser follow logic:** watch `_NET_ACTIVE_WINDOW` on the root window through python-xlib
  PropertyNotify wired into the GLib main loop (no polling). Resolve the active window's
  `_NET_WM_PID` -> walk to the browser PID reported in `hello`; fall back to `WM_CLASS`
  (`firefox`, `zen`, `firedragon`...). Panel shows that browser's model.
- **Non-browser window active:** keep showing the last browser's panel (default); config option
  `follow = last | hide` (see open question).
- **Autohide:** one GTK window, `_NET_WM_WINDOW_TYPE_DOCK`, undecorated, keep-above, on the configured
  monitor + side. Collapsed = 2 px wide hover strip at the screen edge; pointer enter -> expand to the
  configured width after ~120 ms; pointer leave -> collapse after ~400 ms (not while a menu/drag is
  active). Overlay by default (no strut), so windows are not resized. Fullscreen windows sit above the
  dock layer in Openbox, so the panel stays out of the way during fullscreen video.
- **Pin toggle:** header button / hotkey sets `_NET_WM_STRUT_PARTIAL` so the panel stays open and
  windows are laid out beside it; unpin removes the strut and returns to autohide.
- **Left/right:** `side = left | right` and `monitor = primary | <output name>` in
  `~/.config/openbox-sidepanel/config.toml`; changing it reloads on SIGHUP or `sidepanel --reload`.
- **Content:** header (browser name + pin + side flip); pinned row; one collapsible section per
  container (colored bar, icon, name, `+` for a new tab in that container); a "no container" section;
  window switcher when the browser has >1 window; active tab highlighted; search/filter box.
  Favicons: fetched by the panel (no cookies, no referrer) and cached in
  `~/.cache/openbox-sidepanel/favicons`.
  Trade-off: a cookie-less favicon fetch outside the container. The alternative is converting them
  inside the extension, which needs `<all_urls>`.
- Click tab -> `activate_tab` + raise/focus the browser window (extension `windows.update`
  `focused:true`; fallback `wmctrl -ia <xid>` if Openbox declines focus).

### Workspaces (M4, after the container panel works)
Firefox has no native workspaces. Recommended: exclusive workspaces implemented in the extension with
`tabs.hide()`. Each workspace is a named set of tabs (state in `storage.local`, tab membership via
`sessions.setTabValue`); switching hides the others and restores the last active tab. Firefox's native
tab groups (`tabGroups` API, `tabs.group()`, permission `tabGroups`) exist and can be shown as
sub-sections; they don't hide other groups, so they don't behave like Zen workspaces. Check the exact
minimum version on Firefox 156 during M4.

## Repo layout (agreed before commit 1, per global CLAUDE.md)

```
sidepanel                 main executable (python)
install.sh  README.md  CHANGELOG.md  SOURCES.md
lib/sidepanel/            panel python package
lib/native-host/          sidepanel-nmhost
extension/                manifest.json, background.js, icons/
configs/                  config.toml default, nm manifest template, sidepanel.desktop (autostart)
docs/                     PLAN.md, PROTOCOL.md, userChrome-snippet.css
tests/                    protocol fixtures, fake-extension script
packaging/                PKGBUILD later
.gitignore                includes CLAUDE.md, claude.md, __pycache__, web-ext-artifacts/
```
Git repo is initialised on a `feat/` branch; nothing on `main` except README updates.

## Milestones

- **M0 skeleton (done):** dirs, `.gitignore`, git init, config loader, README stub. Write `docs/PROTOCOL.md`.
- **M1 tracer bullet (done, verified with headless Firefox 156):** extension connects, sends snapshot; relay + socket;
  panel prints the tab list in a plain GTK list. Proves the whole pipe end to end in Firefox 156.
- **M2 real panel:** dock window, autohide strip, left/right + monitor from config, container sections,
  colors/icons, click-to-activate + focus, follow `_NET_ACTIVE_WINDOW`, pin/strut.
- **M3 two-way editing:** new tab in container, close, move, pin, container create/rename/recolor/
  delete from the panel, search box, favicons cache. Autostart from `~/.config/openbox/autostart`
  (fits its phased structure), `install.sh` with `--uninstall`.
- **M4 workspaces** via `tabs.hide()`; optional native tab-group display.
- **M5 more browsers:** Zen (native, cheap), then FireDragon and LibreWolf as **native packages**
  (user runs: `yay -S firedragon-bin`, `sudo pacman -S librewolf`, then removes the Flatpaks; check the
  existing `~/.firedragon` / `~/.librewolf` profiles are picked up). `install.sh` writes the
  native-messaging manifest to each browser's dir (`~/.mozilla`, `~/.zen`, `~/.firedragon`,
  `~/.librewolf` `/native-messaging-hosts/`; verify the exact path per browser). PID matching works
  again; `WM_CLASS` stays as fallback. Only start after M2/M3 are solid.
- **Later, only if wanted:** drag-and-drop reorder, tree tabs, Zen-workspace import, AUR packaging.

## Risks

1. **Flatpak browsers (FireDragon, LibreWolf):** not supported, and not needed. Native
   `firedragon-bin` / `librewolf` packages replace them in M5. Firefox and Zen are unaffected.
2. **Extension signing:** release Firefox needs signed add-ons. Use an unlisted AMO self-signed XPI
   (free) or `web-ext run` / `about:debugging` temporary load during development. FireDragon/LibreWolf
   may allow unsigned installs.
3. **Focus stealing:** Openbox may refuse focus changes from the browser; fallback `wmctrl -ia`.
4. **Hover strip vs. other edge users:** on a right-edge panel the browser scrollbar shares the edge on a
   maximised window. Keep the strip at 2 px and prefer outer monitor edges (see Context).
5. **Firefox still shows its own tab strip:** the panel replaces it visually only if the user hides the
   strip (userChrome.css snippet documented in `docs/`; not shipped as an install step).

## Verification

- M1: `web-ext run` (or `about:debugging`) with Firefox 156 and a scratch profile; open tabs in 2
  containers; `sidepanel --debug` prints the snapshot; open/close/switch tabs and see the snapshot
  update within ~100 ms; kill the panel and confirm the extension reconnects when it comes back.
- M2: `xprop` on the panel window shows `_NET_WM_WINDOW_TYPE_DOCK` (and `_NET_WM_STRUT_PARTIAL` only when
  pinned); pointer at the screen edge expands it; switching focus between Firefox and Zen swaps content;
  fullscreen a video and confirm the panel stays hidden; test `side=right` on DP-1.
- M3: each panel action (new tab in container, close, rename container) appears in the browser, and
  browser-side changes appear in the panel. `tests/` fake-extension script drives protocol tests without
  a browser. Shell-style checks per global CLAUDE.md (known-good/known-bad inputs, exit codes).
- Pre-commit: `/code-review` on the diff before the first commit; `git status` before staging.

## Decisions (confirmed by user)

- Default `side = left`, `monitor = primary` (HDMI-1 outer edge); switchable in config.
- `follow = last`: when a non-browser window is active, keep showing the last browser's panel.
- Workspaces (M4) are exclusive, Zen-style, via `tabs.hide()`.

## Assumptions (change if wrong)

- v1 target is native Firefox 156; Zen is the cheap second target; FireDragon/LibreWolf come in M5 as
  native (non-Flatpak) installs.
- Python + GTK3 (already installed, no build step). Go/C not needed.
- Width 320 px, overlay autohide, 2 px hover strip.
