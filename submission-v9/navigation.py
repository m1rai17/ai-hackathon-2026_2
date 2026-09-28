from collections import deque
from protocol import BALANCE, DIRS
import pathing

def neighbors(init, position):
    x, y = position
    for direction, (dx, dy) in DIRS.items():
        destination = x + dx, y + dy
        if init.passable(*destination):
            yield direction, destination


def enemy_danger_cells(view, init):
    danger = set()
    sources = {
        (unit['x'], unit['y']) for unit in view.units
        if unit['team'] == view.opp and unit['kind'] == 'W'
        and unit['count'] > 0
    }
    engineering = sum(
        b['owner'] == view.opp and b['type'] =='ENG'
        for b in view.buildings
    )
    cost = max(
        BALANCE['buildings']['eng_cost_floor'],
        BALANCE['units']['W']['cost'] - engineering * BALANCE['buildings']['eng_discount_per'],
    )
    if view.opp_resource >= cost:
        sources.add(tuple(init.bases[view.opp]))
        sources.update(
            (b['x'], b['y']) for b in view.buildings
            if b['owner'] == view.opp and b['type'] == 'HOSPITAL'
        )
    for position in sources:
        danger.add(position)
        danger.update(p for _, p in neighbors(init, position))
    stations = {
        (b['x'], b['y']) for b in view.buildings
        if b['owner'] == view.opp and b['type'] == 'STATION'
    }
    if len(stations) >= 2 and sources.intersection(stations):
        danger.update(stations)
    return danger


def safe_flag_step(view, init, start, target, danger=None):
    pathing.prepare(init)
    start, target = tuple(start), tuple(target)
    if not init.passable(*start) or not init.passable(*target):
        return None
    if danger is None:
        danger = enemy_danger_cells(view, init)
    if start == target and start not in danger:
        return None
    queue = deque([(start, None)])
    seen = {start}
    while queue:
        position, first = queue.popleft()
        for direction, destination in neighbors(init, position):
            if destination in seen or destination in danger:
                continue
            step = direction if first is None else first
            if destination == target:
                return step
            seen.add(destination)
            queue.append((destination, step))
    if start not in danger:
        return None
    escapes = [
        (direction, position) for direction, position in neighbors(init, start)
        if position not in danger
    ]
    if not escapes:
        return None
    def escape_score(option):
        _, position = option
        exits = sum(p not in danger for _, p in neighbors(init, position))
        distance = pathing.distance(position, target)
        return exits, -(distance if distance is not None else 10000)
    return max(escapes, key=escape_score)[0]
