# m3d-router

A delay-driven 3D router for the [Partcl M3D routing challenge](https://github.com/partcleda/eda-3d-routing-challenge):
connect cell pins between two face-to-face dies through a shared stack of routing
layers, keep every net legal (one net per grid vertex/edge, no routing through
foreign pins), and minimize **total driver→sink delay**.

## Results

Aggregate = geometric mean over cases of `baseline_total / my_total` (baseline = 1.0,
higher is better), computed by the challenge's own checker and scorer. "Ceiling" is
the congestion-free bound: every net routed as if it were alone on the grid, which
no legal solution can beat.

| tier | cases | aggregate | ceiling | best previous entry | time / case |
|---|---:|---:|---:|---:|---|
| intro | 20 | **1.1383** | 1.187 | 1.0000 (baseline) | 5 min |
| hard | 9 | **1.3609** | 1.762 | 1.0168 (`negotiated_x2`) | best of 10 + 20 min runs |
| scale | 8 | **1.1143** | 1.162 | 1.0000 (baseline) | 10 min |
| stress | 1 | **1.0763** | 1.105 | 1.0000 (baseline) | 60 min (baseline: ~33 min) |
| congested | 4 | **1.2625** | 1.647 | 1.0000 (baseline) | 40 min |
| designs (real EPFL circuits) | 3 | **1.3867** | 1.811 | 1.0000 (baseline) | 40 min |

All 45 cases are legal. Runs used 12 CPU threads on a desktop, one case per process.

## Key observation

The score charges every sink its full driver→sink path delay. Both reference
routers grow each net Prim-style, attaching the next sink to the *nearest* point of
the partial tree (multi-source Dijkstra seeded at distance 0). That minimizes
wirelength, but a sink hung off a branch tip pays for the detour the branch took.

For a single net with every other net held fixed, the objective is minimized
exactly by a **shortest-path tree** from the driver: every sink can reach its own
shortest distance simultaneously. Everything below is built around that.

## Method

1. **Source-aware tree growth** (`core.py::route_net`). Each net is grown sink by
   sink with a multi-source search seeded at every tree vertex with its *true
   delay from the driver* (not 0). In hard mode this returns an exact
   shortest-path tree, i.e. the optimal tree for that net given the obstacles.
   A tiny per-vertex epsilon breaks ties toward trees that use fewer resources.
2. **A\*** with an exact obstacle-free heuristic:
   `h = min over layers m of via·(|z−m| + |m−z_t|) + layer_delay[m]·manhattan_xy`
   (to the nearest unreached sink). It is consistent, so optimality is kept; ties
   go to deeper nodes so the search does not flood equal-cost staircase regions.
3. **Slow negotiated congestion** (PathFinder). Nets temporarily overlap and pay
   rising present and history penalties until no vertex is shared. A gentle
   schedule (present factor ×1.03 per iteration, capped; small history increments)
   gives much better legal starting points than a fast one. The cap prevents the
   deadlock where a net walled in by other nets keeps choosing the one contested
   vertex forever.
4. **Exact refinement.** With all other nets fixed, each net is rerouted as an exact
   shortest-path tree and kept if its delay drops. Repeated until stable.
5. **Large-neighbourhood search.** Pick a net with high excess over its own
   congestion-free ideal, rip it up together with the nets occupying its ideal
   tree (≤ 6 nets), rebuild that neighbourhood (sequentially seed-first, or by a
   local negotiation with everything else fixed), refine, and accept by simulated
   annealing on the change in total delay. The best solution seen is kept.

Every emitted solution is re-verified with the challenge's independent checker
before it is written.

## Usage

Requires Python 3.9+, `numpy` and `numba` (`pip install -r requirements.txt`), and a
checkout of the challenge repo next to this one (or point `M3D_REPO` at it).

```bash
# route every case of a tier in parallel; repeated runs only ever keep improvements
python run_suite.py ../eda-3d-routing-challenge/benchmarks_hard out/hard --time 600 --jobs 9

# score with the official scorer
cd ../eda-3d-routing-challenge
python -m m3d.cli score-suite --suite benchmarks_hard --submission-dir ../m3d-router/out/hard

# package as a leaderboard submission
python pack_submission.py out/hard ../eda-3d-routing-challenge hard spt_lns
```

`--time` is the wall-clock budget per case (negotiation + LNS). Grids over 500k
vertices (the stress tier) use the fast negotiation schedule.

## Files

| file | what |
|---|---|
| `core.py` | numba kernel: A\*-guided source-aware tree routing with hard/soft occupancy |
| `router.py` | negotiation, exact refinement, large-neighbourhood search, solution export |
| `run_suite.py` | parallel per-case driver with checker verification, keeps best |
| `pack_submission.py` | builds `submissions/<tier>/<name>/` for a leaderboard PR |

## License

MIT
