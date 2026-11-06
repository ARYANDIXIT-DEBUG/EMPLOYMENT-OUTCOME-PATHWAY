"""Distances between trajectories, and the plan that keeps the distance matrix inside a memory cap.

Why this file exists: clustering needs a dissimilarity between every pair of trajectories, and an
(m x m) float64 matrix grows with the square of m. So this module does two jobs: it defines the
distance, and it decides BEFORE any matrix exists how many units the matrix may have
(`plan_reduction`), then refuses to build anything larger (`build_distance` raises MemoryCapError).

Design choices worth defending in a viva:
  * Dynamic Hamming is the primary distance (`distance.name: dynamic_hamming`). Every person has the
    same T time points, so two sequences can be compared position by position; edit-distance
    alignment (optimal matching) would let a state "slide" in time, which is not what a survey visit
    schedule means. Optimal matching is provided as a sensitivity alternative, not the default.
  * Substitution costs are TRATE: c(i,j) = 2 - (p(i->j) + p(j->i)) for i != j, 0 on the diagonal, where
    p is the observed one-step transition probability (adjacent observed points, unweighted). Two states
    that people often move between are close; states that never exchange people are far (cost near 2).
    A state with no observed outgoing moves has p = 0 (no evidence of closeness). `constant` (cost 1)
    is available as `distance.substitution: constant`. The costs are an ESTIMATE from the data being
    clustered; in subsample mode pass the same `sub_cost` (estimated from all individuals) to
    `build_distance` and `distance_to_medoids`, so the matrix and the extension use one metric.
  * Missing data: the primary policy is pairwise availability. For a pair, only time points observed in
    BOTH count, and the distance is the (time-weighted) MEAN substitution cost over them, so pairs
    with different overlaps are on one scale. A pair with fewer than `missing.min_overlap` common
    points is "undefined" and gets the maximum substitution cost (treated as maximally dissimilar); a
    warning reports how many. Identical sequences are always at distance 0. Two DISTINCT sequences can
    also be at distance 0 (they agree wherever both are observed): collapsing merges only identical
    rows. The other missing policies of `missing_data.apply_state_policy` change the DATA before it
    reaches this module (complete cases, forward fill, an "unobserved" state); the distance itself
    always uses jointly observed points, which does nothing when none are missing.
  * Optimal matching compacts each sequence to its own observed states (unobserved positions are
    dropped), aligns with substitution costs and a constant indel cost, and divides by the longer
    compacted length so the scale matches dynamic Hamming. With TRATE costs up to 2, an indel below 1
    would let two indels beat a substitution; use indel >= max(cost) / 2.
  * Attribute inputs (`distance.attribute_inputs`, empty by default) join the distance as Gower
    features. Every time point and every attribute counts as one equally weighted feature:
    combined = (T * state_distance / scale + A * gower) / (T + A), in [0, 1]. Numeric attributes must be
    float; ranges are taken from the units passed to the function.
  * The matrix is built blockwise (rows per block = `distance.block_rows`, lowered automatically when the
    memory estimate leaves too little headroom), upper triangle only and mirrored, so symmetry is exact
    and the working memory is a few block-sized arrays on top of the matrix itself. Measured with
    tracemalloc on synthetic data (dynamic Hamming and optimal matching, peak_factor 1.2 to 3, 10 to
    2000 units) the peak stayed below `estimate_matrix_mb` for every matrix of about 300 units or more,
    and exceeded it by at most 0.06 MB (a fixed overhead) for smaller ones. The benchmark re-measures
    this on your machine.
  * `plan_reduction` is O(n) in memory and builds no matrix. In `collapse_then_subsample` mode the
    largest random sample whose collapsed unit count fits is found exactly: take a random permutation
    of individuals, count how many distinct units each prefix contains (that count only grows), and
    keep the longest prefix with at most `effective_max_units` units. This is the result a binary
    search over the prefix length would reach, computed in one pass.
  * Protected attributes (sex, social group, religion) are blocked at run time here too:
    `build_distance` and `gower_matrix` raise FairnessError.

Dependency rule: imports only `config`, the shared types and `trajectories`. The smoke demo imports
`synthetic_data` inside the demo function.

Run the smoke demo with:  python -m src.distances
"""
from __future__ import annotations

import math
import time
import tracemalloc
import warnings
from typing import Any

import numpy as np
import pandas as pd

from . import CollapsedTrajectories, ReductionPlan, TrajectoryData
from .config import PROTECTED_ROLES, Config, ConfigError, FairnessError, assert_no_protected, load_config, make_rng
from .trajectories import CollapseRefused, collapse_trajectories, complete_case_mask, identity_collapse

__all__ = [
    "MemoryCapError",
    "substitution_cost_matrix",
    "hamming_matrix",
    "dynamic_hamming_matrix",
    "optimal_matching_matrix",
    "gower_matrix",
    "effective_max_units",
    "estimate_matrix_mb",
    "plan_reduction",
    "build_distance",
    "distance_to_medoids",
    "benchmark_distance",
]

STATE_POLICIES = ("pairwise_available", "complete_cases_only", "forward_fill", "missing_as_state")
SUBSTITUTIONS = ("trate", "constant")
GOWER_BLOCK = 256        # rows per block for the public gower_matrix (it has no block_rows argument)
BLOCK_TEMP_ARRAYS = 16   # float64 arrays of block size alive at once in the worst kernel (measured, with margin)


class MemoryCapError(Exception):
    """The requested distance matrix would exceed the configured memory cap."""


# ---------------------------------------------------------------------------------------------
# Memory arithmetic
# ---------------------------------------------------------------------------------------------
def estimate_matrix_mb(m: int, cfg: Config) -> float:
    """Estimated peak MB for an (m x m) float64 matrix: peak_factor * m * m * 8 / 2**20."""
    return float(cfg.distance.peak_factor) * float(m) * float(m) * 8.0 / 2 ** 20


