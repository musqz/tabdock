# Install

## Program

Pick one.

**AUR:**

```bash
yay -S tabdock-bin
```

**Mabox:**

```bash
sudo pacman -S tabdock
```

**Arch, built from the latest release:**

```bash
git clone https://github.com/musqz/tabdock.git
cd tabdock/packaging && makepkg -si
```

**Manual, per user:**

```bash
git clone https://github.com/musqz/tabdock.git
cd tabdock
./install.sh
```

Installs to `~/.local/share/tabdock` and `~/.local/bin/tabdock`, with a "Tabdock" menu entry, a config to edit and `man tabdock`.
Also writes the native-messaging manifest `~/.mozilla/native-messaging-hosts/openbox_sidepanel.json`
(the name is the extension's id and stays).

```bash
PREFIX=/usr SUDO=sudo ./install.sh   # system-wide
./install.sh --uninstall             # remove what it installed
```

Use one of these, not two: a per-user manifest overrides the package's, and `tabdock-bin` replaces the Mabox `tabdock`.
`install.sh` also removes an install from before the rename to tabdock and points at autostart or `rc.xml` lines that still start `sidepanel`.

### Dependencies

The packages pull in the X11 ones; on Wayland also install `gtk-layer-shell` and `python-pywayland`.
For a manual install:

```bash
sudo pacman -S python-gobject gtk3 python-xlib                                  # X11
sudo pacman -S python-gobject gtk3 gtk-layer-shell python-pywayland             # Wayland (labwc, sway)
```

## Extension

Firefox-based browsers keep only signed extensions.

1. Get `tabdock-<version>.xpi` from the [latest release](https://github.com/musqz/tabdock/releases/latest).
   The packages ship it as `/usr/share/tabdock/tabdock.xpi`.
2. In each browser: `about:addons` → gear → *Install Add-on From File…*.
3. If it is gone after the first restart, install it again.

Your own build: `packaging/sign-extension.sh` asks for your addons.mozilla.org API keys and leaves the `.xpi` in `web-ext-artifacts/`.
`about:debugging` loads an unsigned build until the browser restarts.

A newer extension adds features; an older one keeps working and the panel offers only what it says it handles.

Permissions: `tabs`, `contextualIdentities` + `cookies` (containers), `nativeMessaging`, `storage` (container order,
workspaces), `tabHide` (workspaces), `sessions` (remember workspaces), `tabGroups` (group names and colours; naming a new group).
Optional, in `about:addons` → Tabdock → *Permissions and data*: `bookmarks`, `history` (the Bookmarks and History views).
Nothing leaves your computer.

## Start the panel

Any of these; a second instance refuses to start.

- **With the browser** (default): opening a browser with the extension starts it.
  Turn off: `start_with_browser = false` in `~/.config/tabdock/config.toml`. A panel you quit with `✕` stays gone until the next browser start.
- **Menu:** the "Tabdock" entry.
- **Login, Openbox**, in `~/.config/openbox/autostart`:

  ```bash
  (sleep 5.0s && ~/.local/bin/tabdock) &    # manual install; /usr/bin/tabdock for a package
  ```

- **Login, labwc**, in `~/.config/labwc/autostart`:

  ```bash
  ~/.local/bin/tabdock &                    # manual install; /usr/bin/tabdock for a package
  ```

## Update

AUR or Mabox package: update with your package manager.

Built from the release with `makepkg -si`:

```bash
cd tabdock
git pull
cd packaging && makepkg -si
```

Manual:

```bash
cd tabdock
git pull
./install.sh
```

Then restart the panel: `✕`, then open a browser or use the menu.
Extensions never update themselves: when a release says so, install the new signed `.xpi` in each browser again.

## Wayland (labwc, sway)

```bash
sudo pacman -S gtk-layer-shell python-pywayland
tabdock
```

Two browsers of the same kind (two Firefox profiles) are not told apart; pick one with its chip.

## Troubleshooting

"Waiting for a browser with the Tabdock extension": the extension is missing or disabled (`about:addons`), or the manifest is gone.

```bash
./install.sh                        # manual install only: writes the manifest again
tail "$XDG_RUNTIME_DIR/tabdock.log" # a panel the browser started logs here
```

Extension errors: `about:debugging#/runtime/this-firefox` → Inspect → Console.
