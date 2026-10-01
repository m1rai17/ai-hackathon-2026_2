#Allocate warriors to immediate defense, flag escorts and capture objectives

from collections import defaultdict

from protocol import DIRS, BALANCE, move
from army_v4_2 import neighbours, warrior_cost, planned_warriors
from adaptive import analyze as analyze_adaptive
import pathing

GUARD_RANGE = 4   # v4.2: how many steps away an enemy flag counts as a threat
RETENTION_TURNS = 4

# Cells that were newly captured by us in the previous few turns. Keeping a
# small resident guard here prevents the flag from winning a building and then
# immediately abandoning it to chase the next objective.
_recent_captures = {}
_known_owned = None
_known_init = None
_known_team = None


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
    global _flag_steps, _recent_captures, _known_owned, _known_init, _known_team
    _flag_steps = {}
    #Return legal split orders, reserving each warrior at most once.

    pathing.prepare(init)

    # Detect fresh captures before allocating this turn's warriors. A capture
    # is strategically different from an old owned building because the new
    # owner has not had time to establish a defensive buffer yet.
    owned_now = {
        (b["x"], b["y"])
        for b in view.buildings
        if b["owner"] == view.team
    }
    if _known_init is not init or _known_team != view.team:
        _recent_captures = {}
        _known_owned = set(owned_now)
        _known_init = init
        _known_team = view.team
    else:
        previous = _known_owned or set()
        for cell in owned_now - previous:
            _recent_captures[cell] = view.turn + RETENTION_TURNS
        _recent_captures = {
            cell: until
            for cell, until in _recent_captures.items()
            if until >= view.turn and cell in owned_now
        }
        _known_owned = set(owned_now)

    available = {
        position: count
        for position, count in planned_warriors(
            view, init, production, []
        ).items()
        if count
    }

    threats = enemy_threats(view, init)
    adaptive = analyze_adaptive(view, init)

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
        # v4.2: guard our economy buildings (ENG first, then HALL) BEFORE enemy
    # flags arrive. Only enemy flags can take a building, so a building is in
    # danger when an enemy flag is within GUARD_RANGE steps. We send the nearest
    # free warriors so that, on that cell, we outnumber the enemy warriors that
    # could come with the flag (more warriors = their flag dies, building stays ours).
    enemy_w_stacks = {
        (u["x"], u["y"]): u["count"]
        for u in view.units
        if u["team"] == view.opp and u["kind"] == "W"
    }
    economy = sorted(
        (
            cell for cell, b in buildings.items()
            if b["owner"] == view.team and b["type"] in ("ENG", "HALL")
        ),
        key=lambda c: (buildings[c]["type"] != "ENG", c[1], c[0]),
    )
    for cell in economy:
        flag_gap = min(
            (pathing.distance(f, cell) for f in enemy_f
             if pathing.distance(f, cell) is not None),
            default=None,
        )
        if flag_gap is None or flag_gap > GUARD_RANGE:
            continue
        escort = sum(
            count for pos, count in enemy_w_stacks.items()
            if (pathing.distance(pos, cell) or 99) <= GUARD_RANGE
        )
        missing = escort + 1 - committed[cell]
        # warriors already standing on the building stay there first
        if missing > 0 and available.get(cell, 0):
            take = min(missing, available[cell])
            send(cell, cell, take)
            missing -= take
        if missing <= 0:
            continue
        helpers = sorted(
            (
                (pathing.distance(src, cell), src)
                for src, count in available.items()
                if count and src != cell
                and pathing.distance(src, cell) is not None
                and pathing.distance(src, cell) <= GUARD_RANGE + 2
            )
        )
        for _, src in helpers:
            if missing <= 0:
                break
            step = pathing.step_toward(src, cell)
            if not step:
                continue
            dx, dy = DIRS[step]
            nxt = (src[0] + dx, src[1] + dy)
            take = min(missing, available[src])
            send(src, nxt, take)
            missing -= take
    # RETENTION: newly captured buildings get a short-lived resident guard.
    # This is deliberately below direct threat jobs, so a real attack can still
    # pull the guard outward when necessary.
    for cell, until in sorted(_recent_captures.items()):
        if until < view.turn or cell not in buildings:
            continue
        building = buildings[cell]
        if building["owner"] != view.team:
            continue
        desired = max(1, threats[cell])
        missing = desired - committed[cell]
        if missing > 0 and available.get(cell, 0):
            take = min(missing, available[cell])
            send(cell, cell, take)
            missing -= take
        if missing > 0:
            helpers = sorted(
                (
                    (pathing.distance(src, cell), src)
                    for src, count in available.items()
                    if count and src != cell
                    and pathing.distance(src, cell) is not None
                    and pathing.distance(src, cell) <= 2
                )
            )
            for _, src in helpers:
                if missing <= 0:
                    break
                step = pathing.step_toward(src, cell)
                if not step:
                    continue
                dx, dy = DIRS[step]
                nxt = (src[0] + dx, src[1] + dy)
                take = min(missing, available[src])
                send(src, nxt, take)
                missing -= take

    # LAST-BUILDING EMERGENCY: when only one or two buildings remain, losing
    # another one is much more damaging than a normal objective delay. Protect
    # every remaining building, with extra weight on cells facing enemy flags.
    remaining = [
        cell for cell, b in buildings.items()
        if b["owner"] == view.team
    ]
    if len(remaining) <= 2:
        for cell in sorted(remaining):
            nearby_flag = min(
                (pathing.distance(f, cell) for f in enemy_f
                 if pathing.distance(f, cell) is not None),
                default=None,
            )
            if nearby_flag is None or nearby_flag > GUARD_RANGE + 1:
                continue
            need = max(1, threats[cell]) + 1
            missing = max(0, need - committed[cell])
            if missing <= 0:
                continue
            helpers = sorted(
                (
                    (pathing.distance(src, cell), src)
                    for src, count in available.items()
                    if count and pathing.distance(src, cell) is not None
                    and pathing.distance(src, cell) <= GUARD_RANGE + 2
                )
            )
            for _, src in helpers:
                if missing <= 0:
                    break
                step = pathing.step_toward(src, cell)
                if not step:
                    continue
                dx, dy = DIRS[step]
                nxt = (src[0] + dx, src[1] + dy)
                take = min(missing, available[src])
                send(src, nxt, take)
                missing -= take

    # ADAPTIVE PRESSURE MODE: when the opponent has a materially larger army
    # close to our territory, stop scattering free warriors across many capture
    # objectives. Rally them toward one concrete defensive anchor so the next
    # fight is decided by a combined stack rather than repeated small losses.
    if adaptive["mode"] == "emergency" and (adaptive["recent_losses"] >= 2 or adaptive["threatened_buildings"] >= 2):
        defensive_candidates = []
        for cell, building in buildings.items():
            if building["owner"] != view.team:
                continue
            threat = threats[cell]
            enemy_flag_near = any(
                pathing.distance(f, cell) is not None
                and pathing.distance(f, cell) <= GUARD_RANGE
                for f in enemy_f
            )
            if not threat and not enemy_flag_near:
                continue
            value = max(1, building.get("score", 1))
            if building["type"] == "ENG":
                value += 5
            elif building["type"] == "HALL":
                value += 4
            elif building["type"] == "PLAZA":
                value += 3
            score = threat * 3 + value + (8 if enemy_flag_near else 0)
            defensive_candidates.append((score, cell))

        if not defensive_candidates and adaptive["near_enemy_w_cells"]:
            # The enemy army is close, but no building is under a direct Flag
            # threat yet. Rally on our most valuable owned anchor instead of
            # walking a newly grouped stack straight into the enemy formation.
            safe_anchors = []
            for cell, building in buildings.items():
                if building["owner"] != view.team:
                    continue
                value = max(1, building.get("score", 1))
                if building["type"] == "ENG":
                    value += 5
                elif building["type"] == "HALL":
                    value += 4
                elif building["type"] == "PLAZA":
                    value += 3
                enemy_distance = min(
                    (pathing.distance(wcell, cell) for wcell in adaptive["near_enemy_w_cells"]
                     if pathing.distance(wcell, cell) is not None),
                    default=99,
                )
                safe_anchors.append((value + max(0, 8 - enemy_distance), cell))
            defensive_candidates.extend(safe_anchors)

        if defensive_candidates:
            anchor = max(defensive_candidates, key=lambda item: (item[0], -item[1][1], -item[1][0]))[1]
            for source, count in sorted(list(available.items())):
                if not count:
                    continue
                if source == anchor:
                    continue
                distance = pathing.distance(source, anchor)
                if distance is None:
                    continue
                step = pathing.step_toward(source, anchor)
                if not step:
                    continue
                dx, dy = DIRS[step]
                destination = (source[0] + dx, source[1] + dy)
                # In emergency mode, keep the whole available stack moving
                # toward the anchor. In pressure mode, keep at least one unit
                # free if a direct building guard was already scheduled.
                take = count if adaptive["mode"] == "emergency" else max(0, count - 1)
                if take:
                    send(source, destination, take)

    # PREDICTIVE PRESSURE RALLY: if the opponent can create a materially larger
    # Warrior force next turn, do not wait for an actual capture to be threatened.
    # Rally a bounded portion of otherwise-free Warriors toward one safe owned
    # anchor. This is deliberately weaker than emergency mode so normal expansion
    # still remains the default.
    if adaptive["mode"] == "pressure" and adaptive["projected_gap"] >= 5:
        rally_candidates = []
        for cell, building in buildings.items():
            if building["owner"] != view.team:
                continue
            value = max(1, building.get("score", 1))
            if building["type"] == "ENG":
                value += 5
            elif building["type"] == "HALL":
                value += 4
            elif building["type"] == "PLAZA":
                value += 3
            enemy_distance = min(
                (pathing.distance(w, cell) for w in adaptive["near_enemy_w_cells"]
                 if pathing.distance(w, cell) is not None),
                default=99,
            )
            flag_distance = min(
                (pathing.distance(f, cell) for f in enemy_f
                 if pathing.distance(f, cell) is not None),
                default=99,
            )
            urgency = 0
            if enemy_distance <= GUARD_RANGE + 1:
                urgency += 6
            if flag_distance <= GUARD_RANGE:
                urgency += 8
            if building["type"] in ("ENG", "HALL"):
                urgency += 3
            rally_candidates.append((value + urgency - min(enemy_distance, 8), cell))

        if rally_candidates:
            anchor = max(rally_candidates, key=lambda item: (item[0], -item[1][1], -item[1][0]))[1]
            for source, count in sorted(list(available.items())):
                if not count or source == anchor:
                    continue
                distance = pathing.distance(source, anchor)
                if distance is None or distance > GUARD_RANGE + 2:
                    continue
                step = pathing.step_toward(source, anchor)
                if not step:
                    continue
                dx, dy = DIRS[step]
                destination = (source[0] + dx, source[1] + dy)
                # Keep one Warrior free per source in pressure mode for direct
                # reactions; the rest become part of the rally.
                take = max(0, count - 1)
                if take:
                    send(source, destination, take)

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