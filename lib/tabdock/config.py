import os
import re
import tomllib

from .model import ACCENTS

DEFAULTS = {
    "side": "left",
    "monitor": "outer",
    "width": 320,
    "follow": "last",
    "view": "auto",
    "icons": False,  # site icons before the tab titles: off until asked for, the panel downloads them (see docs/USAGE.md)
    "badges": True,  # a tab's leading "(3)" unread count, shown as a small badge instead of plain text
    "bookmarks": False,  # a Bookmarks view under the tabs; also needs the permission granted in the extension's options
    "history": False,  # a History view under the tabs; also needs the permission granted in the extension's options
    "pinned": False,
    "launch_offline": False,  # list installed browsers that have the add-on but are not running; a click starts one
    "start_with_browser": True,  # read by the native-messaging relay, not by the panel itself
    "theme": {},  # the [theme] section: colours, only those given (model.accents() fills in the rest)
}
CHOICES = {"side": ("left", "right"), "follow": ("last", "hide"), "view": ("auto", "all")}
THEME_KEYS = ("accent", *ACCENTS, "other")
_COLOUR_RE = re.compile(r"#(?:[0-9a-f]{3}){1,2}", re.IGNORECASE)


def socket_path():
    return os.environ.get("TABDOCK_SOCKET") or os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "tabdock.sock")


def log_path():
    """Where the relay sends the output of a panel it starts (it computes the same path itself)."""
    return os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "tabdock.log")


LEGACY_DIR = "openbox-sidepanel"  # the config directory from before the rename to tabdock


def config_dir(name="tabdock"):
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), name)


def config_path():
    """~/.config/tabdock/config.toml, or the one from before the rename to tabdock while only that one exists."""
    path = os.path.join(config_dir(), "config.toml")
    legacy = os.path.join(config_dir(LEGACY_DIR), "config.toml")
    return legacy if not os.path.exists(path) and os.path.exists(legacy) else path


def validate(user):
    """Defaults overlaid with `user`; raises ValueError with a readable message."""
    unknown = sorted(set(user) - set(DEFAULTS))
    if unknown:
        raise ValueError(f'unknown option(s): {", ".join(unknown)} (known: {", ".join(DEFAULTS)})')
    cfg = {**DEFAULTS, **user}
    for key, allowed in CHOICES.items():
        if cfg[key] not in allowed:
            raise ValueError(f'{key} must be one of: {", ".join(allowed)} (got {cfg[key]!r})')
    if isinstance(cfg["width"], bool) or not isinstance(cfg["width"], int) or not 100 <= cfg["width"] <= 1000:
        raise ValueError(f'width must be an integer between 100 and 1000 (got {cfg["width"]!r})')
    if not isinstance(cfg["monitor"], str) or not cfg["monitor"]:
        raise ValueError('monitor must be "outer", "primary" or an output name such as "HDMI-1"')
    for key in ("icons", "badges", "bookmarks", "history", "pinned", "launch_offline", "start_with_browser"):
        if not isinstance(cfg[key], bool):
            raise ValueError(f"{key} must be true or false (got {cfg[key]!r})")
    cfg["theme"] = _theme(cfg["theme"])
    return cfg


def _theme(theme):
    """The [theme] section with every colour as "#rrggbb"; raises ValueError like validate()."""
    if not isinstance(theme, dict):
        raise ValueError(f"theme must be a [theme] section of colours (got {theme!r})")
    unknown = sorted(set(theme) - set(THEME_KEYS))
    if unknown:  # most likely an option written below the [theme] line, which TOML then counts as part of it
        raise ValueError(f'unknown option(s) in [theme]: {", ".join(unknown)} (known: {", ".join(THEME_KEYS)}); '
                         "every other option goes above the [theme] line")
    colours = {}
    for key, value in theme.items():
        if not isinstance(value, str) or not _COLOUR_RE.fullmatch(value):
            raise ValueError(f'theme {key} must be a colour such as "#4c9aff" (got {value!r})')
        value = value.lower()
        colours[key] = value if len(value) == 7 else "#" + "".join(c * 2 for c in value[1:])  # "#abc" -> "#aabbcc"
    return colours


_THEME_HEADER_RE = re.compile(r"^\[theme\]\s*$", re.MULTILINE)


def set_theme_colour(key, value, path=None):
    """Sets `key = "value"` in the [theme] section of the config file on disk (uncommenting or adding the
    line if needed), leaving every other line -- comments included -- untouched."""
    path = path or config_path()
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        text = ""
    new_line = f'{key} = "{value}"'
    header = _THEME_HEADER_RE.search(text)
    if header is None:
        body = text.rstrip("\n")
        text = f"{body}\n\n[theme]\n{new_line}\n" if body else f"[theme]\n{new_line}\n"
    else:
        head, body = text[: header.end()], text[header.end() :]
        line_re = re.compile(rf'^[ \t]*#?[ \t]*{re.escape(key)}\b[ \t]*=.*$', re.MULTILINE)
        body = line_re.sub(new_line, body, count=1) if line_re.search(body) else f"\n{new_line}{body}"
        text = head + body
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(path + ".tmp", path)


def load(path=None):
    """Defaults overlaid with config_path() (if present)."""
    try:
        with open(path or config_path(), "rb") as f:
            user = tomllib.load(f)
    except FileNotFoundError:
        user = {}
    except tomllib.TOMLDecodeError as e:
        lines = e.doc.splitlines() if e.doc else []
        line = lines[e.lineno - 1] if 0 < e.lineno <= len(lines) else None
        raise ValueError(f"{e}\n  {line}" if line else str(e)) from e
    return validate(user)
