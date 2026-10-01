#Allocate warriors to immediate defense, flag escorts and capture objectives

from collections import defaultdict

from protocol import DIRS, BALANCE, move
from army_v4_2 import neighbours, warrior_cost, planned_warriors
import pathing


def enemy_threats(view, init):
    #Upper bound on enemy warriors reaching each cell this turn.

    threats = defaultdict(int)

    stacks = {
        (u["x"], u["y"]): u["count"]
        for u in view.units
        if u["team"] == view.opp and u["kind"] == "W"
    }

    for pos, count in stacks.items():
        for cell in neighbours(pos, init):
            threats[cell] += count

    spawns = {tuple(init.bases[view.opp])}
    spawns.update(
        (b["x"], b["y"])
        for b in view.buildings
        if b["owner"] == view.opp and b["type"] == "HOSPITAL"
    )

    capacity = view.opp_resource // warrior_cost(view, view.opp)

    for cell in {
        position
        for source in spawns
        for position in neighbours(source, init)
    }:
        threats[cell] += capacity

    stations = {
        (b["x"], b["y"])
        for b in view.buildings
        if b["owner"] == view.opp and b["type"] == "STATION"
    }

    if len(stations) >= BALANCE["tele"]["min_stations"]:
        for target in stations:
            threats[target] += max(
                (
                    min(
                        BALANCE["tele"]["max_units"],
                        stacks.get(source, 0),
                    )
                    for source in stations
                    if source not in neighbours(target, init)
                ),
                default=0,
            )

    return threats


_flag_steps = {}


def planned_flag_step(source, goal):
    return _flag_steps.get((source, goal))


def coordinate_warriors(view, init, production, objectives):
    global _flag_steps
    _flag_steps = {}
    #Return legal split orders, reserving each warrior at most once.

    pathing.prepare(init)

    available = {
        position: count
        for position, count in planned_warriors(
            view, init, production, []
        ).items()
        if count
    }

    threats = enemy_threats(view, init)

    enemy_f = {
        (u["x"], u["y"])
        for u in view.units
        if u["team"] == view.opp
        and u["kind"] == "F"
        and u["count"] > 0
    }

    buildings = {
        (b["x"], b["y"]): b
        for b in view.buildings
    }

    flags = {
        (u["x"], u["y"])
        for u in view.my_units("F")
    }

    orders = defaultdict(int)

    # Include warriors explicitly reserved to stay in their current cell.
    committed = defaultdict(int)

    def send(source, destination, count):
        available[source] -= count
        committed[destination] += count

        if source != destination:
            delta = (
                destination[0] - source[0],
                destination[1] - source[1],
            )

            direction = next(
                direction
                for direction, change in DIRS.items()
                if change == delta
            )

            orders[(source, direction)] += count

    jobs = {}

    def job(cell, need, priority):
        if need <= 0:
            return

        previous = jobs.get(cell, (0, 0))

        jobs[cell] = (
            max(need, previous[0]),
            max(priority, previous[1]),
        )

    # An enemy warrior alone cannot take an empty owned building.
    # Protect resident flags and stop incoming enemy flags.
    for cell, building in buildings.items():
        if building["owner"] != view.team:
            continue

        value = max(1, building.get("score", 1))

        if building["type"] in ("ENG", "HALL"):
            value += 4

        incoming_flags = any(
            enemy in neighbours(cell, init)
            for enemy in enemy_f
        )

        if cell in flags and threats[cell]:
            job(cell, threats[cell], 30 + value)

        elif incoming_flags:
            job(cell, threats[cell] + 1, 20 + value)

    goals = set()

    for source, assignments in sorted(objectives.items()):
        for goal in assignments:
            if goal is None:
                continue

            goals.add(goal)

            step = pathing.step_toward(source, goal)

            # Prefer a shortest-path step with a smaller support deficit.
            distance = pathing.distance(source, goal)
            options = [
                cell
                for cell in neighbours(source, init)
                if cell != source
                   and distance is not None
                   and pathing.distance(cell, goal) == distance - 1
            ]

            if options:
                def step_rank(cell):
                    support = sum(
                        count
                        for pos, count in available.items()
                        if pos in neighbours(cell, init)
                    )

                    required = threats[cell] + int(cell in enemy_f)

                    return (
                        max(0, required - support),
                        threats[cell],
                        cell[1],
                        cell[0],
                    )

                chosen = min(options, key=step_rank)

                step = next(
                    direction
                    for direction, (dx, dy) in DIRS.items()
                    if (source[0] + dx, source[1] + dy) == chosen
                )

            _flag_steps[(source, goal)] = step

            if step:
                dx, dy = DIRS[step]
                destination = (
                    source[0] + dx,
                    source[1] + dy,
                )
            else:
                destination = source

            # Equal warrior counts preserve our flag.
            # Removing an enemy flag requires strict superiority.
            need = (
                threats[destination]
                + int(destination in enemy_f)
            )

            job(
                destination,
                need,
                15 + (5 if destination == goal else 0),
            )

            if source in flags and threats[source]:
                job(source, threats[source], 10)

    # Commit only when enough warriors can arrive together this turn.
    ordered_jobs = sorted(
        jobs.items(),
        key=lambda item: (-item[1][1], item[0]),
    )

    for cell, (need, priority) in ordered_jobs:
        sources = [
            source
            for source, count in available.items()
            if count and source in neighbours(cell, init)
        ]

        missing = max(0, need - committed[cell])

        if sum(available[source] for source in sources) < missing:
            continue

        sources.sort(
            key=lambda source: (
                source != cell,
                -available[source],
                source[1],
                source[0],
            )
        )

        for source in sources:
            take = min(missing, available[source])

            if take:
                send(source, cell, take)
                missing -= take

            if not missing:
                break

    # Free warriors clear shared capture goals that face resistance.
    # Enemy flags remain fallback targets.
    contested = {
        goal
        for goal in goals
        if threats[goal] or goal in enemy_f
    }

    targets = contested | enemy_f

    if not targets:
        targets = goals or {
            position
            for position, building in buildings.items()
            if building["owner"] != view.team
        }

    proposals = defaultdict(list)

    for source, count in sorted(available.items()):
        if not count or not targets:
            continue

        def rank(goal):
            distance = pathing.distance(source, goal)

            return (
                10000 if distance is None else distance,
                goal not in contested,
                goal[1],
                goal[0],
            )

        goal = min(targets, key=rank)
        step = pathing.step_toward(source, goal)

        if step:
            dx, dy = DIRS[step]

            destination = (
                source[0] + dx,
                source[1] + dy,
            )

            proposals[destination].append((source, count))

    # Evaluate combined arrivals before issuing movement orders.
    # If outnumbered, wait for reinforcements instead of feeding a stack.
    for destination, group in sorted(proposals.items()):
        arriving = (
            committed[destination]
            + sum(count for _, count in group)
        )

        if arriving < threats[destination]:
            continue

        for source, count in group:
            send(source, destination, count)

    return [
        move(
            position[0],
            position[1],
            "W",
            count,
            direction,
        )
        for (position, direction), count in sorted(orders.items())
    ]