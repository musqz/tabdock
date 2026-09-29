# Using tabdock

## The panel

- **Collapsed:** a 3 px strip in the active browser's colour. Hover opens it (~120 ms), leaving closes it (~400 ms).
- **Open:** the header names the browser; below it a section per container (colour, icon, name, tab count) with
  its tabs. Click a tab to activate it. The `+` on a section opens a tab there and brings the browser forward with
  the address bar ready.
- **Close and pin:** `✕` on a hovered tab, or middle-click. Right-click a tab: pin, reopen in another container
  (the page reloads, its history stays behind), move to a workspace, close. Pinned tabs wear a 📌.
- **Undo a close:** a tab closed from the panel stays for 8 s, struck through, with a `↶` where its `✕` was.
  Click it to bring the tab back (container, workspace and window as before). It goes when another tab closes,
  and shows only where it was closed. A click within 0.5 s is ignored, so a double click on `✕` can't undo itself.
  Tabs closed in the browser get none: use its Ctrl+Shift+T.
- **Find a tab:** the 🔍 opens a small window beside the panel. Typing narrows the list to tabs whose title or
  address holds every word, across all workspaces. Enter opens the first match, Escape gives the list back.
- **From the keyboard:** `tabdock --find` shows the panel and that window from any app (see Hotkey); the same
  key closes it again. There: Down/Up highlight a tab, Page Down/Up move ten, Home/End jump, Enter opens it,
  Escape closes. While nothing is typed, Left/Right switch workspace. Ctrl+Shift+T reopens the last closed tab.
- **Containers:** right-click a section to rename it, change colour or icon, make a new one, or remove it
  (asks first; its tabs close and Firefox deletes its cookies).
- **Reorder:** drag sections, and tabs within their container. The order is kept per browser profile.
- **Several browsers:** chips under the header pick `auto` (browser in use), one browser, or `all`.
  Clicking a tab of another browser raises it.
- **Tab groups:** a tab in a Firefox tab group shows the group's name in its colour.
- **Pin** keeps the panel open and reserves space on an outer screen edge (an inner edge becomes an overlay).
  `⇄` flips the side, `✕` quits until the next browser start. The panel never takes keyboard focus.

## Configuration

`./install.sh` copies [configs/config.toml](../configs/config.toml) (every option explained) to
`~/.config/tabdock/config.toml` if you have none; the Arch package ships it at
`/usr/share/tabdock/configs/config.toml`. `tabdock -h` shows the path. The file is read at start; SIGHUP reloads it.

| key | default | meaning |
|-----|---------|---------|
| `side` | `"left"` | `"left"` or `"right"` |
| `monitor` | `"outer"` | `"outer"` (screen's outer edge for `side`), `"primary"`, or an `xrandr` output name |
| `width` | `320` | px, 100-1000 |
| `follow` | `"last"` | while a non-browser window is active: `"last"` keeps the last browser, `"hide"` hides |
| `view` | `"auto"` | `"auto"` or `"all"` at start |
| `icons` | `false` | site icons before titles (see Site icons); the header's `icons` button switches them for the session |
| `badges` | `true` | badge for an unread count in a title, `"(3) Inbox"` |
| `bookmarks` | `false` | Tabs / Bookmarks buttons at the bottom of the panel (see Bookmarks) |
| `pinned` | `false` | start pinned |
| `start_with_browser` | `true` | start the panel when a browser with the extension opens |

**Colours:** each browser has its own (Firefox orange, Zen purple, FireDragon red, Waterfox teal, LibreWolf blue,
Floorp gold, Midori green). Override in `[theme]`, last in the file, or right-click the browser's name at the top
left of the panel (one browser listed; under "All browsers" pick its chip first):

```toml
[theme]
accent = "#4c9aff"    # every browser
firefox = "#4c9aff"   # or one browser (zen, firedragon, librewolf, waterfox, floorp, midori); wins over accent
other = "#8f9bb3"     # any other browser, and the strip while none is connected
```

Colours are `"#rrggbb"` or `"#rgb"`; on a dark accent the text turns white.

**Bookmarks** are off by default. Turn them on:

1. Install the new extension (`docs/INSTALL.md`).
2. `about:addons` → tabdock → *Preferences* → tick *Allow tabdock to read bookmarks*.
3. Set `bookmarks = true` in the config and restart the panel.

*Tabs* and *Bookmarks* buttons appear at the bottom of the panel. Click a folder to fold it, a bookmark to open it in a
new tab. Find searches the bookmarks while that view is up. Only `http(s)` bookmarks are listed. Bookmarks go to the
panel on this computer only.

**Site icons** are off by default. `data:` icons need no network; every other icon is downloaded by the **panel
itself**, not the browser: from your own address and DNS, outside the browser's proxy, VPN, DoH and per-container
settings, for every listed tab, private-window tabs included if the extension is allowed there. Leave it off if
that matters to you. Limits: `https:` only, no cookies or referrer, public addresses only (checked again after
redirects and DNS), 256 KB and 10 s, decoded in a sandboxed child process, kept in memory only. A tab without an
icon says why on hover.

### Workspaces

Exclusive, Zen style: a window shows one workspace and the other tabs are hidden (`tabs.hide`), in Firefox's tab
strip too. Nothing changes until you add a second one with `+`; your tabs are then "Default".

- Click a chip to switch, right-click to rename, set icon or colour, choose a container for its new tabs, or remove
  it (its tabs move to the neighbour; the last one stays). Right-click a tab to move it.
- New tabs and dragged-in tabs join the workspace the window shows. Pinned tabs show in every workspace.
- Ctrl+Alt+PageDown/PageUp and Ctrl+Alt+1…9 switch (change them in `about:addons` → Manage Extension Shortcuts).
- Workspaces survive browser restarts. Disabling or removing the extension shows every hidden tab again.
  Zen has its own workspaces, so the panel offers none there.
- Set `browser.tabs.closeWindowWithLastTab` to `false` in `about:config`: Firefox ignores hidden tabs when it counts
  a window's last tab, so with `true` closing a workspace's last tab in the browser closes the window and the other
  workspaces' tabs (History → Recently Closed Windows brings them back). Closing from the panel is always safe: the
  workspace gets a new tab first.

### Hotkey

tabdock grabs no key. Bind `tabdock --find` in your window manager. In Openbox, inside `<keyboard>` in
`~/.config/openbox/rc.xml`, then `openbox --reconfigure`:

```xml
<keybind key="W-grave">
  <action name="Execute"><command>tabdock --find</command></action>
</keybind>
```

`W-` is Super, `A-` Alt, `C-` Ctrl, `S-` Shift; `xev` prints key names. The panel must be running.

### Multiple monitors

`monitor = "outer"` puts the panel on the screen's outer edge for `side`, the only edge X11 can reserve space on.
Use `"primary"` or an output name to choose another (a pin there is an overlay). The panel follows monitor changes.

## Troubleshooting

- **No panel when a browser opens:** run `tabdock` in a terminal (a bad `config.toml` is reported there). A panel
  the browser started logs to `$XDG_RUNTIME_DIR/tabdock.log`.
- **"Waiting for a browser with the Tabdock extension":** see [INSTALL.md](INSTALL.md).
- **Panel reacts on part of the edge only:** invisible windows of another tool catch the pointer.
  `xwininfo -root -tree | grep -E ' (2x[0-9]+|[0-9]+x2)\+'` lists them.
