# Tabdock

An autohiding X11/Openbox side panel that mirrors the tabs and containers of Firefox-based browsers, two-way,
through a small WebExtension. Chromium-based browsers are not supported.

## Installing 2 way's

Needs `python-gobject` (GTK 3) and `python-xlib`.

### 1. Manual installation

```bash
git clone https://github.com/musqz/tabdock.git
cd tabdock
./install.sh
```

Then save the signed `tabdock-*.xpi` from the [latest release](https://github.com/musqz/tabdock/releases/latest).

_(right-click → *Save Link As…*)_ and load it in each browser: `about:addons` → gear → *Install Add-on From File…*.

#### Uninstall manual installation
`./install.sh --uninstall` removes what it installed.

### 2. Arch Linux: installs the latest release system-wide

```
git clone https://github.com/musqz/tabdock.git
cd packaging && makepkg -si
```

The extension can be find
```
/usr/share/tabdock/tabdock.xpi
```

## Docs

- [docs/INSTALL.md](docs/INSTALL.md) — install, extension, starting the panel, troubleshooting
- [docs/USAGE.md](docs/USAGE.md) — how it behaves, configuration
- [docs/PROTOCOL.md](docs/PROTOCOL.md) — the panel/extension/relay wire protocol


<img width="320" height="1440" alt="Image" src="https://github.com/user-attachments/assets/2947f70e-d2bc-4bfd-8b50-2c61f582804d" />
