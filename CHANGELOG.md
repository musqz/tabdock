# Changelog

## Unreleased

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
