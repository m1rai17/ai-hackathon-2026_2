"""전략을 수정할 봇. 보조 모듈을 함께 제출 ZIP에 넣는다."""
# 디버깅 stderr는 게임당 1 MiB 이내로 사용하세요.
# 미공개 점수 -1은 실제 음수 점수가 아닙니다.
from protocol import BALANCE, DIRS, spawn, move, run
from search import bfs, capture_reserve
import pathing
from navigation import enemy_danger_cells, safe_flag_step


def decide(view, init):
    commands = []
    # TODO: 점령에 남길 자원과 필요한 병종을 결정해 보세요.
    pathing.prepare(init)    #build 17 paths to all the buildings 
    if view.my_resource >= BALANCE["units"]["F"]["cost"]:
        commands.append(spawn("F", 1))

    danger = enemy_danger_cells(view, init)
    enemy_flags = {
        (u['x'], u['y']) for u in view.units
        if u['team'] == view.opp and u['kind'] == 'F' and u['count'] > 0
    }


    # TODO: 단순한 첫 방향 대신 목표 건물로 가는 경로를 선택해 보세요.
    targets = {
        (b["x"], b["y"])
        for b in view.buildings
        if b["owner"] != view.team
           and (b["x"], b["y"]) not in enemy_flags
    }

    for unit in view.my_units("F"):
        start = (unit["x"], unit["y"])
        building = view.building_at(*start)

        # Stay for capture only if safe and uncontested.
        if (
                building
                and building["owner"] != view.team
                and start not in danger
                and start not in enemy_flags
        ):
            continue

        # Try safe targets in nearest-first order.
        remaining = {
            target for target in targets
            if target not in danger
        }
        step = None

        while remaining:
            _, goal, _ = pathing.nearest(start, remaining)
            if goal is None:
                break

            step = safe_flag_step(view, init, start, goal, danger)
            if step is not None:
                break

            remaining.remove(goal)

        # Retreat even if no capture target is available.
        if step is None and start in danger:
            step = safe_flag_step(view, init, start, start, danger)

        if step is not None:
            commands.append(
                move(unit["x"], unit["y"], "F", unit["count"], step)
            )
    
    # for unit in view.my_units("F"):
    #     building = view.building_at(unit["x"], unit["y"])
    #     if building and building["owner"] != view.team:
    #         continue
    #     for direction, (dx, dy) in DIRS.items():
    #         if init.passable(unit["x"] + dx, unit["y"] + dy):
    #             commands.append(move(unit["x"], unit["y"], "F", unit["count"], direction))
    #             break
    return commands


if __name__ == "__main__":
    run(decide)
