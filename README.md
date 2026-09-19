# openbox-sidepanel

A desktop side panel for Openbox/X11 that shows the tabs and containers of the focused
Firefox-family browser, kept in two-way sync through a small WebExtension. Goal: Zen-style
sidebar (containers, workspaces, autohide) that works in Firefox, FireDragon, LibreWolf, Zen.

Status: **M1 tracer bullet.** The whole pipe works (browser <-> extension <-> relay <-> panel,
both directions, panel restarts), shown in a plain GTK tree. The dock/autohide panel is M2.
See [docs/PLAN.md](docs/PLAN.md) for the plan and [docs/PROTOCOL.md](docs/PROTOCOL.md) for the wire format.

```
Firefox + extension/  <-- native messaging -->  lib/native-host/sidepanel-nmhost  <-- unix socket -->  sidepanel
```

## Try it (development)

Needs `python-gobject` (GTK 3) on X11. Native browser installs only, no Flatpak/Snap.

```bash
./install.sh                # native-messaging manifest for Firefox (points at this checkout)
./sidepanel                 # plain GTK window; add --debug for a console view (no GUI)
```

Then in Firefox open `about:debugging#/runtime/this-firefox`, "Load Temporary Add-on...",
and pick `extension/manifest.json`. The tabs, grouped by container, appear in the window;
double-click a tab to activate it in the browser. `./install.sh --uninstall` removes the manifest.

## Tests

```bash
python3 -m unittest discover -s tests     # model, relay protocol, real panel, install.sh, GTK view
python3 tests/e2e_firefox.py              # slow: real headless Firefox with the extension
```

The end-to-end script uses a scratch profile and a throwaway `$HOME`; it never touches your
real profile or native-messaging directory.

## Layout

| Path | What |
|------|------|
| `sidepanel` | main executable |
| `lib/sidepanel/` | panel: socket server, model, views |
| `lib/native-host/` | native-messaging relay |
| `extension/` | the WebExtension (MV2) |
| `configs/` | native-messaging manifest template |
| `docs/` | plan and protocol |
| `tests/` | unit, protocol and end-to-end tests |
