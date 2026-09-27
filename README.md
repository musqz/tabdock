# Tabdock

A desktop side panel for Openbox/X11 that mirrors the focused browser's tabs and containers, two-way,
through a small WebExtension. Firefox-family (Netscape-lineage, Gecko) browsers only — Firefox, Zen,
FireDragon, Waterfox, LibreWolf; native installs, no Chromium/Blink, no Flatpak/Snap. Goal: a Zen-style
sidebar (containers, workspaces, autohide) everywhere.

Status: **0.3.1, installable.** Autohiding dock on the left/right edge, real install, signed extension,
autostart, drag to reorder, new tab per container. Since 0.3.1, not yet released: Zen-style workspaces, closing
and pinning tabs, and editing containers from the panel (they need the next signed extension). Next: moving a tab
to another container and a search box — see
[docs/PLAN.md](docs/PLAN.md) and [docs/PROTOCOL.md](docs/PROTOCOL.md).

```
Firefox + extension/  <-- native messaging -->  lib/native-host/tabdock-nmhost  <-- unix socket -->  tabdock
```

## How it behaves

- **Collapsed:** a 3 px strip tinted in the active browser's colour (Firefox orange, Zen purple,
  FireDragon red, Waterfox teal, LibreWolf blue). Hover to open (~120 ms); leaving closes it (~400 ms).
- **Open:** the header names the active browser; below it, one collapsible section per container
  (colour, icon, name, tab count) with its tabs, site icons optional (see Site icons). Click a tab to
  activate it.
- **Close and pin:** a hovered tab shows a `✕`; middle-click closes a tab too, as in the browser's tab strip.
  Right-click a tab to pin or unpin it, or close it. Pinned tabs wear a 📌. With workspaces in use, closing a
  workspace's only tab from the panel leaves the window open (see Workspaces).
- **Edit containers:** right-click a container section to rename it, change its colour or icon, make a new
  container, or remove it. Removing asks first, with Cancel as the default: its tabs close (in every window and
  workspace) and Firefox deletes its cookies, which logs you out of the sites you used in it.
- **Drag to reorder:** container sections and tabs within their own container. Order is remembered per
  browser profile (Firefox can't reorder containers itself). "No container" always stays first.
- **Workspaces:** chips above the tabs; each browser window shows one workspace and the others' tabs are
  hidden in the browser's own tab strip too. Click to switch, `+` for a new one, right-click to rename it,
  give it an icon, a colour or a container for its new tabs, or remove it; right-click a tab to move it to
  another; Ctrl+Alt+PageDown/PageUp and Ctrl+Alt+1…9 switch from the keyboard. See Workspaces below.
- **Several browsers:** chips under the header choose what's listed — `auto` (current browser), one
  chip per browser, or `all` (every browser, foldable, its own colour band). Clicking a tab in another
  browser activates it and raises its window. `view = "all"` starts in that view.
- **Follows the active window.** `follow = "last"` (default) keeps showing the last browser while you
  use other apps; `follow = "hide"` removes the panel instead.
- **Pin** reserves screen space on an **outer** monitor edge (the only edge X11 lets a window reserve
  space on, hence `monitor = "outer"` default); pinning an inner edge falls back to an overlay.
- **Quit** (`✕`) stops the panel until you start it again; it never takes keyboard focus.

## Install

Needs `python-gobject` (GTK 3) and `python-xlib`.

```bash
./install.sh                     # program -> ~/.local, browser manifest, "Tabdock" menu entry
packaging/sign-extension.sh      # signs the extension (safe prompts for your Mozilla credentials)
```

Release Firefox and Zen only keep **signed** extensions, so it needs signing once (free, via
addons.mozilla.org, unlisted) before it survives a restart. Full signing steps, install locations and
every way to start the panel: [docs/RELEASE.md](docs/RELEASE.md).

`./install.sh --uninstall` removes exactly what was installed. Day to day you never need a terminal: the
panel starts with the browser (`start_with_browser`), from the "Tabdock" menu entry, or an autostart
line / keybinding.

**Arch Linux:** `cd packaging && makepkg -si` installs the latest release system-wide instead, with the
extension already signed. This works from the next release on: the v0.3.1 release has no signed `.xpi` attached
(and `packaging/PKGBUILD` already follows the renamed layout), so for now use `./install.sh` and install the
signed extension yourself. Install that extension once in each browser: `about:addons` -> gear icon ->
"Install Add-on From File..." -> `/usr/share/tabdock/tabdock.xpi` (the panel shows this path too, until a
browser connects). Use the package or `./install.sh`, not both: the per-user manifest `install.sh` writes
overrides the package's.

## Development

Run from the checkout with `./tabdock` (`--debug` for a console view, no GUI; `-h` for the options and where
its config and log are). To try the extension without signing: `about:debugging#/runtime/this-firefox` ->
"Load Temporary Add-on..." -> `extension/manifest.json` (forgotten on restart). Run `./install.sh` first so the
browser can reach the relay.

## Troubleshooting

- **Panel doesn't appear when a browser opens:** run `tabdock` in a terminal to see why (a bad
  `config.toml` is reported there); the browser-launched copy logs to `$XDG_RUNTIME_DIR/tabdock.log`.
