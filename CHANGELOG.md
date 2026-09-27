# Changelog

## Unreleased

- Firefox's own tab groups show in the panel: a grouped tab wears its group's name, in the group's colour, after
  its title (hover it for the full name). The extension reports them (`tabGroups`, a new permission, asked for
  with the next signed extension along with the workspaces' ones). Tested in real Firefox 156: a tab grouped and
  ungrouped in the browser is reported both ways.

- Find a tab: a 🔍 in the header opens a small window beside the panel (it takes the keyboard, which the dock never
  does). Typing narrows the list at once to the tabs whose title or address holds every word, in any case, from
  every workspace of the window, a match from another workspace saying which one it is in; Enter goes to the
  first match, and a hidden one's workspace is switched to; Escape gives the whole list back. Folded sections
  show their matches. The header no longer makes the panel wider than `width`: the browser's name shortens
  instead (the Openbox test caught the extra button doing that). Tested in real Firefox 156 (activating another
  workspace's hidden tab switches to it) and under Openbox (typing, the list narrowing, Enter, the keyboard back
  in the browser).

- Reopen a tab in another container: *Reopen in container* in a tab's right-click menu. Firefox cannot move a tab
  between containers, so the page opens anew in the one picked, right after it (pinned if it was, in the same
  workspace), and the original closes; the page reloads and its back/forward history stays behind. Offered for
  web pages and the new-tab page, which an extension may open, not for `about:config` and the like. Tested in
  real Firefox 156 with a page served for the test (`tests/e2e_firefox.py`).

- Packaging: `packaging/sign-extension.sh` now also leaves the signed extension as
  `web-ext-artifacts/tabdock-<version>.xpi`, the name the GitHub release attaches it by and `packaging/PKGBUILD`
  downloads it by, and prints the `gh release upload` command for it (also when the version was signed before).
  The v0.3.1 release was published without that file, so `makepkg` failed to download
  `.../releases/download/v0.3.1/tabdock-0.3.1.xpi`; its tag also sits one merge before the 0.3.1 sources. The
  README and docs/RELEASE.md say so and point to `./install.sh` until the next release.

- Edit containers from the panel: right-click a container section to rename it, pick its colour or icon (Firefox's
  own), make a new container (named in a small window; it gets a colour no container has yet), or remove it.
  Removing asks first, with Cancel as the default so a stray Enter removes nothing, and says what goes: its tabs
  close, in every window and workspace, and Firefox deletes its cookies, logging you out of the sites you used in
  it. Its tabs close the way the panel closes one, so never with a window that holds other workspaces' hidden
  tabs, and a workspace that opened its new tabs in it stops doing so first (or its replacement tab would open
  right in the container being removed; the real-browser test fails that way when the order is swapped). "No
  container" offers only a new container. Tested in real Firefox 156 (`tests/e2e_firefox.py`: made, renamed,
  recoloured, re-iconed, and removed with its tab closed and its cookie gone; a workspace's container removed
  while its only tab was in it) and under a real Openbox (`tests/e2e_x11.py`: renamed through the menu and the
  name window; Enter in the removal window cancels, and only Remove removes).

- Close and pin tabs from the panel. A hovered tab shows a `✕`, a middle click closes a tab (let go elsewhere
  and nothing closes, as in the browser), and a tab's right-click menu pins or unpins it and closes it, around
  the workspace moves. Pinned tabs wear a 📌, after the title so the titles still line up. Closing a
  workspace's only visible tab from the panel keeps the window: the workspace gets a new tab first, where Firefox
  would otherwise close the window and every other workspace's hidden tabs with it (with its default
  `browser.tabs.closeWindowWithLastTab`; the real-browser test shows exactly that happening without this). Rows
  now really look hovered: their hover style was never shown, because a GTK EventBox does not mark itself
  hovered. The extension changed, with no new permission, so this is part of the next signed extension. Tested
  in real Firefox 156 (`tests/e2e_firefox.py`: pin, unpin and close through the panel, and the window surviving
  that last-tab close with the pref at Firefox's default) and under a real Openbox (`tests/e2e_x11.py`: the
  hovered row's background and its `✕` drawn, other rows' `✕` not, a click on it and a middle click closing,
  the browser keeping the focus). The panel offers closing, pinning and editing containers only when the
  browser's extension says it handles them (`features` in its hello), so with an older extension there is no `✕`
  or menu item that would do nothing.

