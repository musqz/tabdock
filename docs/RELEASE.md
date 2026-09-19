# Installing for daily use

Release Firefox and Zen only keep **signed** extensions. Loading one through `about:debugging` is
temporary: the browser forgets it on restart. So a permanent setup has three parts: the program
(`install.sh`), a signed extension, and an autostart line.

## 1. Install the program

```bash
./install.sh
```

Installs to `~/.local/share/openbox-sidepanel` with `~/.local/bin/sidepanel` linking to it, plus the
native-messaging manifest `~/.mozilla/native-messaging-hosts/openbox_sidepanel.json` (Firefox and Zen
both read it). It prints every file it touches and ends by running `sidepanel --version` from the
installed copy. Nothing else is edited. `PREFIX=/usr SUDO=sudo ./install.sh` installs the program
system-wide (the manifest stays per-user). `./install.sh --uninstall` removes exactly what was installed.

## 2. Get the extension signed (once per version)

```bash
packaging/build-extension.sh                  # -> web-ext-artifacts/openbox-sidepanel-<version>.xpi (unsigned)
npx web-ext lint --source-dir extension       # Mozilla's linter: expect 0 errors, 0 warnings
```

Signing needs a free Mozilla account, which only you can create:

1. Sign in at <https://addons.mozilla.org/developers/> and open **Manage API Keys**
   (<https://addons.mozilla.org/developers/addon/api/key/>). Generate credentials: a *JWT issuer*
   (looks like `user:12345:67`) and a *JWT secret*. Keep the secret private and never commit it.
2. Sign as **unlisted** (private, automatic, usually done in minutes):

```bash
export WEB_EXT_API_KEY='user:12345:67'            # JWT issuer
export WEB_EXT_API_SECRET='...'                   # JWT secret
npx web-ext sign --source-dir extension --channel=unlisted --artifacts-dir web-ext-artifacts
```

3. The signed `.xpi` is written to `web-ext-artifacts/`. Install it in each browser:
   `about:addons` -> gear icon -> **Install Add-on From File...** -> pick the signed file. It survives
   restarts. Use the same file for Firefox and Zen (LibreWolf and FireDragon later, see the plan).

The add-on id `openbox-sidepanel@musqz.local` is fixed in the manifest and must match the native-messaging
manifest (a test checks this). AMO rejects a version number it has already signed, so bump `VERSION`
and `extension/manifest.json` together for every new signature (a test checks they agree).

What the permissions are for: `nativeMessaging` (talk to the local helper), `tabs` (list and activate
tabs), `contextualIdentities` and `cookies` (list containers; Firefox requires `cookies` for that API).
The manifest declares that no data is collected, and nothing leaves your computer.

*Optional, later:* the **listed** channel publishes it on addons.mozilla.org: a manual review, then
automatic updates for everyone. It is desktop-only (uncheck Android) and the description must explain that
a local helper is required.

## 3. Start the panel at login

Add this to `~/.config/openbox/autostart`, after picom (4.0 s) so the compositor rules apply from
the first frame:

```bash
(sleep 5.0s && ~/.local/bin/sidepanel) &         # Sidepanel
```

A second instance refuses to start, and each browser's helper waits for the panel, so the start order
relative to the browsers does not matter.

## 4. Reboot check

1. Log in again: `pgrep -a -f 'sidepanel$'` shows the panel.
2. Open Firefox: the extension is enabled in `about:addons` and the panel lists your tabs. Same for Zen.

If the panel says "Waiting for a browser with the Sidepanel extension":
- the extension is not installed or is disabled (`about:addons`);
- `~/.mozilla/native-messaging-hosts/openbox_sidepanel.json` is missing, or its `path` no longer exists
  (re-run `./install.sh`);
- see errors in `about:debugging#/runtime/this-firefox` -> Inspect -> Console.

If the panel only reacts on part of the screen edge, another tool has invisible hotspot windows there
(for example `fittsmon`'s `[Left]` position). They sit above every normal window and catch the pointer
first. List them with `xwininfo -root -tree | grep -E ' (2x[0-9]+|[0-9]+x2)\+'`, then either remove that
position from the other tool's config or put the panel on an edge without one (`side` and `monitor` in
`~/.config/openbox-sidepanel/config.toml`).

## 5. Updating

Bump `VERSION` and `extension/manifest.json`, run `./install.sh`, then rebuild, sign and install the new
`.xpi` as above. Unlisted extensions do not auto-update.
