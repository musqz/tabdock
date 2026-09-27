# Installing for daily use

Release Firefox and Zen only keep **signed** extensions. Loading one through `about:debugging` is
temporary: the browser forgets it on restart. So a permanent setup has three parts: the program
(`install.sh`), a signed extension, and an autostart line.

## 1. Install the program

```bash
./install.sh
```

Installs to `~/.local/share/tabdock` with `~/.local/bin/tabdock` linking to it, plus the
native-messaging manifest `~/.mozilla/native-messaging-hosts/openbox_sidepanel.json` (Firefox and Zen
both read it; it keeps the name the extension looks for). It prints every file it touches and ends by
running `tabdock --version` from the installed copy. An install from before the rename to tabdock
(`~/.local/share/openbox-sidepanel`, `~/.local/bin/sidepanel`) is removed on the way, and lines in your
Openbox `autostart` or `rc.xml` that still start `sidepanel` are pointed out. Nothing else is edited.
`PREFIX=/usr SUDO=sudo ./install.sh` installs the program system-wide (the manifest stays per-user).
`./install.sh --uninstall` removes exactly what was installed.

On Arch, the package does all of this system-wide instead: `cd packaging && makepkg -si` installs the
program to `/usr/share/tabdock`, `/usr/bin/tabdock`, the menu entry, the signed extension, and the manifest
in `/usr/lib/mozilla/native-messaging-hosts`. Use one or the other: a per-user manifest from `install.sh`
overrides the package's.

## 2. Get the extension signed (once per version)

**Installed tabdock from a package** (an AUR or repo build)? Skip to step 3 below: the package ships
the extension already signed, at a fixed path (`/usr/share/tabdock/tabdock.xpi`). Signing happens once
per release, by the maintainer (see "Releasing a version"), not per user. The rest of this section is only
for a from-source install.

Signing needs a free Mozilla account, which only you can create. Then:

