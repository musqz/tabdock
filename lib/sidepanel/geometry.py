"""Panel placement math (pure). Rects are (x, y, w, h) in X screen coordinates."""

TRIGGER_PX = 3  # width of the collapsed hover strip


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
