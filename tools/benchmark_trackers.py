#!/usr/bin/env python3
"""Compare the tracking methods on synthetic scenes with known identities.

    python tools/benchmark_trackers.py

ids/object: how many ids each real object was split into (1.00 is perfect).
wrong merges: ids that mix two different objects (0 is perfect). Each cell averages 5 random seeds.
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "relabel_gui_app"), os.path.join(ROOT, "tests")]
import scenes  # noqa: E402
import trackers  # noqa: E402

CONDITIONS = {
    "clean": {},
    "10% missed + weak scores": {"drop": 0.10, "weak_scores": True},
    "30% missed + weak scores": {"drop": 0.30, "weak_scores": True},
}
SEEDS = range(5)


def main():
    methods = [m["id"] for m in trackers.describe()]
    print(f"{'scene':16s} {'condition':26s} " + " ".join(f"{m:>22s}" for m in methods))
    totals = {m: [0.0, 0, 0.0] for m in methods}
    for scene in scenes.SCENES:
        for cond, kw in CONDITIONS.items():
            cells = []
            for m in methods:
                ipo = wm = 0.0
                for seed in SEEDS:
                    frames, truth = scenes.make(scene, seed=seed, **kw)
                    t0 = time.perf_counter()
                    res = trackers.run(frames, method=m)
                    totals[m][2] += time.perf_counter() - t0
                    s = scenes.score(res, truth)
                    ipo += s["ids_per_object"] / len(SEEDS)
                    wm += s["wrong_merges"] / len(SEEDS)
                totals[m][0] += ipo
                totals[m][1] += wm
                cells.append(f"{ipo:5.2f} ids, {wm:3.1f} wrong")
            print(f"{scene:16s} {cond:26s} " + " ".join(f"{c:>22s}" for c in cells))
    n = len(scenes.SCENES) * len(CONDITIONS)
    print("\nmean over all cells:")
    for m, (ipo, wm, secs) in totals.items():
        print(f"  {m:14s} ids/object {ipo / n:4.2f}   wrong merges {wm / n:4.2f}   time {secs * 1000:6.0f} ms total")


if __name__ == "__main__":
    main()
