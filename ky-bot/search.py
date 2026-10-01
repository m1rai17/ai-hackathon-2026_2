"""예제의 너비 우선 탐색과 점령 자원 예약."""
from collections import deque
from protocol import DIRS, BALANCE
import pathing

def directions(init):
    """같은 거리라면 자기 본진 기준의 고정 방향 순서로 결정한다."""
    order = ("U", "D", "L", "R")
    flip = {"U": "D", "D": "U", "L": "R", "R": "L"}
    return tuple(flip[d] for d in order) if init.bases[init.team][0] * 2 > init.width - 1 else order


def bfs(start, targets, init):
    """너비 우선 탐색은 가까운 칸부터 방문하여 가장 가까운 목표의 첫 이동을 찾는다."""
    if start in targets:
        return None
    queue = deque([(start, None)])
    seen = {start}
    while queue:
        (x, y), first = queue.popleft()
        for direction in directions(init):
            dx, dy = DIRS[direction]
            pos = (x + dx, y + dy)
            if pos in seen or not init.passable(*pos):
                continue
            step = first or direction
            if pos in targets:
                return step
            seen.add(pos)
            queue.append((pos, step))
    return None


def capture_reserve(view, objectives=None):
    """Reserve one capture-stage cost for every distinct building being captured this turn."""
    cfg = BALANCE
    owns = any(
        b["type"] == "LIBRARY" and b["owner"] == view.team
        for b in view.buildings
    )
    base = cfg["capture"]["capture_cost"]

    # Multiple flags on the same building still consume only one building-level
    # capture cost. Reserve the sum across distinct buildings.
    pending = {}

    def add_building(b):
        if not b or b["owner"] == view.team or b["id"] in pending:
            return
        cost = base * (
            cfg["capture"]["plaza_multiplier"]
            if b["type"] == "PLAZA"
            else 1
        )
        pending[b["id"]] = max(
            cfg["capture"]["min_capture_cost"],
            cost - (cfg["buildings"]["library_discount"] if owns else 0),
        )

    for u in view.my_units("F"):
        add_building(view.building_at(u["x"], u["y"]))

    # Production is chosen before movement. When an objective is exactly one
    # step away, this flag is expected to reach/capture the building during the
    # same turn, so reserve that cost too. This is what the previous version was
    # missing in multi-capture turns.
    for source, assigned in (objectives or {}).items():
        source = tuple(source)
        for goal in assigned or []:
            if goal is None:
                continue
            goal = tuple(goal)
            b = view.building_at(*goal)
            if not b or b["owner"] == view.team:
                continue
            distance = pathing.distance(source, goal)
            if distance is not None and distance <= 1:
                add_building(b)

    return sum(pending.values())



