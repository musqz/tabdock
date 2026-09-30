# Install

## Program

```bash
./install.sh     # ~/.local/share/tabdock, ~/.local/bin/tabdock, a "Tabdock" menu entry, a config to edit
```

`PREFIX=/usr SUDO=sudo ./install.sh` installs system-wide; `./install.sh --uninstall` removes what it installed.
It also writes the native-messaging manifest `~/.mozilla/native-messaging-hosts/openbox_sidepanel.json`, which
every Firefox-based browser reads (the name is the extension's id and stays). It removes an install from before
the rename to tabdock and points at autostart or `rc.xml` lines that still start `sidepanel`.

**Arch:** `cd packaging && makepkg -si` installs everything system-wide, with the extension at
`/usr/share/tabdock/tabdock.xpi`. Use the package or `install.sh`, not both: a per-user manifest overrides the
package's.

## Extension

Firefox-based browsers keep only **signed** extensions. Install the signed `tabdock-<version>.xpi` from the
GitHub release (the package ships it as `/usr/share/tabdock/tabdock.xpi`): `about:addons` → gear →
*Install Add-on From File…*, once per browser. If it is gone after the first restart, install it again.

`about:debugging` loads an unsigned build, only until the browser restarts. To sign your own,
`packaging/sign-extension.sh` asks for your addons.mozilla.org API keys and leaves the `.xpi` in
`web-ext-artifacts/`.

A newer extension adds features; an older one keeps working and the panel offers only what it says it handles.

Permissions: `tabs`, `contextualIdentities` + `cookies` (containers), `nativeMessaging`, `storage` (container order,
workspaces), `tabHide` (workspaces), `sessions` (remember workspaces), `tabGroups` (group names and colours; naming a new group).
Optional, switched on in `about:addons` → Tabdock → *Permissions and data*: `bookmarks`, `history` (the panel's Bookmarks and History views).
Nothing leaves your computer.

## Update

`git pull`, then `./install.sh` again (it copies the panel; a pull alone changes nothing installed) and restart the
panel (`✕`, then open a browser or use the menu). Extensions are unlisted and never update themselves: when a
release says so, install the new signed `.xpi` in each browser again.

## Start the panel

Any of these; a second instance refuses to start.

- **With the browser** (default): opening a browser with the extension starts it. Turn off with
  `start_with_browser = false`. A panel you quit with `✕` stays gone until the next browser start.
- **Menu:** the "Tabdock" entry.
- **Login:** `(sleep 5.0s && ~/.local/bin/tabdock) &` in `~/.config/openbox/autostart`.

## Troubleshooting

"Waiting for a browser with the Tabdock extension": the extension is missing or disabled (`about:addons`), or the
manifest is gone (re-run `./install.sh`). Errors show in `about:debugging#/runtime/this-firefox` → Inspect →
Console. A panel the browser started logs to `$XDG_RUNTIME_DIR/tabdock.log`.
