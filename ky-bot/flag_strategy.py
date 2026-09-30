#Flag allocation, target ranking, and persistent assignments

from collections import defaultdict, deque

from protocol import DIRS, move
import pathing
from navigation import neighbors, enemy_danger_cells
from army_v4_2 import protected_danger_cells, produced_flags
from coordination import enemy_threats, planned_flag_step


_context = None
_last_turn = -1
_expected = {}
_depots_seen = set()

STALL_LIMIT = 6
COOLDOWN = 5


def _routes(init, start, danger):
    #Calculate safe routes and first steps from one source cell
    routes = {start: (0, None)}
    queue = deque([start])

    while queue:
        pos = queue.popleft()
        distance, first = routes[pos]

        for direction, nxt in neighbors(init, pos):
            if nxt in routes or nxt in danger:
                continue

            routes[nxt] = (
                distance + 1,
                direction if first is None else first,
            )
            queue.append(nxt)

    return routes


def _value(building, view, owned, by_position):
    #Estimate target value using points and economic benefits
    score = building.get("score", -1)

    if score < 0:
        mirror = by_position.get(
            (
                view.init.width - 1 - building["x"],
                view.init.height - 1 - building["y"],
            )
        )

        if mirror and mirror.get("score", -1) >= 0:
            score = mirror["score"]
        else:
            score = 3 if 5 <= building["x"] <= 9 else 1.5

    time_left = max(
        0.0,
        min(1.0, (160 - view.turn) / 100),
    )

    kind = building["type"]
    bonus = 0.0

    if kind == "ENG" and not owned["ENG"]:
        bonus = 7.0
    elif kind == "HALL":
        bonus = 5.0
    elif kind == "LIBRARY" and not owned["LIBRARY"]:
        bonus = 2.0
    elif kind == "DEPOT" and building["id"] not in _depots_seen:
        bonus = 4.0

    # Hospital production and teleportation are not used by our army yet.
    # Do not award extra value for abilities the bot cannot currently use.
    return score + bonus * time_left


