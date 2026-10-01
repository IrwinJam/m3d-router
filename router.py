"""Delay-driven negotiated router + large-neighbourhood search for the M3D challenge.

Pipeline per case:
  1. negotiate: PathFinder congestion negotiation, but every net is grown as a
     source-aware tree (each sink minimizes its own driver->sink cost) instead of
     a nearest-point Steiner tree, because the objective is the SUM of sink path
     delays, not wirelength.
  2. refine: with all other nets fixed as hard obstacles, reroute each net as an
     exact shortest-path tree (optimal for that net); keep if better.
  3. lns: repeatedly rip up a net that is far from its ideal delay together with
     the nets blocking its ideal tree, renegotiate just that neighbourhood with
     everything else fixed, refine, and keep the result only if total delay drops.
"""
import numpy as np

from core import route_net, make_VA


class Router:
    def __init__(self, inst, seed=0):
        self.inst = inst
        self.rng = np.random.default_rng(seed)
        g = inst["grid"]
        self.W, self.H, self.L = g["width"], g["height"], g["layers"]
        self.N = N = self.W * self.H * self.L
        self.ld = np.array(inst["delay"]["layer_delay"], np.float64)
        self.via = float(inst["delay"]["via_delay"])
        W, H = self.W, self.H
        vid = {p["id"]: (p["z"] * H + p["y"]) * W + p["x"] for p in inst["pins"]}
        self.pin_net = np.full(N, -1, np.int64)
        self.net_pins = []
        for i, n in enumerate(inst["nets"]):
            pv = np.array([vid[n["driver"]]] + [vid[s] for s in n["sinks"]], np.int64)
            self.net_pins.append(pv)
            self.pin_net[pv] = i
        self.nnets = len(self.net_pins)
        # scratch
        self.dist = np.zeros(N, np.float64)
        self.prev = np.zeros(N, np.int64)
        self.stamp = np.zeros(N, np.int64)
        self.tstamp = np.zeros(N, np.int64)
        self.tdel = np.zeros(N, np.float64)
        self.tpar = np.zeros(N, np.int64)
        self.hk = np.zeros(6 * N + 16, np.float64)
        self.hv = np.zeros(6 * N + 16, np.int64)
        self.ctr = np.zeros(1, np.int64)
        self.outv = np.zeros(N, np.int64)
        self.closed = np.zeros(N, np.int64)
        self.VA = make_VA(self.L, self.via)
        self.zeros_i = np.zeros(N, np.int64)
        self.zeros_f = np.zeros(N, np.float64)
        self.reset()
        # congestion-free ideal (only foreign pins block): per-net lower bound + ideal tree
        self.ideal = [self._route(i, self.zeros_i) for i in range(self.nnets)]
        self.lb = np.array([r[2] for r in self.ideal])

    def reset(self):
        self.occ = np.zeros(self.N, np.int64)
        self.hist = np.zeros(self.N, np.float64)
        self.routes = [None] * self.nnets   # (verts, parents, delay)

    def bbox(self, i):
        v = self.net_pins[i]
        z, r = np.divmod(v, self.W * self.H)
        y, x = np.divmod(r, self.W)
        return (x.max() - x.min()) + (y.max() - y.min()) + (z.max() - z.min())

    def default_order(self):
        return sorted(range(self.nnets), key=lambda i: (-self.bbox(i), i))

    # ------------------------------------------------------------------
    def _route(self, i, block, occ=None, hist=None, pres=0.0, vcost=0.0, alpha=1.0):
        if occ is None:
            occ, hist = self.zeros_i, self.zeros_f
        n, d = route_net(self.W, self.H, self.L, self.ld, self.via, self.pin_net, i,
                         self.net_pins[i], block, occ, hist, pres, vcost,
                         self.dist, self.prev, self.stamp, self.tstamp, self.tdel,
                         self.tpar, self.hk, self.hv, self.ctr, self.outv, alpha,
                         self.closed, self.VA)
        if n < 0:
            return None
        v = self.outv[:n].copy()
        return v, self.tpar[v].copy(), d

    def _add(self, i, r):
        self.routes[i] = r
        self.occ[r[0]] += 1

    def _rem(self, i):
        r = self.routes[i]
        self.occ[r[0]] -= 1
        self.routes[i] = None
        return r

    def total(self):
        return sum(r[2] for r in self.routes)

    def legal(self):
        return all(r is not None for r in self.routes) and self.occ.max() <= 1

    # ------------------------------------------------------------------
    def negotiate(self, order, pres0=0.5, mult=1.5, hist_fac=1.0, vcost=3.0,
                  alpha=1.0, max_iters=300, pres_max=4.0, full_every=0,
                  legalize_at=0, legalize_every=10):
        self.reset()
        return self._negotiate(order, self.zeros_i, self.occ, self.hist, pres0, mult,
                               hist_fac, vcost, alpha, max_iters, pres_max, full_every,
                               legalize_at, legalize_every)

    def _try_legalize(self, order, over):
        """Rip up every net on an overused vertex and reroute them in hard mode
        (others fixed). Returns True and keeps the result if all succeed."""
        bad = [i for i in order if over[self.routes[i][0]].any()]
        saved = {i: self.routes[i] for i in bad}
        for i in bad:
            self._rem(i)
        done = []
        for i in bad:
            r = self._route(i, self.occ)
            if r is None:
                for j in done:
                    self._rem(j)
                for j in bad:
                    self._add(j, saved[j])
                return False
            self._add(i, r)
            done.append(i)
        return True

    def _negotiate(self, order, block, occ, hist, pres0, mult, hist_fac, vcost, alpha,
                   max_iters, pres_max, full_every, legalize_at=0, legalize_every=10):
        """Negotiate the nets in `order` with `block` fixed. `occ` counts only the
        negotiated nets (self.occ is kept in sync when occ is self.occ)."""
        pres = pres0
        sep = occ is not self.occ
        def add(i, r):
            self.routes[i] = r; occ[r[0]] += 1
            if sep: self.occ[r[0]] += 1
        def rem(i):
            r = self.routes[i]; occ[r[0]] -= 1
            if sep: self.occ[r[0]] -= 1
            self.routes[i] = None
        for i in order:
            r = self._route(i, block, occ, hist, pres, vcost, alpha)
            if r is None:
                return -1
            add(i, r)
        for it in range(max_iters):
            over = occ > 1
            if not over.any():
                return it
            if (legalize_at and not sep and it % legalize_every == 0
                    and over.sum() <= legalize_at and self._try_legalize(order, over)):
                return it
            hist[over] += hist_fac * (occ[over] - 1)
            pres = min(pres * mult, pres_max)
            full = full_every > 0 and (it + 1) % full_every == 0
            for i in order:
                if full or over[self.routes[i][0]].any():
                    rem(i)
                    r = self._route(i, block, occ, hist, pres, vcost, alpha)
                    if r is None:
                        return -1
                    add(i, r)
        return -1 if (occ > 1).any() else max_iters

    def refine(self, order, max_passes=20):
        """Hard-mode exact SPT reroute of each net; accept strict improvements."""
        for _ in range(max_passes):
            improved = False
            for i in order:
                old = self._rem(i)
                new = self._route(i, self.occ)
                if new is not None and (new[2] < old[2] - 1e-6 or
                                        (abs(new[2] - old[2]) < 1e-6 and len(new[0]) < len(old[0]))):
                    self._add(i, new)
                    improved = improved or new[2] < old[2] - 1e-6
                else:
                    self._add(i, old)
            if not improved:
                break

    # ------------------------------------------------------------------
    def lns(self, iters=2000, max_set=12, neg_iters=60, time_limit=None,
            neg_kw=None, verbose=False, p_seq=0.5, refine_passes=2,
            T0=0.0, T1=0.0):
        """Large-neighbourhood search. Moves: rip up a high-excess seed net plus the
        nets blocking its ideal tree; rebuild either (a) sequentially, seed first as an
        exact SPT, or (b) by negotiating the set; refine; accept by annealing on the
        change in total delay (T0->T1 geometric schedule over the time budget, 0 =
        strict descent). The best solution seen is restored at the end."""
        import time
        t0 = time.time()
        neg_kw = dict(pres0=0.5, mult=1.5, hist_fac=1.0, vcost=3.0, alpha=1.0,
                      pres_max=4.0, full_every=0) | (neg_kw or {})
        owner = np.full(self.N, -1, np.int64)
        for i, r in enumerate(self.routes):
            owner[r[0]] = i
        cur = self.total()
        best = cur
        best_routes = list(self.routes)
        self.stats = dict(fail=0, worse=0, acc=0, uphill=0, seq=0, neg=0)
        rng = self.rng
        for it in range(iters):
            el = time.time() - t0
            if time_limit and el > time_limit:
                break
            frac = el / time_limit if time_limit else it / iters
            T = T0 * (T1 / T0) ** frac if T0 > 0 and T1 > 0 else T0 * (1 - frac)
            delays = np.array([r[2] for r in self.routes])
            excess = delays - self.lb
            if excess.sum() <= 1e-6:
                break
            p = excess + 0.05 * excess.mean() + 1e-9
            seed = int(rng.choice(self.nnets, p=p / p.sum()))
            S = [seed]
            cand = [int(b) for b in np.unique(owner[self.ideal[seed][0]]) if b >= 0 and b != seed]
            rng.shuffle(cand)
            S += cand[:max_set - 1]
            if len(S) < max_set and rng.random() < 0.5:
                for b in list(S[1:]):
                    for m in np.unique(owner[self.ideal[b][0]]):
                        m = int(m)
                        if m >= 0 and m not in S and len(S) < max_set:
                            S.append(m)
            old = {i: self.routes[i] for i in S}
            old_sum = sum(r[2] for r in old.values())
            for i in S:
                self._rem(i)
                owner[old[i][0]] = -1
            rest = S[1:]
            rng.shuffle(rest)
            ok = False
            if rng.random() < p_seq:
                # (a) sequential: seed first as exact SPT, then the rest greedily
                self.stats['seq'] += 1
                ok = True
                for i in [S[0]] + rest:
                    r = self._route(i, self.occ)
                    if r is None:
                        ok = False
                        break
                    self._add(i, r)
            if not ok:
                for i in S:
                    if self.routes[i] is not None:
                        self._rem(i)
                self.stats['neg'] += 1
                order = [S[0]] + rest if rng.random() < 0.5 else rng.permutation(S).tolist()
                block = self.occ.copy()
                subocc = np.zeros(self.N, np.int64)
                subhist = np.zeros(self.N, np.float64)
                kw = dict(neg_kw)
                kw["vcost"] = kw["vcost"] * float(rng.choice([0.5, 1.0, 2.0]))
                ok = self._negotiate(order, block, subocc, subhist, max_iters=neg_iters, **kw) >= 0
                if not ok:
                    self.stats['fail'] += 1
            if ok:
                for _ in range(refine_passes):
                    imp = False
                    for i in S:
                        o = self._rem(i)
                        n = self._route(i, self.occ)
                        if n is not None and n[2] < o[2] - 1e-6:
                            self._add(i, n); imp = True
                        else:
                            self._add(i, o)
                    if not imp:
                        break
                new_sum = sum(self.routes[i][2] for i in S)
                delta = new_sum - old_sum
                if delta < -1e-6:
                    pass
                elif T > 0 and delta > 1e-6 and rng.random() < np.exp(-delta / T):
                    self.stats['uphill'] += 1
                elif abs(delta) <= 1e-6 and rng.random() < 0.5:
                    pass                                   # sideways move
                else:
                    ok = False
                    self.stats['worse'] += 1
            if ok:
                for i in S:
                    owner[self.routes[i][0]] = i
                cur += new_sum - old_sum
                self.stats['acc'] += 1
                if cur < best - 1e-6:
                    best = cur
                    best_routes = list(self.routes)
            else:
                for i in S:
                    if self.routes[i] is not None:
                        self._rem(i)
                for i in S:
                    self._add(i, old[i])
                    owner[old[i][0]] = i
            if verbose and it % 200 == 0:
                print(f"  lns {it} cur={cur:.0f} best={best:.0f} T={T:.2f} {self.stats} t={time.time()-t0:.1f}s", flush=True)
        # restore best
        for i in range(self.nnets):
            self._rem(i)
        for i in range(self.nnets):
            self._add(i, best_routes[i])
        return self.total()

    # ------------------------------------------------------------------
    def solution(self):
        W, H = self.W, self.H
        def c(v):
            z, r = divmod(int(v), W * H)
            y, x = divmod(r, W)
            return [x, y, z]
        routes = []
        for i, n in enumerate(self.inst["nets"]):
            verts, par, _ = self.routes[i]
            edges = [[c(p), c(v)] for v, p in zip(verts, par) if p >= 0]
            routes.append({"net": n["id"], "edges": edges})
        return {"format": "m3d-submission", "version": 1,
                "instance": self.inst["name"], "routes": routes}