1. Sign in at <https://addons.mozilla.org/developers/> and open **Manage API Keys**
   (<https://addons.mozilla.org/developers/addon/api/key/>). **Generate new credentials** gives you two values:
   the *JWT issuer*, which looks like `user:12345678:123` (copy all of it, including the word `user:`), and the
   *JWT secret*, 64 characters.
2. Run the script. It asks for the two values one at a time (the secret is hidden while you paste it),
   checks them before anything is sent, lints the extension, signs it as **unlisted** (private, automatic,
   usually a few minutes) and verifies that the signature is inside the resulting file:

   ```bash
   packaging/sign-extension.sh
   ```

   The credentials go to web-ext through the script's own environment only: never on a command line, in
   your shell history, or in the repo. `--save` remembers them in `~/.config/tabdock/amo-credentials`
   (mode 600, outside the repo) so the next release needs no typing; `--forget` deletes that file; `--dry-run`
   checks everything except contacting Mozilla. It refuses to run if the version has already been signed.
   If a value has the wrong shape (an issuer without `user:`, a secret that is not 64 characters) it says so
   and sends nothing.
3. The signed `.xpi` is written to `web-ext-artifacts/` (the script prints the path). Install it in each
   browser: `about:addons` -> gear icon -> **Install Add-on From File...** -> pick the signed file
   (`web-ext-artifacts/*.xpi` here, or `/usr/share/tabdock/tabdock.xpi` if you installed from a package).
   It survives restarts. Use the same signed file in every browser (Firefox, Zen, FireDragon, Waterfox,
   LibreWolf); each has its own add-ons list, so install it once per browser.

To build the unsigned file yourself: `packaging/build-extension.sh`, and to lint by hand:
`npx web-ext lint --source-dir extension` (expect 0 errors, 0 warnings).

The add-on id `openbox-sidepanel@musqz.local` is fixed in the manifest and must match the native-messaging
manifest (a test checks this). The id and the native-messaging name `openbox_sidepanel` kept their old names
through the rename to tabdock: a new id would be a different add-on (losing the stored container order), and a
new native-messaging name would break every install whose extension and manifest are not updated together.
AMO rejects a version number it has already signed, so bump `VERSION` and `extension/manifest.json` together
for every new signature (a test checks they agree).

What the permissions are for: `nativeMessaging` (talk to the local helper), `tabs` (list, activate and move
tabs), `contextualIdentities` and `cookies` (list containers; Firefox requires `cookies` for that API),
`storage` (remember the order you gave your container sections and your workspaces, per browser profile),
`tabHide` (a workspace hides the other workspaces' tabs) and `sessions` (remember, across browser restarts,
which workspace each tab is in and which one each window shows). The manifest declares that no data is
collected, and nothing leaves your computer.

**A new version needs a new signature.** Workspaces (after 0.3.1) add the `tabHide` and `sessions`
permissions and the workspace commands, so the next version needs a new signing and Firefox asks you to
approve the two permissions when you install it; until then the panel works as before, without workspaces.
Version 0.3.0 added the `storage` permission and the reorder commands, so it must be signed again (the
same command as above, and Mozilla rejects a version number it has already signed) and installed in each
browser over the old one. Firefox may ask you to approve the new permission when it updates. Until then
the old extension keeps working, but dragging in the panel does nothing in the browser.

*Optional, later:* the **listed** channel publishes it on addons.mozilla.org: a manual review, then
automatic updates for everyone. It is desktop-only (uncheck Android) and the description must explain that
a local helper is required.

## 3. Start the panel

You never need a terminal. Any of these works, and they combine freely (a second instance refuses to
start, and each browser's helper waits for the panel):

- **With the browser (default).** Opening a browser that has the extension starts the panel if none is
  running. This happens once per browser start, so a panel you quit with its `✕` stays gone until the next
  browser start. The panel keeps running after the browser closes. Turn it off with
  `start_with_browser = false` in `~/.config/tabdock/config.toml`. Its output goes to
  `$XDG_RUNTIME_DIR/tabdock.log` if it ever fails to start (`tabdock -h` shows both paths).
- **From the application menu.** `install.sh` adds a "Tabdock" entry (`~/.local/share/applications/`),
  which jgmenu, rofi and similar launchers list.
- **At login.** Add this to `~/.config/openbox/autostart`, after picom (4.0 s) so the compositor rules
  apply from the first frame:

  ```bash
  (sleep 5.0s && ~/.local/bin/tabdock) &           # Tabdock
  ```
- **From a keyboard shortcut.** In `~/.config/openbox/rc.xml`, inside `<keyboard>`:
  `<keybind key="W-p"><action name="Execute"><command>/home/you/.local/bin/tabdock</command></action></keybind>`
  (pressing it while the panel runs does nothing).

Starting with the browser only needs the extension to be installed; with an autostart line the panel is
also there before any browser opens.

## 4. Reboot check

1. Log in again. With an autostart line, `pgrep -a -f 'tabdock$'` already shows the panel; otherwise
   open Firefox and it appears.
2. Open Firefox: the extension is enabled in `about:addons` and the panel lists your tabs. Same for Zen.

If the panel says "Waiting for a browser with the Tabdock extension":
- the extension is not installed or is disabled (`about:addons`);
- `~/.mozilla/native-messaging-hosts/openbox_sidepanel.json` is missing, or its `path` no longer exists
  (re-run `./install.sh`);
- see errors in `about:debugging#/runtime/this-firefox` -> Inspect -> Console.

If the panel only reacts on part of the screen edge, another tool has invisible hotspot windows there
(for example `fittsmon`'s `[Left]` position). They sit above every normal window and catch the pointer
first. List them with `xwininfo -root -tree | grep -E ' (2x[0-9]+|[0-9]+x2)\+'`, then either remove that
position from the other tool's config or put the panel on an edge without one (`side` and `monitor` in
`~/.config/tabdock/config.toml`).

## 5. Updating

Bump `VERSION` and `extension/manifest.json`, run `./install.sh`, then rebuild, sign and install the new
`.xpi` as above. Unlisted extensions do not auto-update.

## 6. Releasing a version

`VERSION` is the one version number: the panel reports it, the extension's manifest must match it (a test
checks this), the tag is `v` + `VERSION`, and the package refuses sources whose `VERSION` differs from its
`pkgver`.

1. Bump `VERSION` and `extension/manifest.json`, rename the changelog's `## Unreleased` to the new version,
   and merge that to `main`.
2. Sign the extension from that `main`: `packaging/sign-extension.sh`. Sign last, after every change to
   `extension/`: the signed file must match the tagged sources exactly (the PKGBUILD checks this), and a
   version, once signed, cannot be signed again, so a later change to `extension/` needs a new version.
3. Tag `main` once the bump is merged, and push the tag. Take the version from `VERSION` rather than typing
   it: tagging before the bump is merged then asks for the previous version's tag, which already exists, so
   `git tag` refuses instead of tagging sources that still say the old version (v0.3.1 was first tagged
   that way, one merge too early).

   ```bash
   git switch main && git pull && v=$(<VERSION)
   git tag -a "v$v" -m "tabdock $v" && git push origin "v$v"
   ```
4. On GitHub, **Releases -> Draft a new release**, pick the tag, and attach the signed file from
   `web-ext-artifacts/`, renamed to `tabdock-0.3.1.xpi` (the PKGBUILD downloads it by that name, so a
   release without it cannot be packaged).
5. In `packaging/PKGBUILD` set `pkgver` (and `pkgrel=1`), run `updpkgsums`, then `makepkg -si` to try it.
   For the AUR, also `makepkg --printsrcinfo > .SRCINFO`.
