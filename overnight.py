"""Long improvement run over many tiers: workers repeatedly take a case, warm-start
from the best solution on disk (or occasionally restart from scratch for
diversity), run LNS for a chunk of time, and write the result back only if the
official checker says it is legal and strictly better.

usage: python overnight.py --hours 7 --jobs 12 --best-root out
       (out/<tier>/<case>.sol.json must hold the current best for each case)
"""
import argparse
import json
import os
import random
import sys
import time
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("M3D_REPO", os.path.join(HERE, "..", "eda-3d-routing-challenge"))
sys.path.insert(0, REPO)

TIER_DIR = {"intro": "benchmarks", "hard": "benchmarks_hard", "scale": "benchmarks_scale",
            "stress": "benchmarks_stress", "congested": "benchmarks_congested",
            "designs": "benchmarks_designs"}
# relative effort per case, and chunk length in minutes
TIER_WEIGHT = {"intro": 0.5, "hard": 2.0, "scale": 1.0, "stress": 6.0, "congested": 5.0,
               "designs": 5.0}
CHUNK_MIN = {"intro": 15, "hard": 20, "scale": 25, "stress": 90, "congested": 45,
             "designs": 40}
SLOW = dict(pres0=0.05, mult=1.03, hist_fac=0.05, pres_max=3, max_iters=8000, vcost=3.0,
            fan_exp=0.5)


def _lock(path, timeout=600):
    t = time.time()
    while True:
        try:
            return os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if time.time() - t > timeout:
                os.remove(path)
            time.sleep(0.5)


def chunk(args):
    tier, case_file, best_path, minutes, seed, deadline, fresh = args
    if time.time() > deadline - 120:
        return None
    from m3d.model import Instance, Submission
    from m3d.checker import check
    from router import Router
    t0 = time.time()
    budget = min(minutes * 60, deadline - t0)
    inst = json.load(open(case_file))
    I = Instance.from_dict(inst)
    r = Router(inst, seed=seed)
    order = r.default_order()
    rng = random.Random(seed)
    if fresh or not os.path.exists(best_path):
        rng.shuffle(order)
        it = r.negotiate(order, **SLOW) if r.N < 500_000 or fresh == 2 else -1
        if it < 0:
            it = r.negotiate(order)
        if it < 0:
            return tier, os.path.basename(best_path), None, None, "neg failed"
        mode = "fresh"
    else:
        r.load(json.load(open(best_path)))
        mode = "warm"
    r.refine(order)
    start = r.total()
    T0 = rng.choice([5.0, 15.0, 40.0]) if mode == "warm" else 50.0
    rem = budget - (time.time() - t0)
    if rem > 0:
        ms, pw = rng.choice([(6, 0.5), (10, 0.8), (14, 0.9)])
        r.lns(iters=10**9, time_limit=rem, T0=T0, T1=1.0, p_seq=0.2, max_set=ms, p_win=pw)
    sol = r.solution()
    res = check(I, Submission.from_dict(sol))
    if not res.legal:
        return tier, os.path.basename(best_path), None, None, "ILLEGAL " + "; ".join(res.reasons[:2])
    fd = _lock(best_path + ".lock")
    try:
        prev = None
        if os.path.exists(best_path):
            p = check(I, Submission.load(best_path))
            prev = p.total_delay if p.legal else None
        if prev is None or res.total_delay < prev:
            tmp = best_path + f".tmp{seed}"
            with open(tmp, "w") as fh:
                json.dump(sol, fh)
            os.replace(tmp, best_path)
            kept = True
        else:
            kept = False
    finally:
        os.close(fd)
        os.remove(best_path + ".lock")
    return (tier, os.path.basename(best_path), res.total_delay, prev,
            f"{mode} T0={T0} start={start:.0f} {'KEPT' if kept else ''} {time.time()-t0:.0f}s")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, required=True)
    ap.add_argument("--jobs", type=int, default=12)
    ap.add_argument("--best-root", required=True)
    ap.add_argument("--p-fresh", type=float, default=0.25)
    a = ap.parse_args()
    deadline = time.time() + a.hours * 3600
    cases = []
    for tier, d in TIER_DIR.items():
        suite = json.load(open(os.path.join(REPO, d, "suite.json")))
        for c in suite["cases"]:
            cases.append((tier, os.path.join(REPO, d, c["instance_file"]),
                          os.path.join(a.best_root, tier, f"{c['name']}.sol.json")))
    rng = random.Random(12345)
    weights = [TIER_WEIGHT[t] for t, _, _ in cases]
    tasks = []
    # one long from-scratch slow-negotiation attempt on stress (never tried before)
    for t, cf, bp in cases:
        if t == "stress":
            tasks.append((t, cf, bp, 240, 999, deadline, 2))
    for k in range(5000):
        t, cf, bp = rng.choices(cases, weights)[0]
        tasks.append((t, cf, bp, CHUNK_MIN[t], 1000 + k, deadline,
                      1 if rng.random() < a.p_fresh else 0))
    with Pool(a.jobs, maxtasksperchild=1) as pool:
        for res in pool.imap_unordered(chunk, tasks):
            if res is None:
                continue
            print(time.strftime("%H:%M:%S"), *res, flush=True)
            if time.time() > deadline:
                pool.terminate()
                break


if __name__ == "__main__":
    main()
