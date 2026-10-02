"""Route every case of a tier in parallel, keep the best legal solution per case.

usage: python run_suite.py <suite_dir> <out_dir> --time SECONDS [--seeds K] [--jobs J]

A solution is only written if it passes the official m3d checker and beats any
solution already in out_dir (so repeated runs only ever improve the submission).
"""
import argparse
import json
import os
import sys
import time
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("M3D_REPO", os.path.join(HERE, "..", "eda-3d-routing-challenge"))
sys.path.insert(0, REPO)


SLOW = dict(pres0=0.05, mult=1.03, hist_fac=0.05, pres_max=3, max_iters=8000, vcost=3.0, fan_exp=0.5)
LNS = dict(p_seq=0.2, max_set=6, T0=50, T1=2)


def work(args):
    case_path, out_dir, budget, seed, name = args
    from m3d.model import Instance, Submission
    from m3d.checker import check
    from router import Router
    inst = json.load(open(case_path))
    t0 = time.time()
    r = Router(inst, seed=seed)
    order = r.default_order()
    if seed % 2 == 1:
        r.rng.shuffle(order)
    it = r.negotiate(order, **SLOW) if r.N < 500_000 else -1
    if it < 0:
        it = r.negotiate(order)
    if it < 0:
        it = r.negotiate(order, full_every=5)
    if it < 0:
        return name, seed, None, time.time() - t0, "negotiation failed"
    r.refine(order)
    remaining = budget - (time.time() - t0)
    if remaining > 0:
        r.lns(iters=10**9, time_limit=remaining, **LNS)
    sol = r.solution()
    res = check(Instance.from_dict(inst), Submission.from_dict(sol))
    el = time.time() - t0
    if not res.legal:
        return name, seed, None, el, "ILLEGAL: " + "; ".join(res.reasons[:3])
    out = os.path.join(out_dir, f"{name}.sol.json")
    lock = out + ".lock"
    # keep only improvements
    best = None
    if os.path.exists(out):
        try:
            prev = check(Instance.from_dict(inst), Submission.load(out))
            best = prev.total_delay if prev.legal else None
        except Exception:
            best = None
    if best is None or res.total_delay < best:
        tmp = out + f".tmp{seed}"
        with open(tmp, "w") as fh:
            json.dump(sol, fh)
        os.replace(tmp, out)
        rt = os.path.join(out_dir, f"{name}.runtime{seed}")
        with open(rt, "w") as fh:
            fh.write(str(el))
    return name, seed, res.total_delay, el, f"lb={int(r.lb.sum())} prev_best={best}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("suite")
    ap.add_argument("out")
    ap.add_argument("--time", type=float, default=60)
    ap.add_argument("--seeds", type=int, default=1)
    ap.add_argument("--seed0", type=int, default=0)
    ap.add_argument("--jobs", type=int, default=11)
    ap.add_argument("--cases", nargs="*")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    suite = json.load(open(os.path.join(a.suite, "suite.json")))
    base = {c["name"]: c["baseline_total"] for c in suite["cases"]}
    tasks = []
    for c in suite["cases"]:
        if a.cases and c["name"] not in a.cases:
            continue
        for k in range(a.seeds):
            tasks.append((os.path.join(a.suite, c["instance_file"]), a.out, a.time,
                          a.seed0 + k, c["name"]))
    # biggest instances first for load balance
    tasks.sort(key=lambda t: -os.path.getsize(t[0]))
    with Pool(a.jobs) as pool:
        for name, seed, tot, el, msg in pool.imap_unordered(work, tasks):
            ratio = f"{base[name] / tot:.4f}" if tot else "-"
            print(f"{name} seed={seed} total={tot} base={base[name]} ratio={ratio} "
                  f"{el:.0f}s {msg}", flush=True)


if __name__ == "__main__":
    main()
