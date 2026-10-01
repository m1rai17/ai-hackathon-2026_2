"""전략을 수정할 봇. 보조 모듈을 함께 제출 ZIP에 넣는다."""
# 디버깅 stderr는 게임당 1 MiB 이내로 사용하세요.
# 미공개 점수 -1은 실제 음수 점수가 아닙니다.
from protocol import run
import pathing
from army_v4_2 import choose_production, move_warriors_simple, planned_warriors
from flag_strategy import move_flags, plan_objectives
from coordination import coordinate_warriors
from scouting import move_scouts
from teleport import plan_teleport


def decide(view, init):
    commands = []
    # TODO: 점령에 남길 자원과 필요한 병종을 결정해 보세요.
    pathing.prepare(init)    #build 17 paths to all the buildings 
    flags = sorted(
        view.my_units("F"),
        key=lambda u: (u["y"], u["x"]),
    )
    warriors = view.my_units("W")

    def stacks(team, kind):
        result = {}
        for u in view.units:
            if u["team"] == team and u["kind"] == kind:
                pos = (u["x"], u["y"])
                result[pos] = result.get(pos, 0) + u["count"]
        return result

    enemy_w = stacks(view.opp, "W")
    enemy_f = stacks(view.opp, "F")
    my_w = stacks(view.team, "W")
    my_f = stacks(view.team, "F")

    enemy_flags = {
        (u['x'], u['y']) for u in view.units
        if u['team'] == view.opp and u['kind'] == 'F' and u['count'] > 0
    }


    # TODO: 단순한 첫 방향 대신 목표 건물로 가는 경로를 선택해 보세요.
    targets = {
        (b["x"], b["y"])
        for b in view.buildings
        if b["owner"] != view.team
    }

    nf = sum(u["count"] for u in flags)
    nw = sum(u["count"] for u in warriors)

    # v3.3: plan flag targets first so production knows where fights are likely
    objectives = plan_objectives(view, init, flags, targets)

    production = choose_production(view, nf, nw, targets, objectives)
    # production = choose_production(view, nf, nw, targets)

    tele_command = plan_teleport(view, init, objectives)

    # objectives = plan_objectives(view, init, flags, targets)
    warrior_moves = coordinate_warriors(view, init, production, objectives)

    defenders = planned_warriors(
        view, init, production, warrior_moves
    )

    scout_moves = move_scouts(
        view, init, view.my_units("S")
    )

    flag_moves = move_flags(
        view, init, flags, targets, enemy_w, my_w, defenders, objectives
    )

    commands.extend(production)
    # TELE comes before ordinary movement so source units are available for it.
    if tele_command:
        commands.append(tele_command)
    commands.extend(scout_moves)
    commands.extend(warrior_moves)
    commands.extend(flag_moves)

    return commands


if __name__ == "__main__":
    run(decide)
