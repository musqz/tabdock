"""Panel placement math (pure). Rects are (x, y, w, h) in X screen coordinates."""

TRIGGER_PX = 3  # width of the collapsed hover strip


def outer_monitor(rects, side, primary=None):
    """Index of the monitor that owns the screen's outer edge on `side` ("left" or "right").

    Only an outer edge can reserve space (see strut()), and it is where the pointer stops, so
    that is where a panel belongs whatever the monitor layout. When several monitors share
    that edge (stacked vertically) the primary one wins, then the tallest, then the first.
    """
    if side == "left":
        edge = min(x for x, _, _, _ in rects)
        candidates = [i for i, (x, _, _, _) in enumerate(rects) if x == edge]
    else:
        edge = max(x + w for x, _, w, _ in rects)
        candidates = [i for i, (x, _, w, _) in enumerate(rects) if x + w == edge]
    if primary in candidates:
        return primary
    return max(candidates, key=lambda i: (rects[i][3], -i))


def dock_rect(mon, side, width, expanded):
    mx, my, mw, mh = mon
    w = width if expanded else TRIGGER_PX
    x = mx if side == "left" else mx + mw - w
    return (x, my, w, mh)


def strut(mon, screen_w, side, width):
    """_NET_WM_STRUT_PARTIAL values reserving `width` px at this monitor's edge, or None.

    A strut can only reserve space at an edge of the whole X screen. On an inner
    monitor edge (a neighbouring monitor lies beyond it) it would squeeze that
    neighbour, so there is none and the caller keeps the panel as an open overlay.
    """
    mx, my, mw, mh = mon
    y0, y1 = my, my + mh - 1
    if side == "left":
        if mx != 0:
            return None
        return [width, 0, 0, 0, y0, y1, 0, 0, 0, 0, 0, 0]
    if mx + mw != screen_w:
        return None
    return [0, width, 0, 0, 0, 0, y0, y1, 0, 0, 0, 0]
