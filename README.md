# openbox-sidepanel

A desktop side panel for Openbox/X11 that shows the tabs and containers of the focused
Firefox-family browser, kept in two-way sync through a small WebExtension. Goal: a Zen-style
sidebar (containers, workspaces, autohide) that works in Firefox, FireDragon, LibreWolf, Zen.

Status: **M2, the real panel.** An autohiding dock on the left or right screen edge, following
whichever supported browser is active. Two-way editing (new/close/move tabs, containers) and
workspaces come next. See [docs/PLAN.md](docs/PLAN.md) and [docs/PROTOCOL.md](docs/PROTOCOL.md).

```
Firefox + extension/  <-- native messaging -->  lib/native-host/sidepanel-nmhost  <-- unix socket -->  sidepanel
```

## How it behaves

- **Collapsed:** a 3 px strip at the screen edge, tinted in the active browser's colour
  (Firefox orange, Zen purple, FireDragon red, LibreWolf blue). Hover it and the panel opens
  after ~120 ms; it closes ~400 ms after the pointer leaves.
- **Open:** the header always names the browser (in its colour), so you can tell which browser
  you are looking at even when window borders are hidden. Below it, one collapsible section per
  container (coloured bar, icon, name, tab count) with that container's tabs; the active tab
  is highlighted. Click a tab to activate it in the browser.
- **Follows the active window:** focus another browser and the panel switches to it. With
  `follow = "last"` (default) the panel keeps showing the last browser while you use other apps,
  and clicking a tab brings that browser forward; `follow = "hide"` removes the panel instead.
- **Pin:** the `pin` button keeps the panel open and reserves the space (windows are laid out
  beside it). The reservation only works on an outer edge of your monitor layout; on an inner
  edge (a neighbouring monitor beyond it) the panel stays open as an overlay instead.
- The panel never takes keyboard focus, so clicking it does not steal focus from the browser.

## Try it (development)

Needs `python-gobject` (GTK 3) and `python-xlib` on X11. Native browser installs only, no Flatpak/Snap.

```bash
./install.sh                # native-messaging manifest for Firefox (points at this checkout)
./sidepanel                 # the panel; add --debug for a console view (no GUI)
```

Then in Firefox open `about:debugging#/runtime/this-firefox`, "Load Temporary Add-on...",
and pick `extension/manifest.json`. `./install.sh --uninstall` removes the manifest.

## Configuration

Copy [configs/config.toml](configs/config.toml) to `~/.config/openbox-sidepanel/config.toml`:

| key | default | meaning |
|-----|---------|---------|
| `side` | `"left"` | screen edge, `"left"` or `"right"` |
| `monitor` | `"primary"` | `"primary"` or an `xrandr` output name such as `"HDMI-1"` |
| `width` | `320` | expanded width in px (100-1000) |
| `follow` | `"last"` | `"last"` or `"hide"` while a non-browser window is active |
| `pinned` | `false` | start pinned |

Tip: use an outer edge of your monitor layout; the pointer stops there, so hover-to-open is easy.
Reload a running panel with `kill -HUP $(pgrep -f 'sidepanel$')`. The header has a pin toggle and
a side switch (`⇄`); both apply until the next restart or reload.

## Animation (picom)

The panel has no animation code of its own: it only maps and unmaps its window, so your
compositor's open/close animations apply directly. [configs/picom-sidepanel.conf](configs/picom-sidepanel.conf)
is a picom rule (in the one-file-per-app include style) that turns off shadow, blur and corner
radius for the panel windows and adds a slide-in/out. Set its `direction` to match `side`.
Checked against picom 13: the rule loads and the slide-out plays. The open animation could not
be observed in the nested test display, so tune the durations and direction in your own session.

## Tests

```bash
python3 -m unittest discover -s tests     # pure logic, relay protocol, panel routing, GTK view, install.sh
python3 tests/e2e_firefox.py              # slow: real headless Firefox with the extension
python3 tests/e2e_x11.py                  # slow: the dock under real Openbox in a nested Xephyr window
```

The end-to-end scripts use scratch profiles and displays and never touch your real profile or
native-messaging directory. `e2e_x11.py` opens a small Xephyr window on your desktop while it runs.

## Layout

| Path | What |
|------|------|
| `sidepanel` | main executable |
| `lib/sidepanel/` | panel: socket server, model, geometry, autohide, X11 helpers, GTK dock |
| `lib/native-host/` | native-messaging relay |
| `extension/` | the WebExtension (MV2) |
| `configs/` | native-messaging manifest template, sample config, picom rule |
| `docs/` | plan and protocol |
| `tests/` | unit, protocol and end-to-end tests |
