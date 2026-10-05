# m3d-router

My router for the [Partcl M3D routing challenge](https://github.com/partcleda/eda-3d-routing-challenge).
Route wires between two stacked chips through a 3D grid, keep every wire legal, and
get the total delay as low as possible.

## Results

Score is `baseline delay / my delay`, averaged across cases (1.0 = baseline, higher
is better). All 45 cases are legal.

| tier | score |
|---|---:|
| intro | **1.1444** |
| hard | **1.3971** |
| scale | **1.1188** |
| stress | **1.0779** |
| congested | **1.3156** |
| designs | **1.4347** |

Briefly held the top hard-tier score of any submission.

## How it works

The score adds up the delay to every sink, not the total wire length. The reference
routers build minimum-wire trees, so I build each net as a shortest-path tree instead,
where every sink gets its own fastest path from the driver. After that it's all about
congestion, since every net wants the fast middle layers:

1. **Negotiate.** Let nets overlap, then slowly raise the cost of sharing until none do.
   Nets with more sinks get priority on the fast layers.
2. **Refine.** Reroute each net optimally with everything else fixed.
3. **Search.** Rip up a badly routed net plus its neighbours, rebuild them, keep it if
   the total drops. Run this for hours with lots of fresh restarts.

## Hardware

Everything ran on my desktop: an AMD Ryzen 5 7500F (6 cores, 12 threads). About 300
thread-hours in total over three nights. Python with numba, no GPU.

## Usage

```bash
pip install -r requirements.txt
python run_suite.py ../eda-3d-routing-challenge/benchmarks_hard out/hard --time 600
```

Needs Python 3.9+ and the challenge repo cloned next to this one.

## License

MIT
