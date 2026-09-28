"""Batch arena: python arena.py botA.py botB.py --seeds 20
Plays every seed twice (A as Y, then A as K) to cancel side advantage.
Works on Windows: patches the official runner's pipe writer (select() on pipes
is Linux/macOS-only) and quotes paths with spaces correctly for cmd.exe."""
import argparse, os, sys, time, shlex, subprocess
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
BOTDIR = ROOT / "bots/dist/starter/python"
WINDOWS = os.name == "nt"


def _cmd(parts):
    return subprocess.list2cmdline(parts) if WINDOWS else shlex.join(parts)


def _patch_runner_for_windows():
    """Replace SubprocessBot._write with a select()-free version (same results/timeouts)."""
    from runner.bots import SubprocessBot

    def _write(self, text):
        status, error = "timeout", None
        try:
            data = memoryview(text.encode(self.proc.stdin.encoding or "utf-8"))
            fd = self.proc.stdin.fileno()
            while data and not self._cancel_write.is_set():
                if time.monotonic() >= self._deadline:
                    break
                try:
                    n = os.write(fd, data[:4096])
                except BlockingIOError:
                    n = 0
                if n == 0:
                    time.sleep(0.001)
                    continue
                data = data[n:]
            if not data:
                status = "ok"
        except BrokenPipeError:
            status = "closed"
        except Exception as exc:
            status, error = "runner_error", exc
        finally:
            self._write_result = (status, error)
            self._write_done.set()

    SubprocessBot._write = _write


def play(args):
    seed, y, k = args
    if WINDOWS or os.environ.get("ARENA_FORCE_PATCH"):
        _patch_runner_for_windows()
    from engine.config import load_config
    from runner import SubprocessBot, run_match
    bots = [SubprocessBot(_cmd([sys.executable, str(BOTDIR / f)]), name=f) for f in (y, k)]
    try:
        cfg = load_config(); cfg["first_turn_timeout_ms"] = 3000
        _, res = run_match(seed, cfg, *bots, turn_timeout_ms=300)
    finally:
        for b in bots: b.close()
    return seed, y, k, res


def main():
    p = argparse.ArgumentParser()
    p.add_argument("a"); p.add_argument("b")
    p.add_argument("--seeds", type=int, default=20); p.add_argument("--start", type=int, default=1000)
    p.add_argument("-j", type=int, default=4)
    a = p.parse_args()
    for f in (a.a, a.b):
        if not (BOTDIR / f).is_file():
            sys.exit(f"Bot not found: {BOTDIR / f}")
    jobs = []
    for s in range(a.start, a.start + a.seeds):
        jobs += [(s, a.a, a.b), (s, a.b, a.a)]
    t = time.time(); w = l = d = 0; margin = 0; reasons = {}
    with ProcessPoolExecutor(a.j) as ex:
        for seed, y, k, r in ex.map(play, jobs):
            me = "Y" if y == a.a else "K"; opp = "K" if me == "Y" else "Y"
            reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1
            margin += r["score"][me] - r["score"][opp]
            if r["winner"] == me: w += 1
            elif r["winner"] in ("Y", "K"): l += 1
            else: d += 1
    n = len(jobs)
    print(f"{a.a} vs {a.b}: W{w} L{l} D{d}  winrate={w/n:.0%}  avg_margin={margin/n:+.1f}  "
          f"reasons={reasons}  ({time.time()-t:.0f}s)")


if __name__ == "__main__":
    main()
