"""Views. M1 tracer: a console view (--debug) and a plain GTK tree.

The real dock/autohide panel replaces TreeView in M2; both take the same
show(conn, info, state) calls from app.Panel.
"""
from .model import browser_label, focused_window, format_state, group_tabs, tab_label


class ConsoleView:
    def show(self, conn, info, state):
        print(format_state(info, state), flush=True)


class TreeView:
    def __init__(self, on_activate, on_quit):
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk

        self.on_activate = on_activate
        self.conn = None
        self.store = Gtk.TreeStore(str, int, int)  # label, tab id, window id (-1 = container header)
        self.view = Gtk.TreeView(model=self.store)
        self.view.set_headers_visible(False)
        self.view.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=0))
        self.view.connect("row-activated", self._row_activated)

        scroll = Gtk.ScrolledWindow()
        scroll.add(self.view)
        self.win = Gtk.Window(title="openbox-sidepanel")
        self.win.set_default_size(320, 800)
        self.win.add(scroll)
        self.win.connect("destroy", lambda _w: on_quit())
        self.win.show_all()

    def show(self, conn, info, state):
        self.conn = conn
        self.win.set_title(browser_label(info))
        self.store.clear()
        win = focused_window(state)
        for container, tabs in group_tabs(state):
            parent = self.store.append(None, [f'{container["name"]} ({len(tabs)})', -1, -1])
            for tab in tabs:
                mark = "● " if tab.get("active") else "   "
                self.store.append(parent, [mark + tab_label(tab), tab["id"], win["id"]])
        self.view.expand_all()

    def _row_activated(self, _view, path, _column):
        row = self.store[path]
        if row[1] >= 0 and self.conn is not None:
            self.on_activate(self.conn, row[1], row[2])
