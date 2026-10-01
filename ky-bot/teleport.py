"""One-TELE-per-turn routing between owned stations."""
from __future__ import annotations

from protocol import tele
from navigation import enemy_danger_cells
from army_v4_2 import neighbours, warrior_cost
from coordination import enemy_threats
from scouting import unresolved_buildings
import pathing

_last_teleport = None
TELE_REVERSE_COOLDOWN = 4


def _pos(u):
    return (u["x"], u["y"])


def _unit_counts_at_stations(view):
    stations = {
        (b["x"], b["y"])
        for b in view.buildings
        if b["owner"] == view.team and b["type"] == "STATION"
    }
    counts = {}
    for u in view.my_units():
        pos = _pos(u)
        if pos in stations and u["count"] > 0:
            counts[(pos, u["kind"])] = counts.get((pos, u["kind"]), 0) + u["count"]
    return stations, counts


def _building_weight(building, view, init):
    score = building.get("score", -1)
    if score < 0:
        score = 2.0 if 5 <= building["x"] <= 9 else 1.0
    bonus = 0.0
    if building["type"] == "DEPOT":
        bonus += 3.0
    elif building["type"] == "ENG":
        bonus += 2.0
    elif building["type"] == "HALL":
        bonus += 1.5
    elif building["type"] == "PLAZA":
        bonus += 2.0
    return score + bonus


def _targets(view, init, objectives):
    targets = set()
    for assigned in (objectives or {}).values():
        targets.update(t for t in assigned if t is not None)
    for b in view.buildings:
        if b["owner"] != view.team:
            targets.add((b["x"], b["y"]))
    return targets


def _goal_pull(station, targets, buildings):
    best = None
    for target in targets:
        d = pathing.distance(station, target)
        if d is None:
            continue
        b = buildings[target]
        score = _building_weight(b, None, None) / (d + 1)
        key = (score, -d, -target[1], -target[0])
        if best is None or key > best[0]:
            best = (key, target, d)
    return best


def _defense_pull(station, view, init, threats):
    buildings = {
        (b["x"], b["y"]): b
        for b in view.buildings
    }
    best = 0.0
    for pos, b in buildings.items():
        if b["owner"] != view.team:
            continue
        threat = threats.get(pos, 0)
        enemy_flag_near = any(
            u["team"] == view.opp and u["kind"] == "F"
            and max(abs(u["x"] - pos[0]), abs(u["y"] - pos[1])) <= 2
            for u in view.units
        )
        if not threat and not enemy_flag_near:
            continue
        d = pathing.distance(station, pos)
        if d is None:
            continue
        value = (5 + threat * 2 + (4 if enemy_flag_near else 0)) / (d + 1)
        best = max(best, value)
    return best


def _scout_pull(station, view, init):
    unresolved = unresolved_buildings(view, init)
    if not unresolved:
        return 0.0
    best = 0.0
    for b in unresolved:
        d = pathing.distance(station, (b["x"], b["y"]))
        if d is None:
            continue
        weight = 2.5 if 5 <= b["x"] <= 9 else 1.0
        best = max(best, weight / (d + 1))
    return best


def plan_teleport(view, init, objectives=None):
    global _last_teleport
    if _last_teleport is not None and _last_teleport[0] is not init:
        _last_teleport = None

    stations, counts = _unit_counts_at_stations(view)
    if len(stations) < 2:
        return None

    pathing.prepare(init)
    dangers = enemy_danger_cells(view, init)
    threats = enemy_threats(view, init)
    building_map = {(b["x"], b["y"]): b for b in view.buildings}
    targets = _targets(view, init, objectives)

    enemy_flags = {
        (u["x"], u["y"]): u["count"]
        for u in view.units
        if u["team"] == view.opp and u["kind"] == "F" and u["count"] > 0
    }

    candidates = []

    for source in sorted(stations, key=lambda p: (p[1], p[0])):
        for destination in sorted(stations, key=lambda p: (p[1], p[0])):
            if source == destination:
                continue

            for kind in ("W", "F"):
                available = counts.get((source, kind), 0)
                if not available:
                    continue
                count = min(5, available)

                if kind in ("F", "S") and destination in dangers:
                    continue

                # Warriors may intentionally teleport into a fight, but only
                # when the arriving stack can strictly win it.
                if kind == "W" and count <= threats.get(destination, 0):
                    continue

                defense = _defense_pull(destination, view, init, threats)
                goal = _goal_pull(destination, targets, building_map)
                offense = goal[0][0] if goal else 0.0

                nearby_enemy_flags = [
                    (pos, n) for pos, n in enemy_flags.items()
                    if max(abs(pos[0] - destination[0]), abs(pos[1] - destination[1])) <= 2
                ]
                nearby_enemy_w = [
                    u for u in view.units
                    if u["team"] == view.opp and u["kind"] == "W"
                    and u["count"] > 0
                    and max(abs(u["x"] - destination[0]), abs(u["y"] - destination[1])) <= 2
                ]

                # A flag must gain real travel distance toward a useful building.
                travel_gain = 0.0
                target_distance = None
                if goal:
                    target = goal[1]
                    from_d = pathing.distance(source, target)
                    to_d = pathing.distance(destination, target)
                    target_distance = to_d
                    if from_d is not None and to_d is not None:
                        travel_gain = from_d - to_d

                # Avoid immediate reverse shuttles unless the destination is an
                # active fight. The last TELE is purely strategic memory.
                reverse = (
                    _last_teleport is not None
                    and _last_teleport[1] == destination
                    and _last_teleport[2] == source
                    and _last_teleport[3] == kind
                    and view.turn - _last_teleport[4] <= TELE_REVERSE_COOLDOWN
                )
                urgent = bool(nearby_enemy_flags or nearby_enemy_w) or defense >= 8.0
                if reverse and not urgent:
                    continue

                score = 0.0
                if kind == "W":
                    # W TELE is reserved for concrete combat/defense. A generic
                    # target being closer is not enough to spend the one TELE.
                    if not (nearby_enemy_flags or nearby_enemy_w or defense >= 8.0):
                        continue
                    score = defense * 3.0 + len(nearby_enemy_flags) * 7.0 + len(nearby_enemy_w) * 3.0
                else:  # F
                    # F TELE is for a real route cut. Require a target close to
                    # the destination or a substantial travel-distance gain.
                    if not (
                        (target_distance is not None and target_distance <= 3)
                        or travel_gain >= 4
                        or nearby_enemy_flags
                    ):
                        continue
                    score = max(0.0, travel_gain - 2) * 2.0 + offense * 2.0
                    if target_distance is not None and target_distance <= 3:
                        score += 6.0
                    if nearby_enemy_flags:
                        score += 5.0

                # Require a meaningful strategic reason to spend the turn's only TELE.
                if score < 8.0:
                    continue

                candidates.append((
                    -score,
                    kind != "W",  # defense W first on an equal score
                    -count,
                    source[1], source[0], destination[1], destination[0], kind,
                    source, destination, count,
                ))

    if not candidates:
        return None

    best = min(candidates)
    _, _, _, _, _, _, _, kind, source, destination, count = best
    _last_teleport = (init, source, destination, kind, view.turn)
    return tele(
        source[0], source[1], kind, count,
        destination[0], destination[1],
    )
