# Changelog

## Unreleased

- Site icons before the tab titles, and a toggle (the `icons` button in the header, `icons = true` in the
  config). **Off by default**, because the panel downloads the icons itself, from your own address and system
  DNS, outside the browser's proxy, VPN, DNS-over-HTTPS and per-container settings, for every listed tab
  (the README's "Site icons" says exactly what that means). The extension already reported each tab's icon
  address, so nothing changed there: `./install.sh` and a panel restart are enough.
  `data:` icons need no network. `https:` icons are fetched with no cookies or referrer, only from public
  addresses (checked again on every redirect and pinned to the checked address), with a verified certificate,
  a size limit and a hard ten-second limit for the whole download. Only small PNG, ICO and GIF files (by their
  own header) are used, decoded in a separate process with a memory and CPU limit, so a crafted image can only
  fail. Icons live in memory only; nothing is written to disk. Addresses that can never be an icon are asked
  for once, network failures again after five minutes, and switching icons off also drops queued downloads.
  Found by the code review: a tiny GIF could freeze the panel for a minute and a PNG profile could take
  hundreds of MB, which is why decoding happens in that limited process.

- Show more than one browser. With two or more browsers open, chips under the header choose what the panel
  lists: `auto` (the browser in use, as before), a single browser (kept whichever window has focus), or `all`,
  which gives every browser its own foldable section under a solid band in its colour (click it), so the three
  levels differ at a glance: browser = coloured band, container = small bar with an icon, tab = plain line. Each browser keeps its own colour on
  its header, active tab and drop marker; clicking a tab of a browser that is not in use activates it and
  raises that browser's window (found by process when it has not been in use since the panel started); drags,
  drops and reordering stay inside one browser; two profiles of one browser are numbered. New config key
  `view = "auto" | "all"` picks the starting mode. Only the panel changed, not the extension: `./install.sh`
  and a panel restart are enough, no new signing. Tested with unit tests and under a real Openbox with two
  browsers (`tests/e2e_x11.py`: real clicks on the chips, the headers and a tab of the browser not in use).

- `packaging/sign-extension.sh` signs a new release with your addons.mozilla.org credentials: it asks for the
  JWT issuer and the (hidden) JWT secret one at a time, validates their shape before anything is sent (the
  usual mistakes: an issuer without `user:`, a secret cut off or pasted with debris), lints, signs, and verifies
  that the Mozilla signature is inside the result. The credentials live only in the script's environment, never on
  a command line, in shell history or in the repo; `--save` optionally keeps them in a mode-600 file under
  `~/.config`, `--forget` deletes it, `--dry-run` checks everything except contacting Mozilla. Works from any
  shell (it runs in bash), which avoids the zsh `read -p` trap. Tested with a real pseudo-terminal.

- Reorder by dragging (version 0.3.0). Drag a container section to put your containers in your own order, kept per
  browser profile by the extension (`storage`, since Firefox cannot reorder containers) and shown at once; drag a tab
  within its container to move it in the real tab strip (`tabs.move`, with the exact final-index arithmetic covered by
  a simulation of what the API does). "No container" stays first; a tab dropped outside its own container cancels;
  a drag is never also a click (clicks now fire on release); the panel stays open for the whole drag and an orange
  line marks the drop position; browser updates that arrive mid-drag wait until the drop. Verified with unit tests,
  the real-browser test on Firefox, Zen, FireDragon, Waterfox and LibreWolf (`tabs.move` and the stored order, in
  each browser's own default containers) and a real pointer drag under Openbox (`tests/e2e_x11.py`). The extension
  changed, so this needs a new signing: see docs/RELEASE.md.

- `monitor = "outer"` is the new default: the panel sits on the monitor that owns the screen's outer edge for
  `side` (leftmost for left, rightmost for right), so a pinned panel can reserve space and tiling respects it in
  any monitor layout, including a reversed one. `"primary"` and output names still work; a name that is not
  connected falls back to the outer edge. The panel now follows monitors being plugged in, unplugged or
  rearranged. Pinning on an inner edge (which X11 cannot reserve space on) says so: `pinned (overlay)`, with a
  tooltip. `tests/e2e_multihead.py` checks the real Openbox behaviour on two monitors.

## 0.2.0

- Verified on Firefox, Zen, FireDragon, Waterfox and LibreWolf (native packages) with the same extension and
  the single `~/.mozilla/native-messaging-hosts` manifest, so no per-browser manifest directories are
  needed. Waterfox gets its own accent colour (teal).

- No terminal needed to start the panel. The native-messaging relay starts it, detached, when a browser
  with the extension opens and none is running. A panel that dies before it ever listens is started again
  (at most three times); once a relay has seen a panel it never starts one, so a panel quit with its `✕` is
  not undone (`start_with_browser` in `config.toml` turns it off). `install.sh` also installs a "Sidepanel"
  application-menu entry (quoted correctly for paths with spaces or `%`) and its icon. The launcher explains
  itself when copied by hand, and `install.sh` replaces such an identical copy with the link.
- Single instance is now an exclusive lock instead of probing the socket: two panels started together (two
  browsers opening at once) could each take the other's not-yet-listening socket for a stale one and delete
  it. The lock is released by the kernel when the panel dies, however it dies.

- Panel header: the pin state is now unmistakable (`pin` outlined and dim, `pinned` as a filled pill in the
  browser's colour, tooltip says what a click does), and a `✕` quit button stops the panel cleanly.
  `tests/e2e_x11.py` clicks both under a real Openbox.
- Permanent install. `install.sh` now copies the program to `~/.local/share/openbox-sidepanel` with
  `~/.local/bin/sidepanel` linking to it (`PREFIX`/`SUDO` overrides), points the native-messaging
  manifest at the installed relay, keeps a receipt so `--uninstall` removes exactly what it created
  and upgrades drop files a newer version no longer ships, refuses to replace a foreign `sidepanel`
  command, and finishes by running the installed `sidepanel --version`. `VERSION` file and
  `sidepanel --version` added.
- Extension ready for signing: icons, `strict_min_version`, the "no data collected" declaration AMO
  requires, description within AMO's limit; passes `web-ext lint` with 0 errors and 0 warnings.
  `packaging/build-extension.sh` builds a reproducible `.xpi`; tests keep the manifest, the project
  version and the native-messaging manifest consistent.
- `docs/RELEASE.md`: signing (AMO unlisted), installing the signed `.xpi`, the Openbox autostart line,
  a reboot check and troubleshooting, including other tools' edge-hotspot windows that shadow the strip.
- Browser identity comes from the process behind the relay, not from `getBrowserInfo()`, which
  reports Zen as "Firefox". Window ownership is one-directional (the window is the browser
  process or one of its children), so the terminal that launched a browser is not mistaken for it.
- M2: the real panel. Autohiding dock (strip + panel windows) on the left or right edge of a
  chosen monitor; follows the active browser window (process tree first, window class as
  fallback); the header names the browser and the collapsed strip is tinted in its colour so
  the active browser is always recognisable; container sections with colour and icon;
  click-to-activate that never steals focus and raises the browser when another app is active;
  pin (strut on outer edges), side switch, `follow = last|hide`, config file with validation,
  reload on SIGHUP. Animation is left to the compositor: `configs/picom-sidepanel.conf` is a
  picom rule (no shadow/blur/corners, slide-in/out) for the panel windows.
- M1: tracer bullet. WebExtension sends debounced full snapshots (windows, tabs, containers)
  and executes `activate_tab`; native-messaging relay waits for the panel and asks the
  extension to resync on every (re)connect and to stop pushing when the panel is gone;
  `--debug` console view; `install.sh` writes the Firefox native-messaging manifest.
- M0: repo skeleton, config loader, protocol doc.