- Workspaces, more like Zen's: each can have an **icon** and a **colour** (right-click its chip: *Icon* offers a
  few and *Other…* takes any emoji; *Colour* the colours containers have), shown on its chip; a **container for
  its new tabs** (*New tabs in*): while it shows, a new tab (Ctrl+T, the tab strip's `+`) opens in that container.
  Firefox cannot move a tab into a container, so the extension reopens the new tab there at once. Links keep
  their page's container, the panel's own `+` on a container section opens exactly there, and a removed
  container is simply cleared. And **keyboard shortcuts**: Ctrl+Alt+PageDown / PageUp for the next / previous
  workspace, Ctrl+Alt+1 … 9 for the Nth, changeable in `about:addons` → *Manage Extension Shortcuts* (not
  Ctrl+Alt+arrows, which Openbox's default configuration uses to switch desktops). The extension changed, with
  no new permission, so this is part of the next signed extension (docs/RELEASE.md); with the current one the
  panel offers only rename and remove, as before. Tested in real Firefox 156 (`tests/e2e_firefox.py`: icon and
  colour kept across a browser restart, Ctrl+T reopened in the workspace's container, the panel's no-container
  tab left alone, a removed container cleared, an empty workspace's new tab in its container, and the shortcuts
  pressed as real keys) and under a real Openbox (`tests/e2e_x11.py`: the colour picked in the chip's submenu
  by keyboard while the browser keeps the focus, then drawn under the chip).

- Workspaces, Zen-style: each browser window shows one workspace, and the tabs of the others are hidden, in
  Firefox's own tab strip too (`tabs.hide`). Chips above the tabs switch (back to the tab you used last there),
  `+` makes a new one (a small window asks for its name: the dock never takes the keyboard, that window does),
  a right click renames or removes one, and a right click on a tab moves it to another workspace. New tabs join
  the workspace their window shows; pinned tabs show in all of them (Firefox cannot hide them); removing a
  workspace closes nothing (its tabs go to its neighbour, and the menu says which); picking a hidden tab from
  Firefox's "List all tabs" switches to its workspace. Workspaces, their tabs and what each window shows survive
  an extension and a browser restart (kept in the session and `storage`). Nothing changes, nothing is hidden,
  until you make a second workspace; Zen, which has workspaces of its own, gets none.
  **Set `browser.tabs.closeWindowWithLastTab` to `false`** in `about:config` if you use them: Firefox does not
  count hidden tabs when it decides a tab is the window's last, so otherwise closing the last tab of a workspace
  closes the window with every workspace in it (the README has the details).
  The extension changed and asks for two new permissions, `tabHide` and `sessions`, so this needs a new signing
  (docs/RELEASE.md); Firefox asks you to approve them when you install it. A panel with the old extension works as
  before, without workspaces. Tested in real Firefox 156 (`tests/e2e_firefox.py`, now also against the browser's
  own tab strip, and across an extension and a browser restart) and under a real Openbox (`tests/e2e_x11.py`:
  the chips, the right-click menu, typing a name). `tests/e2e_x11.py` now clicks its first tab where the layout
  dump says it is, instead of sweeping pixel rows that depend on fonts.

- The command is `tabdock` now, the project's own name, instead of `sidepanel`: `~/.local/bin/tabdock` (or
  `/usr/bin/tabdock` from the package), installed in `~/.local/share/tabdock`, with a "Tabdock" menu entry, its
  config in `~/.config/tabdock/config.toml` and the output of a panel the browser started in
  `$XDG_RUNTIME_DIR/tabdock.log`. `tabdock -h` lists the options and where those two files are on this machine.
  To update, run `./install.sh` again: it removes the install from before the rename (`~/.local/share/openbox-sidepanel`,
  `~/.local/bin/sidepanel`, the old menu entry) and names every line of your Openbox `autostart` and `rc.xml` that
  still starts `sidepanel`, which it never edits itself; the package says the same when it upgrades. A config still
  in `~/.config/openbox-sidepanel/` keeps working until you move it (`tabdock -h` says where to), and so do signing
  credentials saved there. Quit a panel still running from before (its `✕`) and start `tabdock`: the old one listens
  where only the old relay looks. Window rules (picom, Openbox) that match the panel's windows by
  `openbox-sidepanel` need `tabdock` now (`tabdock-strip`, `tabdock-panel`). The extension shows as "Tabdock" in
  `about:addons` from its next signed version; its id and native-messaging name stay the old ones, so it remains the
  same add-on with the same stored container order, and the one installed now keeps working with the renamed panel.

## 0.3.1

- The extension signed as 0.3.0 was signed before the `+` new-tab button reached the extension, so in the browser
  that button did nothing. 0.3.1 is the same extension with it, under a new version number because Mozilla signs
  each version only once: sign and install it in each browser (docs/RELEASE.md). From now on the Arch package
  refuses a signed extension that differs from the extension in its own sources.

- An Arch package: `packaging/PKGBUILD` builds a release from its `v<version>` tag and installs it system-wide
  (`/usr/share/tabdock`, `/usr/bin/sidepanel`, the menu entry, and the native-messaging manifest in
  `/usr/lib/mozilla/native-messaging-hosts`), with the signed extension, taken from the GitHub release, at
  `/usr/share/tabdock/tabdock.xpi`. Releases are tagged `v` + `VERSION` from 0.2.0 on; docs/RELEASE.md has the
  steps. Until a browser connects, the packaged panel says where that extension is and how to install it, and
  the README's Install section says the same.

## 0.3.0

- Site icons before the tab titles, and a toggle (the `icons` button in the header, `icons = true` in the
  config). **Off by default**, because the panel downloads the icons itself, from your own address and system
  DNS, outside the browser's proxy, VPN, DNS-over-HTTPS and per-container settings, for every listed tab
  (the README's "Site icons" says exactly what that means). The extension already reported each tab's icon
  address, so nothing changed there: `./install.sh` and a panel restart are enough.
  `data:` icons need no network. `https:` icons are fetched with no cookies or referrer, only from public
  addresses (checked again on every redirect and pinned to the checked address), with a verified certificate,
  a size limit and a hard ten-second limit for the whole download. Only small PNG, ICO and GIF files and plain
  SVGs (by their own content) are used, decoded in a separate process with a memory and CPU limit, so a crafted image can only
  fail. Icons live in memory only; nothing is written to disk. Addresses that can never be an icon are asked
  for once, network failures again after five minutes, and switching icons off also drops queued downloads.
  Found by the code review: a tiny GIF could freeze the panel for a minute and a PNG profile could take
  hundreds of MB, which is why decoding happens in that limited process.
  Real sites shaped the next step: Firefox prefers a site's SVG icon (claude.ai, npo.nl), so plain SVGs are
  accepted too (self-contained only: no external references, entities, scripts or embedded images; drawn at
  16 px whatever size they claim); npo.nl's `.ico` has a directory that disagrees with the bitmaps inside,
  which browsers tolerate and the strict decoder refuses, so the directory is made truthful first; and the
  decoder's memory limit was on address space, which made the loaders' thread pools fail (an SVG could not even
  start), so it is a limit on memory in use now, and the bombs still die in a moment. A tab without an icon says
  why when you hover the empty slot.

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
