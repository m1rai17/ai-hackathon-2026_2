"""Teammate's current logic: flags -> nearest non-owned building (+ lv1-style spawning)."""
from protocol import BALANCE, spawn, move, run
from search import bfs

def decide(view, init):
    commands = []
    if view.my_resource >= BALANCE["units"]["F"]["cost"]:
        commands.append(spawn("F", view.my_resource // BALANCE["units"]["F"]["cost"]))
    targets = {(b["x"], b["y"]) for b in view.buildings if b["owner"] != view.team}
    for unit in view.my_units("F"):
        building = view.building_at(unit["x"], unit["y"])
        if building and building["owner"] != view.team:
            continue
        step = bfs((unit["x"], unit["y"]), targets, init)
        if step:
            commands.append(move(unit["x"], unit["y"], "F", unit["count"], step))
    return commands

if __name__ == "__main__":
    run(decide)
