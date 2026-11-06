"""Clustering on a precomputed distance matrix: in-house PAM k-medoids, frequency-weighted average linkage, and
the step that extends a clustering from the fitted units to every individual.

Why this file exists: trajectories are sequences, not points in a vector space, so means (k-means, Ward) have no
meaning for them. What exists is a dissimilarity between sequences, so the primary method is k-medoids on that
matrix (each cluster is represented by one real trajectory, its medoid, which can be read and named), and the
comparison method is hierarchical clustering on the SAME matrix. Both work on unique sequences weighted by how many
individuals each stands for, so collapsing identical trajectories never changes a result.

Design choices worth defending in a viva:
  * PAM is written here, not imported: scikit-learn has no precomputed-distance k-medoids with weights. The cost
    is sum_i f_i * min_m D[i, medoid_m] with f the individual count of unit i (`sample_weight` is always `freq`,
    never a survey weight). BUILD picks the first medoid as the weighted 1-medoid, then adds the unit with the
    largest weighted gain. SWAP evaluates EVERY (medoid, non-medoid) swap exactly in one pass per iteration (the
    FastPAM1 decomposition: a shared term for the candidate plus a per-medoid term from nearest and second-nearest
    distances) and applies the best one while it lowers the cost by more than a tiny tolerance. The result is a
    local optimum with respect to single swaps, which the demo verifies by brute force. PAM is a heuristic: the
    first start is BUILD, the other `n_init - 1` starts are random (drawn with probability proportional to
    individual count), and the lowest-cost run is kept. `converged` is False only if `max_iter` swaps were not
    enough.
  * Determinism: ties are broken by index everywhere (first medoid, BUILD candidate, best swap: lowest candidate
    then lowest medoid slot, nearest medoid: lowest medoid unit index). Medoids are always kept sorted by unit
    index, so "lowest slot" and "lowest unit index" are the same thing. The only randomness is the random starts,
    and it comes from the `rng` the caller passes.
  * A medoid is always assigned to its own cluster, even if another medoid sits at distance 0 from it (distinct
    units can be at distance 0 under pairwise-available missing-data handling), so no cluster is ever empty.
  * Labels are numbered by descending individual count, then ascending minimum unit index, for both methods, and
    `medoid_idx[c]` is the medoid of label `c`. Equal clusterings therefore have equal labels.
  * Hierarchical clustering is average linkage in which the distance between clusters A and B is
    sum_{i in A} sum_{j in B} f_i f_j D_ij / (N_A N_B), N = individual counts. That is exactly ordinary average
    linkage on the expanded individuals, but computed on unique sequences with the Lance-Williams update
    d(A+B, C) = (N_A d(A,C) + N_B d(B,C)) / (N_A + N_B). It is NOT scipy's "weighted" method (WPGMA). Each step
    merges the global minimum pair; ties go to the lowest i, then the lowest j; the merged cluster keeps index i.
    A nearest-neighbour cache makes this about O(u^2) time instead of O(u^3), and the demo proves it gives the
    identical dendrogram to a brute-force version of the same rule. Equality with scipy on the expanded individuals
    is claimed only when all pairwise distances between distinct units differ and no two distinct units are at
    distance zero; with ties only determinism is claimed. The dendrogram cut is not a nearest-medoid partition;
    its medoids are computed afterwards from the labels, and its `cost` is the same frequency-weighted PAM cost
    as for k-medoids so the two methods are comparable.
  * Extension to everyone (`cluster_full`): the clustering is fitted on the units the distance matrix was built on
    (`plan.col_fit`); every other unit of `plan.col_all` gets the label of its nearest medoid, using the same
    distance (`distance_to_medoids`), so the matrix and the extension use ONE metric. The TRATE substitution costs
    are estimated from data, so `sub_cost` must be the matrix `D` was built with (INTERFACES v1.5). If it is None,
    `D` is assumed to have been built with the default costs estimated from `plan.col_fit` and the extension uses
    exactly those.
  * Who may be a medoid (v1.6): `clustering.medoid_min_observed` ("all" by default) lets only trajectories observed
    at that many time points represent a cluster, because pairwise-available distances make trajectories with gaps
    look central. `medoid_candidates` builds the mask; `kmedoids`, `medoids_from_labels` and `hierarchical` accept it;
    `cluster_full` applies it. Every unit is still clustered and counted in the cost.
  * Memory: PAM needs a few (block x n) temporaries on top of D (`SWAP_BLOCK_ROWS` rows at a time); hierarchical
    clustering makes one working copy of D. `benchmark_clustering` measures both on your machine.

Limits: one run of PAM is a local optimum, not a proof of the best partition; the dendrogram of average linkage
can chain; "k" is chosen elsewhere (`stability.select_k`), never here.

Dependency rule: imports `config`, the shared types and `distances` (and, through it, `trajectories`). The smoke
demo imports `synthetic_data` and `trajectories` inside the demo function.

Run the smoke demo with:  python -m src.clustering
"""
from __future__ import annotations

import itertools
import time
import tracemalloc
import warnings
from typing import Any

import numpy as np
import pandas as pd

from . import ClusterResult, CollapsedTrajectories, FullClustering, ReductionPlan
from .config import Config, ConfigError, load_config, make_rng
from .distances import _costs_from_collapsed, build_distance, distance_to_medoids, effective_max_units

__all__ = [
    "kmedoids",
    "hierarchical",
    "weighted_average_linkage",
    "cut_linkage",
    "medoids_from_labels",
    "medoid_candidates",
    "cluster_full",
    "benchmark_clustering",
]

SWAP_BLOCK_ROWS = 128     # candidate rows evaluated at once in BUILD and SWAP (bounds the temporaries to a few block x n arrays)
SWAP_TOL = 1e-9           # a swap must lower the cost by more than this share of the current cost to be applied


# ---------------------------------------------------------------------------------------------
# Input checks
# ---------------------------------------------------------------------------------------------
def _check_D(D: Any) -> np.ndarray:
    D = np.asarray(D)
    if D.ndim != 2 or D.shape[0] != D.shape[1] or D.shape[0] < 1:
        raise ValueError(f"D must be a square matrix with at least one row, got shape {D.shape}")
    if D.dtype != np.float64:
        D = D.astype(np.float64)
    if not np.isfinite(D).all():
        raise ValueError("D contains non-finite values")
    if (D < 0).any():
        raise ValueError("D contains negative distances")
    if np.any(np.diag(D) != 0):
        raise ValueError("D must have an exactly zero diagonal")
    if not np.array_equal(D, D.T):
        raise ValueError("D must be exactly symmetric")
    return D


def _weights(w: Any, n: int, positive: bool = False) -> np.ndarray:
    if w is None:
        return np.ones(n)
    w = np.asarray(w, dtype=np.float64)
    if w.shape != (n,) or not np.isfinite(w).all() or (w < 0).any() or w.sum() <= 0:
        raise ValueError(f"sample_weight must be {n} finite non-negative numbers, not all zero")
    if positive and (w <= 0).any():
        raise ValueError("sample_weight (individual counts) must all be positive")
    return w


def _check_int(name: str, v: Any, lo: int, hi: int | None = None) -> int:
    if isinstance(v, bool) or int(v) != v or v < lo or (hi is not None and v > hi):
        raise ValueError(f"{name} must be a whole number in [{lo}, {hi if hi is not None else 'inf'}], got {v!r}")
    return int(v)


# ---------------------------------------------------------------------------------------------
# PAM
# ---------------------------------------------------------------------------------------------
def _wrows(D: np.ndarray, f: np.ndarray) -> np.ndarray:
    """sum_j f_j D[i, j] for every i, a block of rows at a time."""
    n = len(D)
    out = np.empty(n)
    for i0 in range(0, n, SWAP_BLOCK_ROWS):
        i1 = min(i0 + SWAP_BLOCK_ROWS, n)
        out[i0:i1] = (D[i0:i1] * f[None, :]).sum(axis=1)
    return out


