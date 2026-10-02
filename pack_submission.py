"""Copy the best routed solutions into a challenge-repo submission directory.

usage: python pack_submission.py <out_dir> <challenge_repo> <tier> <name> [--date YYYY-MM-DD]

Writes <challenge_repo>/submissions/<tier>/<name>/ with one <case>.sol.json per case,
runtime.json (wall seconds of the run that produced each kept solution) and meta.json.
Refuses to pack unless every case is present and legal under the official checker.
"""
import argparse
import datetime
import glob
import json
import os
import shutil
import sys

TIER_DIR = {"intro": "benchmarks", "hard": "benchmarks_hard", "scale": "benchmarks_scale",
            "stress": "benchmarks_stress", "congested": "benchmarks_congested",
            "designs": "benchmarks_designs"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("repo")
    ap.add_argument("tier", choices=sorted(TIER_DIR))
    ap.add_argument("name")
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    ap.add_argument("--author", default="James (IrwinJam)")
    ap.add_argument("--url", default="https://github.com/IrwinJam/m3d-router")
    a = ap.parse_args()
    sys.path.insert(0, a.repo)
    from m3d.model import Instance, Submission
    from m3d.checker import check

    suite_dir = os.path.join(a.repo, TIER_DIR[a.tier])
    suite = json.load(open(os.path.join(suite_dir, "suite.json")))
    dest = os.path.join(a.repo, "submissions", a.tier, a.name)
    os.makedirs(dest, exist_ok=True)
    runtime = {}
    for c in suite["cases"]:
        name = c["name"]
        sol = os.path.join(a.out_dir, f"{name}.sol.json")
        res = check(Instance.load(os.path.join(suite_dir, c["instance_file"])), Submission.load(sol))
        if not res.legal:
            sys.exit(f"{name}: not legal, refusing to pack")
        shutil.copyfile(sol, os.path.join(dest, f"{name}.sol.json"))
        rts = sorted(glob.glob(os.path.join(a.out_dir, f"{name}.runtime*")), key=os.path.getmtime)
        if rts:
            runtime[name] = round(float(open(rts[-1]).read()), 2)
        print(f"{name}: total={res.total_delay} baseline={c['baseline_total']} "
              f"ratio={c['baseline_total'] / res.total_delay:.4f}")
    with open(os.path.join(dest, "runtime.json"), "w") as fh:
        json.dump(runtime, fh, indent=1)
    meta = {
        "author": a.author,
        "url": a.url,
        "method": ("Source-aware shortest-path-tree nets + slow fanout-scaled negotiated "
                   "congestion (PathFinder) + per-net exact SPT refinement + annealed "
                   "large-neighbourhood search with ideal-tree and window moves (numba)"),
        "date": a.date,
    }
    with open(os.path.join(dest, "meta.json"), "w") as fh:
        json.dump(meta, fh, indent=1)
    print("packed ->", dest)


if __name__ == "__main__":
    main()
