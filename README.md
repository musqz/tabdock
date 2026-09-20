# openbox-sidepanel

A desktop side panel for Openbox/X11 that shows the tabs and containers of the focused
Firefox-family browser, kept in two-way sync through a small WebExtension. Goal: a Zen-style
sidebar (containers, workspaces, autohide) that works in Firefox, Zen, FireDragon, Waterfox and LibreWolf.

**Browsers.** All five run from the same extension and the one native-messaging manifest that
`install.sh` writes, and each passes `tests/e2e_firefox.py --firefox <browser>` (native packages; Flatpak
and Snap builds cannot start the helper). Each gets its own colour on the strip and header:
Firefox orange, Zen purple, FireDragon red, Waterfox teal, LibreWolf blue.

Status: **0.2.0, installable.** An autohiding dock on the left or right screen edge, following
whichever supported browser is active, with a real install, a lint-clean extension ready for signing,
and autostart instructions. Two-way editing (new/close/move tabs, containers) and workspaces come next. See [docs/PLAN.md](docs/PLAN.md) and [docs/PROTOCOL.md](docs/PROTOCOL.md).

```
Firefox + extension/  <-- native messaging -->  lib/native-host/sidepanel-nmhost  <-- unix socket -->  sidepanel
```

## How it behaves

- **Collapsed:** a 3 px strip at the screen edge, tinted in the active browser's colour
  (see Browsers above). Hover it and the panel opens
  after ~120 ms; it closes ~400 ms after the pointer leaves.
- **Open:** the header always names the browser (in its colour), so you can tell which browser
  you are looking at even when window borders are hidden. Below it, one collapsible section per
  container (coloured bar, icon, name, tab count) with that container's tabs, each with its site icon
  before the title when icons are on (they are off until you ask: see Site icons below); the active tab is highlighted. Click a tab to activate it in
  the browser.
- **Reorder by dragging.** Drag a container section header up or down to put your containers in your own
  order; the order is remembered per browser profile (Firefox cannot reorder containers itself, so the order
  lives in the panel's extension and does not change Firefox's own menus). "No container" always stays first.
  Drag a tab up or down within its container to move it in the real tab strip. A tab only moves within its own
  container: dropping it well outside that group cancels the drag, and a drag is never also a click. The panel
  stays open for the whole drag, even if the pointer leaves it, and an orange line shows where the row will land.
- **Several browsers.** While two or more browsers with the extension are open, a row of chips under the
  header chooses what is listed: `auto` (the browser you are using, the default), one chip per browser
  (that browser stays listed whichever window has focus), and `all` (every browser, one foldable section
  each under a solid band in its colour, so a browser never looks like a container: click the band to fold
  or unfold it). Every browser the panel recognises keeps its own
  colour on its header, its active tab and the drop marker (an unknown one is grey), and the strip wears the
  colour of the browser in use. Clicking a tab
  of a browser you are not using activates it and brings that browser's window forward; a drag stays inside
  one browser. Two profiles of one browser show as `Firefox 1` and `Firefox 2`. `view = "all"` in the config
  starts the panel in the `all` view.
- **Follows the active window:** focus another browser and the panel switches to it. With
  `follow = "last"` (default) the panel keeps showing the last browser while you use other apps,
  and clicking a tab brings that browser forward; `follow = "hide"` removes the panel instead.
- **Pin:** the `pin` button keeps the panel open and reserves the space (windows are laid out
  beside it). While pinned it reads `pinned` on a filled pill in the browser's colour; unpinned it is a
  dim outlined `pin`. Space can only be reserved on an **outer** edge of the whole screen (X11 cannot do it
  on an edge shared with another monitor), which is why `monitor = "outer"` is the default (see Multiple
  monitors below). If you pin on an inner edge anyway, the panel stays open as an overlay, windows can slide
  under it, and the button says `pinned (overlay)` with a tooltip explaining why.
- **Quit:** the `✕` at the far right of the header stops the panel (it stays gone until you run
  `sidepanel` again or log in again; the browser extension just waits).
- The panel never takes keyboard focus, so clicking it does not steal focus from the browser.

## Install

Needs `python-gobject` (GTK 3) and `python-xlib` on X11. Native browser installs only, no Flatpak/Snap.

```bash
./install.sh                     # program -> ~/.local, browser manifest, "Sidepanel" menu entry
packaging/sign-extension.sh      # signs the extension with your Mozilla credentials (safe prompts)
packaging/build-extension.sh     # just the unsigned .xpi
```

Release Firefox and Zen only keep **signed** extensions, so a permanent setup needs the extension
signed once (free, via addons.mozilla.org, unlisted). Signing, a reboot check and all the ways to
start the panel are in [docs/RELEASE.md](docs/RELEASE.md).

**You never need a terminal to start it:** opening a browser that has the extension starts the panel if
none is running (`start_with_browser`), and there is a "Sidepanel" entry in your application menu; an
Openbox autostart line or a keybinding work too. `./install.sh --uninstall` removes exactly what was
installed.

## Development

Run from the checkout with `./sidepanel` (add `--debug` for a console view without a GUI). To try the
extension without signing, load it as a temporary add-on: `about:debugging#/runtime/this-firefox` ->
"Load Temporary Add-on..." -> `extension/manifest.json` (forgotten on browser restart). Run
`./install.sh` first so the browser can start the relay.

## Troubleshooting

- **The panel does not appear when a browser opens:** run `sidepanel` in a terminal to see why it cannot
  start (a bad `config.toml` is reported there); when the browser starts it, the output goes to
  `$XDG_RUNTIME_DIR/openbox-sidepanel.log` instead. A panel that dies at startup is retried up to three times.

