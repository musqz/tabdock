# Tabdock

An autohiding X11/Openbox side panel that mirrors the focused browser's tabs and containers, two-way,
through a small WebExtension.

Status: **0.4.0, installable.**

```
Firefox + extension/  <-- native messaging -->  lib/native-host/tabdock-nmhost  <-- unix socket -->  tabdock
```

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

<img width="320" height="1440" alt="Image" src="https://github.com/user-attachments/assets/14557b70-0a00-4510-99c8-65a62725c298" />

<img width="320" height="1440" alt="Image" src="https://github.com/user-attachments/assets/d7ae7694-e9c7-4da3-9797-a997a611c256" />
