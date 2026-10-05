"""Numba kernels: source-aware (shortest-path-tree) net routing on the 3D grid.

Vertex id: vid = (z*H + y)*W + x.  Capacity is per vertex only: two nets cannot
share an edge without sharing its endpoint vertices, so vertex capacity implies
edge capacity.
"""
import numpy as np
from numba import njit

INF = 1e300
EPS = 1e-4  # per-new-vertex tie-break: among equal-delay trees prefer fewer resources
TB = 1e-9   # heap tie-break: among equal f prefer deeper nodes (larger g)


@njit(cache=True, inline='always')
def _push(hk, hv, n, key, val):
    i = n
    while i > 0:
        p = (i - 1) >> 1
        if hk[p] > key:
            hk[i] = hk[p]; hv[i] = hv[p]; i = p
        else:
            break
    hk[i] = key; hv[i] = val
    return n + 1


@njit(cache=True, inline='always')
def _pop(hk, hv, n):
    n -= 1
    if n > 0:
        k = hk[n]; v = hv[n]; i = 0
        while True:
            c = 2 * i + 1
            if c >= n:
                break
            if c + 1 < n and hk[c + 1] < hk[c]:
                c += 1
            if hk[c] < k:
                hk[i] = hk[c]; hv[i] = hv[c]; i = c
            else:
                break
        hk[i] = k; hv[i] = v
    return n


@njit(cache=True, inline='always')
def _h(v, W, WH, L, ld, VA, sx, sy, sz, alive, np_):
    z = v // WH; r = v - z * WH; y = r // W; x = r - y * W
    best = 1e300
    for i in range(1, np_):
        if not alive[i]:
            continue
        dxy = abs(x - sx[i]) + abs(y - sy[i])
        zt = sz[i]
        for m in range(L):
            c = VA[z, zt, m] + (ld[m] + EPS) * dxy
            if c < best:
                best = c
    return best


def make_VA(L, via):
    VA = np.zeros((L, L, L), np.float64)
    for z in range(L):
        for zt in range(L):
            for m in range(L):
                VA[z, zt, m] = (via + EPS) * (abs(z - m) + abs(m - zt))
    return VA


