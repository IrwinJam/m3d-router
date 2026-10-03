# m3d-router

My router for the [Partcl M3D routing challenge](https://github.com/partcleda/eda-3d-routing-challenge):
connect pins between two stacked dies through a 3D grid of routing layers, keep
every net legal, and minimize total delay.

## Results

Score = geometric mean of `baseline_delay / my_delay` from the challenge's own
scorer (baseline = 1.0, higher is better). All 45 cases legal.

| tier | score | best on `main` |
|---|---:|---:|
| intro | **1.1444** | 1.1514 |
| hard | **1.3971** | 1.3884 |
| scale | **1.1188** | 1.1277 |
| stress | **1.0779** | 1.0914 |
| congested | **1.3069** | 1.3111 |
| designs | **1.4237** | 1.4354 |

Scores are from my latest update (submitted 3 Oct 2026, pending merge). On hard it
beats every entry merged so far, and my routes are my own router's work throughout.
I also got a
[Windows fix](https://github.com/partcleda/eda-3d-routing-challenge/pull/13)
merged into the challenge toolkit.

## Key idea

The score adds up the delay from each net's driver to every sink. The reference
routers attach each sink to the *nearest point* of the tree, which minimizes wire
length, not delay. For a single net, the best possible tree is a
**shortest-path tree** from the driver, so that is what I build. The real
challenge is then congestion: every net wants the fast middle layers.

## Method

1. **Shortest-path trees.** Each sink is routed with A\* from the existing tree,
   starting each tree point at its real delay from the driver (not 0).
2. **Slow negotiation.** Nets start overlapping and gradually pay more to share
   space until none do (PathFinder). A slow schedule gave much better results,
   and scaling congestion cost by `sinks^-0.5` lets high-fanout nets keep the fast
   layers.
3. **Refinement.** Each net is rerouted optimally with all others fixed.
4. **Neighbourhood search.** Rip up a badly routed net plus the nets around it,
   rebuild them, and keep the change if total delay drops.

Python with numba, run on a 12-thread desktop.

## What I learned

* Measure first: a congestion-free ceiling showed congestion, not single-net
  routing, was the real problem.
* A walled-in net can loop forever in PathFinder; capping the congestion penalty fixed it.
* Spreading compute evenly stalls; focusing every core on the few cases with the
  biggest gap, with many fresh restarts, took hard from 1.3845 to 1.3971 overnight.

## Usage

```bash
pip install -r requirements.txt
python run_suite.py ../eda-3d-routing-challenge/benchmarks_hard out/hard --time 600
```

Needs Python 3.9+ and the challenge repo cloned next to this one.

## License

MIT
