"""army_v4: army_v3 + flag safety + minimum-flag production.

NOTE: move_warriors() (combat-aware jobs) is kept for reference but NOT used:
it measured 25% vs army_v3. Simple chase-the-enemy-flag warriors are used instead.

Combat rules used (rulebook ch.6): combat only on shared cells after moves;
W cancel 1:1; surviving W remove all enemy F and S. Units move 1 cell/turn,
so the enemy W that can hit a cell next turn are those ON it or ADJACENT to it.
"""
import sys
from protocol import BALANCE, DIRS, spawn, move
from search import capture_reserve
import pathing
from navigation import enemy_danger_cells, safe_flag_step

MAX_FLAGS = 6
MIN_FLAGS = 3
DEBUG = False


def log(*a):
    if DEBUG:
        print(*a, file=sys.stderr)


# ---------------------------------------------------------------- combat core
def neighbours(cell, init):
    x, y = cell
    out = [cell]
    for dx, dy in DIRS.values():
        if init.passable(x + dx, y + dy):
            out.append((x + dx, y + dy))
    return out


def reach(stacks, cell, init):
    """How many units from `stacks` ({cell: count}) could be on `cell` next turn."""
    return sum(stacks.get(c, 0) for c in neighbours(cell, init))


def we_win(ours, theirs):
    """Rulebook C1-C2: strictly more warriors wins; equal = both wiped."""
    return ours > theirs


