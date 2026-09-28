# Testing tools

## Setup (once)
1. Extract the official `yk-development-tools` zip.
2. Put `arena.py` and `econ.py` in its root folder (next to `engine/`, `runner/`, `bots/`).
3. Put any bot you want to test in `bots/dist/starter/python/`.

## Commands (run from the dev-tools root)
- Win rate: `python arena.py army_v2.py example_lv2.py --seeds 30`
  (each seed is played twice with sides swapped, so 30 seeds = 60 games)
- Money report: `python econ.py army_v2.py example_lv2.py --seeds 10`

Works on Windows: arena.py patches the official runner's Linux-only pipe code
without modifying any official files.

## Results so far
| Bot | Change | vs example_lv2 | Notes |
|---|---|---|---|
| teammate_v0 | flags only, nearest target | 0% (60 games) | wiped out by turns 45-85 |
| army_v1 | lv2 with warrior cap 3 -> 8 | 90% (60 games) | 97% of money spent on flags (~275 per game) |
| army_v2 | warriors = enemy W + 2; flags capped at targets + 1; leftover -> warriors | 85% (40 games) | beats army_v1 100%, beats a 25-warrior bot 95% |
| army_v3 | target claiming using the pathing module. 92% vs lv2, 50% vs v2 → combat is the bottleneck
| army_v4 | min 3 flags + flags avoid enemy warriors (smart warrior logic rejected: 32%) | 90% | 53-57% vs v3, 60% vs v2; economy-building priority (v5) tested: 50%, rejected |
   | army_v5 | economy buildings (ENG/HALL/DEPOT) prioritised | - | 50% vs v4, rejected |
   | army_v6 | warriors spawn at owned hospital | - | 58% then 50% on fresh seeds (noise), rejected |
| army_v9 | army_v4 + teammate's danger-map flag routing (navigation.py) | 95% | 93% / 85% vs v4 (120 games), worst turn 66 ms, official checker ok; v1 (routing only, no warriors) = 8% vs lv2 |
