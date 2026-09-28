"""Pathfinding for our bot (owner: pathfinding).

Public functions:
    prepare(init)
    distance(cell, target)
    step_toward(cell, target)
    nearest(cell, targets)   -> (first_step, target, distance)
    bfs_map(start, init)
"""
from collections import deque
from protocol import DIRS

_ORDER = ("U", "D", "L", "R")

_maps = {}
_init = None


def bfs_map(start, init):
    dist = {start: 0}
    queue = deque([start])
    while queue:
        x, y = queue.popleft()
        for d in _ORDER:
            dx, dy = DIRS[d]
            nxt = (x + dx, y + dy)
            if nxt not in dist and init.passable(*nxt):
                dist[nxt] = dist[(x, y)] + 1
                queue.append(nxt)
    return dist


def prepare(init):
    global _init
    if _init is init:
        return
    _init = init
    _maps.clear()
    for b in init.buildings:
        pos = (b["x"], b["y"])
        _maps[pos] = bfs_map(pos, init)


def _map_for(target):
    m = _maps.get(target)
    if m is None:
        m = bfs_map(target, _init)
        _maps[target] = m
    return m


def distance(cell, target):
    return _map_for(target).get(cell)


def step_toward(cell, target):
    m = _map_for(target)
    here = m.get(cell)
    if here is None or here == 0:
        return None
    for d in _ORDER:
        dx, dy = DIRS[d]
        if m.get((cell[0] + dx, cell[1] + dy)) == here - 1:
            return d
    return None


def nearest(cell, targets):
    best = None
    for t in targets:
        d = distance(cell, t)
        if d is None:
            continue
        key = (d, t[1], t[0])
        if best is None or key < best[0]:
            best = (key, t, d)
    if best is None:
        return None, None, None
    _, t, d = best
    return step_toward(cell, t), t, d