def effective_max_units(cfg: Config) -> int:
    """Largest number of units a matrix may have: min(distance.max_n, the largest m whose estimate fits the cap)."""
    cap = float(cfg.distance.max_matrix_mb)
    m = int(math.isqrt(int(cap * 2 ** 20 // (float(cfg.distance.peak_factor) * 8.0))))
    while m > 0 and estimate_matrix_mb(m, cfg) > cap:
        m -= 1
    while estimate_matrix_mb(m + 1, cfg) <= cap:
        m += 1
    return max(1, min(int(cfg.distance.max_n), m))


# ---------------------------------------------------------------------------------------------
# Substitution costs
# ---------------------------------------------------------------------------------------------
def _costs_from_counts(counts: np.ndarray, kind: str) -> np.ndarray:
    K = counts.shape[0]
    if kind == "constant":
        return 1.0 - np.eye(K)
    rows = counts.sum(axis=1, keepdims=True)
    P = np.divide(counts, rows, out=np.zeros_like(counts, dtype=np.float64), where=rows > 0)
    C = 2.0 - (P + P.T)                       # (P + P.T) is exactly symmetric, so C is too
    np.fill_diagonal(C, 0.0)
    return C


def _substitution_kind(cfg: Config) -> str:
    kind = str(cfg.distance.substitution)
    if kind not in SUBSTITUTIONS:
        raise ConfigError(f"distance.substitution must be one of {SUBSTITUTIONS}, got {kind!r}")
    return kind


def substitution_cost_matrix(td: TrajectoryData, cfg: Config) -> np.ndarray:
    """(K,K) symmetric substitution costs, zero diagonal, estimated from all individuals in `td`.

    `distance.substitution: trate` gives c(i,j) = 2 - (p(i->j) + p(j->i)) with p the unweighted
    one-step transition probability between ADJACENT observed time points (survey weights are not
    used, so the metric does not depend on them); a state with no observed outgoing moves has p = 0.
    Costs lie in [0, 2]. `constant` gives 1 for every pair of different states. K is the number of
    states of `td` (an "unobserved" state added by a sensitivity policy is included).
    """
    kind = _substitution_kind(cfg)
    K = len(td.state_names)
    S = td.states
    counts = np.zeros((K, K))
    if td.T >= 2:
        a, b = S[:, :-1], S[:, 1:]
        ok = (a >= 0) & (b >= 0)
        counts = np.bincount(a[ok].astype(np.int64) * K + b[ok].astype(np.int64), minlength=K * K).reshape(K, K).astype(np.float64)
    return _costs_from_counts(counts, kind)


def _costs_from_collapsed(col: CollapsedTrajectories, cfg: Config) -> np.ndarray:
    """The same estimate from unique rows weighted by `freq` (equal to the individual-level estimate)."""
    S = col.unique_states
    K = max(len(cfg.to_dict()["states"]), int(S.max()) + 1 if S.size else 1)
    counts = np.zeros((K, K))
    if S.shape[1] >= 2:
        a, b = S[:, :-1], S[:, 1:]
        ok = (a >= 0) & (b >= 0)
        w = np.broadcast_to(col.freq.astype(np.float64)[:, None], a.shape)[ok]
        counts = np.bincount(a[ok].astype(np.int64) * K + b[ok].astype(np.int64), weights=w, minlength=K * K).reshape(K, K)
    return _costs_from_counts(counts, _substitution_kind(cfg))


def _check_cost(C: np.ndarray, max_code: int) -> np.ndarray:
    C = np.asarray(C, dtype=np.float64)
    if C.ndim != 2 or C.shape[0] != C.shape[1]:
        raise ValueError(f"sub_cost must be a square matrix, got shape {C.shape}")
    if C.shape[0] < max_code + 1:
        raise ValueError(f"sub_cost has {C.shape[0]} states but the data use state code {max_code}")
    if not np.all(np.isfinite(C)) or (C < 0).any():
        raise ValueError("sub_cost must be finite and non-negative")
    if not np.array_equal(C, C.T) or np.any(np.diag(C) != 0):
        raise ValueError("sub_cost must be exactly symmetric with a zero diagonal")
    return C


# ---------------------------------------------------------------------------------------------
# Kernels (private): one block of the distance between two sets of rows
# ---------------------------------------------------------------------------------------------
def _states_array(states: Any) -> np.ndarray:
    S = np.asarray(states)
    if S.ndim != 2:
        raise ValueError(f"states must be two-dimensional (units, T), got shape {S.shape}")
    if S.size and (S.min() < -2 or S.max() > 127):
        raise ValueError("state codes must lie in [-2, 127]")
    return np.ascontiguousarray(S.astype(np.int8, copy=False))


def _check_policy(missing_policy: str) -> None:
    if missing_policy not in STATE_POLICIES:
        raise ValueError(f"missing_policy must be one of {STATE_POLICIES}, got {missing_policy!r}")


def _compact(S: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Left-pack each row's observed states (unobserved dropped); pad with 0. Returns (packed, lengths)."""
    obs = S >= 0
    order = np.argsort(~obs, axis=1, kind="stable")
    packed = np.take_along_axis(np.where(obs, S, 0), order, axis=1).astype(np.int64)
    return packed, obs.sum(axis=1).astype(np.int64)


def _prep(S: np.ndarray, kind: str) -> dict[str, Any]:
    out: dict[str, Any] = {"S": S}
    if kind == "om":
        out["X"], out["L"] = _compact(S)
    return out


def _hamming_block(Sa: np.ndarray, Sb: np.ndarray, C: np.ndarray, w: np.ndarray, min_overlap: int, cmax: float) -> tuple[np.ndarray, np.ndarray]:
    """(distance, undefined) for rows Sa x rows Sb: weighted mean substitution cost over jointly observed points."""
    Ba, Bb, T = len(Sa), len(Sb), Sa.shape[1]
    num = np.zeros((Ba, Bb))
    den = np.zeros((Ba, Bb))
    cnt = np.zeros((Ba, Bb), dtype=np.int16)
    tmp = np.empty((Ba, Bb))
    for t in range(T):
        a, b = Sa[:, t], Sb[:, t]
        oa, ob = a >= 0, b >= 0
        both = oa[:, None] & ob[None, :]
        c = C[np.where(oa, a, 0)[:, None], np.where(ob, b, 0)[None, :]]
        np.multiply(c, both, out=c)
        c *= w[t]
        num += c
        np.multiply(both, w[t], out=tmp)
        den += tmp
        cnt += both
    del c, tmp
    ok = (cnt >= min_overlap) & (den > 0)
    del cnt
    out = np.full((Ba, Bb), cmax)
    np.divide(num, den, out=out, where=ok)
    del num, den
    same = (Sa[:, None, :] == Sb[None, :, :]).all(axis=2)
    out[same] = 0.0
    return out, ~ok & ~same


def _om_block(Xa: np.ndarray, La: np.ndarray, Xb: np.ndarray, Lb: np.ndarray, C: np.ndarray, indel: float) -> np.ndarray:
    """Normalised optimal-matching distance between compacted sequences (rolling DP, one result per pair)."""
    Ba, Bb, T = len(Xa), len(Xb), Xa.shape[1]
    res = np.zeros((Ba, Bb))
    prev = [np.full((Ba, Bb), j * indel) for j in range(T + 1)]

    def capture(i: int, row: list[np.ndarray]) -> None:
        for j in range(T + 1):
            sel = (La[:, None] == i) & (Lb[None, :] == j)
            if sel.any():
                res[sel] = row[j][sel]

    capture(0, prev)
    for i in range(1, T + 1):
        cur = [np.full((Ba, Bb), i * indel)]
        xa = Xa[:, i - 1][:, None]
        for j in range(1, T + 1):
            sub = C[xa, Xb[:, j - 1][None, :]]
            cur.append(np.minimum(np.minimum(prev[j] + indel, cur[j - 1] + indel), prev[j - 1] + sub))
        capture(i, cur)
        prev = cur
    longest = np.maximum(La[:, None], Lb[None, :])
    out = np.zeros((Ba, Bb))
    np.divide(res, longest, out=out, where=longest > 0)
    return out


# ---------------------------------------------------------------------------------------------
# Attribute (Gower) part (private)
# ---------------------------------------------------------------------------------------------
def _is_null(x: Any) -> bool:
    return x is None or (isinstance(x, (float, np.floating)) and bool(np.isnan(x)))


def _attr_prep(a: np.ndarray, b: np.ndarray | None, kinds: list[str] | None = None) -> dict[str, Any]:
    """Per attribute: numeric (float values, range from `a`) or categorical (shared integer codes, -1 missing)."""
    a = np.asarray(a, dtype=object)
    bb = a if b is None else np.asarray(b, dtype=object)
    if a.ndim != 2 or bb.ndim != 2 or a.shape[1] != bb.shape[1]:
        raise ValueError("attribute arrays must be two-dimensional with the same number of columns")
    feats = []
    for j in range(a.shape[1]):
        va, vb = a[:, j], bb[:, j]
        vals = [x for x in np.concatenate([va, vb]) if not _is_null(x)]
        if kinds is not None:
            numeric = kinds[j] == "numeric"
        else:
            numeric = bool(vals) and all(isinstance(x, (float, np.floating)) for x in vals)
        if numeric:
            xa = np.array([np.nan if _is_null(x) else float(x) for x in va])
            xb = xa if b is None else np.array([np.nan if _is_null(x) else float(x) for x in vb])
            seen = xa[~np.isnan(xa)]
            rng = float(seen.max() - seen.min()) if seen.size else 0.0
            feats.append({"numeric": True, "a": xa, "b": xb, "range": rng})
        else:
            codes, _ = pd.factorize(pd.Series(np.concatenate([va, vb]), dtype="object"))
            codes = codes.astype(np.int64)
            feats.append({"numeric": False, "a": codes[:len(va)], "b": codes[len(va):] if b is not None else codes[:len(va)]})
    return {"feats": feats, "n_feat": len(feats)}


def _gower_block(P: dict[str, Any], w: np.ndarray, i0: int, i1: int, j0: int, j1: int) -> tuple[np.ndarray, np.ndarray]:
    """(gower distance, rows-equal flag) between rows i0:i1 of side A and rows j0:j1 of side B."""
    shape = (i1 - i0, j1 - j0)
    num, den = np.zeros(shape), np.zeros(shape)
    same = np.ones(shape, dtype=bool)
    for f, wt in zip(P["feats"], w):
        xa, xb = f["a"][i0:i1, None], f["b"][None, j0:j1]
        if f["numeric"]:
            na, nb = np.isnan(xa), np.isnan(xb)
            avail = ~na & ~nb
            diff = np.zeros(shape) if f["range"] == 0 else np.where(avail, np.abs(np.where(na, 0, xa) - np.where(nb, 0, xb)) / f["range"], 0.0)
            same &= (avail & (xa == xb)) | (na & nb)
        else:
            avail = (xa >= 0) & (xb >= 0)
            diff = np.where(avail, (xa != xb).astype(np.float64), 0.0)
            same &= xa == xb
        num += wt * diff
        den += wt * avail
    out = np.ones(shape)
    np.divide(num, den, out=out, where=den > 0)
    return out, same


def _gower_weights(n_feat: int, weights: dict[str, float] | None, names: list[str]) -> np.ndarray:
    w = np.ones(n_feat)
    if weights is not None:
        unknown = sorted(set(weights) - set(names))
        if unknown:
            raise ValueError(f"weights name unknown feature(s) {unknown}")
        for j, nm in enumerate(names):
            w[j] = float(weights.get(nm, 1.0))
    if (w < 0).any() or not np.isfinite(w).all() or w.sum() <= 0:
        raise ValueError("feature weights must be finite, non-negative and not all zero")
    return w


def gower_matrix(df: pd.DataFrame, types: dict[str, str], weights: dict[str, float] | None = None,
                 cfg: Config | None = None) -> np.ndarray:
    """Gower distance (m,m) between the rows of `df` over the features in `types` ("numeric" or "categorical").

    Numeric: |x - y| / range. Categorical: 0 if equal, else 1. A feature missing in either row is left
    out for that pair and the rest are re-normalised; a pair with no jointly available feature is at
    distance 1. Weights default to 1 per feature. Protected attributes raise FairnessError: the role
    names (sex, social_group, religion) are always blocked, and when `cfg` is given the verified column
    names and declared derived features are blocked too (pass `cfg` whenever you have it).
    """
    cols = list(types)
    if cfg is not None:
        assert_no_protected(cols, cfg, "gower_matrix")
    bad = sorted(c for c in cols if str(c).lower() in PROTECTED_ROLES)
    if bad:
        raise FairnessError(f"protected attribute(s) {bad} may not be used as input to gower_matrix")
    for c, k in types.items():
        if k not in ("numeric", "categorical"):
            raise ValueError(f"types[{c!r}] must be 'numeric' or 'categorical', got {k!r}")
        if c not in df.columns:
            raise ValueError(f"column {c!r} is not in the data frame")
    m = len(df)
    P = _attr_prep(df[cols].to_numpy(dtype=object), None, [types[c] for c in cols])
    w = _gower_weights(len(cols), weights, cols)
    D = np.zeros((m, m))
    for i0 in range(0, m, GOWER_BLOCK):
        i1 = min(i0 + GOWER_BLOCK, m)
        blk, _ = _gower_block(P, w, i0, i1, i0, m)
        D[i0:i1, i0:] = blk
        D[i0:, i0:i1] = blk.T
    np.fill_diagonal(D, 0.0)
    return D


# ---------------------------------------------------------------------------------------------
# Square and rectangular drivers (private)
# ---------------------------------------------------------------------------------------------
class _Spec:
    """Everything that defines one distance: kernel kind, costs, weights, overlap rule and optional attributes."""

    def __init__(self, kind: str, C: np.ndarray, w: np.ndarray, indel: float, min_overlap: int,
                 attr: dict[str, Any] | None = None, attr_w: np.ndarray | None = None) -> None:
        self.kind, self.C, self.w, self.indel, self.min_overlap = kind, C, w, float(indel), int(min_overlap)
        self.cmax = float(C.max()) if C.size else 0.0
        self.attr, self.attr_w = attr, attr_w
        self.scale = max(self.cmax, self.indel) if kind == "om" else self.cmax
        if attr is not None and self.scale <= 0:
            raise ValueError("cannot combine attributes with a state distance whose maximum cost is 0")


def _block(spec: _Spec, A: dict[str, Any], B: dict[str, Any], i0: int, i1: int, j0: int, j1: int) -> tuple[np.ndarray, np.ndarray]:
    if spec.kind == "hamming":
        d, undef = _hamming_block(A["S"][i0:i1], B["S"][j0:j1], spec.C, spec.w, spec.min_overlap, spec.cmax)
    else:
        d = _om_block(A["X"][i0:i1], A["L"][i0:i1], B["X"][j0:j1], B["L"][j0:j1], spec.C, spec.indel)
        undef = np.zeros(d.shape, dtype=bool)
    if spec.attr is None:
        return d, undef
    g, same_attr = _gower_block(spec.attr, spec.attr_w, i0, i1, j0, j1)
    n_state = float(spec.w.sum()) if spec.kind == "hamming" else float(A["S"].shape[1])
    n_attr = float(spec.attr_w.sum())
    out = (n_state * d / spec.scale + n_attr * g) / (n_state + n_attr)
    same_state = (A["S"][i0:i1, None, :] == B["S"][None, j0:j1, :]).all(axis=2)
    out[same_state & same_attr] = 0.0
    return out, undef


def _square(spec: _Spec, S: np.ndarray, block_rows: int) -> np.ndarray:
    m = len(S)
    if block_rows < 1:
        raise ValueError("block_rows must be a positive integer")
    A = _prep(S, spec.kind)
    D = np.zeros((m, m))
    n_undef = 0
    for i0 in range(0, m, block_rows):
        i1 = min(i0 + block_rows, m)
        blk, undef = _block(spec, A, A, i0, i1, i0, m)
        ii = np.arange(i1 - i0)[:, None]
        jj = np.arange(m - i0)[None, :]
        n_undef += int((undef & (jj > ii)).sum())
        D[i0:, i0:i1] = blk.T
        D[i0:i1, i0:] = blk
    np.fill_diagonal(D, 0.0)
    if n_undef:
        warnings.warn(f"{n_undef} of {m * (m - 1) // 2} unit pairs have fewer than {spec.min_overlap} jointly observed "
                      f"time points; they were given the maximum cost ({spec.cmax:g}) as 'maximally dissimilar'",
                      UserWarning, stacklevel=3)
    return D


def _rect(spec: _Spec, Sa: np.ndarray, Sb: np.ndarray, block_rows: int) -> np.ndarray:
    A, B = _prep(Sa, spec.kind), _prep(Sb, spec.kind)
    out = np.zeros((len(Sa), len(Sb)))
    for i0 in range(0, len(Sa), block_rows):
        i1 = min(i0 + block_rows, len(Sa))
        out[i0:i1] = _block(spec, A, B, i0, i1, 0, len(Sb))[0]
    return out


def _safe_block_rows(m: int, cfg: Config) -> int:
    """`distance.block_rows`, lowered if needed so the temporaries fit in the headroom the memory estimate allows.

    The estimate is peak_factor * matrix size, so the headroom beyond the matrix is (peak_factor - 1) * m * m * 8
    bytes; one block row needs about BLOCK_TEMP_ARRAYS * m * 8 bytes of temporaries.
    """
    room = (float(cfg.distance.peak_factor) - 1.0) * m / BLOCK_TEMP_ARRAYS
    return max(1, min(int(cfg.distance.block_rows), int(room)))


def _time_weights(time_weights: Any, T: int) -> np.ndarray:
    if time_weights is None:
        return np.ones(T)
    w = np.asarray(time_weights, dtype=np.float64)
    if w.shape != (T,) or not np.isfinite(w).all() or (w < 0).any() or w.sum() <= 0:
        raise ValueError(f"time_weights must be {T} finite non-negative numbers, not all zero")
    return w


def _min_overlap(min_overlap: int, T: int) -> int:
    if int(min_overlap) != min_overlap or min_overlap < 1:
        raise ValueError(f"min_overlap must be a whole number >= 1, got {min_overlap!r}")
    return min(int(min_overlap), T)


# ---------------------------------------------------------------------------------------------
# Public matrix functions
# ---------------------------------------------------------------------------------------------
def hamming_matrix(states: np.ndarray, missing_policy: str, min_overlap: int, block_rows: int) -> np.ndarray:
    """Plain Hamming distance: the share of jointly observed time points where two sequences differ.

    Cost 1 for any two different states, equal time weights, otherwise as `dynamic_hamming_matrix`
    (mean over jointly observed points; fewer than `min_overlap` common points -> distance 1).
    """
    _check_policy(missing_policy)
    S = _states_array(states)
    K = int(S.max()) + 1 if S.size and S.max() >= 0 else 1
    spec = _Spec("hamming", 1.0 - np.eye(max(K, 1)), np.ones(S.shape[1]), 0.0, _min_overlap(min_overlap, S.shape[1]))
    return _square(spec, S, int(block_rows))


def dynamic_hamming_matrix(states: np.ndarray, sub_cost: np.ndarray, time_weights: np.ndarray | None,
                           missing_policy: str, min_overlap: int, block_rows: int) -> np.ndarray:
    """Dynamic Hamming distance (m,m): weighted mean substitution cost over the time points observed in both rows.

    d(i,j) = sum_t w_t c(s_it, s_jt) / sum_t w_t over t observed in both, with `sub_cost` (K,K),
    `time_weights` (T,) or None for equal weights. Fewer than `min_overlap` jointly observed points
    gives the maximum cost in `sub_cost` and a UserWarning with the count. Identical rows are at 0;
    the result is symmetric with an exactly zero diagonal. `missing_policy` is validated and
    documented in the module docstring: the other policies act on the data before this call.
    """
    _check_policy(missing_policy)
    S = _states_array(states)
    C = _check_cost(sub_cost, int(S.max()) if S.size else 0)
    spec = _Spec("hamming", C, _time_weights(time_weights, S.shape[1]), 0.0, _min_overlap(min_overlap, S.shape[1]))
    return _square(spec, S, int(block_rows))


def optimal_matching_matrix(states: np.ndarray, sub_cost: np.ndarray, indel: float, missing_policy: str,
                            block_rows: int) -> np.ndarray:
    """Optimal-matching (edit) distance (m,m) between each row's observed states, divided by the longer length.

    Unobserved positions are dropped from each row before alignment, so this does NOT use the
    jointly-observed rule; a row with no observed state is at distance `indel` from any row with
    observed states and 0 from another empty row. Insertions and deletions cost `indel` (> 0);
    substitutions cost `sub_cost`. Use indel >= max(sub_cost) / 2 so that two indels never beat a
    substitution. Identical rows are at 0; the result is symmetric with a zero diagonal.
    """
    _check_policy(missing_policy)
    if not np.isfinite(indel) or indel <= 0:
        raise ValueError(f"indel must be a positive number, got {indel!r}")
    S = _states_array(states)
    C = _check_cost(sub_cost, int(S.max()) if S.size else 0)
    spec = _Spec("om", C, np.ones(S.shape[1]), float(indel), 1)
    return _square(spec, S, int(block_rows))


# ---------------------------------------------------------------------------------------------
# Reduction plan
# ---------------------------------------------------------------------------------------------
def _overlap_note(col_fit: CollapsedTrajectories, cfg: Config) -> str:
    if str(cfg.distance.name) == "optimal_matching":
        return "optimal matching compacts each sequence, so the minimum-overlap rule does not apply"
    T = col_fit.T
    p_min = int((col_fit.unique_states >= 0).sum(axis=1).min())
    need = _min_overlap(int(cfg.missing.min_overlap), T)
    if 2 * p_min - T >= need:
        return f"every pair shares at least {need} observed time points (fewest observed per unit: {p_min} of {T})"
    return (f"some pairs may share fewer than {need} observed time points (fewest observed per unit: {p_min} of {T}); "
            "such pairs get the maximum substitution cost")


def plan_reduction(td: TrajectoryData, cfg: Config, rng: np.random.Generator) -> ReductionPlan:
    """Decide which units the distance matrix is built on. O(n) memory; builds NO distance matrix.

    `collapse`: collapse identical rows; if the unit count exceeds `effective_max_units` raise
    MemoryCapError (no fallback; a CollapseRefused from numeric attribute inputs is re-raised).
    `subsample`: a uniform random sample (without replacement, drawn with `rng.choice`) of
    `effective_max_units` individuals, each its own unit; everyone if n fits. `collapse_then_subsample`:
    `collapse` when the collapsed count fits; otherwise the largest uniform random sample of
    individuals (prefix of `rng.permutation(n)`) whose collapsed unit count is at most the limit,
    found exactly in one pass. If collapsing is refused (numeric attribute inputs) this mode and
    `subsample` use identity units. `col_all` always covers every individual; `fit_unit_idx` maps each
    fit unit to its unit in `col_all`. Unit counts and the memory estimate are recorded in the plan.
    """
    mode = str(cfg.distance.reduction)
    eff = effective_max_units(cfg)
    cap = float(cfg.distance.max_matrix_mb)
    n = td.n
    refused: str | None = None
    try:
        col_all = collapse_trajectories(td, cfg)
    except CollapseRefused as exc:
        refused = str(exc)
        if mode == "collapse":
            raise
        col_all = identity_collapse(td, None, cfg)

    if mode == "collapse" or (mode == "collapse_then_subsample" and refused is None and col_all.u <= eff):
        if col_all.u > eff:
            raise MemoryCapError(
                f"collapse needs {col_all.u} units but at most {eff} fit (distance.max_n={cfg.distance.max_n}, "
                f"max_matrix_mb={cap:g}, estimate {estimate_matrix_mb(col_all.u, cfg):.1f} MB); use "
                "distance.reduction: collapse_then_subsample or subsample")
        fit, fit_idx, used = col_all, None, "collapse"
        reason = f"collapse: {n} individuals fit in {col_all.u} units (limit {eff})"
    elif mode == "subsample" or refused is not None:
        used = "subsample"
        if n <= eff:
            idx = np.arange(n, dtype=np.int64)
        else:
            idx = np.sort(rng.choice(n, size=eff, replace=False)).astype(np.int64)
        fit = identity_collapse(td, idx, cfg)
        fit_idx = col_all.inverse[idx]
        reason = (f"subsample: {len(idx)} of {n} individuals, each its own unit (limit {eff})"
                  + (f"; collapsing was refused: {refused}" if refused else ""))
    else:
        used = "collapse_then_subsample"
        perm = rng.permutation(n)
        units_in_order = col_all.inverse[perm]
        _, first_pos = np.unique(units_in_order, return_index=True)
        first_pos.sort()
        p = int(first_pos[eff])                       # position of the (eff+1)-th new unit; u > eff here
        sel = np.sort(perm[:p])
        seen_units = col_all.inverse[sel]
        seen, inv = np.unique(seen_units, return_inverse=True)
        inv = inv.reshape(-1)
        fit = CollapsedTrajectories(
            unique_states=col_all.unique_states[seen], freq=np.bincount(inv, minlength=len(seen)), inverse=inv,
            attr_cols=list(col_all.attr_cols),
            unique_attrs=None if col_all.unique_attrs is None else col_all.unique_attrs[seen])
        fit_idx = seen.astype(np.int64)
        reason = (f"collapse_then_subsample: {col_all.u} units for {n} individuals exceed the limit {eff}; "
                  f"random sample of {p} individuals collapses to {fit.u} units")
    reason += "; " + _overlap_note(fit, cfg)
    return ReductionPlan(
        mode_requested=mode, mode_used=used, col_all=col_all, col_fit=fit, fit_unit_idx=fit_idx,
        n_individuals=int(col_all.n), n_units_all=int(col_all.u), n_units_fit=int(fit.u),
        est_peak_mb=estimate_matrix_mb(fit.u, cfg), cap_mb=cap, max_n=eff, reason=reason)


# ---------------------------------------------------------------------------------------------
# Building the matrix and extending to other units
# ---------------------------------------------------------------------------------------------
def _spec_for(col: CollapsedTrajectories, cfg: Config, sub_cost: np.ndarray | None,
              attr_prep: dict[str, Any] | None = None) -> _Spec:
    name = str(cfg.distance.name)
    S = col.unique_states
    T = S.shape[1]
    max_code = int(S.max()) if S.size else 0
    if name == "hamming":
        C = 1.0 - np.eye(max(len(cfg.to_dict()["states"]), max_code + 1))
    else:
        C = _check_cost(_costs_from_collapsed(col, cfg) if sub_cost is None else sub_cost, max_code)
    policy = str(cfg.missing.policy)
    _check_policy(policy)
    mo = _min_overlap(int(cfg.missing.min_overlap), T)
    kind = "om" if name == "optimal_matching" else "hamming"
    attr, attr_w = None, None
    if attr_prep is not None:
        attr = attr_prep
        attr_w = np.ones(attr_prep["n_feat"])
    return _Spec(kind, C, np.ones(T), float(cfg.distance.indel), mo, attr, attr_w)


def _identical_groups_ok(col: CollapsedTrajectories, D: np.ndarray) -> bool:
    """True if every set of units identical on all inputs (states and attributes) is at distance 0."""
    key = [col.unique_states.astype(np.int64)]
    for j in range(len(col.attr_cols)):
        codes, _ = pd.factorize(pd.Series(col.unique_attrs[:, j], dtype="object"))
        key.append(codes.astype(np.int64).reshape(-1, 1))
    _, inv, counts = np.unique(np.concatenate(key, axis=1), axis=0, return_inverse=True, return_counts=True)
    inv = inv.reshape(-1)
    for g in np.flatnonzero(counts > 1):
        members = np.flatnonzero(inv == g)
        if np.any(D[np.ix_(members, members)] != 0):
            return False
    return True


def build_distance(col_fit: CollapsedTrajectories, cfg: Config, sub_cost: np.ndarray | None = None) -> np.ndarray:
    """The (u,u) float64 distance matrix between the units of `col_fit`, blockwise, under the memory cap.

    Raises MemoryCapError before allocating anything if u exceeds `effective_max_units(cfg)` or the
    estimate exceeds `distance.max_matrix_mb`, FairnessError if a protected attribute is among
    `col_fit.attr_cols`. `distance.block_rows` is an upper bound: rows per block are lowered when the
    memory estimate leaves too little headroom for the block temporaries. The distance is
    `distance.name`; `sub_cost` (K,K) overrides the substitution costs, which by default are
    estimated from `col_fit` (in subsample mode pass the costs estimated from all individuals, and
    pass the same ones to `distance_to_medoids`). Attribute inputs, if any, are combined as
    described in the module docstring. Before returning it asserts finiteness,
    symmetry, an exactly zero diagonal and zero distance between identical units.
    """
    u = col_fit.u
    est = estimate_matrix_mb(u, cfg)
    if u > effective_max_units(cfg) or est > float(cfg.distance.max_matrix_mb):
        raise MemoryCapError(f"a matrix for {u} units needs about {est:.1f} MB (cap {float(cfg.distance.max_matrix_mb):g} MB, "
                             f"at most {effective_max_units(cfg)} units); reduce the units with plan_reduction")
    if col_fit.attr_cols:
        assert_no_protected(col_fit.attr_cols, cfg, "build_distance")
    prep = _attr_prep(col_fit.unique_attrs, None) if col_fit.attr_cols else None
    spec = _spec_for(col_fit, cfg, sub_cost, prep)
    D = _square(spec, col_fit.unique_states, _safe_block_rows(u, cfg))
    if not np.isfinite(D).all():
        raise AssertionError("distance matrix contains non-finite values")
    if not np.array_equal(D, D.T):
        raise AssertionError("distance matrix is not exactly symmetric")
    if np.any(np.diag(D) != 0):
        raise AssertionError("distance matrix diagonal is not exactly zero")
    if not _identical_groups_ok(col_fit, D):
        raise AssertionError("identical units are not at distance zero")
    return D


def distance_to_medoids(col: CollapsedTrajectories, medoid_states: np.ndarray, cfg: Config,
                        medoid_attrs: np.ndarray | None = None, idx: np.ndarray | None = None,
                        sub_cost: np.ndarray | None = None) -> np.ndarray:
    """Distances (len(idx) or u, k) from units of `col` to k medoids, blockwise, memory O(block_rows * k).

    Uses the same distance as `build_distance`, so for a fit unit it returns exactly the matching
    column of D when `sub_cost` (and, with attributes, the unit set) is the same. `medoid_attrs`
    (k, A) is required if `col.attr_cols` is set. `idx` selects units (integer array or boolean mask).
    Numeric attribute ranges are taken from `col`, so in subsample mode with numeric attribute inputs
    the extension uses slightly different ranges than the fit sample (only the assignment of non-fit
    units is affected, never D).
    """
    M = _states_array(medoid_states)
    if M.shape[1] != col.T:
        raise ValueError(f"medoid_states has {M.shape[1]} time points, the units have {col.T}")
    sel = np.arange(col.u) if idx is None else np.asarray(idx)
    if sel.dtype == bool:
        sel = np.flatnonzero(sel)
    sel = sel.astype(np.int64)
    if sel.size and (sel.min() < 0 or sel.max() >= col.u):
        raise IndexError(f"idx out of range for {col.u} units")
    prep = None
    if col.attr_cols:
        assert_no_protected(col.attr_cols, cfg, "distance_to_medoids")
        if medoid_attrs is None or np.asarray(medoid_attrs, dtype=object).shape != (len(M), len(col.attr_cols)):
            raise ValueError(f"medoid_attrs must have shape ({len(M)}, {len(col.attr_cols)}) when the units carry attributes")
        prep = _attr_prep(col.unique_attrs[sel], np.asarray(medoid_attrs, dtype=object))
        for f, f_all in zip(prep["feats"], _attr_prep(col.unique_attrs, None)["feats"]):
            if f["numeric"]:
                f["range"] = f_all["range"]                    # one range for all units, whatever idx selects
    spec = _spec_for(col, cfg, sub_cost, prep)
    _check_cost(spec.C, max(int(col.unique_states.max()) if col.unique_states.size else 0, int(M.max()) if M.size else 0))
    return _rect(spec, col.unique_states[sel], M, max(1, int(cfg.distance.block_rows)))


# ---------------------------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------------------------
def benchmark_distance(td: TrajectoryData, cfg: Config, sizes: list[int]) -> pd.DataFrame:
    """Measured seconds and peak MB (tracemalloc) to build a matrix for each size, with the estimate beside them.

    For each `m` in `sizes`, `m` individuals are drawn at random (each its own unit, the worst case for
    memory), the matrix is built with the configured distance and costs estimated from all of `td`,
    and time and peak traced memory are recorded. A size above `effective_max_units`, or larger than
    the number of individuals, is skipped and says why in `status`. Columns: m, seconds, peak_mb,
    estimated_mb, peak_over_estimate, status. Use the result to replace the placeholder limits in config.
    """
    eff = effective_max_units(cfg)
    rng = make_rng(cfg, "benchmark_distance")
    sub_cost = substitution_cost_matrix(td, cfg) if str(cfg.distance.name) != "hamming" else None
    rows = []
    for m in sizes:
        row: dict[str, Any] = {"m": int(m), "seconds": np.nan, "peak_mb": np.nan,
                               "estimated_mb": estimate_matrix_mb(int(m), cfg), "peak_over_estimate": np.nan}
        if m > eff:
            row["status"] = f"skipped: {m} units exceed the limit {eff}"
        elif m > td.n:
            row["status"] = f"skipped: only {td.n} individuals available"
        elif m < 1:
            row["status"] = "skipped: size must be at least 1"
        else:
            idx = np.sort(rng.choice(td.n, size=int(m), replace=False))
            col = identity_collapse(td, idx, cfg)
            tracemalloc.start()
            t0 = time.perf_counter()
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                build_distance(col, cfg, sub_cost)
            row["seconds"] = time.perf_counter() - t0
            row["peak_mb"] = tracemalloc.get_traced_memory()[1] / 2 ** 20
            tracemalloc.stop()
            row["peak_over_estimate"] = row["peak_mb"] / row["estimated_mb"]
            row["status"] = "ok"
        rows.append(row)
    return pd.DataFrame(rows, columns=["m", "seconds", "peak_mb", "estimated_mb", "peak_over_estimate", "status"])


# ---------------------------------------------------------------------------------------------
# Smoke demo
# ---------------------------------------------------------------------------------------------
def _cfg_with(cfg: Config, **distance: Any) -> Config:
    d = cfg.to_dict()
    return Config({**d, "distance": {**d["distance"], **distance}}, cfg.root)


def _ref_hamming(a: np.ndarray, b: np.ndarray, C: np.ndarray, w: np.ndarray, mo: int) -> float:
    """Reference implementation, pair by pair with plain Python sets."""
    common = [t for t in range(len(a)) if a[t] >= 0 and b[t] >= 0]
    if list(a) == list(b):
        return 0.0
    if len(common) < mo or sum(w[t] for t in common) <= 0:
        return float(C.max())
    return sum(w[t] * C[a[t], b[t]] for t in common) / sum(w[t] for t in common)


def _ref_om(a: np.ndarray, b: np.ndarray, C: np.ndarray, indel: float) -> float:
    x, y = [int(s) for s in a if s >= 0], [int(s) for s in b if s >= 0]
    D = [[0.0] * (len(y) + 1) for _ in range(len(x) + 1)]
    for i in range(len(x) + 1):
        for j in range(len(y) + 1):
            if i == 0 or j == 0:
                D[i][j] = indel * max(i, j)
            else:
                D[i][j] = min(D[i - 1][j] + indel, D[i][j - 1] + indel, D[i - 1][j - 1] + C[x[i - 1], y[j - 1]])
    longest = max(len(x), len(y))
    return 0.0 if longest == 0 else D[len(x)][len(y)] / longest


def _demo() -> int:
    from .config import FairnessError as FE
    from .synthetic_data import generate_synthetic
    from .trajectories import build_trajectories

    cfg = load_config()
    print("SYNTHETIC DEMONSTRATION - NOT PLFS RESULTS")
    df, truth = generate_synthetic(cfg, n=2500, seed_offset=31)
    td_full = build_trajectories(df, cfg)
    td = td_full.subset(complete_case_mask(td_full, int(cfg.trainee.min_time_points)))     # the eligible trainees
    K = len(td.state_names)
    C = substitution_cost_matrix(td, cfg)
    col = collapse_trajectories(td, cfg)
    print(f"individuals={td.n} units={col.u} effective_max_units={effective_max_units(cfg)} "
          f"TRATE costs: min off-diag={C[~np.eye(K, dtype=bool)].min():.3f} max={C.max():.3f}")

    def raises(exc: type, fn: Any) -> bool:
        try:
            fn()
        except exc:
            return True
        except Exception:
            return False
        return False

    # --- reference checks on a small slice
    sub = col.unique_states[:60]
    w = np.ones(td.T)
    D_dh = dynamic_hamming_matrix(sub, C, None, "pairwise_available", 2, 7)
    ref_dh = np.array([[_ref_hamming(a, b, C, w, 2) for b in sub] for a in sub])
    D_om = optimal_matching_matrix(sub, C, 1.0, "pairwise_available", 7)
    ref_om = np.array([[_ref_om(a, b, C, 1.0) for b in sub] for a in sub])
    D_h = hamming_matrix(sub, "pairwise_available", 2, 7)
    ref_h = np.array([[_ref_hamming(a, b, 1 - np.eye(K), w, 2) for b in sub] for a in sub])
    tw = np.array([1.0, 2.0, 3.0, 4.0])
    D_tw = dynamic_hamming_matrix(sub, C, tw, "pairwise_available", 2, 64)
    ref_tw = np.array([[_ref_hamming(a, b, C, tw, 2) for b in sub] for a in sub])

    # --- TRATE by hand: states 0,1,2; moves 0->1 (x3), 1->0 (x1), 1->1 (x4), 2->2 (x2)
    hand_states = np.array([[0, 1, 1, 1], [0, 1, 0, 0], [1, 1, 1, 0], [2, 2, 2, -1]], dtype=np.int8)
    counts = np.zeros((3, 3))
    for r in hand_states:
        for t in range(3):
            if r[t] >= 0 and r[t + 1] >= 0:
                counts[r[t], r[t + 1]] += 1
    P = counts / counts.sum(axis=1, keepdims=True)
    hand_C = 2 - (P + P.T)
    np.fill_diagonal(hand_C, 0)
    td_hand = TrajectoryData(np.array(list("abcd"), dtype=object), hand_states, ["t0", "t1", "t2", "t3"], ["x", "y", "z"],
                             pd.DataFrame({"person_id": list("abcd")}), None, True)
    C_hand = substitution_cost_matrix(td_hand, cfg)
    cfg_const = _cfg_with(cfg, substitution="constant")

    # --- full matrices
    D = build_distance(col, cfg)
    D_b1 = build_distance(col, _cfg_with(cfg, block_rows=1))
    D_b300 = build_distance(col, _cfg_with(cfg, block_rows=300))
    D_costs = build_distance(col, cfg, sub_cost=C)
    cfg_om = _cfg_with(cfg, name="optimal_matching")
    D_omf = build_distance(col, cfg_om)

    # --- distance to medoids
    med_idx = np.array([0, 5, 17, 200])
    d2m = distance_to_medoids(col, col.unique_states[med_idx], cfg)
    d2m_om = distance_to_medoids(col, col.unique_states[med_idx], cfg_om)
    d2m_sel = distance_to_medoids(col, col.unique_states[med_idx], cfg, idx=np.array([3, 1, 2]))

    # --- attributes
    sub_td = td.subset(np.arange(400))
    sub_td.attrs["sector"] = sub_td.attrs["sector"].astype(object)
    cfg_attr = _cfg_with(cfg, attribute_inputs=["sector"])
    col_a = collapse_trajectories(sub_td, cfg_attr)
    D_a = build_distance(col_a, cfg_attr)
    med_a = np.array([0, 3])
    d2m_a = distance_to_medoids(col_a, col_a.unique_states[med_a], cfg_attr, col_a.unique_attrs[med_a])
    sector_diff = (col_a.unique_attrs[:, 0][:, None] != col_a.unique_attrs[:, 0][None, :]).astype(float)
    col_a_plain = CollapsedTrajectories(col_a.unique_states, col_a.freq, col_a.inverse, [], None)
    D_plain = build_distance(col_a_plain, cfg, sub_cost=_costs_from_collapsed(col_a, cfg))
    cmax_a = _costs_from_collapsed(col_a, cfg).max()
    expected_combined = (td.T * D_plain / cmax_a + 1.0 * sector_diff) / (td.T + 1.0)
    gdf = pd.DataFrame({"age": [20.0, 30.0, np.nan, 40.0], "sector": ["U", "R", "U", None], "k": [1.0, 1.0, 1.0, 1.0]})
    G = gower_matrix(gdf, {"age": "numeric", "sector": "categorical"})
    cfg_sex = _cfg_with(cfg, attribute_inputs=["sex"])
    col_sex = CollapsedTrajectories(col.unique_states[:3], np.array([1, 1, 1]), np.arange(3), ["sex"], np.array([["M"], ["F"], ["M"]], dtype=object))

    # --- undefined pairs and the min_overlap rule
    few = np.array([[0, -1, -1, -1], [1, -1, -1, -1], [0, 1, 1, 1], [0, 1, 1, 1], [-1, -1, -1, -1], [-1, -1, -1, -1]], dtype=np.int8)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        D_few = dynamic_hamming_matrix(few, C, None, "pairwise_available", 2, 4)
    distinct_zero = dynamic_hamming_matrix(np.array([[0, -1, 2, 2], [0, 1, -1, 2]], dtype=np.int8), C, None, "pairwise_available", 2, 4)

    # --- reduction plans
    def plan_for(**kw: Any) -> ReductionPlan:
        return plan_reduction(td, _cfg_with(cfg, **kw), make_rng(cfg, "demo-plan"))

    big = col.u
    plan_c = plan_for(reduction="collapse", max_n=big + 10)
    plan_c_fail = raises(MemoryCapError, lambda: plan_for(reduction="collapse", max_n=big - 1))
    eff_small = 120
    plan_cs = plan_for(reduction="collapse_then_subsample", max_n=eff_small)
    plan_s = plan_for(reduction="subsample", max_n=eff_small)
    plan_cs_fit = plan_for(reduction="collapse_then_subsample", max_n=big + 10)
    # replay the permutation to prove the prefix is the largest one that fits
    perm = make_rng(cfg, "demo-plan").permutation(td.n)
    units = plan_cs.col_all.inverse[perm]
    distinct_prefix = lambda p: len(np.unique(units[:p]))
    p_used = int(plan_cs.col_fit.n)
    plan_cs2 = plan_for(reduction="collapse_then_subsample", max_n=eff_small)
    # memory-driven limit: 1 MB cap, factor 2 -> 256 units
    cfg_cap = _cfg_with(cfg, max_matrix_mb=1.0, peak_factor=2.0, max_n=100000)
    # numeric attribute input -> collapse refused -> fallback to subsample under collapse_then_subsample
    td_age = td
    cfg_age = _cfg_with(cfg, attribute_inputs=["age"], reduction="collapse_then_subsample", max_n=150)
    plan_age = plan_reduction(td_age, cfg_age, make_rng(cfg, "demo-age"))
    D_age = build_distance(plan_age.col_fit, cfg_age)
    cfg_age_collapse = _cfg_with(cfg, attribute_inputs=["age"], reduction="collapse")

    # --- memory
    bench = benchmark_distance(td, _cfg_with(cfg, max_n=800), [100, 400, 800, 5000])
    tiny = _cfg_with(cfg, max_matrix_mb=1.0, max_n=100000)
    col_over = identity_collapse(td, np.arange(400))
    ok_rows = bench[bench["status"] == "ok"]
    print(bench.round(3).to_string(index=False))
    print(f"plans: collapse -> {plan_c.n_units_fit} units; collapse_then_subsample -> {plan_cs.n_units_fit} units from "
          f"{plan_cs.col_fit.n} individuals; subsample -> {plan_s.n_units_fit} units")
    print(f"reason: {plan_cs.reason}")

    checks = {
        "matrix is float64, square, finite, symmetric, zero diagonal": D.dtype == np.float64 and D.shape == (col.u, col.u)
            and np.isfinite(D).all() and np.array_equal(D, D.T) and (np.diag(D) == 0).all(),
        "dynamic Hamming equals the pair-by-pair reference": np.allclose(D_dh, ref_dh, atol=1e-12, rtol=0),
        "time weights equal the reference": np.allclose(D_tw, ref_tw, atol=1e-12, rtol=0),
        "optimal matching equals the reference DP": np.allclose(D_om, ref_om, atol=1e-12, rtol=0),
        "plain Hamming equals the reference": np.allclose(D_h, ref_h, atol=1e-12, rtol=0),
        "TRATE costs equal the hand calculation": np.allclose(C_hand, hand_C, atol=1e-12) and np.array_equal(C_hand, C_hand.T),
        "constant substitution is 1 off the diagonal": np.array_equal(substitution_cost_matrix(td_hand, cfg_const), 1 - np.eye(3)),
        "costs from individuals equal costs from collapsed rows": np.allclose(_costs_from_collapsed(col, cfg), C, atol=1e-12)
            and np.allclose(D, D_costs, atol=1e-12, rtol=0),
        "block size does not change the matrix": np.array_equal(D, D_b1) and np.array_equal(D, D_b300),
        "optimal matching matrix is symmetric with zero diagonal": np.array_equal(D_omf, D_omf.T) and (np.diag(D_omf) == 0).all(),
        "distance_to_medoids equals matrix columns (dynamic Hamming)": np.array_equal(d2m, D[:, med_idx]),
        "distance_to_medoids equals matrix columns (optimal matching)": np.array_equal(d2m_om, D_omf[:, med_idx]),
        "distance_to_medoids honours idx": np.array_equal(d2m_sel, D[np.ix_([3, 1, 2], med_idx)]),
        "attributes: combined distance equals the stated formula": np.allclose(D_a, expected_combined, atol=1e-12, rtol=0),
        "attributes: distance_to_medoids equals matrix columns": np.array_equal(d2m_a, D_a[:, med_a]),
        "attributes: distance stays in [0,1]": D_a.min() >= 0 and D_a.max() <= 1 + 1e-12,
        "Gower by hand": abs(G[0, 1] - 0.75) < 1e-12 and abs(G[0, 2] - 0.0) < 1e-12 and abs(G[1, 3] - 0.5) < 1e-12 and abs(G[0, 3] - 1.0) < 1e-12 and np.array_equal(G, G.T),
        "protected attribute: gower_matrix raises": raises(FE, lambda: gower_matrix(gdf.assign(sex="M"), {"sex": "categorical"}))
            and raises(FE, lambda: gower_matrix(gdf, {"religion": "categorical"})),
        "protected attribute: build_distance raises": raises(FE, lambda: build_distance(col_sex, cfg_sex)),
        "undefined pairs get the maximum cost and a warning": D_few[0, 1] == C.max() and D_few[0, 2] == C.max() and len(caught) == 1 and "fewer than 2" in str(caught[0].message),
        "identical sparse rows are at distance 0": D_few[2, 3] == 0 and D_few[4, 5] == 0,
        "distinct rows can be at distance 0 (pairwise)": distinct_zero[0, 1] == C[2, 2] == 0,
        "bad inputs raise": raises(ValueError, lambda: dynamic_hamming_matrix(sub, C, None, "not_a_policy", 2, 8))
            and raises(ValueError, lambda: dynamic_hamming_matrix(sub, C[:2, :2], None, "pairwise_available", 2, 8))
            and raises(ValueError, lambda: dynamic_hamming_matrix(sub, C, np.ones(3), "pairwise_available", 2, 8))
            and raises(ValueError, lambda: optimal_matching_matrix(sub, C, 0.0, "pairwise_available", 8))
            and raises(ValueError, lambda: dynamic_hamming_matrix(sub, C, None, "pairwise_available", 0, 8)),
        "effective_max_units by memory: 1 MB, factor 2 -> 256": effective_max_units(cfg_cap) == 256
            and estimate_matrix_mb(256, cfg_cap) <= 1.0 < estimate_matrix_mb(257, cfg_cap),
        "effective_max_units respects max_n": effective_max_units(_cfg_with(cfg, max_n=50)) == 50,
        "plan collapse: every individual represented, no sampling": plan_c.mode_used == "collapse" and plan_c.col_fit is plan_c.col_all
            and plan_c.fit_unit_idx is None and plan_c.col_all.n == td.n,
        "plan collapse refuses without fallback (MemoryCapError)": plan_c_fail,
        "plan collapse_then_subsample behaves as collapse when it fits": plan_cs_fit.mode_used == "collapse",
        "plan collapse_then_subsample: units within the limit": plan_cs.mode_used == "collapse_then_subsample" and plan_cs.n_units_fit <= eff_small,
        "plan collapse_then_subsample: the prefix is the largest that fits": distinct_prefix(p_used) <= eff_small and distinct_prefix(p_used + 1) == eff_small + 1
            and plan_cs.n_units_fit == eff_small,
        "plan collapse_then_subsample: fit units map into col_all": np.array_equal(plan_cs.col_all.unique_states[plan_cs.fit_unit_idx], plan_cs.col_fit.unique_states)
            and plan_cs.col_fit.freq.sum() == plan_cs.col_fit.n,
        "plan is reproducible for one seed": np.array_equal(plan_cs.col_fit.unique_states, plan_cs2.col_fit.unique_states) and plan_cs.reason == plan_cs2.reason,
        "plan subsample: eff individuals, each its own unit": plan_s.mode_used == "subsample" and plan_s.n_units_fit == eff_small
            and (plan_s.col_fit.freq == 1).all() and plan_s.col_all.n == td.n,
        "plan reason states the overlap guarantee": "every pair shares at least 2" in plan_cs.reason,
        "plan col_all always covers every individual": all(p.col_all.n == td.n and p.n_individuals == td.n for p in (plan_c, plan_cs, plan_s)),
        "plan estimate within the cap": all(p.est_peak_mb <= p.cap_mb for p in (plan_c, plan_cs, plan_s, plan_age)),
        "numeric attribute: collapse refused, plan falls back to subsample": plan_age.mode_used == "subsample" and plan_age.col_fit.attr_cols == ["age"]
            and plan_age.col_all.attr_cols == ["age"] and "refused" in plan_age.reason,
        "numeric attribute: distance builds and stays in [0,1]": D_age.shape[0] == 150 and 0 <= D_age.min() and D_age.max() <= 1 + 1e-12,
        "numeric attribute under mode collapse raises CollapseRefused": raises(CollapseRefused, lambda: plan_reduction(td_age, cfg_age_collapse, make_rng(cfg, "x"))),
        "build_distance refuses an oversized matrix before allocating": raises(MemoryCapError, lambda: build_distance(col_over, tiny)),
        "benchmark: oversized and too-large sizes are skipped": list(bench["status"].str.startswith("skipped")) == [False, False, False, True],
        "benchmark: measured peak is within the estimate plus 0.1 MB": bool((ok_rows["peak_mb"] <= ok_rows["estimated_mb"] + 0.1).all()) and len(ok_rows) == 3,
    }
    for name, ok in checks.items():
        print(f"  demo check [{'ok' if ok else 'FAILED'}]: {name}")
    if not all(checks.values()):
        return 1
    print(f"Demo checks passed ({len(checks)}). All data above is SYNTHETIC or hand-built.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_demo())
