"""army_v4: army_v3 + flag safety + minimum-flag production.

NOTE: move_warriors() (combat-aware jobs) is kept for reference but NOT used:
it measured 25% vs army_v3. Simple chase-the-enemy-flag warriors are used instead.

Combat rules used (rulebook ch.6): combat only on shared cells after moves;
W cancel 1:1; surviving W remove all enemy F and S. Units move 1 cell/turn,
so the enemy W that can hit a cell next turn are those ON it or ADJACENT to it.
"""
import sys
from protocol import BALANCE, DIRS, spawn, move, run
from search import capture_reserve
import pathing

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
            if not we_win(n, reach(enemy_w, pos, init)):   # current cell unsafe too
                step = pathing.step_toward(pos, home)
            else:
                step = None
        if step:
            cmds.append(move(pos[0], pos[1], "W", n, step))
        log("W", pos, n, "->", best, step)
    return cmds


# ---------------------------------------------------------------- flags
def move_flags(view, init, flags, live, enemy_w, my_w):
    cmds = []
    claimed = set()
    movers = []
    for u in flags:
        pos = (u["x"], u["y"])
        if pos in live:
            claimed.add(pos)
        else:
            movers.append(u)
    for u in movers:
        pos = (u["x"], u["y"])
        free = live - claimed
        step, target, _ = pathing.nearest(pos, free or live)
        if target is not None:
            claimed.add(target)
        if not step:
            continue
        dx, dy = DIRS[step]
        nxt = (pos[0] + dx, pos[1] + dy)
        danger_next = reach(enemy_w, nxt, init) - reach(my_w, nxt, init)
        danger_here = reach(enemy_w, pos, init) - reach(my_w, pos, init)
        if danger_next > 0 and danger_here <= 0:
            continue                      # wait where it's safe
        cmds.append(move(pos[0], pos[1], "F", u["count"], step))
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

# ---------------------------------------------------------------- main
def decide(view, init):
    pathing.prepare(init)
    flags = sorted(view.my_units("F"), key=lambda u: (u["y"], u["x"]))
    warriors = view.my_units("W")

    def stacks(team, kind):
        s = {}
        for u in view.units:
            if u["team"] == team and u["kind"] == kind:
                s[(u["x"], u["y"])] = s.get((u["x"], u["y"]), 0) + u["count"]
        return s

    enemy_w, enemy_f = stacks(view.opp, "W"), stacks(view.opp, "F")
    my_w, my_f = stacks(view.team, "W"), stacks(view.team, "F")
    targets = {(b["x"], b["y"]) for b in view.buildings if b["owner"] != view.team}
    live = targets - set(enemy_f)

    nf = sum(u["count"] for u in flags)
    nw = sum(u["count"] for u in warriors)
    cmds = choose_production(view, nf, nw, live)
    cmds += move_warriors_simple(view, init, warriors, enemy_w, enemy_f, my_f, live)
    cmds += move_flags(view, init, flags, live, enemy_w, my_w)
    return cmds


if __name__ == "__main__":
    run(decide)
