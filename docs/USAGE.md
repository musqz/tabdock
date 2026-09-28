# Using tabdock

## Behaviour

- **Collapsed:** a 3 px strip tinted in the active browser's colour (Firefox orange, Zen purple,
  FireDragon red, Waterfox teal, LibreWolf blue, Floorp gold, Midori green). Hover to open (~120 ms);
  leaving closes it (~400 ms).
- **Open:** the header names the active browser; below it, one collapsible section per container
  (colour, icon, name, tab count) with its tabs, site icons optional (see Site icons). Click a tab to
  activate it.
- **Close and pin:** a hovered tab shows a `✕`; middle-click closes a tab too, as in the browser's tab strip.
  Right-click a tab to pin or unpin it, reopen it in another container (Firefox cannot move a tab between
  containers, so the page loads anew there and its back/forward history stays behind), or close it. Pinned tabs wear a 📌. With workspaces in use, closing a
  workspace's only tab from the panel leaves the window open (see Workspaces).
- **Tab groups:** a tab in one of Firefox's own tab groups wears the group's name in its colour.
- **Find a tab:** the 🔍 in the header opens a small window beside the panel. What you type there narrows the
  list at once to the tabs whose title or address holds every word, from every workspace of the window (a tab
  of another workspace says which); Enter goes to the highlighted tab (see the next item), or to the first
  one when none is, switching workspace if needed, and Escape gives the whole list back.
- **Find from the keyboard:** `tabdock --find` shows the panel and the find window from whatever has the
  focus, so a key bound to it walks you through the tabs without the mouse. Down and Up highlight a tab
  (from nothing, the first or the last), Page Down and Page Up move ten, Home and End go to the first and
  the last, Enter opens the highlighted tab and raises its browser, Escape closes the window and gives the
  keyboard back. The same key closes the window too. The panel has to be running (`tabdock: not running`,
  exit 1, otherwise). tabdock binds no key itself: see Hotkey below.
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
- **Advanced:** a collapsed line at the bottom of the panel lists every known browser with a colour
  swatch button, so a `[theme]` colour (see Configuration) can be set without editing `config.toml` or
  needing that browser connected.

## Configuration

`./install.sh` puts [../configs/config.toml](../configs/config.toml), every option explained, at
`~/.config/tabdock/config.toml` when you have none, and never overwrites yours. With the Arch package,
copy `/usr/share/tabdock/configs/config.toml` there. `tabdock -h` shows the path it reads; one still in
`~/.config/openbox-sidepanel/` from before the rename is used until you move it:

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

A `[theme]` section, last in the file, sets the accent colour instead of each browser's own (Firefox orange,
Zen purple, ...). The accent is on the strip, the header's line and browser name, buttons that are on, the
active tab's bar and the chips:

```toml
[theme]
accent = "#4c9aff"    # every browser in this one colour
firefox = "#4c9aff"   # or one browser (also zen, firedragon, librewolf, waterfox, floorp, midori); wins over accent
other = "#8f9bb3"     # any other browser, and the strip while none is connected
```

Colours are `"#rrggbb"` or `"#rgb"`. On a dark accent the text turns white, and the browser's name in the
header takes the usual text colour, so both stay readable. The header's right-click menu and the panel's
Advanced section (see Behaviour) set these with a colour chooser instead of editing the file.

Config is read at startup only: quit (`✕`) and restart from the menu to apply changes (a `[theme]` change
from the colour chooser or a SIGHUP reload applies at once). The header also has live toggles (icons, pin,
side, quit) that last until the next restart.

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

### Hotkey

tabdock grabs no key; the window manager runs `tabdock --find` for one you choose, and `install.sh` leaves
your `rc.xml` alone. In Openbox add a `<keybind>` to the `<keyboard>` section of `~/.config/openbox/rc.xml`
(copy `/etc/xdg/openbox/rc.xml` there first if you have none), then run `openbox --reconfigure`:

```xml
<openbox_config xmlns="http://openbox.org/3.4/rc">
  <!-- ... -->
  <keyboard>
    <!-- ... -->
    <keybind key="W-grave">
      <action name="Execute">
        <command>tabdock --find</command>
      </action>
    </keybind>
  </keyboard>
  <!-- ... -->
</openbox_config>
```

`W-grave` is Super+`` ` ``. In a key name `W-` is Super, `A-` Alt, `C-` Ctrl and `S-` Shift, and the key
itself is an X keysym (`xev` prints them). Pick one no other `<keybind>` uses. Any other window manager works
the same way: bind a key to the command `tabdock --find`.

### Multiple monitors

`monitor = "outer"` (default) puts the panel on the outer monitor for `side` — the only edge X11 lets a
pinned window reserve space on — in any layout, including reversed. `⇄` hops edges; the panel follows
monitor changes without a restart. Use `"primary"` or an output name to pin a specific monitor instead
(a pin there becomes an overlay).

## Troubleshooting

- **Panel doesn't appear when a browser opens:** run `tabdock` in a terminal to see why (a bad
  `config.toml` is reported there); the browser-launched copy logs to `$XDG_RUNTIME_DIR/tabdock.log`.
- **"Waiting for a browser with the Tabdock extension":** extension not installed/enabled, or the
  native-messaging manifest is missing — see [RELEASE.md](RELEASE.md).
- **Panel only opens on part of the edge:** another tool's invisible hotspot windows are catching the
  pointer first. Find them: `xwininfo -root -tree | grep -E ' (2x[0-9]+|[0-9]+x2)\+'`.
