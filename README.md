# Tabdock

An autohiding X11/Openbox side panel that mirrors Firefox based browser's tabs and containers, two-way,
through a small WebExtension. Chromium based browser's are not supported.

## Install

Needs `python-gobject` (GTK 3) and `python-xlib`.

```bash
./install.sh                     # program -> ~/.local, browser manifest, "Tabdock" menu entry, a config
packaging/sign-extension.sh      # signs the extension (safe prompts for your Mozilla credentials)
```

Release Firefox and Zen only keep **signed** extensions, so it needs signing once (free, via
addons.mozilla.org, unlisted) before it survives a restart.

`./install.sh --uninstall` removes exactly what was installed.

**Arch Linux:** `cd packaging && makepkg -si` installs the latest release system-wide instead. Full
signing steps, install locations and every way to start the panel: [docs/RELEASE.md](docs/RELEASE.md).

## Docs

- [docs/USAGE.md](docs/USAGE.md) — how it behaves, configuration, troubleshooting
- [docs/RELEASE.md](docs/RELEASE.md) — signing, install locations, releasing a version
- [docs/PROTOCOL.md](docs/PROTOCOL.md) — the panel/extension/relay wire protocol
- [docs/PLAN.md](docs/PLAN.md) — design, milestones, repo layout

<img width="320" height="1440" alt="Image" src="https://github.com/user-attachments/assets/764e92bf-bfef-45dd-8a08-6cd2d1bb4fdc" />

<img width="320" height="1440" alt="Image" src="https://github.com/user-attachments/assets/a7a5d1f0-794a-4a29-b622-d81934ae400d" />
