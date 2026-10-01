"""Predictive opponent adaptation for v4.6.

Both sides start symmetrically, so a later military advantage must be created by
an economic/positional snowball. The rules expose the opponent's current
resources, so we use that information to estimate the *next* Warrior burst
rather than waiting until the army is already on top of us.
"""
from __future__ import annotations

from collections import deque
from protocol import BALANCE

PRESSURE = "pressure"
EMERGENCY = "emergency"
NORMAL = "normal"
GUARD_DISTANCE = 4

_history = {}


def _pos(u):
    return (u["x"], u["y"])


def _dist(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _state_key(view, init):
    return (id(init), view.team)


def _update_history(view, init, owned):
    key = _state_key(view, init)
    state = _history.get(key)
    if state is None:
        state = {
            "last_owned": set(owned),
            "loss_turns": deque(maxlen=8),
            "last_turn": view.turn,
        }
        _history[key] = state
        return state

    if view.turn < state["last_turn"]:
        state["last_owned"] = set(owned)
        state["loss_turns"].clear()
        state["last_turn"] = view.turn
        return state

    lost = state["last_owned"] - set(owned)
    if lost:
        state["loss_turns"].append(view.turn)
    state["last_owned"] = set(owned)
    state["loss_turns"] = deque(
        (t for t in state["loss_turns"] if view.turn - t <= 10),
        maxlen=8,
    )
    state["last_turn"] = view.turn
    return state


def _owned_count(view, team, kind):
    return sum(
        1 for b in view.buildings
        if b["owner"] == team and b["type"] == kind
    )


def _warrior_cost(view, team):
    eng = _owned_count(view, team, "ENG")
    cfg = BALANCE
    return max(
        cfg["buildings"]["eng_cost_floor"],
        cfg["units"]["W"]["cost"] - eng * cfg["buildings"]["eng_discount_per"],
    )


def analyze(view, init):
    """Return predictive economic/military pressure metrics for the turn."""
    owned = {
        (b["x"], b["y"])
        for b in view.buildings
        if b["owner"] == view.team
    }
    enemy_w = [u for u in view.units if u["team"] == view.opp and u["kind"] == "W"]
    my_w = [u for u in view.units if u["team"] == view.team and u["kind"] == "W"]
    enemy_f = [u for u in view.units if u["team"] == view.opp and u["kind"] == "F"]

    enemy_w_total = sum(u["count"] for u in enemy_w)
    my_w_total = sum(u["count"] for u in my_w)

    owned_cells = list(owned)
    near_enemy_w = 0
    near_enemy_w_cells = {}
    for u in enemy_w:
        p = _pos(u)
        if any(_dist(p, b) <= GUARD_DISTANCE for b in owned_cells):
            near_enemy_w += u["count"]
            near_enemy_w_cells[p] = u["count"]

    threatened_buildings = 0
    incoming_flags = 0
    for b in view.buildings:
        if b["owner"] != view.team:
            continue
        p = (b["x"], b["y"])
        if any(_dist(_pos(u), p) <= GUARD_DISTANCE for u in enemy_w):
            threatened_buildings += 1
        if any(_dist(_pos(u), p) <= GUARD_DISTANCE for u in enemy_f):
            incoming_flags += 1

    state = _update_history(view, init, owned)
    recent_losses = len(state["loss_turns"])

    my_eng = _owned_count(view, view.team, "ENG")
    enemy_eng = _owned_count(view, view.opp, "ENG")
    my_hall = _owned_count(view, view.team, "HALL")
    enemy_hall = _owned_count(view, view.opp, "HALL")
    my_hospital = _owned_count(view, view.team, "HOSPITAL")
    enemy_hospital = _owned_count(view, view.opp, "HOSPITAL")

    my_income = 10 + 2 * my_hall
    enemy_income = 10 + 2 * enemy_hall

    my_wc = _warrior_cost(view, view.team)
    enemy_wc = _warrior_cost(view, view.opp)

    # Upper-bound next production. We intentionally do not assume the opponent
    # will spend all resources on W; this is a threat envelope for deciding
    # whether we need to preserve a response force now.
    my_max_new_w = max(0, view.my_resource // my_wc)
    enemy_max_new_w = max(0, view.opp_resource // enemy_wc)
    my_projected_w = my_w_total + my_max_new_w
    enemy_projected_w = enemy_w_total + enemy_max_new_w
    projected_gap = enemy_projected_w - my_projected_w

    current_gap = enemy_w_total - my_w_total
    ratio = enemy_w_total / max(1, my_w_total)
    local_ratio = near_enemy_w / max(1, my_w_total)
    resource_gap = view.opp_resource - view.my_resource
    income_gap = enemy_income - my_income
    economic_advantage = (
        enemy_income > my_income
        or enemy_eng > my_eng
        or resource_gap >= 6
        or enemy_hospital > my_hospital
    )

    local_pressure = (
        near_enemy_w >= 4
        or threatened_buildings >= 1
        or incoming_flags >= 1
    )

    # Pressure means the opponent can plausibly create a materially larger
    # Warrior force AND has a reason/position to use it against our territory.
    pressure = (
        view.turn >= 15
        and economic_advantage
        and projected_gap >= 4
        and local_pressure
    ) or (
        view.turn >= 25
        and projected_gap >= 6
        and near_enemy_w >= 5
    )

    # Emergency is reserved for actual collapse, not merely a large enemy army.
    emergency = (
        view.turn >= 25
        and recent_losses >= 2
        and projected_gap >= 4
        and local_pressure
    ) or (
        view.turn >= 45
        and len(owned) <= 4
        and projected_gap >= 5
        and ratio >= 1.15
    ) or (
        len(owned) <= 2
        and view.turn >= 60
        and local_pressure
    )

    if emergency:
        current_mode = EMERGENCY
    elif pressure:
        current_mode = PRESSURE
    else:
        current_mode = NORMAL

    return {
        "mode": current_mode,
        "enemy_w": enemy_w_total,
        "my_w": my_w_total,
        "near_enemy_w": near_enemy_w,
        "threatened_buildings": threatened_buildings,
        "incoming_flags": incoming_flags,
        "recent_losses": recent_losses,
        "ratio": ratio,
        "local_ratio": local_ratio,
        "near_enemy_w_cells": near_enemy_w_cells,
        "my_eng": my_eng,
        "enemy_eng": enemy_eng,
        "my_hall": my_hall,
        "enemy_hall": enemy_hall,
        "my_hospital": my_hospital,
        "enemy_hospital": enemy_hospital,
        "my_income": my_income,
        "enemy_income": enemy_income,
        "income_gap": income_gap,
        "resource_gap": resource_gap,
        "my_w_cost": my_wc,
        "enemy_w_cost": enemy_wc,
        "my_max_new_w": my_max_new_w,
        "enemy_max_new_w": enemy_max_new_w,
        "my_projected_w": my_projected_w,
        "enemy_projected_w": enemy_projected_w,
        "projected_gap": projected_gap,
        "current_gap": current_gap,
        "economic_advantage": economic_advantage,
    }


def mode(view, init):
    return analyze(view, init)["mode"]