- **"Waiting for a browser with the Tabdock extension":** extension not installed/enabled, or the
  native-messaging manifest is missing — see [docs/RELEASE.md](docs/RELEASE.md).
- **Panel only opens on part of the edge:** another tool's invisible hotspot windows (e.g. `fittsmon`'s
  `[Left]`) are catching the pointer first. Find them: `xwininfo -root -tree | grep -E ' (2x[0-9]+|[0-9]+x2)\+'`.

## Configuration

Copy [configs/config.toml](configs/config.toml) to `~/.config/tabdock/config.toml` (`tabdock -h` shows the path it
reads; one still in `~/.config/openbox-sidepanel/` from before the rename is used until you move it):

| key | default | meaning |
|-----|---------|---------|
| `side` | `"left"` | screen edge, `"left"` or `"right"` |
| `monitor` | `"outer"` | `"outer"` (screen's outer edge for `side`), `"primary"`, or an `xrandr` output name |
| `width` | `320` | expanded width in px (100-1000) |
| `follow` | `"last"` | `"last"` or `"hide"` while a non-browser window is active |
| `view` | `"auto"` | `"auto"` (browser in use) or `"all"` (every open browser) at startup; chips switch it live |
| `icons` | `false` | site icons before tab titles — the panel fetches them itself, outside the browser's proxy/DNS; read Site icons below first |
| `badges` | `true` | a leading unread count in a tab title (`"(3) Inbox"`) gets a small badge |
| `pinned` | `false` | start pinned |
| `start_with_browser` | `true` | start the panel when a browser with the extension opens and none is running |

Config is read at startup only: quit (`✕`) and restart from the menu to apply changes. The header also
has live toggles (icons, pin, side, quit) that last until the next restart.

### Site icons

Off by default (`icons = true`, or the header toggle for the session). `data:` icons need no network;
anything else is downloaded by the **panel itself**, not the browser — bypassing the browser's proxy,
VPN, DoH and per-container settings, and covering private-window tabs if the extension is allowed there.
Leave it off if that matters to you.

Safeguards: `https:` only, no cookies/referrer, public addresses only (checked after redirects and DNS,
max 3 redirects), 256 KB / 10 s hard limits, sniffed and decoded (PNG/ICO/GIF, or a self-contained SVG)
in a sandboxed child process with memory/CPU limits, memory-only cache (nothing written to disk). A tab
without an icon says why on hover.

### Workspaces

Zen-style and exclusive: each browser window shows one workspace, and the tabs of the others are hidden
(`tabs.hide`), in Firefox's own tab strip as well as in the panel. Nothing changes until you make a second
workspace with `+`: until then no tab is ever hidden, and your existing tabs become the "Default" workspace.

- **Switching** goes back to the tab you used last in that workspace (a new tab if it has none).
- **New tabs** join the workspace their window shows, and so does a tab dragged in from another window. A
  new window starts in the workspace of the window you were in.
- **Pinned tabs** can't be hidden by Firefox, so they show in every workspace. Unpinning one puts it in the
  workspace you unpinned it in.
- **Removing** a workspace closes nothing: its tabs move to the workspace next to it (the menu says which).
  The last workspace stays.
- **Icon and colour:** right-click a chip → *Icon* (a few to pick from, or *Other…* for any emoji) and
  *Colour* (the colours containers have). The chip shows the icon before the name and a bar in the colour.
- **A container for its new tabs:** right-click a chip → *New tabs in* → a container. While that workspace
  shows, a new tab (Ctrl+T, the `+` in the tab strip) opens in that container: Firefox cannot move a tab
  into a container, so the extension reopens the new tab there at once. Links keep the container of the page
  they come from, and the panel's own `+` on a container section opens exactly there ("No container"
  included). Removing the container clears the choice; private windows cannot hold containers, so nothing
  changes there.
