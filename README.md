# m3d-router

A router for the [Partcl M3D routing challenge](https://github.com/partcleda/eda-3d-routing-challenge):
connect cell pins between two stacked dies through a shared stack of routing
layers, keep every net legal, and minimize total delay.

## Results

Score = geometric mean over cases of `baseline_delay / my_delay`, computed by the
challenge's own checker and scorer (baseline = 1.0, higher is better). All 45 cases
are legal.

| tier | cases | score | rank | #1 | congestion-free ceiling |
|---|---:|---:|---:|---:|---:|
| intro | 20 | **1.1444** | 4 | 1.1514 | 1.187 |
| hard | 9 | **1.3845** | 4 | 1.3884 | 1.762 |
| scale | 8 | **1.1188** | 4 | 1.1277 | 1.162 |
| stress | 1 | **1.0779** | 4 | 1.0914 | 1.105 |
| congested | 4 | **1.3069** | 3 | 1.3111 | 1.647 |
| designs (real EPFL circuits) | 3 | **1.4237** | 4 | 1.4354 | 1.811 |

Ranks are where these scores place on the challenge leaderboard (update submitted
2 October 2026; an earlier version of this entry is already merged). On every tier the
only independent entry ahead of this one is #1; the other entries above it are
marked on the leaderboard as derivatives that start from #1's routes. The
"ceiling" is what you would get if every net were routed as if it were alone on
the grid. No legal solution can reach it, but it shows how much congestion costs.

I also fixed a bug in the challenge toolkit along the way: the leaderboard tools
crashed on Windows because Markdown files were read and written with the default
cp1252 encoding ([merged](https://github.com/partcleda/eda-3d-routing-challenge/pull/13)).

## The problem in one paragraph

Routing happens on a 3D grid. Bottom-die pins sit on layer 0, top-die pins on the
top layer, and wire delay per step is lowest on the middle layers and highest next
to the dies. Each grid vertex can belong to at most one net, and a net must be a
tree from its driver to all its sinks. The score adds up, for every sink, the
delay of its path from the driver, so a shared wire counts once per sink that uses it.

## Key observation

Both reference routers grow a net Prim-style: they attach each new sink to the
**nearest point of the tree built so far** (a multi-source Dijkstra seeded at
distance 0). That minimizes wirelength, but the score is not wirelength. A sink
hung off the tip of a branch pays for every detour that branch took.

For a single net with everything else held fixed, the score is minimized
exactly by a **shortest-path tree** from the driver: every sink can reach its own
shortest distance at the same time. So the right building block is "give every
sink its shortest path", and the hard part is the competition between nets for the
cheap middle layers.

Measuring this first told me where the room was. Even ignoring congestion
completely, the best possible score is about 1.19 on the sparse intro tier but
1.65 to 1.81 on the contended tiers, so the real problem is congestion.

## Method

1. **Source-aware tree growth** (`core.py`). Each net is grown sink by sink. Every
   search is seeded from each tree vertex at its *true delay from the driver*
   instead of 0, so each sink is attached to minimize its own driver-to-sink
   delay. With obstacles fixed this gives an exact shortest-path tree. A tiny
   per-vertex cost breaks ties toward trees that use fewer grid vertices, which
   leaves more room for other nets.

2. **A\* search with an exact free-space heuristic.** For a vertex on layer `z` and a
   sink on layer `zt` at xy distance `d`, the cheapest obstacle-free path goes to
   some travel layer `m` and does all its horizontal steps there:
   `h = min over m of via*(|z-m| + |m-zt|) + layer_delay[m]*d`.
   This is consistent, so results stay exact. Equal-cost ties go to deeper nodes,
   so the search does not flood the whole rectangle of equally short staircase paths.

3. **Slow, fanout-scaled negotiation** (PathFinder). Nets may overlap at first and
   pay growing present and history penalties until no vertex is shared. Two things
   mattered a lot:
   * **A slow schedule.** Raising the pressure gently (x1.03 per round) gave much
     better legal starting points than an aggressive one (on the largest congested case:
     ratio 1.20 from negotiation alone, versus 1.05 from a fast schedule plus two
     minutes of search).
   * **Fanout scaling.** Each net's congestion cost is scaled by
     `sinks^-0.5`. A trunk wire is shared by every downstream sink, so nets with
     many sinks should win the contested middle layers. This improved starting
     solutions by about 3%.

   I also hit a deadlock: a net walled in by other nets kept choosing the one
   contested vertex forever, because crossing two other nets always cost more,
   and history penalties grow too slowly to catch up with an exponentially
   growing present factor. Capping the present factor fixed it.

4. **Exact refinement.** With all other nets fixed, each net is rerouted as an exact
   shortest-path tree (optimal for that net) and kept if its delay drops, repeated
   until nothing improves.

5. **Large-neighbourhood search.** Repeatedly pick a net that is far above its own
   congestion-free delay, rip it up together with either the nets sitting on its
   ideal tree or every net crossing a small window around a point on its route,
   rebuild that group (sequentially or with a local negotiation), refine, and
   accept the result by simulated annealing on the change in total delay. The best
   solution seen is always kept. The window moves roughly tripled the improvement
   rate.

6. **Long runs.** `overnight.py` keeps the best legal solution for every case and
   has parallel workers continue from it (or occasionally restart from scratch),
   writing back only results the official checker confirms are legal and better.

Everything is Python with the hot loop compiled by numba, run on a 12-thread desktop.

## What did not help

* **More time at the end.** By the last run, five extra minutes of search from the
  best solutions improved them by about 0.01%. The search had converged rather than
  run out of time.
* **A faster heuristic.** Precomputing the A\* heuristic as a lookup table gave
  identical routes but only about 6% more speed; the cost is in the expansions,
  not the heuristic.
* **Early legalization.** Forcing the last few conflicts out of negotiation early
  made it finish faster but gave worse starting solutions.
* **Fresh restarts on the largest case.** On the 530x530 stress case, restarting
  from scratch always landed worse than continuing from the best solution.

Closing the last 0.3 to 1.2% to #1 would likely need a different kind of move,
for example solving small windows exactly with an integer program, rather than
more of the same search.

## Usage

Needs Python 3.9+, `pip install -r requirements.txt` (numpy, numba), and the
challenge repo cloned next to this one (or set `M3D_REPO` to its path).

```bash
# route every case of a tier in parallel, 10 minutes per case
python run_suite.py ../eda-3d-routing-challenge/benchmarks_hard out/hard --time 600

# score with the challenge's own scorer
cd ../eda-3d-routing-challenge
python -m m3d.cli score-suite --suite benchmarks_hard --submission-dir ../m3d-router/out/hard
```

For long runs that keep improving the best solution per case, put the current
solutions in `out/<tier>/` and run `python overnight.py --hours 8 --best-root out`.

## Files

| file | what it does |
|---|---|
| `core.py` | numba kernel: A\*-guided shortest-path-tree routing of one net |
| `router.py` | negotiation, exact refinement, large-neighbourhood search, load/save |
| `run_suite.py` | routes every case of a tier in parallel and keeps the best legal result |
| `overnight.py` | long multi-worker improvement run across all tiers |
| `pack_submission.py` | builds a `submissions/<tier>/<name>/` folder for the leaderboard |

## License

MIT
