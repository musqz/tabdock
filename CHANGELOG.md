# Changelog

## Unreleased

- M0: repo skeleton, config loader, protocol doc.
- M1: tracer bullet. WebExtension sends debounced full snapshots (windows, tabs, containers)
  and executes `activate_tab`; native-messaging relay waits for the panel and asks the
  extension to resync on every (re)connect; panel shows tabs grouped by container in a plain
  GTK tree (`--debug` for a console view); `install.sh` writes the Firefox native-messaging manifest.
