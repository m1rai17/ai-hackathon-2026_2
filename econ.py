"""Money report: python econ.py botA.py botB.py --seeds 10
For bot A: avg unspent resources, turns sitting at the 40 cap (income wasted),
and what the money was spent on (F / W / S / captures)."""
import argparse, sys
from arena import play  # reuses the Windows-safe runner
import arena

def analyse(replay, me):
    res, capped, spent = [], 0, {"F": 0, "W": 0, "S": 0}
    for t in replay["turns"]:
        r = t["state"]["resources"][me]
        res.append(r); capped += (r >= 40)
        for a in t["applied"][me]:
            if a["cmd"] == "Spawn":
                spent[a["kind"]] += a["count"]
    return sum(res) / len(res), capped, len(res), spent

def main():
    p = argparse.ArgumentParser(); p.add_argument("a"); p.add_argument("b")
    p.add_argument("--seeds", type=int, default=10); a = p.parse_args()
    import shlex, os
    from engine.config import load_config
    from runner import SubprocessBot, run_match
    if arena.WINDOWS: arena._patch_runner_for_windows()
    tot = [0, 0, 0, {"F": 0, "W": 0, "S": 0}]; games = 0
    for s in range(1000, 1000 + a.seeds):
        for y, k in ((a.a, a.b), (a.b, a.a)):
            bots = [SubprocessBot(arena._cmd([sys.executable, str(arena.BOTDIR / f)]), name=f) for f in (y, k)]
            try:
                cfg = load_config(); cfg["first_turn_timeout_ms"] = 3000
                rep, _ = run_match(s, cfg, *bots, turn_timeout_ms=300)
            finally:
                for b in bots: b.close()
            avg, cap, n, sp = analyse(rep, "Y" if y == a.a else "K")
            tot[0] += avg; tot[1] += cap; tot[2] += n; games += 1
            for k2 in sp: tot[3][k2] += sp[k2]
    g = games; cost = {"F": 5, "W": 3, "S": 2}
    print(f"{a.a} (vs {a.b}, {g} games)")
    print(f"  avg unspent money per turn : {tot[0]/g:.1f}")
    print(f"  turns stuck at cap (40)    : {tot[1]/g:.1f} per game  (~{tot[1]/g*10:.0f} income wasted)")
    print(f"  avg game length            : {tot[2]/g:.0f} turns")
    print("  units built per game       : " + ", ".join(f"{k} {v/g:.1f}" for k, v in tot[3].items()))
    print("  money on units per game    : " + ", ".join(f"{k} {v/g*cost[k]:.0f}" for k, v in tot[3].items()))

if __name__ == "__main__":
    main()