- **"Waiting for a browser with the Sidepanel extension":** the extension is not installed or
  enabled, or the native-messaging manifest is missing; see [docs/RELEASE.md](docs/RELEASE.md).
- **The panel only opens on part of the screen edge:** another tool's invisible hotspot windows
  (for example `fittsmon`'s `[Left]` position) sit above the strip and catch the pointer first. Find them
  with `xwininfo -root -tree | grep -E ' (2x[0-9]+|[0-9]+x2)\+'`, remove that position from the other tool's
  config, or move the panel to a free edge.

## Configuration

Copy [configs/config.toml](configs/config.toml) to `~/.config/openbox-sidepanel/config.toml`:

| key | default | meaning |
|-----|---------|---------|
| `side` | `"left"` | screen edge, `"left"` or `"right"` |
| `monitor` | `"outer"` | `"outer"` (the monitor at the screen's outer edge for `side`), `"primary"`, or an `xrandr` output name such as `"HDMI-1"` |
| `width` | `320` | expanded width in px (100-1000) |
| `follow` | `"last"` | `"last"` or `"hide"` while a non-browser window is active |
| `view` | `"auto"` | `"auto"` (the browser in use) or `"all"` (every open browser) when the panel starts; the chips switch it while running |
| `icons` | `false` | site icons before the tab titles. Off by default because the panel downloads them itself, outside the browser's proxy and DNS settings: read "Site icons" below first. The `icons` button in the header switches it while running |
| `pinned` | `false` | start pinned |
| `start_with_browser` | `true` | start the panel when a browser with the extension opens and none is running |

Tip: use an outer edge of your monitor layout; the pointer stops there, so hover-to-open is easy.
The config is read at startup: quit the panel (`✕`) and start it again from the menu. The header has an
icons toggle, a pin toggle, a side switch (`⇄`) and a quit button (`✕`); icons, pin, side and the chosen
browsers apply until the next restart.

### Site icons

Off by default. Turn them on with `icons = true` in the config, or with the `icons` button in the header (that
lasts until the panel restarts). The browser already tells the panel each tab's icon address; the panel then
shows the icon before the title.

**Read this before turning it on.** An icon that is part of the page (a `data:` address) needs no network. Any
other icon has to be downloaded, and it is the *panel* that downloads it, not the browser:

- it connects from your own address using your system's DNS. The browser's proxy, its VPN or Tor setup, its
  DNS-over-HTTPS and per-container proxies do not apply, so your provider's resolver sees the name of every
  site with a listed tab, and each of those sites sees a request for its icon from your real address;
- it does so for every tab the panel lists, including private-window tabs if you have allowed the extension in
  private windows (leave icons off if you do);
- the request says `User-Agent: openbox-sidepanel`, so a site can tell it from the browser's own.

If you use the browser's own privacy settings for that reason, leave icons off. What the panel does to keep
the rest safe, since a web page chooses the address and the panel is not sandboxed like the browser:

- only `https:` is fetched (`http:`, `chrome:`, `about:` and the rest never are: those tabs have no icon), with
  no cookies and no referrer, once per address per run, at most a few at a time;
- it never connects to your own machine or network: loopback, private, link-local and similar addresses are
  refused, also after redirects and for names that resolve to them, and the connection goes to the address that
  was checked. The certificate must verify. At most three redirects, at most 256 KB, and the whole download
  is cut off after ten seconds however slowly the server drips;
- what arrives is only used if its own header says it is a small PNG, ICO or GIF (SVG and everything else is
  refused). It is decoded in a separate short-lived process with a memory and a time limit, not in the panel,
  and only 16x16 pixels come back, so a crafted image can at worst fail;
- icons live in memory only: nothing about your tabs is written to disk and quitting the panel forgets them, at
  the price of downloading them again on the next start. An address that can never be an icon is asked for once;
  one that failed for a network reason is tried again after five minutes.

`icons = false` (or the header button) stops all of it, including downloads queued but not yet started.

### Multiple monitors

Pinning only makes tiling and maximising respect the panel when it sits on an **outer** edge of the whole
screen, because that is all X11 lets a window reserve. `monitor = "outer"` (the default) therefore puts the
panel on the leftmost monitor for `side = "left"` and on the rightmost for `side = "right"`. It works in any
layout (a reversed arrangement just works), and the `⇄` button hops to the other outer edge. The panel also
follows monitors being plugged in, unplugged or rearranged, without a restart. Use `"primary"` or an output
name only if you want the panel on a specific monitor even when its edge borders another one (then a pinned
panel is an overlay). Verified with `tests/e2e_multihead.py` under a real Openbox with two monitors: a pin on
the outer left edge shrinks only the left monitor's maximised windows, and on the outer right edge only the
right one's.

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
python3 tests/e2e_multihead.py            # slow: two monitors under real Openbox: tiling respects a pinned panel
```

The end-to-end scripts use scratch profiles and displays and never touch your real profile or
native-messaging directory. `e2e_x11.py` opens a small Xephyr window on your desktop while it runs.

## Layout

| Path | What |
|------|------|
| `sidepanel`, `VERSION` | main executable and the version it reports |
| `install.sh` | install / uninstall (see docs/RELEASE.md) |
| `lib/sidepanel/` | panel: socket server, model, geometry, autohide, X11 helpers, site icons, GTK dock |
| `lib/native-host/` | native-messaging relay |
| `extension/` | the WebExtension (MV2), with icons |
| `packaging/` | `build-extension.sh` (reproducible .xpi); AUR packaging later |
| `configs/` | native-messaging manifest template, sample config, picom rule |
| `docs/` | plan, protocol, install and release guide |
| `tests/` | unit, protocol and end-to-end tests |