def move_flags(
    view,
    init,
    flags,
    live,
    enemy_w,
    my_w,
    defenders,
    objectives=None,
):
    #Move flags using planned protection and optional shared objectives
    global _context, _last_turn, _expected, _depots_seen

    # Reset memory when a new game starts.
    if _context is not init or view.turn <= _last_turn:
        _context = init
        _expected = {}
        _depots_seen = set()

    _last_turn = view.turn
    pathing.prepare(init)

    buildings = {
        (b["x"], b["y"]): b
        for b in view.buildings
    }

    owned = defaultdict(int)

    for building in view.buildings:
        if building["owner"] == view.team:
            owned[building["type"]] += 1

            if building["type"] == "DEPOT":
                _depots_seen.add(building["id"])

    danger = enemy_danger_cells(view, init)
    immediate = protected_danger_cells(view, init, defenders)

    # A surviving enemy flag contests capture even when warriors cancel equally.
    threats = enemy_threats(view, init)

    for unit in view.units:
        if (
            unit["team"] == view.opp
            and unit["kind"] == "F"
            and unit["count"] > 0
        ):
            cell = (unit["x"], unit["y"])

            if defenders.get(cell, 0) <= threats[cell]:
                immediate.add(cell)

    # Include flags bought this turn; spawning resolves before movement.
    combined = {}

    for unit in list(flags) + produced_flags(view, init):
        pos = (unit["x"], unit["y"])

        if pos not in combined:
            combined[pos] = dict(unit)
        else:
            combined[pos]["count"] += unit["count"]

    flags = list(combined.values())

    # Restore one assignment record per surviving flag.
    records = []

    for unit in sorted(flags, key=lambda u: (u["y"], u["x"])):
        pos = (unit["x"], unit["y"])
        previous = _expected.get(pos, [])

        for index in range(unit["count"]):
            if index < len(previous):
                record = dict(previous[index])
            else:
                record = {
                    "goal": None,
                    "best": 10000,
                    "stall": 0,
                    "blocked": {},
                }

            record["blocked"] = {
                target: until
                for target, until in record["blocked"].items()
                if until > view.turn
            }

            records.append((pos, record))

    # Keep exactly one flag at each safe capture already in progress.
    claimed = set()
    stay = set()

    for index, (pos, record) in enumerate(records):
        if (
            pos in live
            and pos not in immediate
            and pos not in claimed
        ):
            stay.add(index)
            claimed.add(pos)
            record.update(goal=pos, best=0, stall=0)

    next_expected = defaultdict(list)
    orders = defaultdict(int)
    route_cache = {}
    assignment_index = defaultdict(int)

    for index, (pos, record) in enumerate(records):
        assignment = None

        if objectives is not None:
            candidates = objectives.get(pos, [])
            offset = assignment_index[pos]

            assignment = (
                candidates[offset]
                if offset < len(candidates)
                else None
            )

            assignment_index[pos] += 1

        step = None

        if index not in stay:
            if pos not in route_cache:
                local = {pos} | {
                    destination
                    for _, destination in neighbors(init, pos)
                }

                blocked = (
                    (danger - local)
                    | (immediate & local)
                )

                route_cache[pos] = _routes(init, pos, blocked)

            routes = route_cache[pos]
            goal = record["goal"]

            # Keep an assignment while it remains useful.
            if goal in live:
                distance = pathing.distance(pos, goal)

                if distance is not None and distance < record["best"]:
                    record.update(best=distance, stall=0)
                else:
                    record["stall"] += 1

                if record["stall"] >= STALL_LIMIT:
                    record["blocked"][goal] = view.turn + COOLDOWN
                    goal = None
            else:
                goal = None

            valid = {
                target
                for target in live
                if target not in claimed
                and target in routes
                and target != pos
                and target not in record["blocked"]
            }

            if goal not in valid:
                goal = None

            # Select a new target when the previous one is unsuitable.
            if goal is None and valid:

                def ranking(target):
                    building = buildings[target]
                    distance = routes[target][0]

                    capture_delay = (
                        2 if building["owner"] == view.opp else 1
                    )

                    utility = _value(
                        building,
                        view,
                        owned,
                        buildings,
                    ) / (distance + capture_delay + 1)

                    return (
                        -utility,
                        distance,
                        target[1],
                        target[0],
                    )

                goal = min(valid, key=ranking)

                record.update(
                    best=pathing.distance(pos, goal),
                    stall=0,
                )

            # Shared objectives may lie beyond today's danger zone.
            # Check the next step with the planned escort and replan next turn.
            if (
                assignment in live
                and assignment not in claimed
                and assignment not in record["blocked"]
            ):
                goal = assignment

                if record["goal"] != goal:
                    record.update(
                        best=pathing.distance(pos, goal),
                        stall=0,
                    )

            record["goal"] = goal

            if goal is not None:
                claimed.add(goal)

                if goal in routes:
                    step = routes[goal][1]
                else:
                    distance = pathing.distance(pos, goal)

                    options = [
                        (direction, destination)
                        for direction, destination in neighbors(init, pos)
                        if destination not in immediate
                        and pathing.distance(destination, goal) is not None
                        and pathing.distance(destination, goal) < distance
                    ] if distance is not None else []

                    if options:
                        step = options[0][0]

                # Follow the step for which warrior support was planned.
                shared_step = planned_flag_step(pos, goal)

                if shared_step is not None and goal == assignment:
                    dx, dy = DIRS[shared_step]
                    shared_cell = (pos[0] + dx, pos[1] + dy)

                    step = (
                        shared_step
                        if shared_cell not in immediate
                        else None
                    )

                # Waiting for an escort must not trap a flag in immediate danger.
                if step is None and pos in immediate:
                    escapes = [
                        (direction, destination)
                        for direction, destination in neighbors(init, pos)
                        if destination not in immediate
                    ]

                    if escapes:
                        step = min(
                            escapes,
                            key=lambda item: (
                                pathing.distance(item[1], goal)
                                if pathing.distance(item[1], goal) is not None
                                else 10000
                            ),
                        )[0]

            elif pos in immediate:
                # No suitable target: escape the immediate threat.
                escapes = [
                    (direction, destination)
                    for direction, destination in neighbors(init, pos)
                    if destination not in immediate
                ]

                if escapes:
                    step = max(
                        escapes,
                        key=lambda item: sum(
                            destination not in immediate
                            for _, destination in neighbors(init, item[1])
                        ),
                    )[0]

        destination = pos

        if isinstance(step, str):
            dx, dy = DIRS[step]
            destination = (pos[0] + dx, pos[1] + dy)
            orders[(pos, step)] += 1

        next_expected[destination].append(record)

    _expected = dict(next_expected)

    # Combine identical moves without sending more flags than available.
    return [
        move(pos[0], pos[1], "F", count, step)
        for (pos, step), count in sorted(orders.items())
    ]


def plan_objectives(view, init, flags, targets):
    #Share one persistent capture objective per flag with the warrior planner.

    pathing.prepare(init)

    buildings = {
        (b["x"], b["y"]): b
        for b in view.buildings
    }

    owned = defaultdict(int)

    for building in view.buildings:
        if building["owner"] == view.team:
            owned[building["type"]] += 1

    claimed = set()
    result = defaultdict(list)

    current_memory = (
        _expected
        if _context is init and view.turn > _last_turn
        else {}
    )

    # Reserve flags for captures already in progress before assigning extras.
    reserved = {
        (u["x"], u["y"])
        for u in flags
        if (u["x"], u["y"]) in targets
    }

    claimed.update(reserved)

    for unit in sorted(flags, key=lambda u: (u["y"], u["x"])):
        pos = (unit["x"], unit["y"])
        previous = current_memory.get(pos, [])

        for index in range(unit["count"]):
            if pos in reserved and index == 0:
                result[pos].append(pos)
                continue

            record = (
                previous[index]
                if index < len(previous)
                else {}
            )

            blocked = {
                position
                for position, until in record.get("blocked", {}).items()
                if until > view.turn
            }

            if record.get("stall", 0) >= STALL_LIMIT - 1:
                blocked.add(record.get("goal"))

            valid = {
                position
                for position in targets - claimed
                if position not in blocked
                and pathing.distance(pos, position) is not None
            }

            goal = record.get("goal")

            if goal not in valid:

                def rank(target):
                    building = buildings[target]
                    distance = pathing.distance(pos, target)
                    delay = 2 if building["owner"] == view.opp else 1

                    value = _value(
                        building,
                        view,
                        owned,
                        buildings,
                    )

                    return (
                        -value / (distance + delay + 1),
                        distance,
                        target[1],
                        target[0],
                    )

                goal = min(valid, key=rank) if valid else None

            if goal is not None:
                claimed.add(goal)

            result[pos].append(goal)

    return dict(result)