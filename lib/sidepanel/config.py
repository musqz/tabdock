import os
import tomllib

DEFAULTS = {"side": "left", "monitor": "primary", "width": 320, "follow": "last", "pinned": False}
CHOICES = {"side": ("left", "right"), "follow": ("last", "hide")}


def socket_path():
    return os.environ.get("SIDEPANEL_SOCKET") or os.path.join(
        os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "openbox-sidepanel.sock"
    )


def config_path():
    return os.path.join(
        os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
        "openbox-sidepanel",
        "config.toml",
    )


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
        raise ValueError('monitor must be "primary" or an output name such as "HDMI-1"')
    if not isinstance(cfg["pinned"], bool):
        raise ValueError(f'pinned must be true or false (got {cfg["pinned"]!r})')
    return cfg


def load(path=None):
    """Defaults overlaid with ~/.config/openbox-sidepanel/config.toml (if present)."""
    try:
        with open(path or config_path(), "rb") as f:
            user = tomllib.load(f)
    except FileNotFoundError:
        user = {}
    return validate(user)
