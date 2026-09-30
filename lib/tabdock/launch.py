import glob
import json
import os
import shutil
import subprocess
import sys
import threading

from .model import KNOWN_BROWSERS

ADDON_ID = "openbox-sidepanel@musqz.local"
# key -> (executables to try, profile roots relative to $HOME); Flatpak and Snap are not covered
BROWSERS = {
    "firefox": (("firefox",), (".mozilla/firefox", ".config/mozilla/firefox")),
    "zen": (("zen-browser", "zen"), (".zen", ".config/zen")),
    "librewolf": (("librewolf",), (".librewolf", ".config/librewolf")),
    "waterfox": (("waterfox",), (".waterfox", ".config/waterfox")),
    "floorp": (("floorp",), (".floorp", ".config/floorp")),
    "firedragon": (("firedragon",), (".firedragon", ".config/firedragon")),
}


def _has_addon(path):
    """Whether a profile's extensions.json lists the add-on; reads nothing else from it."""
    try:
        with open(path, encoding="utf-8") as f:
            return any(a.get("id") == ADDON_ID for a in json.load(f).get("addons", []))
    except (OSError, ValueError, AttributeError, TypeError):
        return False


def installed_browsers(home=None, which=shutil.which):
    """[(display name, executable)] of the browsers on PATH with a profile that has the add-on."""
    home = home or os.path.expanduser("~")
    found = []
    for key, name in KNOWN_BROWSERS:
        if key not in BROWSERS:
            continue
        names, roots = BROWSERS[key]
        binary = next((b for b in map(which, names) if b), None)
        if not binary:
            continue
        for root in roots:
            base = glob.escape(os.path.join(home, root))
            if any(_has_addon(p) for depth in ("/*", "/*/*") for p in glob.glob(base + depth + "/extensions.json")):
                found.append((name, binary))
                break
    return found


def launch(binary):
    # the panel may have been started by another browser's relay: its XRE_*/MOZ_* variables must not reach this one
    env = {k: v for k, v in os.environ.items() if not k.startswith(("XRE_", "MOZ_"))}
    try:
        proc = subprocess.Popen([binary], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True, close_fds=True, env=env)
    except OSError as e:
        print(f"tabdock: cannot start {binary}: {e}", file=sys.stderr)
        return
    threading.Thread(target=proc.wait, daemon=True).start()  # reap it when it exits
