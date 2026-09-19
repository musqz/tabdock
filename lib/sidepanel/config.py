import os
import tomllib

DEFAULTS = {"side": "left", "monitor": "primary", "width": 320, "follow": "last"}


def socket_path():
    return os.environ.get("SIDEPANEL_SOCKET") or os.path.join(
        os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "openbox-sidepanel.sock"
    )


def load(path=None):
    """Defaults overlaid with ~/.config/openbox-sidepanel/config.toml (if present)."""
    path = path or os.path.join(
        os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
        "openbox-sidepanel",
        "config.toml",
    )
    cfg = dict(DEFAULTS)
    try:
        with open(path, "rb") as f:
            cfg.update(tomllib.load(f))
    except FileNotFoundError:
        pass
    return cfg
