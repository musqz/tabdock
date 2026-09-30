"""Console view for --debug (no GUI, no display needed). The real panel is dock.DockView;
both take the same calls from app.Panel."""
from .model import format_state


class ConsoleView:
    xids = frozenset()

    def show(self, sources, mode="auto", choices=(), focus=None, offline=()):
        for _conn, info, state in sources:
            print(format_state(info, state), flush=True)

    def clear(self, mode="auto", choices=(), offline=()):
        pass

    def set_hidden(self, hidden):
        pass

    def show_bookmarks(self, conn, msg):
        pass

    def show_history(self, conn, msg):
        pass

    def find(self):
        pass

    def toggle_pin(self):
        pass

    def toggle_icons(self):
        pass

    def flip_side(self):
        pass

    def new_workspace(self):
        pass

    def nav_next(self):
        pass

    def nav_prev(self):
        pass

    def nav_open(self):
        pass

    def toggle_all(self):
        pass

    def ws_next(self):
        pass

    def ws_prev(self):
        pass

    def reconfigure(self, cfg):
        pass
