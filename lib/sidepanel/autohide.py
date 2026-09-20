"""Open/close decisions for the hover strip (pure; timers are injected)."""


class Autohide:
    """Expands shortly after the pointer enters, collapses a bit after it leaves.

    apply(expanded) does the real work. schedule(ms, fn) -> handle and cancel(handle)
    wrap the main loop's timers, so this can be unit-tested with a fake clock.
    """

    def __init__(self, apply, schedule, cancel, open_ms=120, close_ms=400):
        self.apply = apply
        self.schedule = schedule
        self.cancel = cancel
        self.open_ms = open_ms
        self.close_ms = close_ms
        self.expanded = False
        self.pinned = False
        self.hovering = False
        self.held = False  # a drag is in progress: stay open wherever the pointer goes
        self._timer = None

    def enter(self):
        self.hovering = True
        self._update()

    def leave(self):
        self.hovering = False
        self._update()

    def set_pinned(self, pinned):
        self.pinned = pinned
        self._update()

    def set_held(self, held):
        self.held = held
        self._update()

    def _want(self):
        return self.pinned or self.hovering or self.held

    def _update(self):
        if self._timer is not None:
            self.cancel(self._timer)
            self._timer = None
        want = self._want()
        if want == self.expanded:
            return
        if self.pinned:
            self._fire()  # pin/unpin toggles need no delay
        else:
            self._timer = self.schedule(self.open_ms if want else self.close_ms, self._fire)

    def _fire(self):
        self._timer = None
        want = self._want()
        if want != self.expanded:
            self.expanded = want
            self.apply(want)
