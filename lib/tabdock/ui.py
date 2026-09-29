"""Console view for --debug (no GUI, no display needed). The real panel is dock.DockView;
both take the same calls from app.Panel."""
from .model import format_state


class ConsoleView:
    xids = frozenset()

    def show(self, sources, mode="auto", choices=(), focus=None):
        for _conn, info, state in sources:
            print(format_state(info, state), flush=True)

    def clear(self, mode="auto", choices=()):
        pass

    def set_hidden(self, hidden):
        pass

    def show_bookmarks(self, conn, msg):
        pass

    def show_history(self, conn, msg):
        pass

    def find(self):
        pass

    def reconfigure(self, cfg):
        pass