- **Keyboard:** Ctrl+Alt+PageDown / Ctrl+Alt+PageUp go to the next / previous workspace (round the list),
  Ctrl+Alt+1 … 9 to the first … ninth. Change or clear them in `about:addons` → gear icon → *Manage Extension
  Shortcuts*. (Not Ctrl+Alt+arrows: Openbox's default configuration switches desktops with those.) They do
  nothing until there is a second workspace, and never in Zen, where you may want to clear them.
- **Restarts:** workspaces, the tabs in each and what every window shows survive a browser restart
  (restoring the previous session). Disabling or removing the extension shows every hidden tab again.
- **Zen** has workspaces of its own, so the panel offers none there, and the extension never hides a tab in it.
- Firefox tells you once that an extension is hiding tabs, and still lists hidden tabs under "List all
  tabs" (the `⌄` at the end of the tab strip). Picking one from there switches to its workspace.

**Set `browser.tabs.closeWindowWithLastTab` to `false`** in `about:config` if you use workspaces. (Closing a tab
from the panel is always safe: when it is the only one the window shows, the workspace gets a new tab first.) Firefox
does not count hidden tabs when it decides whether a tab is the window's last: with the default `true`,
closing the last tab of a workspace closes the whole window, and the other workspaces' tabs with it (they
come back with History → Recently Closed Windows, or Restore Previous Session if it was the last window). With
`false`, Firefox leaves a new tab instead and the workspace stays. An extension can neither read nor change
this setting, nor stop a window from closing.

### Multiple monitors

`monitor = "outer"` (default) puts the panel on the outer monitor for `side` — the only edge X11 lets a
pinned window reserve space on — in any layout, including reversed. `⇄` hops edges; the panel follows
monitor changes without a restart. Use `"primary"` or an output name to pin a specific monitor instead
(a pin there becomes an overlay).

## Tests

```bash
python3 -m unittest discover -s tests     # pure logic, relay protocol, panel routing, GTK view, install.sh, PKGBUILD
python3 tests/e2e_firefox.py              # slow: real headless Firefox with the extension
python3 tests/e2e_x11.py                  # slow: the dock under real Openbox in a nested Xephyr window
python3 tests/e2e_multihead.py            # slow: two monitors under real Openbox: tiling respects a pinned panel
```

End-to-end tests use scratch profiles/displays and never touch your real profile or native-messaging
directory. `e2e_x11.py` opens a small Xephyr window on your desktop while it runs.

## Layout

| Path | What |
|------|------|
| `tabdock`, `VERSION` | main executable and the version it reports |
| `install.sh` | install / uninstall (see docs/RELEASE.md) |
| `lib/tabdock/` | panel: socket server, model, geometry, autohide, X11 helpers, site icons, GTK dock |
| `lib/native-host/` | native-messaging relay |
| `extension/` | the WebExtension (MV2), with icons |
| `packaging/` | `build-extension.sh` (reproducible .xpi), `sign-extension.sh`, Arch `PKGBUILD` |
| `configs/` | native-messaging manifest template, sample config |
| `docs/` | plan, protocol, install and release guide |
| `tests/` | unit, protocol and end-to-end tests |

<img width="320" height="1440" alt="Image" src="https://github.com/user-attachments/assets/14557b70-0a00-4510-99c8-65a62725c298" />

<img width="320" height="1440" alt="Image" src="https://github.com/user-attachments/assets/d7ae7694-e9c7-4da3-9797-a997a611c256" />
