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

## Development

Run from the checkout with `./tabdock` (`--debug` for a console view, no GUI; `-h` for the options and where
its config and log are). To try the extension without signing: `about:debugging#/runtime/this-firefox` ->
"Load Temporary Add-on..." -> `extension/manifest.json` (forgotten on restart). Run `./install.sh` first so the
browser can reach the relay.

## Tests

```bash
python3 -m unittest discover -s tests     # pure logic, relay protocol, panel routing, GTK view, install.sh, PKGBUILD
python3 tests/e2e_firefox.py              # slow: real headless Firefox with the extension
python3 tests/e2e_x11.py                  # slow: the dock under real Openbox in a nested Xephyr window
python3 tests/e2e_multihead.py            # slow: two monitors under real Openbox: tiling respects a pinned panel
```

End-to-end tests use scratch profiles/displays and never touch your real profile or native-messaging
directory. `e2e_x11.py` opens a small Xephyr window on your desktop while it runs.

<img width="320" height="1440" alt="Image" src="https://github.com/user-attachments/assets/14557b70-0a00-4510-99c8-65a62725c298" />

<img width="320" height="1440" alt="Image" src="https://github.com/user-attachments/assets/d7ae7694-e9c7-4da3-9797-a997a611c256" />