def _build(D: np.ndarray, f: np.ndarray, k: int, cand: np.ndarray | None = None) -> np.ndarray:
    """PAM BUILD: weighted 1-medoid first, then the unit with the largest weighted gain, k times (ties: lowest index).

    With `cand` (boolean mask) only candidate units can become medoids; every unit still counts in the cost.
    """
    n = len(D)
    blocked = np.zeros(n, dtype=bool) if cand is None else ~cand
    scores = _wrows(D, f)
    scores[blocked] = np.inf
    first = int(np.argmin(scores))
    med = [first]
    is_med = np.zeros(n, dtype=bool)
    is_med[first] = True
    near = D[first].copy()
    while len(med) < k:
        gain = np.empty(n)
        for h0 in range(0, n, SWAP_BLOCK_ROWS):
            h1 = min(h0 + SWAP_BLOCK_ROWS, n)
            gain[h0:h1] = (f[None, :] * np.maximum(near[None, :] - D[h0:h1], 0.0)).sum(axis=1)
        gain[is_med | blocked] = -np.inf
        c = int(np.argmax(gain))
        med.append(c)
        is_med[c] = True
        near = np.minimum(near, D[c])
    return np.array(med, dtype=np.int64)


def _assign(D: np.ndarray, f: np.ndarray, medoids: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """(slot of nearest medoid, nearest distance, second-nearest distance, weighted cost) for SORTED medoids.

    Ties go to the lowest slot (= lowest unit index). Every medoid is forced into its own slot.
    """
    k, n = len(medoids), len(D)
    Dm = D[medoids]                                    # (k, n); D is symmetric, so a row is a column
    assign = np.argmin(Dm, axis=0)
    assign[medoids] = np.arange(k)
    d1 = Dm.min(axis=0)
    d2 = np.partition(Dm, 1, axis=0)[1] if k >= 2 else np.full(n, np.inf)
    return assign, d1, d2, float((f * d1).sum())


def _best_swap(D: np.ndarray, f: np.ndarray, medoids: np.ndarray, assign: np.ndarray, d1: np.ndarray,
               d2: np.ndarray, cand: np.ndarray | None = None) -> tuple[float, int, int]:
    """The (medoid slot, candidate) swap with the lowest cost change, over ALL swaps. Returns (delta, slot, candidate).

    For a unit j whose nearest medoid is not the removed one, the swap changes its distance by min(D[j,h] - d1_j, 0);
    for a unit whose nearest medoid IS the removed one, its new distance is min(d2_j, D[j,h]). So
    delta(m, h) = A_h + B_m,h with A_h = sum_j f_j min(D[j,h] - d1_j, 0) shared by all m, and
    B_m,h = sum over j assigned to m of f_j (min(d2_j, D[j,h]) - d1_j - min(D[j,h] - d1_j, 0)).
    Ties: lowest candidate, then lowest slot. With `cand` (boolean mask) only candidate units are tried as the
    incoming medoid.
    """
    n, k = len(D), len(medoids)
    is_med = np.zeros(n, dtype=bool)
    is_med[medoids] = True
    if cand is not None:
        is_med |= ~cand
    groups = [np.flatnonzero(assign == s) for s in range(k)]
    best = (np.inf, -1, -1)
    for h0 in range(0, n, SWAP_BLOCK_ROWS):
        h1 = min(h0 + SWAP_BLOCK_ROWS, n)
        blk = D[h0:h1]
        neg = np.minimum(blk - d1[None, :], 0.0)
        w = np.minimum(d2[None, :], blk)
        w -= d1[None, :]
        w -= neg
        w *= f[None, :]
        neg *= f[None, :]
        a = neg.sum(axis=1)
        delta = np.empty((k, h1 - h0))
        for s in range(k):
            delta[s] = a + w[:, groups[s]].sum(axis=1)
        delta[:, is_med[h0:h1]] = np.inf
        slot = delta.argmin(axis=0)
        vals = delta[slot, np.arange(h1 - h0)]
        hb = int(vals.argmin())
        if vals[hb] < best[0]:
            best = (float(vals[hb]), int(slot[hb]), h0 + hb)
    return best


def _swap_phase(D: np.ndarray, f: np.ndarray, medoids: np.ndarray, max_iter: int,
                cand: np.ndarray | None = None) -> tuple[np.ndarray, int, bool]:
    """PAM SWAP from a starting set: apply the best improving swap until none improves or `max_iter` swaps were made."""
    n = len(D)
    medoids = np.sort(np.asarray(medoids, dtype=np.int64))
    if len(medoids) == n:
        return medoids, 0, True
    assign, d1, d2, cost = _assign(D, f, medoids)
    n_iter = 0
    while True:
        delta, slot, h = _best_swap(D, f, medoids, assign, d1, d2, cand)
        if not delta < -SWAP_TOL * max(cost, 1e-300):
            return medoids, n_iter, True
        if n_iter >= max_iter:
            return medoids, n_iter, False
        new = medoids.copy()
        new[slot] = h
        new = np.sort(new)
        assign2, d1_2, d2_2, cost2 = _assign(D, f, new)
        if not cost2 < cost:                      # numerical safeguard: the exact cost must really fall
            return medoids, n_iter, True
        medoids, assign, d1, d2, cost = new, assign2, d1_2, d2_2, cost2
        n_iter += 1


def _canonical(D: np.ndarray, f: np.ndarray, assign: np.ndarray, medoids: np.ndarray, method: str,
               converged: bool, n_iter: int) -> ClusterResult:
    """Number clusters by descending individual count, then ascending minimum unit index; cost recomputed exactly."""
    k, n = len(medoids), len(D)
    counts = np.bincount(assign, weights=f, minlength=k)
    min_idx = np.array([int(np.flatnonzero(assign == s).min()) for s in range(k)])
    order = np.lexsort((min_idx, -counts))
    rank = np.empty(k, dtype=np.int64)
    rank[order] = np.arange(k)
    labels = rank[assign]
    med = medoids[order]
    cost = float((f * D[med[labels], np.arange(n)]).sum())
    return ClusterResult(labels=labels, medoid_idx=med, k=k, cost=cost, method=method, converged=converged, n_iter=n_iter)


def kmedoids(D: np.ndarray, k: int, n_init: int, max_iter: int, rng: np.random.Generator,
             sample_weight: np.ndarray | None = None, candidates: np.ndarray | None = None) -> ClusterResult:
    """Frequency-weighted PAM (BUILD + SWAP) on the precomputed distance matrix `D` (m,m).

    `sample_weight` is the individual count of each unit (`CollapsedTrajectories.freq`), never a survey weight;
    None means one individual per unit. Run 1 starts from BUILD (deterministic); runs 2..n_init start from k
    distinct random units drawn with probability proportional to the weight. The lowest-cost run wins (ties: the
    earlier run). `rng` is consumed only by the random starts. Returns labels in [0,k-1] numbered by descending
    individual count then ascending minimum unit index, `medoid_idx[c]` the medoid of label c (an index into D),
    `cost` = sum_i w_i D[i, medoid of i], `converged` False only if `max_iter` swaps were not enough, and `n_iter`
    the number of swaps made in the winning run. `candidates` (v1.6) is an optional boolean mask of the units that may
    be chosen as medoids (None: every unit); every unit is still assigned and still counts in the cost, so this
    restricts only who may represent a cluster. BUILD, the random starts and SWAP all respect it; with it set to all
    True the result is identical to None. Raises ValueError for a non-symmetric, negative or non-finite D, a bad
    weight vector, k outside [1, m], or a mask that is not (m,) boolean or has fewer than k True entries.
    """
    D = _check_D(D)
    n = len(D)
    f = _weights(sample_weight, n)
    k = _check_int("k", k, 1, n)
    n_init = _check_int("n_init", n_init, 1)
    max_iter = _check_int("max_iter", max_iter, 1)
    cand = None
    if candidates is not None:
        cand = np.asarray(candidates)
        if cand.shape != (n,) or cand.dtype != bool:
            raise ValueError(f"candidates must be a boolean mask of shape ({n},)")
        if int(cand.sum()) < k:
            raise ValueError(f"only {int(cand.sum())} candidate units for k={k} medoids")
        if cand.all():
            cand = None
    if k == n:
        return _canonical(D, f, np.arange(n), np.arange(n, dtype=np.int64), "kmedoids", True, 0)
    best: tuple[float, np.ndarray, int, bool] | None = None
    pc = f if cand is None else f * cand
    p = pc / pc.sum() if pc.sum() > 0 else None
    for run in range(n_init):
        if run == 0:
            start = _build(D, f, k, cand)
        elif p is not None and int((p > 0).sum()) >= k:
            start = rng.choice(n, size=k, replace=False, p=p)
        elif cand is None:
            start = rng.choice(n, size=k, replace=False)
        else:
            start = rng.choice(np.flatnonzero(cand), size=k, replace=False)
        med, n_it, conv = _swap_phase(D, f, start, max_iter, cand)
        cost = _assign(D, f, med)[3]
        if best is None or cost < best[0]:
            best = (cost, med, n_it, conv)
    assert best is not None
    _, med, n_it, conv = best
    assign = _assign(D, f, med)[0]
    return _canonical(D, f, assign, med, "kmedoids", conv, n_it)


# ---------------------------------------------------------------------------------------------
# Medoids from labels
# ---------------------------------------------------------------------------------------------
def medoids_from_labels(D: np.ndarray, labels: np.ndarray, sample_weight: np.ndarray | None = None,
                        candidates: np.ndarray | None = None) -> np.ndarray:
    """(k,) medoid of each cluster: argmin over members i of sum_{j in cluster} w_j D[i,j]; ties go to the lowest index.

    `labels` must use every value 0..k-1 (entry c of the result belongs to label c). Weights are individual counts.
    Works for any partition (k-medoids, dendrogram cuts, the employed-versus-not baseline). With `candidates`
    (boolean mask, v1.6) the medoid of a cluster is chosen among its candidate members only; a cluster with no
    candidate member falls back to all its members (check `candidates[result]` to see which clusters did).
    """
    D = _check_D(D)
    n = len(D)
    lab = np.asarray(labels)
    if lab.shape != (n,) or lab.dtype.kind not in "iu" or (lab.size and lab.min() < 0):
        raise ValueError(f"labels must be {n} non-negative integers")
    k = int(lab.max()) + 1
    if len(np.unique(lab)) != k:
        raise ValueError("labels must use every value 0..k-1 (a cluster is empty)")
    f = _weights(sample_weight, n)
    if candidates is not None:
        candidates = np.asarray(candidates)
        if candidates.shape != (n,) or candidates.dtype != bool:
            raise ValueError(f"candidates must be a boolean mask of shape ({n},)")
    out = np.empty(k, dtype=np.int64)
    for c in range(k):
        members = np.flatnonzero(lab == c)
        pool = members
        if candidates is not None and candidates[members].any():
            pool = members[candidates[members]]
        scores = np.empty(len(pool))
        for i0 in range(0, len(pool), SWAP_BLOCK_ROWS):
            blk = pool[i0:i0 + SWAP_BLOCK_ROWS]
            scores[i0:i0 + len(blk)] = (D[np.ix_(blk, members)] * f[members][None, :]).sum(axis=1)
        out[c] = pool[int(np.argmin(scores))]
    return out


# ---------------------------------------------------------------------------------------------
# Hierarchical: weighted average linkage
# ---------------------------------------------------------------------------------------------
def weighted_average_linkage(D: np.ndarray, freq: np.ndarray) -> np.ndarray:
    """(u-1, 4) linkage matrix in scipy's format for frequency-weighted average linkage on `D` (u,u).

    Columns: id of the lower cluster, id of the higher cluster (originals are 0..u-1, the merge made at step s is
    u+s), merge height D(A,B) = sum f_i f_j D_ij / (N_A N_B), and the number of INDIVIDUALS in the merged cluster
    (sum of `freq`, not a unit count and not a survey weight). `freq` must be positive. Each step merges the global
    minimum pair; ties go to the lowest i, then the lowest j; the merged cluster keeps index i. Uses one working
    copy of D (about O(u^2) memory and time). Heights are non-decreasing.
    """
    D = _check_D(D)
    u = len(D)
    f = _weights(freq, u, positive=True)
    if u == 1:
        return np.zeros((0, 4))
    W = D.copy()
    np.fill_diagonal(W, np.inf)
    size = f.copy()
    cid = np.arange(u)
    active = np.ones(u, dtype=bool)
    rowmin = np.full(u, np.inf)
    nn = np.full(u, -1, dtype=np.int64)

    def refresh(i: int) -> None:
        """Nearest active neighbour of row i among columns l > i (first minimum = lowest l)."""
        if i + 1 >= u:
            rowmin[i], nn[i] = np.inf, -1
            return
        seg = W[i, i + 1:]
        a = int(np.argmin(seg))
        if np.isinf(seg[a]):
            rowmin[i], nn[i] = np.inf, -1
        else:
            rowmin[i], nn[i] = seg[a], i + 1 + a

    for i in range(u):
        refresh(i)
    Z = np.empty((u - 1, 4))
    for step in range(u - 1):
        i = int(np.argmin(rowmin))                     # first minimum = lowest i
        j = int(nn[i])
        h = float(rowmin[i])
        ni, nj = size[i], size[j]
        others = np.flatnonzero(active)
        others = others[(others != i) & (others != j)]
        new = (ni * W[i, others] + nj * W[j, others]) / (ni + nj)
        Z[step] = (min(cid[i], cid[j]), max(cid[i], cid[j]), h, ni + nj)
        active[j] = False
        W[j, :] = np.inf
        W[:, j] = np.inf
        rowmin[j], nn[j] = np.inf, -1
        W[i, others] = new
        W[others, i] = new
        size[i] = ni + nj
        cid[i] = u + step
        refresh(i)
        before = others < i
        ks = others[before]
        if ks.size:
            cand = new[:ks.size]
            stale = (nn[ks] == i) | (nn[ks] == j)
            better = ~stale & ((cand < rowmin[ks]) | ((cand == rowmin[ks]) & (i < nn[ks])))
            rowmin[ks[better]] = cand[better]
            nn[ks[better]] = i
            for k_ in ks[stale]:
                refresh(int(k_))
        after = others[others > i]
        for k_ in after[nn[after] == j]:
            refresh(int(k_))
    return Z


def cut_linkage(Z: np.ndarray, k: int, u: int) -> np.ndarray:
    """(u,) labels from applying the first u-k merges of the linkage matrix `Z`.

    Labels are numbered by first appearance (ascending minimum unit index): `Z` carries individual counts only for
    merged clusters, not for single units, so ordering by size needs the unit counts and is done by `hierarchical`.
    Raises ValueError if `Z` is not a valid (u-1, 4) linkage or k is outside [1, u].
    """
    Z = np.asarray(Z, dtype=np.float64)
    u = _check_int("u", u, 1)
    k = _check_int("k", k, 1, u)
    if Z.shape != (u - 1, 4):
        raise ValueError(f"Z must have shape ({u - 1}, 4), got {Z.shape}")
    parent = np.arange(2 * u - 1)
    for s in range(u - k):
        a, b = int(Z[s, 0]), int(Z[s, 1])
        if not (0 <= a < u + s and 0 <= b < u + s and a != b) or parent[a] != a or parent[b] != b:
            raise ValueError(f"Z row {s} merges a cluster that does not exist or was already merged")
        parent[a] = parent[b] = u + s
    while True:
        up = parent[parent]
        if np.array_equal(up, parent):
            break
        parent = up
    roots = parent[:u]
    uniq, inv = np.unique(roots, return_inverse=True)
    first = np.full(len(uniq), u)
    np.minimum.at(first, inv.reshape(-1), np.arange(u))
    rank = np.empty(len(uniq), dtype=np.int64)
    rank[np.argsort(first, kind="stable")] = np.arange(len(uniq))
    return rank[inv.reshape(-1)]


def hierarchical(D: np.ndarray, k: int, sample_weight: np.ndarray | None = None, linkage: str = "average",
                 candidates: np.ndarray | None = None) -> ClusterResult:
    """Frequency-weighted average-linkage clustering of the units of `D` into k clusters (dendrogram cut).

    Only `linkage="average"` exists; anything else raises ConfigError. `sample_weight` is the individual count per
    unit (positive; None means one each). Labels are numbered by descending individual count then ascending minimum
    unit index; `medoid_idx` comes from `medoids_from_labels` afterwards; `cost` is the same frequency-weighted
    PAM cost as `kmedoids`, so the two methods are comparable; `n_iter` is the number of merges applied
    (u - k) and `converged` is True. `candidates` (v1.6) restricts which units may be named as the medoid of a
    cluster (see `medoids_from_labels`); the dendrogram itself never depends on it.
    """
    if linkage != "average":
        raise ConfigError(f"clustering.linkage must be 'average', got {linkage!r}")
    D = _check_D(D)
    u = len(D)
    f = _weights(sample_weight, u, positive=True)
    k = _check_int("k", k, 1, u)
    lab = cut_linkage(weighted_average_linkage(D, f), k, u)
    counts = np.bincount(lab, weights=f, minlength=k)
    min_idx = np.array([int(np.flatnonzero(lab == c).min()) for c in range(k)])
    order = np.lexsort((min_idx, -counts))
    rank = np.empty(k, dtype=np.int64)
    rank[order] = np.arange(k)
    labels = rank[lab]
    med = medoids_from_labels(D, labels, f, candidates)
    cost = float((f * D[med[labels], np.arange(u)]).sum())
    return ClusterResult(labels=labels, medoid_idx=med, k=k, cost=cost, method="hierarchical", converged=True, n_iter=u - k)


# ---------------------------------------------------------------------------------------------
# Which units may be medoids
# ---------------------------------------------------------------------------------------------
def medoid_candidates(col: CollapsedTrajectories, cfg: Config, k: int) -> tuple[np.ndarray, int]:
    """(mask, threshold): the fit units allowed to be medoids under `clustering.medoid_min_observed`, and the threshold used.

    Why: with pairwise-available missing-data handling a trajectory with gaps is compared with others on fewer
    time points, so it looks closer to everything and PAM keeps choosing it as a medoid (on synthetic data every
    medoid had a gap although most units were complete, and agreement with the planted pathways fell by 0.11 to
    0.17 ARI). Restricting who may REPRESENT a cluster fixes this without dropping anyone: every unit is still
    assigned and still counts in the cost.
    The setting is null (no restriction, threshold 0), "all" (observed at every time point) or an integer; units with
    at least that many observed states (codes >= 0) are candidates. If fewer than k units qualify the threshold is
    lowered until k do, with a UserWarning, so a run on data with little complete follow-up still finishes; the
    threshold actually used is returned and the orchestrator reports it with each medoid's observed-point count.
    """
    spec = cfg.clustering.medoid_min_observed
    u, T = col.u, col.T
    if spec is None:
        return np.ones(u, dtype=bool), 0
    req = T if spec == "all" else min(int(spec), T)
    obs = (col.unique_states >= 0).sum(axis=1)
    thr = req
    while thr > 1 and int((obs >= thr).sum()) < k:
        thr -= 1
    if thr < req:
        warnings.warn(f"only {int((obs >= req).sum())} of {u} units are observed at {req} time points, fewer than k={k}: "
                      f"medoids are drawn from units observed at {thr} or more (clustering.medoid_min_observed)", UserWarning, stacklevel=2)
    mask = obs >= thr
    if int(mask.sum()) < k:                                   # thr reached 1 and still too few: no restriction is possible
        return np.ones(u, dtype=bool), 0
    return mask, int(thr)


# ---------------------------------------------------------------------------------------------
# Fit on the fit units, extend to everyone
# ---------------------------------------------------------------------------------------------
def cluster_full(plan: ReductionPlan, D: np.ndarray, cfg: Config, k: int, rng: np.random.Generator,
                 sub_cost: np.ndarray | None = None) -> FullClustering:
    """Cluster the fit units with k-medoids and give every unit and every individual a pathway label.

    `D` must be the matrix built from `plan.col_fit` (this function never builds D and never samples). The fit
    uses `clustering.n_init` and `clustering.max_iter` with `col_fit.freq` as the weight. Fit units keep their fit
    labels; every other unit of `plan.col_all` takes the label of its nearest medoid under the same distance
    (`distance_to_medoids`, ties to the lowest medoid unit index). `sub_cost` must be the substitution-cost matrix
    `D` was built with; None means D used the default costs estimated from `plan.col_fit`, and the extension then
    uses exactly those (INTERFACES v1.5). When several fit individuals share one unit of `col_all` (subsample
    mode), the unit takes the label of the first of them; they are at distance 0 from each other, so this matters
    only in exact ties. Medoids are drawn only from the fit units allowed by `medoid_candidates` (v1.6). Raises ConfigError unless
    `clustering.primary` is "kmedoids", ValueError for a D of the wrong size or k outside [1, number of fit units].
    """
    if str(cfg.clustering.primary) != "kmedoids":
        raise ConfigError(f"clustering.primary must be 'kmedoids', got {cfg.clustering.primary!r}")
    fit, col_all = plan.col_fit, plan.col_all
    D = np.asarray(D)
    if D.shape != (fit.u, fit.u):
        raise ValueError(f"D has shape {D.shape} but plan.col_fit has {fit.u} units: build D from plan.col_fit")
    k = _check_int("k", k, 1, fit.u)
    cand, _ = medoid_candidates(fit, cfg, k)
    res = kmedoids(D, k, int(cfg.clustering.n_init), int(cfg.clustering.max_iter), rng, fit.freq.astype(np.float64), cand)
    med_states = fit.unique_states[res.medoid_idx]
    med_attrs = fit.unique_attrs[res.medoid_idx] if fit.attr_cols else None
    if plan.fit_unit_idx is None:
        unit_labels = res.labels.copy()
    else:
        unit_labels = np.full(col_all.u, -1, dtype=np.int64)
        uniq, first = np.unique(plan.fit_unit_idx, return_index=True)
        unit_labels[uniq] = res.labels[first]
        rest = np.flatnonzero(unit_labels < 0)
        if rest.size:
            costs = sub_cost
            if costs is None and str(cfg.distance.name) != "hamming":
                costs = _costs_from_collapsed(fit, cfg)
            d = distance_to_medoids(col_all, med_states, cfg, med_attrs, idx=rest, sub_cost=costs)
            order = np.argsort(res.medoid_idx, kind="stable")      # ties -> lowest medoid unit index
            unit_labels[rest] = order[np.argmin(d[:, order], axis=1)]
    return FullClustering(plan=plan, fit_result=res, unit_labels=unit_labels, full_labels=unit_labels[col_all.inverse],
                          medoid_states=med_states, medoid_attrs=med_attrs)


# ---------------------------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------------------------
def _subset_units(col: CollapsedTrajectories, sel: np.ndarray) -> CollapsedTrajectories:
    return CollapsedTrajectories(
        unique_states=col.unique_states[sel], freq=col.freq[sel], inverse=np.repeat(np.arange(len(sel)), col.freq[sel]),
        attr_cols=list(col.attr_cols), unique_attrs=None if col.unique_attrs is None else col.unique_attrs[sel])


def benchmark_clustering(plan: ReductionPlan, cfg: Config, sizes: list[int], rng: np.random.Generator) -> pd.DataFrame:
    """Measured seconds and EXTRA peak MB (tracemalloc, beyond the matrix itself) of PAM and hierarchical clustering.

    For each size m, m of the fit units are drawn at random (keeping their individual counts), the distance matrix
    is built under the configured cap, and both methods run once with the largest candidate k. `matrix_mb` is the
    size of D; `total_peak_mb` = matrix + the larger extra peak, to be compared with `cap_mb`. A size above
    `effective_max_units`, above the number of fit units, or below k is skipped and `status` says why; a total above
    the cap is reported as "over cap". Columns: m, k, matrix_mb, pam_seconds, pam_extra_peak_mb, hier_seconds,
    hier_extra_peak_mb, total_peak_mb, cap_mb, status. Use it to replace the placeholder limits in config.
    """
    eff = effective_max_units(cfg)
    cap = float(cfg.distance.max_matrix_mb)
    fit = plan.col_fit
    k = max(int(x) for x in cfg.clustering.k_candidates)
    costs = None if str(cfg.distance.name) == "hamming" else _costs_from_collapsed(plan.col_all, cfg)
    cols = ["m", "k", "matrix_mb", "pam_seconds", "pam_extra_peak_mb", "hier_seconds", "hier_extra_peak_mb",
            "total_peak_mb", "cap_mb", "status"]
    rows = []
    for m in sizes:
        row: dict[str, Any] = {c: np.nan for c in cols}
        row.update(m=int(m), k=k, cap_mb=cap)
        if m > eff:
            row["status"] = f"skipped: {m} units exceed the limit {eff}"
        elif m > fit.u:
            row["status"] = f"skipped: only {fit.u} fit units available"
        elif m < max(k, 2):
            row["status"] = f"skipped: fewer units than k={k}"
        else:
            sub = _subset_units(fit, np.sort(rng.choice(fit.u, size=int(m), replace=False)))
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                D = build_distance(sub, cfg, costs)
            f = sub.freq.astype(np.float64)
            row["matrix_mb"] = D.nbytes / 2 ** 20
            local = make_rng(cfg, f"benchmark_clustering/{m}")
            tracemalloc.start()
            t0 = time.perf_counter()
            kmedoids(D, k, int(cfg.clustering.n_init), int(cfg.clustering.max_iter), local, f)
            row["pam_seconds"] = time.perf_counter() - t0
            row["pam_extra_peak_mb"] = tracemalloc.get_traced_memory()[1] / 2 ** 20
            tracemalloc.stop()
            tracemalloc.start()
            t0 = time.perf_counter()
            hierarchical(D, k, f)
            row["hier_seconds"] = time.perf_counter() - t0
            row["hier_extra_peak_mb"] = tracemalloc.get_traced_memory()[1] / 2 ** 20
            tracemalloc.stop()
            row["total_peak_mb"] = row["matrix_mb"] + max(row["pam_extra_peak_mb"], row["hier_extra_peak_mb"])
            row["status"] = "ok" if row["total_peak_mb"] <= cap else f"over cap: {row['total_peak_mb']:.1f} MB > {cap:g} MB"
        rows.append(row)
    return pd.DataFrame(rows, columns=cols)


# ---------------------------------------------------------------------------------------------
# Smoke demo
# ---------------------------------------------------------------------------------------------
def _cfg_with(cfg: Config, **distance: Any) -> Config:
    d = cfg.to_dict()
    return Config({**d, "distance": {**d["distance"], **distance}}, cfg.root)


def _euclid(X: np.ndarray) -> np.ndarray:
    D = np.sqrt(((X[:, None, :] - X[None, :, :]) ** 2).sum(-1))
    np.fill_diagonal(D, 0.0)
    return D


def _wcost(D: np.ndarray, f: np.ndarray, med: Any) -> float:
    return float((f * D[list(med)].min(axis=0)).sum())


def _opt_cost(D: np.ndarray, f: np.ndarray, k: int) -> float:
    """Exhaustive optimum over every set of k medoids (reference for tiny instances)."""
    return min(_wcost(D, f, c) for c in itertools.combinations(range(len(D)), k))


def _ref_build(D: np.ndarray, f: np.ndarray, k: int) -> list[int]:
    """BUILD written as plain Python loops (reference)."""
    n = len(D)
    first = min(range(n), key=lambda i: (sum(f[j] * D[i, j] for j in range(n)), i))
    med = [first]
    while len(med) < k:
        near = [min(D[m, j] for m in med) for j in range(n)]
        gains = {c: sum(f[j] * max(near[j] - D[c, j], 0.0) for j in range(n)) for c in range(n) if c not in med}
        med.append(max(sorted(gains), key=lambda c: gains[c]))
    return med


def _is_swap_optimal(D: np.ndarray, f: np.ndarray, med: np.ndarray) -> bool:
    cost = _wcost(D, f, med)
    for s in range(len(med)):
        for h in range(len(D)):
            if h in med:
                continue
            new = list(med)
            new[s] = h
            if _wcost(D, f, new) < cost - 1e-9 * cost:
                return False
    return True


def _ref_linkage(D: np.ndarray, f: np.ndarray) -> np.ndarray:
    """The same Lance-Williams rule and tie-break with a brute-force global minimum search each step (reference)."""
    u = len(D)
    W = D.astype(np.float64).copy()
    size = f.astype(np.float64).copy()
    active = list(range(u))
    cid = list(range(u))
    Z = []
    for step in range(u - 1):
        best = None
        for ai, i in enumerate(active):
            for j in active[ai + 1:]:
                if best is None or W[i, j] < best[0]:
                    best = (W[i, j], i, j)
        v, i, j = best
        ni, nj = size[i], size[j]
        for k_ in active:
            if k_ != i and k_ != j:
                W[i, k_] = W[k_, i] = (ni * W[i, k_] + nj * W[j, k_]) / (ni + nj)
        Z.append([min(cid[i], cid[j]), max(cid[i], cid[j]), v, ni + nj])
        active.remove(j)
        size[i] = ni + nj
        cid[i] = u + step
    return np.array(Z).reshape(-1, 4)


def _demo() -> int:
    from scipy.cluster.hierarchy import cut_tree, linkage as sp_linkage
    from scipy.spatial.distance import squareform
    from sklearn.metrics import adjusted_rand_score

    from .distances import build_distance as bd, plan_reduction, substitution_cost_matrix
    from .synthetic_data import generate_synthetic
    from .trajectories import build_trajectories, complete_case_mask

    cfg = load_config()
    print("SYNTHETIC DEMONSTRATION - NOT PLFS RESULTS")

    def raises(exc: type, fn: Any) -> bool:
        try:
            fn()
        except exc:
            return True
        except Exception:
            return False
        return False

    # ----- PAM on small instances
    rg = np.random.default_rng(11)
    blobs = np.vstack([rg.normal(c, 0.15, size=(4, 2)) for c in ([0, 0], [4, 0], [2, 3.5])])
    Db = _euclid(blobs)
    fb = rg.integers(1, 5, size=12).astype(float)
    r_b = kmedoids(Db, 3, 10, 100, make_rng(cfg, "a"), fb)
    opt_b = _opt_cost(Db, fb, 3)
    # weighting check: optimum on units with weights equals the optimum on the expanded individuals
    pts = rg.normal(size=(10, 2))
    fu = rg.integers(1, 4, size=10)
    Du = _euclid(pts)
    inv = np.repeat(np.arange(10), fu)
    Dexp = Du[np.ix_(inv, inv)]
    opt_units, opt_exp = _opt_cost(Du, fu.astype(float), 3), _opt_cost(Dexp, np.ones(len(inv)), 3)
    r_u = kmedoids(Du, 3, 10, 100, make_rng(cfg, "u"), fu.astype(float))
    # larger random instance: local optimality and BUILD reference
    X = rg.normal(size=(60, 2))
    Dr = _euclid(X)
    fr = rg.integers(1, 6, size=60).astype(float)
    r_r = kmedoids(Dr, 4, 5, 100, make_rng(cfg, "r"), fr)
    build_fast, build_ref = np.sort(_build(Dr, fr, 4)), sorted(_ref_build(Dr, fr, 4))
    # max_iter semantics: a random poor start with one swap allowed cannot have converged
    start = np.array([0, 1, 2, 3, 4])
    m1, it1, c1 = _swap_phase(Dr, fr, start, 1)
    m_end, it_end, c_end = _swap_phase(Dr, fr, start, 1000)
    # one medoid, k == n, rng use
    r_k1 = kmedoids(Dr, 1, 1, 10, make_rng(cfg, "k1"), fr)
    r_kn = kmedoids(Du, 10, 3, 10, make_rng(cfg, "kn"), fu.astype(float))
    g = make_rng(cfg, "rngcheck")
    state0 = g.bit_generator.state
    kmedoids(Dr, 3, 1, 10, g, fr)
    state1 = g.bit_generator.state
    r_a1, r_a2 = kmedoids(Dr, 4, 6, 100, make_rng(cfg, "rep"), fr), kmedoids(Dr, 4, 6, 100, make_rng(cfg, "rep"), fr)
    # twins at distance zero
    tw = np.array([[0, 0], [0, 0], [0, 0], [5, 0], [5, 0], [10, 0]], dtype=float)
    Dt = _euclid(tw)
    r_t3, r_t4 = kmedoids(Dt, 3, 4, 50, make_rng(cfg, "t"), np.ones(6)), kmedoids(Dt, 4, 4, 50, make_rng(cfg, "t"), np.ones(6))

    def canonical_ok(res: ClusterResult, f: np.ndarray) -> bool:
        counts = np.bincount(res.labels, weights=f, minlength=res.k)
        mins = [int(np.flatnonzero(res.labels == c).min()) for c in range(res.k)]
        keys = list(zip((-counts).tolist(), mins))
        return keys == sorted(keys) and all(res.labels[res.medoid_idx[c]] == c for c in range(res.k)) and len(np.unique(res.labels)) == res.k

    # ----- medoids_from_labels
    lab_r = r_r.labels
    mfl = medoids_from_labels(Dr, lab_r, fr)
    ref_mfl = [min(np.flatnonzero(lab_r == c), key=lambda i: (sum(fr[j] * Dr[i, j] for j in np.flatnonzero(lab_r == c)), i)) for c in range(4)]
    tie_D = np.array([[0, 1, 1, 9], [1, 0, 1, 9], [1, 1, 0, 9], [9, 9, 9, 0]], dtype=float)
    mfl_tie = medoids_from_labels(tie_D, np.array([0, 0, 0, 1]))

    # ----- hierarchical against scipy on the expanded individuals (no ties, no zero distances between distinct units)
    P = rg.normal(size=(25, 2))
    f25 = rg.integers(1, 5, size=25)
    D25 = _euclid(P)
    inv25 = np.repeat(np.arange(25), f25)
    Dexp25 = D25[np.ix_(inv25, inv25)]
    Zs = sp_linkage(squareform(Dexp25, checks=False), "average")
    Zo = weighted_average_linkage(D25, f25.astype(float))
    n_zero = len(inv25) - 25
    heights_ok = np.allclose(np.sort(Zs[:, 2])[n_zero:], Zo[:, 2], rtol=1e-9, atol=1e-12) and np.allclose(np.sort(Zs[:, 2])[:n_zero], 0.0)
    part_ok = all(adjusted_rand_score(cut_tree(Zs, n_clusters=k_).ravel(), cut_linkage(Zo, k_, 25)[inv25]) == 1.0 for k_ in range(1, 9))
    counts_ok = True
    members = {i: {i} for i in range(25)}
    for s, (a, b, h_, c_) in enumerate(Zo):
        members[25 + s] = members.pop(int(a)) | members.pop(int(b))
        counts_ok &= abs(c_ - sum(f25[i] for i in members[25 + s])) < 1e-9
    h25 = hierarchical(D25, 4, f25.astype(float))
    # ----- tie-heavy fixture: identical to the brute-force version of the same rule
    gp = rg.integers(0, 5, size=(40, 2))
    Dg = np.abs(gp[:, None, :] - gp[None, :, :]).sum(-1).astype(float)
    fg = rg.integers(1, 4, size=40).astype(float)
    Zg, Zg_ref = weighted_average_linkage(Dg, fg), _ref_linkage(Dg, fg)
    Dg2 = _euclid(rg.normal(size=(30, 3)))
    fg2 = rg.integers(1, 6, size=30).astype(float)
    ties_zero = np.count_nonzero(Dg[np.triu_indices(40, 1)] == 0)
    # ----- hierarchical vs k-medoids on separated blobs
    h_b = hierarchical(Db, 3, fb)
    # ----- cut and edge cases
    Z2 = weighted_average_linkage(np.array([[0, 2.0], [2.0, 0]]), np.array([1.0, 3.0]))
    h_k1 = hierarchical(Du, 1, fu.astype(float))
    h_ku = hierarchical(Du, 10, fu.astype(float))

    # ----- synthetic data: eligible trainees, plans, cluster_full
    df, truth = generate_synthetic(cfg, n=1500, seed_offset=51)
    td_all = build_trajectories(df, cfg)
    td = td_all.subset(complete_case_mask(td_all, int(cfg.trainee.min_time_points)))
    rng_plan = make_rng(cfg, "demo-plan")
    plan = plan_reduction(td, cfg, rng_plan)
    D = bd(plan.col_fit, cfg)
    full = cluster_full(plan, D, cfg, 6, make_rng(cfg, "demo-full"))
    pid = np.array([int(x[1:]) for x in td.ids])
    planted = truth.labels[pid]
    ari_planted = adjusted_rand_score(planted, full.full_labels)
    fit_freq = plan.col_fit.freq.astype(float)
    h_syn = hierarchical(D, 6, fit_freq)
    sub_cost = substitution_cost_matrix(td, cfg)
    cfg_small = _cfg_with(cfg, max_n=120, reduction="collapse_then_subsample")
    plan2 = plan_reduction(td, cfg_small, make_rng(cfg, "demo-plan2"))
    D2 = bd(plan2.col_fit, cfg_small, sub_cost)
    full2 = cluster_full(plan2, D2, cfg_small, 5, make_rng(cfg, "demo-full2"), sub_cost)
    D_all = bd(plan2.col_all, cfg, sub_cost)                       # the whole thing, built directly, as the reference
    med_all = plan2.fit_unit_idx[full2.fit_result.medoid_idx]
    order2 = np.argsort(full2.fit_result.medoid_idx, kind="stable")
    expected2 = order2[np.argmin(D_all[:, med_all][:, order2], axis=1)]
    D3 = bd(plan2.col_fit, cfg_small)                              # default costs (None)
    full3 = cluster_full(plan2, D3, cfg_small, 5, make_rng(cfg, "demo-full2"), None)
    D_all3 = bd(plan2.col_all, cfg, _costs_from_collapsed(plan2.col_fit, cfg))
    med_all3 = plan2.fit_unit_idx[full3.fit_result.medoid_idx]
    order3 = np.argsort(full3.fit_result.medoid_idx, kind="stable")
    expected3 = order3[np.argmin(D_all3[:, med_all3][:, order3], axis=1)]
    not_med2 = np.setdiff1d(np.arange(plan2.n_units_all), med_all)
    not_med3 = np.setdiff1d(np.arange(plan2.n_units_all), med_all3)
    plan_s = plan_reduction(td, _cfg_with(cfg, max_n=100, reduction="subsample"), make_rng(cfg, "demo-plan3"))
    D_s = bd(plan_s.col_fit, cfg, sub_cost)
    full_s = cluster_full(plan_s, D_s, cfg, 4, make_rng(cfg, "demo-full3"), sub_cost)
    D_all_s = bd(plan_s.col_all, cfg, sub_cost)
    med_s = plan_s.fit_unit_idx[full_s.fit_result.medoid_idx]
    order_s = np.argsort(full_s.fit_result.medoid_idx, kind="stable")
    expected_s = order_s[np.argmin(D_all_s[:, med_s][:, order_s], axis=1)]
    # attribute inputs
    sub_td = td.subset(np.arange(500))
    sub_td.attrs["sector"] = sub_td.attrs["sector"].astype(object)
    cfg_attr = _cfg_with(cfg, attribute_inputs=["sector"], max_n=60, reduction="collapse_then_subsample")
    plan_a = plan_reduction(sub_td, cfg_attr, make_rng(cfg, "demo-plan-a"))
    sc_a = substitution_cost_matrix(sub_td, cfg)
    D_a = bd(plan_a.col_fit, cfg_attr, sc_a)
    full_a = cluster_full(plan_a, D_a, cfg_attr, 3, make_rng(cfg, "demo-full-a"), sc_a)
    D_all_a = bd(plan_a.col_all, _cfg_with(cfg, attribute_inputs=["sector"]), sc_a)
    med_a = plan_a.fit_unit_idx[full_a.fit_result.medoid_idx]
    order_a = np.argsort(full_a.fit_result.medoid_idx, kind="stable")
    expected_a = order_a[np.argmin(D_all_a[:, med_a][:, order_a], axis=1)]
    not_med_s = np.setdiff1d(np.arange(plan_s.n_units_all), med_s)
    not_med_a = np.setdiff1d(np.arange(plan_a.n_units_all), med_a)
    cfg_bad = Config({**cfg.to_dict(), "clustering": {**cfg.to_dict()["clustering"], "primary": "hierarchical"}}, cfg.root)
    # ----- benchmark
    bench = benchmark_clustering(plan, cfg, [60, 200, plan.col_fit.u, 10 ** 6], make_rng(cfg, "demo-bench"))
    print(bench.round(3).to_string(index=False))
    ok_rows = bench[bench["status"] == "ok"]
    t0 = time.perf_counter()
    kmedoids(D, 6, int(cfg.clustering.n_init), int(cfg.clustering.max_iter), make_rng(cfg, "time"), fit_freq)
    t_pam = time.perf_counter() - t0
    print(f"synthetic units={plan.col_fit.u}, individuals={td.n}; PAM k=6 {t_pam:.2f}s; planted-structure ARI={ari_planted:.3f} "
          f"(hierarchical k=6 vs PAM ARI={adjusted_rand_score(full.fit_result.labels, h_syn.labels):.3f})")

    # ----- v1.6: who may be a medoid
    rc = np.random.default_rng(23)
    Xc = rc.normal(size=(14, 2))
    Dc14 = _euclid(Xc)
    fc14 = rc.integers(1, 4, size=14).astype(float)
    cand14 = np.zeros(14, dtype=bool)
    cand14[[0, 2, 3, 5, 8, 9, 12, 13]] = True
    r_all = kmedoids(Dc14, 3, 10, 100, make_rng(cfg, "cand"), fc14)
    r_true = kmedoids(Dc14, 3, 10, 100, make_rng(cfg, "cand"), fc14, np.ones(14, dtype=bool))
    r_cand = kmedoids(Dc14, 3, 10, 100, make_rng(cfg, "cand"), fc14, cand14)
    opt_cand = min(_wcost(Dc14, fc14, c) for c in itertools.combinations(np.flatnonzero(cand14), 3))
    swap_ok = True
    for h in np.flatnonzero(cand14):
        if h in r_cand.medoid_idx:
            continue
        for s_ in range(3):
            new = list(r_cand.medoid_idx)
            new[s_] = h
            swap_ok &= _wcost(Dc14, fc14, new) >= _wcost(Dc14, fc14, r_cand.medoid_idx) - 1e-9
    b_cand = _build(Dc14, fc14, 3, cand14)
    lab14 = np.array([0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 2, 0, 1])
    mfl_free = medoids_from_labels(Dc14, lab14, fc14)
    mfl_cand = medoids_from_labels(Dc14, lab14, fc14, cand14)
    only_two = np.zeros(14, dtype=bool)
    only_two[[0, 3]] = True                                    # clusters 0 and 1 have a candidate, cluster 2 has none
    mfl_fb = medoids_from_labels(Dc14, lab14, fc14, only_two)
    h_free = hierarchical(Dc14, 3, fc14)
    h_cand = hierarchical(Dc14, 3, fc14, candidates=cand14)
    col_c = CollapsedTrajectories(
        unique_states=np.array([[0, 0, 1, 1], [0, 1, 1, 1], [0, 0, -1, 1], [0, -1, 1, 1], [-1, 0, 1, 1], [0, 0, 1, -1]], dtype=np.int8),
        freq=np.ones(6, dtype=np.int64), inverse=np.arange(6), attr_cols=[], unique_attrs=None)
    d_cfg = cfg.to_dict()

    def cfg_mm(value: Any) -> Config:
        return Config({**d_cfg, "clustering": {**d_cfg["clustering"], "medoid_min_observed": value}}, cfg.root)

    mc_all, thr_all = medoid_candidates(col_c, cfg_mm("all"), 2)
    mc_none, thr_none = medoid_candidates(col_c, cfg_mm(None), 2)
    mc_three, thr_three = medoid_candidates(col_c, cfg_mm(3), 2)
    with warnings.catch_warnings(record=True) as w_rel:
        warnings.simplefilter("always")
        mc_rel, thr_rel = medoid_candidates(col_c, cfg_mm("all"), 4)
    cfg_free = cfg_mm(None)
    full_free = cluster_full(plan, D, cfg_free, 6, make_rng(cfg, "demo-full"))
    ari_free = adjusted_rand_score(planted, full_free.full_labels)
    obs_free = float((full_free.medoid_states >= 0).sum(axis=1).mean())
    cfg_rel = cfg_mm("all")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        plan_few = plan_reduction(td.subset(np.arange(40)), cfg_rel, make_rng(cfg, "few"))

    checks = {
        "PAM: blobs, cost equals the exhaustive optimum": abs(r_b.cost - opt_b) < 1e-9 and r_b.converged and r_b.method == "kmedoids",
        "PAM: weighted optimum on units equals the optimum on expanded individuals": abs(opt_units - opt_exp) < 1e-9 and abs(r_u.cost - opt_units) < 1e-9,
        "PAM: SWAP result is a local optimum under every single swap (brute force)": r_r.converged and _is_swap_optimal(Dr, fr, r_r.medoid_idx),
        "PAM: reported cost equals the independent weighted cost": abs(r_r.cost - _wcost(Dr, fr, r_r.medoid_idx)) < 1e-9
            and abs(r_r.cost - float((fr * Dr[r_r.medoid_idx[r_r.labels], np.arange(60)]).sum())) < 1e-9,
        "PAM: BUILD equals the plain-Python reference": build_fast.tolist() == build_ref,
        "PAM: max_iter=1 from a poor start reports not converged, more iterations converge": (not c1) and it1 == 1 and c_end and it_end > 1
            and _wcost(Dr, fr, m_end) < _wcost(Dr, fr, m1),
        "PAM: k=1 is the weighted 1-medoid, k=n has cost 0": r_k1.medoid_idx[0] == int(np.argmin((Dr * fr[None, :]).sum(1))) and r_kn.cost == 0 and r_kn.k == 10,
        "PAM: labels canonical (descending count), medoid of label c is in c, no empty cluster": canonical_ok(r_r, fr) and canonical_ok(r_b, fb) and canonical_ok(r_u, fu.astype(float)),
        "PAM: n_init=1 draws nothing from rng; same seed gives the same result": state0 == state1
            and np.array_equal(r_a1.labels, r_a2.labels) and np.array_equal(r_a1.medoid_idx, r_a2.medoid_idx) and r_a1.cost == r_a2.cost,
        "PAM: twins at distance 0 never leave a cluster empty": canonical_ok(r_t3, np.ones(6)) and canonical_ok(r_t4, np.ones(6)) and r_t3.cost == 0 and r_t4.cost == 0,
        "PAM: bad inputs raise": raises(ValueError, lambda: kmedoids(Dr, 0, 1, 1, g)) and raises(ValueError, lambda: kmedoids(Dr, 61, 1, 1, g))
            and raises(ValueError, lambda: kmedoids(Dr, 3, 0, 1, g)) and raises(ValueError, lambda: kmedoids(Dr, 3, 1, 0, g))
            and raises(ValueError, lambda: kmedoids(Dr + np.triu(np.ones((60, 60)), 1), 3, 1, 1, g))
            and raises(ValueError, lambda: kmedoids(Dr, 3, 1, 1, g, -np.ones(60))) and raises(ValueError, lambda: kmedoids(Dr, 3, 1, 1, g, np.ones(5)))
            and raises(ValueError, lambda: kmedoids(np.where(np.eye(60) > 0, 0, np.nan), 3, 1, 1, g)),
        "medoids_from_labels equals the plain-Python reference; ties go to the lowest index": mfl.tolist() == [int(x) for x in ref_mfl]
            and mfl_tie.tolist() == [0, 3] and raises(ValueError, lambda: medoids_from_labels(Dr, np.where(lab_r == 3, 5, lab_r)))
            and raises(ValueError, lambda: medoids_from_labels(Dr, lab_r[:-1])),
        "hierarchical: merge heights equal scipy average linkage on the expanded individuals": heights_ok,
        "hierarchical: every cut k=1..8 equals scipy's partition (ARI 1)": part_ok,
        "hierarchical: linkage rows are valid (heights non-decreasing, ids ordered, individual counts)": counts_ok
            and bool(np.all(np.diff(Zo[:, 2]) >= -1e-12)) and bool(np.all(Zo[:, 0] < Zo[:, 1])) and Zo[-1, 3] == f25.sum(),
        "hierarchical: tie-heavy fixture equals the brute-force version of the same rule (bitwise)": ties_zero > 0 and np.array_equal(Zg, Zg_ref)
            and np.array_equal(weighted_average_linkage(Dg2, fg2), _ref_linkage(Dg2, fg2)),
        "hierarchical: result is deterministic": np.array_equal(Zg, weighted_average_linkage(Dg, fg)),
        "hierarchical: cut labels, canonical numbering, medoids, PAM-comparable cost": canonical_ok(h25, f25.astype(float)) and h25.method == "hierarchical"
            and h25.n_iter == 21 and abs(h25.cost - sum(f25[i] * D25[i, h25.medoid_idx[h25.labels[i]]] for i in range(25))) < 1e-9
            and h25.medoid_idx.tolist() == medoids_from_labels(D25, h25.labels, f25.astype(float)).tolist(),
        "hierarchical: blobs agree with PAM (ARI 1) and cost is not below the optimum": adjusted_rand_score(h_b.labels, r_b.labels) == 1.0 and h_b.cost >= opt_b - 1e-9,
        "hierarchical: edge cases (two units, k=1, k=u)": Z2.shape == (1, 4) and Z2[0].tolist() == [0, 1, 2.0, 4.0] and set(h_k1.labels) == {0}
            and h_ku.labels.tolist() == np.lexsort((np.arange(10), -fu)).argsort().tolist() and cut_linkage(np.zeros((0, 4)), 1, 1).tolist() == [0],
        "hierarchical and cut: bad inputs raise": raises(ConfigError, lambda: hierarchical(Du, 3, None, "ward")) and raises(ValueError, lambda: hierarchical(Du, 3, np.zeros(10)))
            and raises(ValueError, lambda: cut_linkage(Zo, 0, 25)) and raises(ValueError, lambda: cut_linkage(Zo[:-1], 3, 25))
            and raises(ValueError, lambda: cut_linkage(np.vstack([Zo[:1], Zo[:1]]), 23, 25)),
        "cluster_full (collapse): unit labels are the fit labels and the object validates": plan.mode_used == "collapse" and np.array_equal(full.unit_labels, full.fit_result.labels)
            and np.array_equal(full.full_labels, full.fit_result.labels[plan.col_all.inverse]) and full.medoid_states.shape == (6, td.T) and full.medoid_attrs is None,
        "cluster_full (collapse): recovers the planted pathways on synthetic data (ARI > 0.5; a sanity check, not a result)": ari_planted > 0.5,
        "cluster_full (collapse_then_subsample): every non-fit unit takes its nearest medoid under the whole-data matrix": plan2.mode_used == "collapse_then_subsample"
            and plan2.n_units_fit < plan2.n_units_all and np.array_equal(full2.unit_labels[not_med2], expected2[not_med2]) and len(full2.full_labels) == td.n
            and np.array_equal(full2.unit_labels[med_all], np.arange(5)),
        "cluster_full: sub_cost=None uses the costs D was built with (default from col_fit)": np.array_equal(full3.unit_labels[not_med3], expected3[not_med3]),
        "cluster_full (subsample): identity units, extension equals the whole-data nearest medoid": plan_s.mode_used == "subsample" and np.array_equal(full_s.unit_labels[not_med_s], expected_s[not_med_s]) and np.array_equal(full_s.unit_labels[med_s], np.arange(4)),
        "cluster_full: attribute inputs give medoid_attrs and extend with them": full_a.medoid_attrs is not None and full_a.medoid_attrs.shape == (3, 1)
            and np.array_equal(full_a.unit_labels[not_med_a], expected_a[not_med_a]),
        "cluster_full: bad inputs raise": raises(ValueError, lambda: cluster_full(plan, D[:-1, :-1], cfg, 3, g)) and raises(ValueError, lambda: cluster_full(plan, D, cfg, 0, g))
            and raises(ValueError, lambda: cluster_full(plan, D, cfg, plan.col_fit.u + 1, g)) and raises(ConfigError, lambda: cluster_full(plan, D, cfg_bad, 3, g)),
        "benchmark: skips oversized and tiny sizes, measures the rest, total within the cap": list(bench["status"].str.startswith("skipped")) == [False, False, False, True]
            and len(ok_rows) == 3 and bool((ok_rows["total_peak_mb"] <= ok_rows["cap_mb"]).all()) and bool((ok_rows["pam_seconds"] > 0).all())
            and bool((ok_rows["hier_extra_peak_mb"] <= 1.2 * ok_rows["matrix_mb"] + 1.0).all()),
        "v1.6 kmedoids: candidates all True is identical to None (labels, medoids, cost)": np.array_equal(r_all.labels, r_true.labels)
            and np.array_equal(r_all.medoid_idx, r_true.medoid_idx) and r_all.cost == r_true.cost,
        "v1.6 kmedoids: medoids come only from the candidates, cost reaches the restricted exhaustive optimum, no candidate swap improves": bool(cand14[r_cand.medoid_idx].all())
            and abs(r_cand.cost - opt_cand) < 1e-9 and swap_ok and r_cand.cost >= r_all.cost - 1e-9 and bool(cand14[b_cand].all()),
        "v1.6 kmedoids: every unit is still clustered and costed (non-candidates are assigned)": len(r_cand.labels) == 14 and len(np.unique(r_cand.labels)) == 3
            and abs(r_cand.cost - float((fc14 * Dc14[r_cand.medoid_idx[r_cand.labels], np.arange(14)]).sum())) < 1e-9,
        "v1.6 kmedoids: bad candidate masks raise": raises(ValueError, lambda: kmedoids(Dc14, 3, 2, 10, g, fc14, np.ones(13, dtype=bool)))
            and raises(ValueError, lambda: kmedoids(Dc14, 3, 2, 10, g, fc14, np.ones(14))) and raises(ValueError, lambda: kmedoids(Dc14, 3, 2, 10, g, fc14, only_two)),
        "v1.6 medoids_from_labels: candidate members only, falls back to all members when a cluster has none": bool(cand14[mfl_cand[[0, 1, 2]]].all())
            and all(lab14[m] == c for c, m in enumerate(mfl_cand)) and bool(only_two[mfl_fb[0]]) and bool(only_two[mfl_fb[1]]) and lab14[mfl_fb[2]] == 2
            and np.array_equal(mfl_free, medoids_from_labels(Dc14, lab14, fc14, np.ones(14, dtype=bool))) and all(lab14[m] == c for c, m in enumerate(mfl_free)),
        "v1.6 hierarchical: candidates change only the medoids, never the dendrogram cut": np.array_equal(h_free.labels, h_cand.labels) and bool(cand14[h_cand.medoid_idx].all()),
        "v1.6 medoid_candidates: all, null and integer settings, threshold returned": np.array_equal(mc_all, (col_c.unique_states >= 0).all(axis=1)) and thr_all == 4
            and mc_none.all() and thr_none == 0 and np.array_equal(mc_three, (col_c.unique_states >= 0).sum(axis=1) >= 3) and thr_three == 3,
        "v1.6 medoid_candidates: too few complete units lowers the threshold with a UserWarning": thr_rel == 3 and int(mc_rel.sum()) >= 4 and any(issubclass(w.category, UserWarning) for w in w_rel),
        "v1.6 cluster_full: default config draws every medoid from fully observed units and recovers the planted pathways better": bool((full.medoid_states >= 0).all())
            and obs_free < col_c.T and ari_planted > ari_free + 0.03,
        "v1.6 cluster_full: medoid choice follows the setting (null allows medoids with gaps; a tiny sample still plans)": bool((full_free.medoid_states >= 0).sum(axis=1).mean() < full.medoid_states.shape[1])
            and plan_few.n_units_fit >= 1,
    }
    for name, ok in checks.items():
        print(f"  demo check [{'ok' if ok else 'FAILED'}]: {name}")
    if not all(checks.values()):
        return 1
    print(f"Demo checks passed ({len(checks)}). All data above is SYNTHETIC or hand-built.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_demo())
