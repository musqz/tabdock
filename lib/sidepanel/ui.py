"""Console view for --debug (no GUI, no display needed). The real panel is dock.DockView;
both take the same calls from app.Panel."""
from .model import format_state


class ConsoleView:
    xids = frozenset()

    def show(self, conn, info, state):
        print(format_state(info, state), flush=True)

    def clear(self):
        pass

    def set_hidden(self, hidden):
        pass

    def reconfigure(self, cfg):
        pass
