# Tabdock

An autohiding X11/Openbox side panel that mirrors the tabs and containers of Firefox-based browsers, two-way,
through a small WebExtension. Chromium-based browsers are not supported.

## Install

Needs `python-gobject` (GTK 3) and `python-xlib`.

```bash
./install.sh     # program -> ~/.local, browser manifest, "Tabdock" menu entry, a config
```

Then install the signed `tabdock-*.xpi` from the [latest release](https://github.com/musqz/tabdock/releases/latest)
in each browser: `about:addons` → gear → *Install Add-on From File…* (Firefox-based browsers keep only signed
extensions). Download it with right-click → *Save Link As…*; clicking the link makes the browser try to install
it directly, which can fail. `./install.sh --uninstall` removes exactly what it installed.

**Arch Linux:** `cd packaging && makepkg -si` installs the latest release system-wide; the extension is then
`/usr/share/tabdock/tabdock.xpi`.

## Docs

- [docs/INSTALL.md](docs/INSTALL.md) — install, extension, starting the panel, troubleshooting
- [docs/USAGE.md](docs/USAGE.md) — how it behaves, configuration
- [docs/PROTOCOL.md](docs/PROTOCOL.md) — the panel/extension/relay wire protocol


<img width="320" height="1440" alt="Image" src="https://github.com/user-attachments/assets/2947f70e-d2bc-4bfd-8b50-2c61f582804d" />
