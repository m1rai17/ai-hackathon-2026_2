"""Pathfinding for our bot (owner: pathfinding).

Idea: the map (walls + buildings) never changes during a game, and units never
block each other's movement. So we compute, ONCE, a "distance map" from every
building: a dict {cell: number of steps from that cell to the building}.
After that, any distance question is an instant dictionary lookup.

Public functions (this is the agreed interface - don't rename without telling the team):

    prepare(init)                       call once at the top of decide()
    distance(cell, target)       -> int steps, or None if unreachable
    step_toward(cell, target)    -> "U"/"D"/"L"/"R", or None if already there / unreachable
    nearest(cell, targets)       -> (first_step, target, distance), or (None, None, None)
    bfs_map(start, init)    -> {cell: steps} from any start cell (low-level helper)

`cell` and `target` are (x, y) tuples. `target` can be ANY cell (a building, an
enemy unit, a base) - non-building targets get their map computed the first
time they're asked for and are then remembered too.
"""
from collections import deque
from protocol import DIRS

# Direction order used to break ties when two moves are equally good.
# Fixed order = the bot behaves the same way every run (easier to debug).
_ORDER = ("U", "D", "L", "R")

_maps = {}       # target (x, y) -> {cell (x, y): steps from cell to target}
_init = None     # the game's Init object, remembered by prepare()


def bfs_map(start, init):
    """BFS 'water ripple' from `start`: how many steps every reachable cell is away.

    Moves are 4-directional and walls ('#') can't be entered. Because every move
    is reversible, 'steps from start to cell' == 'steps from cell to start'.
    """
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
    """Build the 17 building distance maps. Safe to call every turn: only the
    first call does work (a few milliseconds, well inside turn 1's 3 seconds)."""
    global _init
    if _init is init:
        return
    _init = init
    _maps.clear()
    for b in init.buildings:
        pos = (b["x"], b["y"])
        _maps[pos] = bfs_map(pos, init)


def _map_for(target):
    """Distance map for `target`, computing and remembering it if it's new."""
    m = _maps.get(target)
    if m is None:
        m = bfs_map(target, _init)
        _maps[target] = m
    return m


def distance(cell, target):
    """Steps from `cell` to `target`, or None if it can't be reached."""
    return _map_for(target).get(cell)


def step_toward(cell, target):
    """First move from `cell` along a shortest path to `target`.

    Looks at the 4 neighbours and picks the one that is 1 step closer.
    Returns None if we're already on the target or it's unreachable.
    """
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
    """Closest of `targets` from `cell`: returns (first_step, target, distance).

    Ties are broken by position (smallest (y, x)) so results are repeatable.
    If `cell` is itself a target, returns (None, cell, 0).
    Returns (None, None, None) if no target is reachable.
    """
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
