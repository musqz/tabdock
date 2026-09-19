# Changelog

## 0.2.0 (unreleased)

- Permanent install. `install.sh` now copies the program to `~/.local/share/openbox-sidepanel` with
  `~/.local/bin/sidepanel` linking to it (`PREFIX`/`SUDO` overrides), points the native-messaging
  manifest at the installed relay, keeps a receipt so `--uninstall` removes exactly what it created
  and upgrades drop files a newer version no longer ships, refuses to replace a foreign `sidepanel`
  command, and finishes by running the installed `sidepanel --version`. `VERSION` file and
  `sidepanel --version` added.
- Extension ready for signing: icons, `strict_min_version`, the "no data collected" declaration AMO
  requires, description within AMO's limit; passes `web-ext lint` with 0 errors and 0 warnings.
  `packaging/build-extension.sh` builds a reproducible `.xpi`; tests keep the manifest, the project
  version and the native-messaging manifest consistent.
- `docs/RELEASE.md`: signing (AMO unlisted), installing the signed `.xpi`, the Openbox autostart line,
  a reboot check and troubleshooting, including other tools' edge-hotspot windows that shadow the strip.
- Browser identity comes from the process behind the relay, not from `getBrowserInfo()`, which
  reports Zen as "Firefox". Window ownership is one-directional (the window is the browser
  process or one of its children), so the terminal that launched a browser is not mistaken for it.
- M2: the real panel. Autohiding dock (strip + panel windows) on the left or right edge of a
  chosen monitor; follows the active browser window (process tree first, window class as
  fallback); the header names the browser and the collapsed strip is tinted in its colour so
  the active browser is always recognisable; container sections with colour and icon;
  click-to-activate that never steals focus and raises the browser when another app is active;
  pin (strut on outer edges), side switch, `follow = last|hide`, config file with validation,
  reload on SIGHUP. Animation is left to the compositor: `configs/picom-sidepanel.conf` is a
  picom rule (no shadow/blur/corners, slide-in/out) for the panel windows.
- M1: tracer bullet. WebExtension sends debounced full snapshots (windows, tabs, containers)
  and executes `activate_tab`; native-messaging relay waits for the panel and asks the
  extension to resync on every (re)connect and to stop pushing when the panel is gone;
  `--debug` console view; `install.sh` writes the Firefox native-messaging manifest.
- M0: repo skeleton, config loader, protocol doc.