# ---------------------------------------------------------------- production
def choose_production(view, flags_n, warriors_n, live):
    cfg = BALANCE
    budget = max(0, view.my_resource - capture_reserve(view))
    eng = sum(b["type"] == "ENG" and b["owner"] == view.team for b in view.buildings)
    wc = max(cfg["buildings"]["eng_cost_floor"],
             cfg["units"]["W"]["cost"] - eng * cfg["buildings"]["eng_discount_per"])
    fc = cfg["units"]["F"]["cost"]
    enemy_w = sum(u["count"] for u in view.units if u["team"] == view.opp and u["kind"] == "W")
    make_f = min(max(0, MIN_FLAGS - flags_n), budget // fc) if live else 0
    budget -= make_f * fc
    make_w = min(max(0, max(3, enemy_w + 2) - warriors_n), budget // wc)
    budget -= make_w * wc
    extra_f = min(max(0, min(len(live), MAX_FLAGS) + 1 - flags_n - make_f), budget // fc)
    make_f += extra_f
    budget -= extra_f * fc
    make_w += budget // wc
    cmds = []
    if make_w:
        cmds.append(spawn("W", make_w))
    if make_f:
        cmds.append(spawn("F", make_f))
    return cmds



# ---------------------------------------------------------------- warriors
def warrior_jobs(view, init, enemy_w, enemy_f, my_f):
    """List of (value, cell, need) jobs. need = warriors required to win there."""
    jobs = []
    mine = [(b["x"], b["y"]) for b in view.buildings if b["owner"] == view.team]
    # 1) DEFEND our buildings / flags that enemy warriors can reach soon
    for cell in set(mine) | set(my_f):
        threat = sum(c for e, c in enemy_w.items() if (pathing.distance(e, cell) or 99) <= 2)
        if threat:
            jobs.append((3.0, cell, threat + 1))
    # 2) HUNT enemy flags (extra value if they sit on a building)
    for cell, cnt in enemy_f.items():
        guard = reach(enemy_w, cell, init)
        on_b = view.building_at(*cell) is not None
        jobs.append((2.0 + (1.0 if on_b else 0) + 0.1 * cnt, cell, guard + 1))
    # 3) HUNT enemy warrior stacks we clearly outnumber
    for cell, cnt in enemy_w.items():
        jobs.append((1.5, cell, reach(enemy_w, cell, init) + 1))
    return jobs



def move_warriors(view, init, warriors, enemy_w, enemy_f, my_f, escort_cells):
    cmds = []
    jobs = warrior_jobs(view, init, enemy_w, enemy_f, my_f)
    stacks = sorted(warriors, key=lambda u: -u["count"])
    biggest = (stacks[0]["x"], stacks[0]["y"]) if stacks else None
    home = init.bases[view.team]
    for u in stacks:
        pos, n = (u["x"], u["y"]), u["count"]
        best, best_score = None, 0.0
        for value, cell, need in jobs:
            if n < need:
                continue
            d = pathing.distance(pos, cell)
            if d is None:
                continue
            score = value / (d + 1)
            if score > best_score:
                best, best_score = cell, score
        if best is None:
            # Too weak for any fight: merge with the biggest stack, else escort flags
            if biggest and biggest != pos:
                best = biggest
            elif escort_cells:
                _, best, _ = pathing.nearest(pos, escort_cells)
        if best is None:
            continue
        step = pathing.step_toward(pos, best)
        if not step:
            continue
        dx, dy = DIRS[step]
        nxt = (pos[0] + dx, pos[1] + dy)
        # Never walk into a cell where the enemy could bring more warriors
        if not we_win(n, reach(enemy_w, nxt, init)):
            if not we_win(n, reach(enemy_w, pos, init)):  # current cell unsafe too
                step = pathing.step_toward(pos, home)
            else:
                step = None
        if step:
            cmds.append(move(pos[0], pos[1], "W", n, step))
        log("W", pos, n, "->", best, step)
    return cmds



def warrior_cost(view, team):
    """Return the current warrior production cost for a team."""
    engineering = sum(
        b['owner'] == team and b['type'] == 'ENG'
        for b in view.buildings
    )
    return max(
        BALANCE['buildings']['eng_cost_floor'],
        BALANCE['units']['W']['cost']
        - engineering * BALANCE['buildings']['eng_discount_per'],
    )

def planned_warriors(view, init, production, warrior_moves):
    available = {
        (u['x'], u['y']): u['count'] for u in view.my_units('W')
    }
    budget = view.my_resource
    for command in production:
        parts = command.split()
        if parts[0] != 'SPAWN':
            raise ValueError('Projection expects SPAWN production orders')
        kind, requested = parts[1], int(parts[2])
        position = tuple(init.bases[view.team])
        if len(parts) == 5:
            position = (int(parts[3]), int(parts[4]))
            building = view.building_at(*position)
            if not building or building['owner'] != view.team or building['type'] != 'HOSPITAL':
                continue
        cost = warrior_cost(view, view.team) if kind == 'W' else BALANCE['units'][kind]['cost']
        count = min(requested, budget // cost)
        budget -= count * cost
        if kind == 'W':
            available[position] = available.get(position, 0) + count

    arrivals = {}
    for command in warrior_moves:
        parts = command.split()
        if parts[0] != 'MOVE' or parts[3] != 'W':
            raise ValueError('Projection expects one-step warrior MOVE orders')
        source = (int(parts[1]), int(parts[2]))
        dx, dy = DIRS[parts[5]]
        destination = (source[0] + dx, source[1] + dy)
        if not init.passable(*destination):
            continue
        count = min(int(parts[4]), available.get(source, 0))
        available[source] = available.get(source, 0) - count
        arrivals[destination] = arrivals.get(destination, 0) + count

    result = dict(available)
    for cell, count in arrivals.items():
        result[cell] = result.get(cell, 0) + count
    return result


def protected_danger_cells(view, init, defenders):
    threats = {}
    enemy_w = {}
    for unit in view.units:
        if unit['team'] == view.opp and unit['kind'] == 'W':
            cell = (unit['x'], unit['y'])
            enemy_w[cell] = enemy_w.get(cell, 0) + unit['count']
    for source, count in enemy_w.items():
        for cell in neighbours(source, init):
            threats[cell] = threats.get(cell, 0) + count

    spawn_capacity = view.opp_resource // warrior_cost(view, view.opp)
    spawn_sources = {tuple(init.bases[view.opp])}
    spawn_sources.update(
        (b['x'], b['y']) for b in view.buildings
        if b['owner'] == view.opp and b['type'] == 'HOSPITAL'
    )
    spawn_reach = {
        cell for source in spawn_sources for cell in neighbours(source, init)
    }

    # The same resource budget must not be counted once per spawn location.
    for cell in spawn_reach:
        threats[cell] = threats.get(cell, 0) + spawn_capacity

    stations = {
        (b['x'], b['y']) for b in view.buildings
        if b['owner'] == view.opp and b['type'] == 'STATION'
    }
    if len(stations) >= BALANCE['tele']['min_stations']:
        for target in stations:
            # One TELE order can use only one source station per turn.
            # Adjacent sources were already included as ordinary movement.
            extra = max(
                (min(BALANCE['tele']['max_units'], enemy_w.get(source, 0))
                 for source in stations
                 if source not in neighbours(target, init)),
                default=0,
            )
            threats[target] = threats.get(target, 0) + extra

    return {
        cell for cell, threat in threats.items()
        if threat > defenders.get(cell, 0)
    }

# ---------------------------------------------------------------- flags
def move_flags(view, init, flags, live, enemy_w, my_w, defenders):
    """Assign targets and account for planned warrior protection."""
    cmds, claimed, movers = [], set(), []
    danger = enemy_danger_cells(view, init)
    immediate_danger = protected_danger_cells(view, init, defenders)

    for u in flags:
        pos = (u["x"], u["y"])
        if pos in live and pos not in immediate_danger:
            claimed.add(pos)
        else:
            movers.append(u)

    for u in movers:
        pos = (u["x"], u["y"])

        # Use planned protection only for cells reachable this turn.
        local_cells = set(neighbours(pos, init))
        route_danger = (
            (danger - local_cells)
            | (immediate_danger & local_cells)
        )

        remaining = {
            t for t in (live - claimed) if t not in route_danger
        } or {
            t for t in live if t not in route_danger
        }
        step = None

        while remaining:
            _, goal, _ = pathing.nearest(pos, remaining)
            if goal is None:
                break

            step = safe_flag_step(
                view, init, pos, goal, route_danger
            )
            if step is not None:
                claimed.add(goal)
                break

            remaining.discard(goal)

        # Retreat if the planned protection is insufficient.
        if step is None and pos in immediate_danger:
            step = safe_flag_step(
                view, init, pos, pos, route_danger
            )

        if step is not None:
            cmds.append(
                move(pos[0], pos[1], "F", u["count"], step)
            )

    return cmds


def move_warriors_simple(view, init, warriors, enemy_w, enemy_f, my_f, live):
    """v2/v3 warrior logic: chase nearest enemy flag, else head for targets."""
    cmds = []
    goals = set(enemy_f) or live
    for u in warriors:
        step, _, _ = pathing.nearest((u["x"], u["y"]), goals)
        if step:
            cmds.append(move(u["x"], u["y"], "W", u["count"], step))
    return cmds



def move_flags_simple(view, init, flags, live, enemy_w, my_w):
    cmds, claimed, movers = [], set(), []
    for u in flags:
        pos = (u["x"], u["y"])
        (claimed.add(pos) if pos in live else movers.append(u))
    for u in movers:
        pos = (u["x"], u["y"])
        step, target, _ = pathing.nearest(pos, (live - claimed) or live)
        if target is not None: claimed.add(target)
        if step: cmds.append(move(pos[0], pos[1], "F", u["count"], step))
    return cmds