@njit(cache=True)
def route_net(W, H, L, ld, via, pin_net, nid, pins, block, occ, hist, pres, vcost,
              dist, prev, stamp, tstamp, tdel, tpar, hk, hv, ctr, outv,
              alpha, closed, VA):
    """Route one net as a source-aware tree.

    Seeds every multi-source Dijkstra round with each tree vertex at its true
    driver delay (scaled by alpha), so each sink is attached minimizing its own
    driver->sink path cost.  alpha=1 gives an exact shortest-path tree in hard
    mode; alpha<1 trades sink delay for shorter (less congesting) trees.

    A* guided: h(v) = exact obstacle-free delay to the nearest remaining sink,
    min over layers m of VA[z,zt,m] + ld[m]*manhattan  (VA = via*(|z-m|+|m-zt|)).
    Consistent, so each sink is still reached at its optimal cost.

    Returns (n_vertices, net_delay); vertices written to outv[:n] with the
    tree parent of each non-driver vertex in tpar.  n=-1 on failure.
    """
    WH = W * H
    driver = pins[0]
    ctr[0] += 1
    tg = ctr[0]                      # tree tag for this call
    nt = 0
    outv[nt] = driver; nt += 1
    tstamp[driver] = tg
    tdel[driver] = 0.0
    nrem = len(pins) - 1
    # mark remaining sinks via tstamp=-tg
    for i in range(1, len(pins)):
        tstamp[pins[i]] = -tg
    total = 0.0
    tpar[driver] = -1
    np_ = len(pins)
    sx = np.empty(np_, np.int64); sy = np.empty(np_, np.int64); sz = np.empty(np_, np.int64)
    alive = np.zeros(np_, np.bool_)
    for i in range(1, np_):
        p = pins[i]
        sz[i] = p // WH; rr = p - sz[i] * WH; sy[i] = rr // W; sx[i] = rr - sy[i] * W
        alive[i] = True
    while nrem > 0:
        ctr[0] += 1
        s = ctr[0]
        n = 0
        for i in range(nt):
            v = outv[i]
            stamp[v] = s
            k = alpha * tdel[v]
            dist[v] = k
            prev[v] = -1
            n = _push(hk, hv, n, k * (1.0 - TB) + _h(v, W, WH, L, ld, VA, sx, sy, sz, alive, np_), v)
        found = -1
        while n > 0:
            u = hv[0]
            n = _pop(hk, hv, n)
            if closed[u] == s:
                continue
            closed[u] = s
            if tstamp[u] == -tg:
                found = u
                break
            d = dist[u]
            z = u // WH; r = u - z * WH; y = r // W; x = r - y * W
            for m in range(6):
                if m == 0:
                    if x + 1 >= W: continue
                    v = u + 1; w = ld[z]
                elif m == 1:
                    if x == 0: continue
                    v = u - 1; w = ld[z]
                elif m == 2:
                    if y + 1 >= H: continue
                    v = u + W; w = ld[z]
                elif m == 3:
                    if y == 0: continue
                    v = u - W; w = ld[z]
                elif m == 4:
                    if z + 1 >= L: continue
                    v = u + WH; w = via
                else:
                    if z == 0: continue
                    v = u - WH; w = via
                if tstamp[v] == tg:
                    continue                      # own tree vertex: would cycle
                pn = pin_net[v]
                if pn >= 0 and pn != nid:
                    continue                      # another net's pin
                if block[v] > 0:
                    continue                      # hard obstacle (fixed net)
                nd = d + w + vcost * (hist[v] + pres * occ[v]) + EPS
                if stamp[v] != s or nd < dist[v]:
                    if stamp[v] == s and closed[v] == s:
                        continue
                    stamp[v] = s
                    dist[v] = nd
                    prev[v] = u
                    n = _push(hk, hv, n, nd * (1.0 - TB) + _h(v, W, WH, L, ld, VA, sx, sy, sz, alive, np_), v)
        if found < 0:
            return -1, 0.0
        # walk back to the tree, collect path
        path_start = nt
        cur = found
        while tstamp[cur] != tg:
            outv[nt] = cur; nt += 1
            cur = prev[cur]
        # cur is the attach point; assign true delays forward along the path
        base = tdel[cur]
        # path is outv[path_start:nt] from sink back to attach point; reverse walk
        acc = base
        last = cur
        for i in range(nt - 1, path_start - 1, -1):
            v = outv[i]
            # delay of edge last->v
            if v - last == WH or last - v == WH:
                acc += via
            else:
                acc += ld[v // WH]
            tdel[v] = acc
            tpar[v] = last
            tstamp[v] = tg
            last = v
        total += tdel[found]
        nrem -= 1
        for i in range(1, np_):
            if pins[i] == found:
                alive[i] = False
    return nt, total




# ---------------------------------------------------------------------------
# Integer bucket-queue variant (Dial's algorithm with A*).
#
# Costs are integers in units of 1/S delay. In exact (hard) mode every edge cost is
# delay*S, so results are exact; congestion terms in soft mode are rounded to the
# same grid and clamped to CLAMP units so live keys always fit in the circular
# bucket array. Ties within a bucket pop newest-first (deeper nodes first); a
# secondary vertex-count label prefers equal-delay paths that use fewer vertices.
# ---------------------------------------------------------------------------

S_UNITS = 4
NBUCKET = 1 << 15
CLAMP = NBUCKET // 2


def make_HTi(L, via, ld, D, S=S_UNITS):
    """Integer heuristic table: exact obstacle-free delay (x S) from layer z to a
    target on layer zt at xy-manhattan distance d."""
    d = np.arange(D + 1, dtype=np.int64)
    HT = np.full((L, L, D + 1), np.iinfo(np.int64).max // 4, np.int64)
    for z in range(L):
        for zt in range(L):
            for m in range(L):
                c = S * (int(via) * (abs(z - m) + abs(m - zt)) + int(ld[m]) * d)
                HT[z, zt] = np.minimum(HT[z, zt], c)
    return HT


@njit(cache=True, inline='always')
def _hi(v, W, WH, HT, sx, sy, sz, alive, np_):
    z = v // WH; r = v - z * WH; y = r // W; x = r - y * W
    best = np.iinfo(np.int64).max
    for i in range(1, np_):
        if not alive[i]:
            continue
        c = HT[z, sz[i], abs(x - sx[i]) + abs(y - sy[i])]
        if c < best:
            best = c
    return best


@njit(cache=True)
def route_net_b(W, H, L, ld, via, pin_net, nid, pins, block, occ, hist, pres, vcost,
                dist, cnt, prev, stamp, tstamp, tdel, tpar, ctr, outv, closed, HT,
                bhead, bstamp, ev, eg, enext):
    """Same contract as route_net (alpha = 1), using an integer bucket queue.

    Returns (n_vertices, net_delay); vertices in outv[:n], tree parents in tpar.
    """
    S = S_UNITS
    MASK = NBUCKET - 1
    WH = W * H
    driver = pins[0]
    ctr[0] += 1
    tg = ctr[0]
    nt = 0
    outv[nt] = driver; nt += 1
    tstamp[driver] = tg
    tdel[driver] = 0.0
    tpar[driver] = -1
    np_ = len(pins)
    nrem = np_ - 1
    sx = np.empty(np_, np.int64); sy = np.empty(np_, np.int64); sz = np.empty(np_, np.int64)
    alive = np.zeros(np_, np.bool_)
    for i in range(1, np_):
        p = pins[i]
        tstamp[p] = -tg
        sz[i] = p // WH; rr = p - sz[i] * WH; sy[i] = rr // W; sx[i] = rr - sy[i] * W
        alive[i] = True
    soft = vcost > 0.0
    total = 0.0
    while nrem > 0:
        ctr[0] += 1
        s = ctr[0]
        ne = 0
        live = 0
        fmin = np.iinfo(np.int64).max
        for i in range(nt):
            v = outv[i]
            g = np.int64(tdel[v] * S + 0.5)
            stamp[v] = s
            dist[v] = g
            cnt[v] = 0
            prev[v] = -1
            f = g + _hi(v, W, WH, HT, sx, sy, sz, alive, np_)
            b = f & MASK
            if bstamp[b] != s:
                bstamp[b] = s
                bhead[b] = -1
            ev[ne] = v; eg[ne] = g; enext[ne] = bhead[b]; bhead[b] = ne; ne += 1
            live += 1
            if f < fmin:
                fmin = f
        cur = fmin
        found = -1
        while live > 0:
            b = cur & MASK
            if bstamp[b] != s or bhead[b] < 0:
                cur += 1
                continue
            e = bhead[b]
            bhead[b] = enext[e]
            live -= 1
            u = ev[e]
            if closed[u] == s or eg[e] != dist[u]:
                continue
            closed[u] = s
            if tstamp[u] == -tg:
                found = u
                break
            d = dist[u]
            cu = cnt[u]
            z = u // WH; r = u - z * WH; y = r // W; x = r - y * W
            for m in range(6):
                if m == 0:
                    if x + 1 >= W: continue
                    v = u + 1; w = ld[z]
                elif m == 1:
                    if x == 0: continue
                    v = u - 1; w = ld[z]
                elif m == 2:
                    if y + 1 >= H: continue
                    v = u + W; w = ld[z]
                elif m == 3:
                    if y == 0: continue
                    v = u - W; w = ld[z]
                elif m == 4:
                    if z + 1 >= L: continue
                    v = u + WH; w = via
                else:
                    if z == 0: continue
                    v = u - WH; w = via
                if tstamp[v] == tg:
                    continue
                pn = pin_net[v]
                if pn >= 0 and pn != nid:
                    continue
                if block[v] > 0:
                    continue
                c = np.int64(w) * S
                if soft:
                    q = np.int64(S * vcost * (hist[v] + pres * occ[v]) + 0.5)
                    if q > CLAMP:
                        q = CLAMP
                    c += q
                nd = d + c
                nc = cu + 1
                if stamp[v] == s:
                    if closed[v] == s:
                        continue
                    if nd > dist[v] or (nd == dist[v] and nc >= cnt[v]):
                        continue
                stamp[v] = s
                dist[v] = nd
                cnt[v] = nc
                prev[v] = u
                f = nd + _hi(v, W, WH, HT, sx, sy, sz, alive, np_)
                bb = f & MASK
                if bstamp[bb] != s:
                    bstamp[bb] = s
                    bhead[bb] = -1
                ev[ne] = v; eg[ne] = nd; enext[ne] = bhead[bb]; bhead[bb] = ne; ne += 1
                live += 1
        if found < 0:
            return -1, 0.0
        path_start = nt
        cur_v = found
        while tstamp[cur_v] != tg:
            outv[nt] = cur_v; nt += 1
            cur_v = prev[cur_v]
        acc = tdel[cur_v]
        last = cur_v
        for i in range(nt - 1, path_start - 1, -1):
            v = outv[i]
            if v - last == WH or last - v == WH:
                acc += via
            else:
                acc += ld[v // WH]
            tdel[v] = acc
            tpar[v] = last
            tstamp[v] = tg
            last = v
        total += tdel[found]
        nrem -= 1
        for i in range(1, np_):
            if pins[i] == found:
                alive[i] = False
    return nt, total
