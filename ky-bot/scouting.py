"""Score discovery and movement for the fast, non-combat scout unit (S)."""
from __future__ import annotations

from protocol import DIRS, move, move2
from navigation import enemy_danger_cells
from army_v4_2 import neighbours
import pathing

MAX_SCOUTS = 2
SCOUT_PHASE_END = 90


def _pos(u):
    return (u["x"], u["y"])


def _mirror(pos, init):
    return (init.width - 1 - pos[0], init.height - 1 - pos[1])


def _unresolved(building, by_pos, init):
    """True only when neither the building nor its symmetric partner is known."""
    if building.get("score", -1) >= 0:
        return False
    mirror = by_pos.get(_mirror((building["x"], building["y"]), init))
    return not mirror or mirror.get("score", -1) < 0


def unresolved_buildings(view, init):
    by_pos = {(b["x"], b["y"]): b for b in view.buildings}
    return [
        b for b in view.buildings
        if _unresolved(b, by_pos, init)
    ]


def _info_weight(building, init):
    x, y = building["x"], building["y"]
    weight = 1.0
    if 5 <= x <= 9:
        weight += 1.5
    if building["type"] in ("DEPOT", "ENG", "HALL", "LIBRARY"):
        weight += 0.5
    return weight


def _info_cells(view, init):
    """Return information value for passable cells based on Chebyshev-2 reveal."""
    targets = unresolved_buildings(view, init)
    values = {}
    for y in range(init.height):
        for x in range(init.width):
            if not init.passable(x, y):
                continue
            value = 0.0
            covered = []
            for b in targets:
                if max(abs(b["x"] - x), abs(b["y"] - y)) <= 2:
                    w = _info_weight(b, init)
                    value += w
                    covered.append((b["x"], b["y"]))
            values[(x, y)] = (value, tuple(covered))
    return values


def choose_scout_spawn(view, init):
    """Pick a safe base/hospital spawn nearest to unresolved score information."""
    targets = unresolved_buildings(view, init)
    if not targets:
        return None

    base = tuple(init.bases[view.team])
    hospitals = [
        (b["x"], b["y"])
        for b in view.buildings
        if b["owner"] == view.team and b["type"] == "HOSPITAL"
    ]
    spots = [None] + hospitals
    danger = enemy_danger_cells(view, init)

    def score(spot):
        start = base if spot is None else spot
        if spot is not None and spot in danger:
            return (10_000, 10_000)
        distances = [
            (pathing.distance(start, (b["x"], b["y"])), _info_weight(b, init))
            for b in targets
        ]
        distances = [x for x in distances if x[0] is not None]
        best = min((d - w * 0.75 for d, w in distances), default=10_000)
        return (best, 0 if spot is None else 1)

    return min(spots, key=score)


def _two_step_options(pos, init, danger):
    x, y = pos
    out = []
    for d1, (dx1, dy1) in DIRS.items():
        mid = (x + dx1, y + dy1)
        if not init.passable(*mid):
            continue
        for d2, (dx2, dy2) in DIRS.items():
            dst = (mid[0] + dx2, mid[1] + dy2)
            if not init.passable(*dst) or dst in danger or dst == pos:
                continue
            out.append((d1, d2, dst))
    return out


def _one_step_options(pos, init, danger):
    x, y = pos
    out = []
    for d, (dx, dy) in DIRS.items():
        dst = (x + dx, y + dy)
        if init.passable(*dst) and dst not in danger:
            out.append((d, dst))
    return out


def move_scouts(view, init, scouts):
    """Move scouts toward the best unresolved score cluster, using MOVE2 whenever possible."""
    if not scouts or view.turn > SCOUT_PHASE_END:
        return []

    pathing.prepare(init)
    info = _info_cells(view, init)
    useful = [
        cell for cell, (value, covered) in info.items()
        if value > 0 and covered
    ]
    if not useful:
        return []

    danger = enemy_danger_cells(view, init)
    commands = []
    used_coverage = set()

    for unit in sorted(
        scouts,
        key=lambda u: (-u["count"], u["y"], u["x"]),
    ):
        pos = _pos(unit)

        # Choose an information destination by value per walking turn. Penalize
        # cells already selected by another scout this turn so two scouts spread out.
        goals = []
        for cell in useful:
            distance = pathing.distance(pos, cell)
            if distance is None:
                continue
            value, covered = info[cell]
            fresh = sum(1 for b in covered if b not in used_coverage)
            goals.append((
                -(fresh * 2.0 + value / (distance + 1)),
                distance,
                cell[1],
                cell[0],
                cell,
            ))

        if not goals:
            continue

        goal = min(goals)[-1]

        # Take two safe shortest-path steps when possible. We do not care about
        # enemy occupation of the intermediate cell because combat happens only
        # at the final cell.
        first, second, current = None, None, pos
        for _ in range(2):
            step = pathing.step_toward(current, goal)
            if not step:
                break
            dx, dy = DIRS[step]
            nxt = (current[0] + dx, current[1] + dy)
            if not init.passable(*nxt):
                break
            current = nxt
            if first is None:
                first = step
            else:
                second = step
                break

        # If the two-step endpoint is dangerous, fall back to a safe one-step
        # move, then reconsider the route next turn.
        if first is not None and second is not None and current not in danger:
            commands.append(
                move2(
                    pos[0], pos[1], unit["count"], first, second
                )
            )
            used_coverage.update(
                info.get(current, (0.0, ()))[1]
            )
            continue

        safe_one = []
        for direction, dst in _one_step_options(pos, init, danger):
            distance = pathing.distance(dst, goal)
            if distance is None:
                continue
            safe_one.append((distance, dst[1], dst[0], direction, dst))

        if safe_one:
            _, _, _, direction, dst = min(safe_one)
            commands.append(
                move(
                    pos[0], pos[1], "S", unit["count"], direction
                )
            )
            used_coverage.update(
                info.get(dst, (0.0, ()))[1]
            )

    return commands
