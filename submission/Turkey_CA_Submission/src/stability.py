"""Stability of the pathways under attrition and censoring, and the choice of k.

Why this file exists: a clustering is only useful to a skilling programme if it would survive the data the
programme really gets: trainees drop out of follow-up, and some are followed for fewer visits than others. This
module re-runs the WHOLE analysis on degraded copies of the sample and asks two questions. (1) Do the same
individuals end up grouped together (adjusted Rand index, ARI, against the reference clustering)? (2) Does each
reference pathway still exist (some new medoid is close to it)? It also hosts the k-selection table and rule,
because both need `clustering` and `evaluation`, which are delivered before this file.

Design choices worth defending in a viva:
  * Drop FIRST, then reduce. Each repeat removes individuals (or truncates time) before collapsing identical rows,
    before the reduction plan, before the TRATE substitution costs are re-estimated and before the distance matrix
    is built, so the repeat is a faithful re-run of the analysis on the sample it would really have had. Slicing the
    reference matrix would be exact only if the costs did not depend on the sample, so every repeat rebuilds the
    matrix (cheap compared with PAM). This is a deliberate deviation from the wording of INTERFACES section on
    stability ("existing matrix is sliced"); the signatures are unchanged.
  * Three schemes. (a) random loss: exactly round(frac * n) individuals removed uniformly. (b) informative loss:
    exactly round(frac * n) individuals removed, with removal odds exp(strength * z), where z in [-1, 1] is the
    centred rank of the attribute (older = higher z for age); strength 1.0 gives the highest-ranked individual
    about e^2 = 7.4 times the odds of the lowest-ranked; strength 0 is random loss; a negative strength reverses
    the direction; a missing attribute gets z = 0. Sampling without replacement proportional to the odds is the
    Efraimidis-Spirakis scheme (the demo checks it against the exact probabilities). The scale is PROPOSED.
    Informative loss is not a correction for attrition bias: it is a stress test of how far a plausible
    dependence of dropout on one attribute can move the pathways. Protected attributes cannot drive it (the same
    rule as for clustering inputs; lift it deliberately, not by default). (c) censoring: keep only the first
    n_points visits. Individuals left with fewer than min(trainee.min_time_points, n_points) observed points are
    removed, because the eligibility rule of the real analysis cannot be met; that changes the sample as well as
    the follow-up length, and the reference labels are compared only on the individuals that remain.
  * The yardstick for "does this pathway still exist" is plain Hamming distance (share of jointly observed visits
    on which two medoids differ, pairwise-available missing handling, `missing.min_overlap`), NOT the clustering
    distance. The TRATE costs are re-estimated in every repeat, so a threshold in TRATE units would mean something
    different each time; a share of visits means the same thing in every repeat. `stability.survival_max_dist`
    is therefore a share of visits (0.25 = one visit in four). Each new medoid maps to its NEAREST reference
    medoid (ties to the lowest reference index); several new medoids may map to one reference medoid; reference
    pathway j survives in a repeat if at least one new medoid maps to it within the threshold. Under censoring
    the reference medoids are truncated to the same visits.
  * k selection never uses the silhouette alone. A k is admissible only if it is stable (subsample ARI at least
    `k_rule.min_stability_ari`), has no cluster below `clustering.min_cluster_frac`, and wastes no medoid (no two
    medoids at distance 0). Among admissible k the SMALLEST k whose silhouette is within `k_rule.silhouette_margin`
    of the best admissible silhouette is chosen, and the written reason names every exclusion. If nothing is
    admissible the rule falls back to the most stable k and says so in capitals: that is a flag, not a finding.
    The k-stability ARI compares the reference partition of all fit units with the partition of a random
    `K_SUBSAMPLE_FRAC` (0.8, PROPOSED) of the fit individuals, on the individuals in the subsample, reusing the
    one matrix (rows and columns sliced); it measures the sensitivity of the partition to which individuals were
    drawn, not to a changed distance.
  * Medoid candidates (v1.6): the reference clustering, every k-selection fit and every stability repeat draw medoids
    only from units allowed by `clustering.medoid_min_observed` (default: observed at every time point), because
    pairwise-available distances make trajectories with gaps look central. Everyone is still clustered.
  * ARI is computed from the contingency table of individuals (frequency-weighted when units are collapsed) and
    equals scikit-learn's value on the expanded individuals; the demo proves it.
  * UserWarnings about trajectory pairs with too few jointly observed points are silenced inside repeats (they
    would repeat hundreds of times); the same warning is raised once by the reference run.

Limits: stability is conditional on the reference clustering and on the synthetic or real sample it was built on;
a high ARI shows the pathways are not an accident of which individuals stayed, not that they are the "true"
groups. Censoring repeats differ only through the clustering's random starts (and sample redraws in subsample
modes), so their spread understates the uncertainty of a changed sample.

Dependency rule: imports `config`, the shared types, `trajectories`, `distances`, `clustering`, `evaluation`. The
smoke demo imports later-delivered helpers (`synthetic_data`, `preprocessing`) inside the demo function only.

Run the smoke demo with:  python -m src.stability
"""
from __future__ import annotations

import warnings
from typing import Any

import numpy as np
import pandas as pd

from . import FullClustering, ReductionPlan, StabilityResult, TrajectoryData, CollapsedTrajectories
from .clustering import cluster_full, kmedoids, medoid_candidates
from .config import Config, ConfigError, assert_no_protected, load_config, make_rng
from .distances import build_distance, distance_to_medoids, plan_reduction, substitution_cost_matrix
from .evaluation import evaluate_partition

__all__ = [
    "K_SUBSAMPLE_FRAC",
    "adjusted_rand_index",
    "random_attrition",
    "informative_attrition",
    "censor_trajectories",
    "censored_eligible_mask",
    "match_clusters",
    "pathway_survival",
    "k_selection_table",
    "select_k",
    "run_stability",
    "stability_tables",
    "stability_curves",
]

K_SUBSAMPLE_FRAC = 0.8          # PROPOSED: share of fit individuals drawn for each k-stability repeat
_SCHEMES = ("random", "informative", "censoring")
_TOL = 1e-12


# ---------------------------------------------------------------------------------------------
# Adjusted Rand index
# ---------------------------------------------------------------------------------------------
def _c2(x: np.ndarray | float) -> np.ndarray | float:
    return x * (x - 1.0) / 2.0


def adjusted_rand_index(a: Any, b: Any, weights: Any = None) -> float:
    """Adjusted Rand index of two partitions of the same individuals, from the contingency table.

    `weights` (integer counts, e.g. `freq`) lets one row stand for several identical individuals, so the result
    equals the unweighted ARI of the expanded individuals. ARI = (Index - Expected) / (Max - Expected) with
    Index = sum C(n_ij, 2), Expected = (sum_i C(a_i, 2))(sum_j C(b_j, 2)) / C(n, 2), Max = the mean of the two sums.
    When Max equals Expected (both partitions trivial in the same way) the value is 1.0, as in scikit-learn.
    Raises ValueError for different lengths, fewer than 2 individuals, or weights that are not non-negative integers.
    """
    a = np.asarray(a)
    b = np.asarray(b)
    if a.ndim != 1 or a.shape != b.shape:
        raise ValueError(f"partitions must be one-dimensional and the same length, got {a.shape} and {b.shape}")
    if weights is None:
        w = np.ones(len(a))
    else:
        w = np.asarray(weights, dtype=np.float64)
        if w.shape != a.shape or not np.all(np.isfinite(w)) or np.any(w < 0) or np.any(w != np.round(w)):
            raise ValueError("weights must be non-negative integer counts, one per row")
    n = float(w.sum())
    if n < 2:
        raise ValueError("the adjusted Rand index needs at least 2 individuals")
    _, ia = np.unique(a, return_inverse=True)
    _, ib = np.unique(b, return_inverse=True)
    ia, ib = ia.reshape(-1), ib.reshape(-1)
    na, nb = int(ia.max()) + 1, int(ib.max()) + 1
    table = np.bincount(ia * nb + ib, weights=w, minlength=na * nb).reshape(na, nb)
    index = float(_c2(table).sum())
    sa = float(_c2(table.sum(axis=1)).sum())
    sb = float(_c2(table.sum(axis=0)).sum())
    expected = sa * sb / float(_c2(n))
    best = 0.5 * (sa + sb)
    if abs(best - expected) <= 1e-12 * max(1.0, abs(best)):
        return 1.0
    return float((index - expected) / (best - expected))


# ---------------------------------------------------------------------------------------------
# Attrition and censoring
# ---------------------------------------------------------------------------------------------
def _n_drop(n: int, frac: float) -> int:
    if not isinstance(n, (int, np.integer)) or n < 1:
        raise ValueError(f"n must be a positive integer, got {n!r}")
    frac = float(frac)
    if not np.isfinite(frac) or not 0.0 <= frac < 1.0:
        raise ValueError(f"the share lost must lie in [0, 1), got {frac}")
    return min(int(round(frac * n)), n - 1)          # at least one individual always stays


def random_attrition(n: int, frac: float, rng: np.random.Generator) -> np.ndarray:
    """Sorted indices of the individuals that STAY after exactly round(frac * n) are removed uniformly at random.

    At least one individual always stays. Raises ValueError for n < 1 or frac outside [0, 1).
    """
    drop = _n_drop(n, frac)
    return np.sort(rng.choice(int(n), size=int(n) - drop, replace=False)).astype(np.int64)


def informative_attrition(attr: Any, frac: float, strength: float, rng: np.random.Generator) -> np.ndarray:
    """Sorted indices of the individuals that STAY when removal odds depend on one attribute.

    z = 2 * (average rank percentile - 0.5) lies in [-1, 1] (a missing value gets z = 0, so it is neither favoured
    nor protected); removal odds are w = exp(strength * z); exactly round(frac * n) individuals are removed,
    sampled without replacement with probability proportional to w (Efraimidis-Spirakis: remove the individuals
    with the largest u ** (1 / w), u uniform). strength 0 equals random loss, a positive strength removes
    higher-valued individuals more often, a negative one lower-valued. The attribute must be numeric (ranks need
    an order); a non-numeric or all-missing attribute raises ValueError. PROPOSED scale: see the module docstring.
    """
    s = pd.to_numeric(pd.Series(np.asarray(attr, dtype=object)), errors="coerce")
    n = len(s)
    strength = float(strength)
    if not np.isfinite(strength):
        raise ValueError("strength must be finite")
    if s.notna().sum() == 0:
        raise ValueError("the attribute has no numeric values, so removal odds cannot depend on it")
    drop = _n_drop(n, frac)
    rank = s.rank(method="average")
    nv = int(s.notna().sum())
    pct = (rank - 1.0) / (nv - 1.0) if nv > 1 else pd.Series(0.5, index=s.index)
    z = (2.0 * (pct - 0.5)).fillna(0.0).to_numpy(dtype=np.float64)
    w = np.exp(strength * z)
    key = np.log(1.0 - rng.random(n)) / w            # u in (0, 1]; a larger key is removed first
    removed = np.argsort(-key, kind="stable")[:drop]
    keep = np.ones(n, dtype=bool)
    keep[removed] = False
    return np.flatnonzero(keep).astype(np.int64)


def censor_trajectories(td: TrajectoryData, n_points: int) -> TrajectoryData:
    """A copy of `td` that keeps only the first `n_points` visits (columns) of every individual.

    Everyone stays; individuals with too few observed points left are removed separately by
    `censored_eligible_mask`. `meta` records `censored_to` and `censored_from`. Raises ValueError unless
    n_points is an integer in [1, T].
    """
    if isinstance(n_points, bool) or not isinstance(n_points, (int, np.integer)) or not 1 <= n_points <= td.T:
        raise ValueError(f"n_points must be an integer in [1, {td.T}], got {n_points!r}")
    n_points = int(n_points)
    meta = dict(td.meta)
    meta.update(censored_to=n_points, censored_from=td.T)
    return TrajectoryData(
        ids=td.ids.copy(), states=td.states[:, :n_points].copy(), time_labels=list(td.time_labels[:n_points]),
        state_names=list(td.state_names), attrs=td.attrs.copy(), weights=None if td.weights is None else td.weights.copy(),
        is_synthetic=td.is_synthetic, meta=meta)


def censored_eligible_mask(td_censored: TrajectoryData, cfg: Config) -> np.ndarray:
    """Boolean mask of individuals with at least min(trainee.min_time_points, T) observed points in the censored data."""
    need = min(int(cfg.trainee.min_time_points), td_censored.T)
    return (td_censored.states >= 0).sum(axis=1) >= need


# ---------------------------------------------------------------------------------------------
# Matching new pathways to the reference pathways
# ---------------------------------------------------------------------------------------------
def _hamming_cfg(cfg: Config) -> Config:
    d = cfg.to_dict()
    return Config({**d, "distance": {**d["distance"], "name": "hamming", "attribute_inputs": []}}, cfg.root)


def match_clusters(ref_medoid_states: Any, new_medoid_states: Any, cfg: Config, n_points: int | None = None,
                   ref_medoid_attrs: Any = None, new_medoid_attrs: Any = None) -> tuple[np.ndarray, np.ndarray]:
    """Map every new medoid to its nearest reference medoid. Returns (mapping, dist), both of length k_new.

    Distance: plain Hamming, the share of jointly observed visits on which two medoids differ (pairwise-available
    missing handling and `missing.min_overlap`; a pair below the minimum overlap gets the maximum, 1.0, with a
    UserWarning), so the survival threshold means the same in every repeat whatever `distance.name` is.
    `mapping[i]` is the lowest-indexed reference medoid at the minimum distance, many new medoids may share one
    reference medoid. `n_points` truncates the reference medoids to their first visits (use it under censoring);
    the new medoids must then have exactly that many columns. Medoid attributes are accepted for interface
    compatibility but never used: matching compares state sequences only. Raises ValueError for non-2-D input or a
    visit-count mismatch.
    """
    ref = np.asarray(ref_medoid_states)
    new = np.asarray(new_medoid_states)
    if ref.ndim != 2 or new.ndim != 2 or ref.shape[0] < 1 or new.shape[0] < 1:
        raise ValueError("medoid states must be two-dimensional with at least one medoid each")
    if n_points is not None:
        if isinstance(n_points, bool) or not isinstance(n_points, (int, np.integer)) or not 1 <= n_points <= ref.shape[1]:
            raise ValueError(f"n_points must be an integer in [1, {ref.shape[1]}], got {n_points!r}")
        ref = ref[:, :int(n_points)]
    if ref.shape[1] != new.shape[1]:
        raise ValueError(f"reference medoids have {ref.shape[1]} visits but new medoids have {new.shape[1]}: pass n_points under censoring")
    for name, attrs, rows in (("ref_medoid_attrs", ref_medoid_attrs, ref.shape[0]), ("new_medoid_attrs", new_medoid_attrs, new.shape[0])):
        if attrs is not None and len(attrs) != rows:
            raise ValueError(f"{name} must have one row per medoid")
    k_new = new.shape[0]
    col = CollapsedTrajectories(unique_states=new.astype(np.int8), freq=np.ones(k_new, dtype=np.int64),
                                inverse=np.arange(k_new), attr_cols=[], unique_attrs=None)
    d = distance_to_medoids(col, ref.astype(np.int8), _hamming_cfg(cfg))
    mapping = np.argmin(d, axis=1).astype(np.int64)
    return mapping, d[np.arange(k_new), mapping].astype(np.float64)


def pathway_survival(mapping: np.ndarray, dist: np.ndarray, k_ref: int, max_dist: float) -> tuple[np.ndarray, np.ndarray]:
    """Per reference pathway: (survived, min_dist). A pathway survives if at least one new medoid maps to it within `max_dist`.

    `min_dist[j]` is the smallest distance among the new medoids mapped to j, NaN if none maps to it. A tiny tolerance
    (1e-12) keeps a distance of exactly `max_dist` (e.g. 1 visit in 4 = 0.25) on the surviving side.
    """
    mapping = np.asarray(mapping)
    dist = np.asarray(dist, dtype=np.float64)
    survived = np.zeros(k_ref, dtype=bool)
    min_dist = np.full(k_ref, np.nan)
    for j in range(k_ref):
        sel = mapping == j
        if sel.any():
            min_dist[j] = float(dist[sel].min())
            survived[j] = bool(min_dist[j] <= float(max_dist) + _TOL)
    return survived, min_dist


# ---------------------------------------------------------------------------------------------
# k selection
# ---------------------------------------------------------------------------------------------
def _subsample_ari(D: np.ndarray, fit: CollapsedTrajectories, ref_labels: np.ndarray, k: int, cfg: Config,
                   rng: np.random.Generator, cand: np.ndarray | None = None) -> float:
    """ARI between the reference partition and a PAM partition of a random share of the fit individuals (one matrix, sliced).

    `cand` is the medoid-candidate mask of the fit units (v1.6); it is sliced with the units, and a draw with fewer than
    k candidate units left gives NaN.
    """
    m = int(round(K_SUBSAMPLE_FRAC * fit.n))
    if m < 2:
        return float("nan")
    idx = np.sort(rng.choice(fit.n, size=m, replace=False))
    f_sub = np.bincount(fit.inverse[idx], minlength=fit.u)
    keep = np.flatnonzero(f_sub > 0)
    if len(keep) < k:
        return float("nan")
    c_sub = None if cand is None else cand[keep]
    if c_sub is not None and int(c_sub.sum()) < k:
        return float("nan")
    res = kmedoids(D[np.ix_(keep, keep)], k, int(cfg.clustering.n_init), int(cfg.clustering.max_iter), rng,
                   f_sub[keep].astype(np.float64), c_sub)
    return adjusted_rand_index(ref_labels[keep], res.labels, weights=f_sub[keep])


def k_selection_table(plan: ReductionPlan, D: np.ndarray, cfg: Config, rng: np.random.Generator) -> pd.DataFrame:
    """One row per candidate k in `clustering.k_candidates`, all from the ONE matrix `D` of `plan.col_fit`.

    PAM (weighted by `freq`) is fitted on the fit units for each k; the silhouette and separation are computed on the
    fit sample with `evaluate_partition`; stability is the mean of `clustering.k_stability_repeats` subsample ARIs
    (see the module docstring). Columns: k, silhouette, separation_ratio, min_inter_medoid, n_zero_distance_medoid_pairs,
    min_cluster_size, min_cluster_share, n_small_clusters, stability_ari_mean, stability_ari_sd, stability_ari_min,
    n_stability_repeats, n_units_fit, n_individuals_in_fit, reduction, medoid_min_observed_used, n_candidate_units, note.
    Medoids are drawn only from the units allowed by `clustering.medoid_min_observed` (v1.6; `medoid_candidates`), in
    the reference fit and in every stability draw. A k larger than the number of fit units is
    listed with NaN metrics and a note. Undefined values are NaN, never zero.
    """
    fit = plan.col_fit
    D = np.asarray(D)
    if D.shape != (fit.u, fit.u):
        raise ValueError(f"D has shape {D.shape} but plan.col_fit has {fit.u} units: build D from plan.col_fit")
    f = fit.freq.astype(np.float64)
    repeats = int(cfg.clustering.k_stability_repeats)
    nan = float("nan")
    rows = []
    for k in sorted(int(x) for x in cfg.clustering.k_candidates):
        row: dict[str, Any] = {
            "k": k, "silhouette": nan, "separation_ratio": nan, "min_inter_medoid": nan, "n_zero_distance_medoid_pairs": nan,
            "min_cluster_size": nan, "min_cluster_share": nan, "n_small_clusters": nan, "stability_ari_mean": nan,
            "stability_ari_sd": nan, "stability_ari_min": nan, "n_stability_repeats": 0, "n_units_fit": int(fit.u),
            "n_individuals_in_fit": int(fit.n), "reduction": plan.mode_used, "medoid_min_observed_used": nan,
            "n_candidate_units": nan, "note": None}
        if k > fit.u:
            row["note"] = f"skipped: only {fit.u} fit units for k={k}"
            rows.append(row)
            continue
        cand, thr = medoid_candidates(fit, cfg, k)
        res = kmedoids(D, k, int(cfg.clustering.n_init), int(cfg.clustering.max_iter), rng, f, cand)
        row.update(medoid_min_observed_used=int(thr), n_candidate_units=int(cand.sum()))
        ev = evaluate_partition(D, res.labels, cfg, res.medoid_idx, None, fit.freq, "fit_sample")
        sep = ev["separation"]
        num = lambda v: nan if v is None else float(v)       # noqa: E731  (None means "not defined")
        row.update(
            silhouette=num(ev["silhouette"]["overall"]), separation_ratio=num(sep["separation_ratio"]),
            min_inter_medoid=num(sep["min_inter_medoid"]), n_zero_distance_medoid_pairs=num(sep["n_zero_distance_medoid_pairs"]),
            min_cluster_size=int(min(ev["sizes"].values())), min_cluster_share=float(ev["min_cluster_share"]),
            n_small_clusters=int(len(ev["small_clusters"])))
        aris = np.array([_subsample_ari(D, fit, res.labels, k, cfg, rng, cand) for _ in range(repeats)], dtype=np.float64)
        aris = aris[np.isfinite(aris)]
        if aris.size:
            row.update(stability_ari_mean=float(aris.mean()), stability_ari_sd=float(aris.std(ddof=1)) if aris.size > 1 else nan,
                       stability_ari_min=float(aris.min()), n_stability_repeats=int(aris.size))
        rows.append(row)
    return pd.DataFrame(rows)


def select_k(table: pd.DataFrame, cfg: Config) -> tuple[int, str]:
    """Choose k by the multi-criterion rule and return (k, written reason). Never silhouette alone.

    Admissible: silhouette defined; stability_ari_mean >= clustering.k_rule.min_stability_ari; no cluster below
    clustering.min_cluster_frac of the individuals; no two medoids at distance 0. Among admissible k, the smallest
    k whose silhouette is within clustering.k_rule.silhouette_margin of the best admissible silhouette. If no k is
    admissible the most stable k (ties: smaller k) is returned with a reason that starts "FALLBACK:". Raises
    ValueError for an empty table or when no k has a defined silhouette and stability.
    """
    need = {"k", "silhouette", "stability_ari_mean", "n_small_clusters", "n_zero_distance_medoid_pairs", "note"}
    if table.empty or not need <= set(table.columns):
        raise ValueError(f"table must be non-empty with columns {sorted(need)}")
    min_ari = float(cfg.clustering.k_rule.min_stability_ari)
    margin = float(cfg.clustering.k_rule.silhouette_margin)
    min_frac = float(cfg.clustering.min_cluster_frac)
    admissible, excluded = [], []
    for r in table.itertuples(index=False):
        why = []
        if r.note is not None and not (isinstance(r.note, float) and np.isnan(r.note)):
            why.append("not fitted")
        else:
            if not np.isfinite(r.silhouette):
                why.append("silhouette undefined")
            if not np.isfinite(r.stability_ari_mean):
                why.append("stability undefined")
            elif r.stability_ari_mean < min_ari:
                why.append(f"stability ARI {r.stability_ari_mean:.3f} < {min_ari:g}")
            if np.isfinite(r.n_small_clusters) and r.n_small_clusters > 0:
                why.append(f"{int(r.n_small_clusters)} cluster(s) below {min_frac:.1%} of individuals")
            if np.isfinite(r.n_zero_distance_medoid_pairs) and r.n_zero_distance_medoid_pairs > 0:
                why.append("two medoids at distance 0 (a wasted cluster)")
        (excluded if why else admissible).append((int(r.k), why, r))
    ex_txt = "; ".join(f"k={k} ({', '.join(w)})" for k, w, _ in excluded) or "none"
    if admissible:
        best = max(r.silhouette for _, _, r in admissible)
        within = [(k, r) for k, _, r in admissible if r.silhouette >= best - margin - _TOL]
        k, r = min(within, key=lambda t: t[0])
        best_k = [kk for kk, _, rr in admissible if rr.silhouette == best][0]
        reason = (f"k={k}: admissible k = {[kk for kk, _, _ in admissible]}; excluded: {ex_txt}. Best admissible silhouette "
                  f"{best:.3f} at k={best_k}; the smallest admissible k within the margin {margin:g} is k={k} (silhouette "
                  f"{r.silhouette:.3f}, stability ARI {r.stability_ari_mean:.3f}). The silhouette alone did not decide.")
        return k, reason
    usable = [r for r in table.itertuples(index=False) if np.isfinite(r.stability_ari_mean) and np.isfinite(r.silhouette)]
    if not usable:
        raise ValueError("no candidate k has a defined silhouette and stability: nothing to select from")
    r = max(usable, key=lambda t: (t.stability_ari_mean, -t.k))
    reason = (f"FALLBACK: no candidate k met every admissibility rule (excluded: {ex_txt}). The most stable k was taken "
              f"(k={int(r.k)}, stability ARI {r.stability_ari_mean:.3f}, silhouette {r.silhouette:.3f}). Treat this as a flag "
              "that the data do not show a clearly supported number of pathways.")
    return int(r.k), reason


# ---------------------------------------------------------------------------------------------
# Stability under attrition and censoring
# ---------------------------------------------------------------------------------------------
def _check_setting(td: TrajectoryData, ref: FullClustering, scheme: str, level: float, n_repeats: int) -> None:
    if scheme not in _SCHEMES:
        raise ValueError(f"scheme must be one of {_SCHEMES}, got {scheme!r}")
    if isinstance(n_repeats, bool) or not isinstance(n_repeats, (int, np.integer)) or n_repeats < 1:
        raise ValueError(f"n_repeats must be an integer >= 1, got {n_repeats!r}")
    if ref.full_labels.shape != (td.n,):
        raise ValueError(f"ref labels cover {ref.full_labels.shape[0]} individuals but td has {td.n}: pass the td the reference was fitted on")
    if scheme == "censoring":
        if float(level) != int(level) or not 1 <= int(level) <= td.T - 1:
            raise ValueError(f"censoring level must be an integer number of visits in [1, {td.T - 1}], got {level!r}")
    elif not 0.0 < float(level) < 1.0:
        raise ValueError(f"{scheme} level must lie in (0, 1), got {level!r}")


def _one_repeat(td: TrajectoryData, cfg: Config, ref: FullClustering, scheme: str, level: float,
                rng: np.random.Generator) -> tuple[float, int, int, np.ndarray, np.ndarray]:
    if scheme == "random":
        kept = random_attrition(td.n, level, rng)
        td_r = td.subset(kept)
        n_points = None
    elif scheme == "informative":
        attr = str(cfg.stability.informative.attribute)
        assert_no_protected([attr], cfg, "informative_attrition")
        if attr not in td.attrs.columns:
            raise ConfigError(f"stability.informative.attribute {attr!r} is not a column of the trainee attributes")
        kept = informative_attrition(td.attrs[attr].to_numpy(), level, float(cfg.stability.informative.strength), rng)
        td_r = td.subset(kept)
        n_points = None
    else:
        n_points = int(level)
        tc = censor_trajectories(td, n_points)
        kept = np.flatnonzero(censored_eligible_mask(tc, cfg)).astype(np.int64)
        if kept.size < 2:
            raise ValueError(f"fewer than 2 individuals have enough observed points within the first {n_points} visits")
        td_r = tc.subset(kept)
    k = int(ref.fit_result.k)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        sub_cost = substitution_cost_matrix(td_r, cfg)           # re-estimated on the retained (or censored) sample
        plan = plan_reduction(td_r, cfg, rng)                    # collapse AFTER the loss
        if plan.col_fit.u < k:
            raise ValueError(f"only {plan.col_fit.u} fit units remain for k={k}: the degraded sample is too small")
        D = build_distance(plan.col_fit, cfg, sub_cost)
        full = cluster_full(plan, D, cfg, k, rng, sub_cost)
        mapping, dist = match_clusters(ref.medoid_states, full.medoid_states, cfg, n_points=n_points)
    ari = adjusted_rand_index(ref.full_labels[kept], full.full_labels)
    survived, min_dist = pathway_survival(mapping, dist, k, float(cfg.stability.survival_max_dist))
    return ari, int(kept.size), int(plan.col_fit.u), survived, min_dist


def _run(td: TrajectoryData, cfg: Config, ref: FullClustering, scheme: str, level: float, n_repeats: int,
         rng: np.random.Generator) -> tuple[StabilityResult, dict[str, np.ndarray]]:
    _check_setting(td, ref, scheme, level, n_repeats)
    k = int(ref.fit_result.k)
    ari = np.empty(n_repeats)
    n_ret = np.empty(n_repeats, dtype=np.int64)
    n_fit = np.empty(n_repeats, dtype=np.int64)
    surv = np.zeros((n_repeats, k), dtype=bool)
    mind = np.full((n_repeats, k), np.nan)
    for r in range(n_repeats):
        ari[r], n_ret[r], n_fit[r], surv[r], mind[r] = _one_repeat(td, cfg, ref, scheme, level, rng)
    seen = np.isfinite(mind)
    cnt = seen.sum(axis=0)
    mean_min = np.where(cnt > 0, np.where(seen, mind, 0.0).sum(axis=0) / np.maximum(cnt, 1), np.nan)
    survival = pd.DataFrame({"pathway": np.arange(k), "survival_rate": surv.mean(axis=0), "mean_min_dist": mean_min,
                             "n_repeats": n_repeats})
    return (StabilityResult(scheme=scheme, level=float(level), ari=ari, survival=survival),
            {"n_retained": n_ret, "n_units_fit": n_fit})


def run_stability(td: TrajectoryData, cfg: Config, ref: FullClustering, scheme: str, level: float, n_repeats: int,
                  rng: np.random.Generator) -> StabilityResult:
    """Repeat the analysis on degraded copies of `td` and compare with the reference clustering `ref`.

    `scheme` is "random" or "informative" (level = share of individuals lost, in (0, 1)) or "censoring" (level = number
    of visits kept, an integer in [1, T-1]; stored as a float). Each repeat: remove individuals (or truncate visits and
    drop individuals who can no longer meet the eligibility rule) FIRST; re-estimate the substitution costs on what is
    left; `plan_reduction` on the retained individuals; build the matrix under the memory cap; `cluster_full` with the
    reference k; ARI against `ref.full_labels` on the retained individuals; match the new medoids to the reference
    medoids (`match_clusters`). `td` must be the object `ref` was fitted on. `result.ari` has one value per repeat;
    `result.survival` has one row per reference pathway (survival_rate, mean_min_dist over the repeats in which some
    new medoid mapped to it, n_repeats). Raises ValueError for a bad scheme, level or repeat count, a td that does not
    match `ref`, or a degraded sample too small for k.
    """
    return _run(td, cfg, ref, scheme, level, n_repeats, rng)[0]


def _settings(cfg: Config) -> list[tuple[str, float]]:
    loss = [float(x) for x in cfg.stability.random_loss]
    return ([("random", x) for x in loss] + [("informative", x) for x in loss]
            + [("censoring", float(int(x))) for x in cfg.stability.censor_points])


def stability_tables(td: TrajectoryData, cfg: Config, ref: FullClustering) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(curves, survival): every configured setting run `stability.n_repeats` times.

    Settings: random loss at each `stability.random_loss`, informative loss at the same levels, censoring at each
    `stability.censor_points`. Each setting has its own generator `make_rng(cfg, "stability/<scheme>/<level>")`, so
    results do not depend on the order of settings. `curves` columns: scheme, level, level_kind, n_repeats,
    n_retained_mean, n_units_fit_mean, ari_mean, ari_sd, ari_median, ari_p05, ari_min, mean_pathway_survival,
    min_pathway_survival. `survival` columns: scheme, level, pathway, survival_rate, mean_min_dist, n_repeats.
    """
    n_rep = int(cfg.stability.n_repeats)
    curves, surv_rows = [], []
    for scheme, level in _settings(cfg):
        res, info = _run(td, cfg, ref, scheme, level, n_rep, make_rng(cfg, f"stability/{scheme}/{level:g}"))
        a = res.ari
        curves.append({
            "scheme": scheme, "level": level,
            "level_kind": "visits kept" if scheme == "censoring" else "share of individuals lost",
            "n_repeats": n_rep, "n_retained_mean": float(info["n_retained"].mean()), "n_units_fit_mean": float(info["n_units_fit"].mean()),
            "ari_mean": float(a.mean()), "ari_sd": float(a.std(ddof=1)) if a.size > 1 else float("nan"),
            "ari_median": float(np.median(a)), "ari_p05": float(np.percentile(a, 5)), "ari_min": float(a.min()),
            "mean_pathway_survival": float(res.survival["survival_rate"].mean()),
            "min_pathway_survival": float(res.survival["survival_rate"].min())})
        for r in res.survival.itertuples(index=False):
            surv_rows.append({"scheme": scheme, "level": level, "pathway": int(r.pathway), "survival_rate": float(r.survival_rate),
                              "mean_min_dist": float(r.mean_min_dist), "n_repeats": int(r.n_repeats)})
    return pd.DataFrame(curves), pd.DataFrame(surv_rows)


def stability_curves(td: TrajectoryData, cfg: Config, ref: FullClustering) -> pd.DataFrame:
    """The `curves` table of `stability_tables`: schemes (a) random 10-40%, (b) informative, (c) censoring."""
    return stability_tables(td, cfg, ref)[0]


# ---------------------------------------------------------------------------------------------
# Smoke demo
# ---------------------------------------------------------------------------------------------
def _cfg_with(cfg: Config, section: str, **values: Any) -> Config:
    d = cfg.to_dict()
    return Config({**d, section: {**d[section], **values}}, cfg.root)


def _demo() -> int:
    import copy
    import json
    import time

    from sklearn.metrics import adjusted_rand_score, silhouette_score

    from .distances import _min_overlap
    from .preprocessing import apply_eligibility
    from .synthetic_data import generate_synthetic
    from .trajectories import build_trajectories

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

    rg = np.random.default_rng(7)

    # ----- ARI against scikit-learn, brute-force pair counting, and weights = expanded individuals
    def brute_ari(a: np.ndarray, b: np.ndarray) -> float:
        n = len(a)
        same_a = a[:, None] == a[None, :]
        same_b = b[:, None] == b[None, :]
        iu = np.triu_indices(n, 1)
        n11 = float((same_a & same_b)[iu].sum())
        sa, sb = float(same_a[iu].sum()), float(same_b[iu].sum())
        tot = n * (n - 1) / 2
        exp = sa * sb / tot
        mx = 0.5 * (sa + sb)
        return 1.0 if mx == exp else (n11 - exp) / (mx - exp)

    ari_ok, ari_brute_ok, ari_w_ok = True, True, True
    for _ in range(25):
        n = int(rg.integers(6, 60))
        a, b = rg.integers(0, int(rg.integers(1, 6)), n), rg.integers(0, int(rg.integers(1, 6)), n)
        ari_ok &= abs(adjusted_rand_index(a, b) - adjusted_rand_score(a, b)) < 1e-12
        ari_brute_ok &= abs(adjusted_rand_index(a, b) - brute_ari(a, b)) < 1e-12
        m = int(rg.integers(3, 15))
        ua, ub, wt = rg.integers(0, 4, m), rg.integers(0, 4, m), rg.integers(1, 6, m)
        if wt.sum() >= 2:
            ari_w_ok &= abs(adjusted_rand_index(ua, ub, wt) - adjusted_rand_score(np.repeat(ua, wt), np.repeat(ub, wt))) < 1e-12
    pa = rg.integers(0, 4, 40)

    # ----- attrition: exact counts, reproducibility, exact removal probabilities for the informative scheme
    r1, r2 = random_attrition(1000, 0.3, np.random.default_rng(1)), random_attrition(1000, 0.3, np.random.default_rng(1))
    w3 = np.exp(np.array([-1.0, 0.0, 1.0]))                                   # n = 3, strength 1: z = -1, 0, 1
    drops = np.zeros(3)
    rr = np.random.default_rng(3)
    trials = 20000
    for _ in range(trials):
        kept = informative_attrition(np.array([10.0, 20.0, 30.0]), 1 / 3, 1.0, rr)
        drops[np.setdiff1d(np.arange(3), kept)[0]] += 1
    p_emp, p_exact = drops / trials, w3 / w3.sum()
    se = np.sqrt(p_exact * (1 - p_exact) / trials)
    age = rg.normal(30, 6, 2000)
    inf_keep = informative_attrition(age, 0.3, 1.0, np.random.default_rng(2))
    inf_zero = informative_attrition(age, 0.3, 0.0, np.random.default_rng(2))
    inf_neg = informative_attrition(age, 0.3, -1.0, np.random.default_rng(2))
    age_nan = age.copy()
    age_nan[:200] = np.nan

    def dropped_mean(keep: np.ndarray) -> float:
        return float(age[np.setdiff1d(np.arange(len(age)), keep)].mean())

    # ----- censoring
    df, truth = generate_synthetic(cfg, n=1500, seed_offset=61)
    td = apply_eligibility(build_trajectories(df, cfg), cfg)
    t3 = censor_trajectories(td, 3)
    elig3 = censored_eligible_mask(t3, cfg)

    # ----- match_clusters: hand example, brute force with missing points, many-to-one, truncation, distance independence
    ref_h = np.array([[0, 0, 1, 1], [2, 2, 2, 2]], dtype=np.int8)
    m_h, d_h = match_clusters(ref_h, np.array([[0, 0, 1, 2], [2, 2, 2, 2], [2, 2, 0, 0]], dtype=np.int8), cfg)

    def brute_match(ref: np.ndarray, new: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        need = _min_overlap(int(cfg.missing.min_overlap), ref.shape[1])
        out = np.zeros((len(new), len(ref)))
        for i, x in enumerate(new):
            for j, y in enumerate(ref):
                ok = (x >= 0) & (y >= 0)
                out[i, j] = 1.0 if ok.sum() < need else float((x[ok] != y[ok]).mean())
        mp = out.argmin(axis=1)
        return mp, out[np.arange(len(new)), mp]

    ref6 = np.array([[0, 0, 0, 0], [1, 1, 1, 1], [3, 3, 0, 0], [0, 0, 3, 4], [4, 4, 4, 4], [5, 5, 0, 0]], dtype=np.int8)
    new6 = np.array([[0, 0, 0, 1], [1, -1, 1, 1], [0, 0, 0, 0], [3, 3, -1, 0], [-1, -1, 4, 4], [2, 2, 2, 2], [0, 0, 3, -2]], dtype=np.int8)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        m6, d6 = match_clusters(ref6, new6, cfg)
        m6c, d6c = match_clusters(ref6, new6[:, :3], cfg, n_points=3)
        m6o, d6o = match_clusters(ref6, new6, _cfg_with(cfg, "distance", name="optimal_matching"))
    bm, bd = brute_match(ref6, new6)
    bmc, bdc = brute_match(ref6[:, :3], new6[:, :3])
    sv, md = pathway_survival(np.array([0, 0, 2]), np.array([0.5, 0.25, 0.3]), 3, 0.25)

    # ----- reference clustering on synthetic data
    plan = plan_reduction(td, cfg, make_rng(cfg, "st-plan"))
    sub_cost = substitution_cost_matrix(td, cfg)
    D = build_distance(plan.col_fit, cfg, sub_cost)
    ref = cluster_full(plan, D, cfg, 6, make_rng(cfg, "st-ref"), sub_cost)
    pid = np.array([int(x[1:]) for x in td.ids])
    ari_planted = adjusted_rand_score(truth.labels[pid], ref.full_labels)

    # ----- k-stability helper equals a manual expanded-individual computation
    fit = plan.col_fit
    rng_a = make_rng(cfg, "st-sub")
    rng_b = copy.deepcopy(rng_a)
    cand6, _ = medoid_candidates(fit, cfg, 6)
    a_val = _subsample_ari(D, fit, ref.fit_result.labels, 6, cfg, rng_a, cand6)
    idx = np.sort(rng_b.choice(fit.n, size=int(round(K_SUBSAMPLE_FRAC * fit.n)), replace=False))
    f_sub = np.bincount(fit.inverse[idx], minlength=fit.u)
    keep_u = np.flatnonzero(f_sub > 0)
    res_b = kmedoids(D[np.ix_(keep_u, keep_u)], 6, int(cfg.clustering.n_init), int(cfg.clustering.max_iter), rng_b, f_sub[keep_u].astype(float), cand6[keep_u])
    pos = np.full(fit.u, -1)
    pos[keep_u] = np.arange(len(keep_u))
    b_val = adjusted_rand_score(ref.fit_result.labels[fit.inverse[idx]], res_b.labels[pos[fit.inverse[idx]]])

    # ----- k-selection table
    cfg_k = _cfg_with(cfg, "clustering", k_stability_repeats=4)
    rng_t = make_rng(cfg, "st-table")
    tab = k_selection_table(plan, D, cfg_k, copy.deepcopy(rng_t))
    tab2 = k_selection_table(plan, D, cfg_k, copy.deepcopy(rng_t))
    k_chosen, k_reason = select_k(tab, cfg_k)
    rng_c = copy.deepcopy(rng_t)
    res_k2 = kmedoids(D, 2, int(cfg.clustering.n_init), int(cfg.clustering.max_iter), rng_c, fit.freq.astype(float), medoid_candidates(fit, cfg, 2)[0])
    inv_f = fit.inverse
    sil_k2 = silhouette_score(D[np.ix_(inv_f, inv_f)], res_k2.labels[inv_f], metric="precomputed")
    print(tab[["k", "silhouette", "separation_ratio", "min_cluster_share", "stability_ari_mean", "n_zero_distance_medoid_pairs"]].round(3).to_string(index=False))
    print(f"  select_k -> {k_chosen}: {k_reason}")

    # ----- select_k branches on hand-made tables
    def mk(rows: list[tuple[int, float, float, float, float]]) -> pd.DataFrame:
        return pd.DataFrame([{"k": k, "silhouette": s, "stability_ari_mean": a, "n_small_clusters": sm, "n_zero_distance_medoid_pairs": z, "note": None}
                             for k, s, a, sm, z in rows])

    cfg_r = _cfg_with(cfg, "clustering", k_rule={"min_stability_ari": 0.6, "silhouette_margin": 0.02}, min_cluster_frac=0.02)
    t_margin = mk([(2, 0.40, 0.9, 0, 0), (3, 0.50, 0.9, 0, 0), (4, 0.49, 0.9, 0, 0), (5, 0.52, 0.9, 0, 0)])
    t_filter = mk([(2, 0.30, 0.9, 0, 0), (3, 0.60, 0.3, 0, 0), (4, 0.55, 0.9, 1, 0), (5, 0.58, 0.9, 0, 1), (6, 0.35, 0.9, 0, 0)])
    t_none = mk([(2, 0.40, 0.2, 0, 0), (3, 0.45, 0.5, 0, 0), (4, 0.30, 0.4, 0, 0)])
    k_m, why_m = select_k(t_margin, cfg_r)
    k_f, why_f = select_k(t_filter, cfg_r)
    k_n, why_n = select_k(t_none, cfg_r)

    # ----- run_stability: manual replication of one repeat (drop first, then plan, costs, matrix, cluster, ARI)
    rng_r1 = make_rng(cfg, "st-run")
    rng_r2 = copy.deepcopy(rng_r1)
    res1 = run_stability(td, cfg, ref, "random", 0.2, 1, rng_r1)
    kept = random_attrition(td.n, 0.2, rng_r2)
    td_r = td.subset(kept)
    sc_r = substitution_cost_matrix(td_r, cfg)
    pl_r = plan_reduction(td_r, cfg, rng_r2)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        D_r = build_distance(pl_r.col_fit, cfg, sc_r)
        fr = cluster_full(pl_r, D_r, cfg, 6, rng_r2, sc_r)
    man_ari = adjusted_rand_score(ref.full_labels[kept], fr.full_labels)
    cost_changes = not np.array_equal(sc_r, sub_cost)

    # censoring replication
    rng_c1 = make_rng(cfg, "st-cens")
    rng_c2 = copy.deepcopy(rng_c1)
    res_c = run_stability(td, cfg, ref, "censoring", 3, 1, rng_c1)
    kc = np.flatnonzero(censored_eligible_mask(censor_trajectories(td, 3), cfg))
    tdc = censor_trajectories(td, 3).subset(kc)
    scc = substitution_cost_matrix(tdc, cfg)
    plc = plan_reduction(tdc, cfg, rng_c2)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        Dc = build_distance(plc.col_fit, cfg, scc)
        frc = cluster_full(plc, Dc, cfg, 6, rng_c2, scc)
    man_ari_c = adjusted_rand_score(ref.full_labels[kc], frc.full_labels)

    # level behaviour, schemes, reproducibility
    cfg_n = _cfg_with(cfg, "stability", n_repeats=4)
    res_lo = run_stability(td, cfg, ref, "random", 0.1, 4, make_rng(cfg, "st-lo"))
    res_hi = run_stability(td, cfg, ref, "random", 0.4, 4, make_rng(cfg, "st-hi"))
    res_inf = run_stability(td, cfg, ref, "informative", 0.3, 3, make_rng(cfg, "st-inf"))
    res_cen2 = run_stability(td, cfg, ref, "censoring", 2, 2, make_rng(cfg, "st-cen2"))
    res_again = run_stability(td, cfg, ref, "random", 0.1, 4, make_rng(cfg, "st-lo"))

    # sampled reduction mode (units limited) still runs and compares on the same individuals
    cfg_s = _cfg_with(cfg, "distance", max_n=120, reduction="collapse_then_subsample")
    plan_s = plan_reduction(td, cfg_s, make_rng(cfg, "st-plan-s"))
    D_s = build_distance(plan_s.col_fit, cfg_s, sub_cost)
    ref_s = cluster_full(plan_s, D_s, cfg_s, 5, make_rng(cfg, "st-ref-s"), sub_cost)
    res_s = run_stability(td, cfg_s, ref_s, "random", 0.2, 2, make_rng(cfg, "st-s"))

    # whole table of settings
    t0 = time.perf_counter()
    curves, surv = stability_tables(td, cfg_n, ref)
    t_tables = time.perf_counter() - t0
    print(curves[["scheme", "level", "n_retained_mean", "ari_mean", "ari_min", "mean_pathway_survival", "min_pathway_survival"]].round(3).to_string(index=False))
    print(f"  stability_tables: {len(curves)} settings x 4 repeats in {t_tables:.1f} s; planted-structure ARI of the reference = {ari_planted:.3f}")

    cfg_sex = _cfg_with(cfg, "stability", informative={"attribute": "sex", "strength": 1.0})
    cfg_nope = _cfg_with(cfg, "stability", informative={"attribute": "no_such_column", "strength": 1.0})

    checks = {
        "ARI equals scikit-learn and a brute-force pair count (25 random pairs of partitions)": ari_ok and ari_brute_ok,
        "ARI with weights equals the expanded individuals": ari_w_ok,
        "ARI edge cases: identical = 1, relabelled = 1, symmetric, trivial pair = 1": adjusted_rand_index(pa, pa) == 1.0
            and adjusted_rand_index(pa, (pa + 1) % 4) == 1.0 and abs(adjusted_rand_index(pa, pa[::-1]) - adjusted_rand_index(pa[::-1], pa)) < 1e-15
            and adjusted_rand_index(np.zeros(5, int), np.zeros(5, int)) == 1.0,
        "ARI rejects bad input": raises(ValueError, lambda: adjusted_rand_index([0, 1], [0, 1, 1])) and raises(ValueError, lambda: adjusted_rand_index([0], [0]))
            and raises(ValueError, lambda: adjusted_rand_index([0, 1], [0, 1], [1.5, 1])) and raises(ValueError, lambda: adjusted_rand_index([0, 1], [0, 1], [-1, 3])),
        "random_attrition: exact count, sorted, unique, reproducible, frac 0 keeps everyone": len(r1) == 700 and np.array_equal(r1, r2)
            and np.array_equal(r1, np.unique(r1)) and np.array_equal(random_attrition(50, 0.0, rg), np.arange(50)) and len(random_attrition(3, 0.9, rg)) >= 1,
        "attrition rejects bad input": raises(ValueError, lambda: random_attrition(10, 1.0, rg)) and raises(ValueError, lambda: random_attrition(10, -0.1, rg))
            and raises(ValueError, lambda: random_attrition(0, 0.1, rg)) and raises(ValueError, lambda: informative_attrition(np.full(5, np.nan), 0.2, 1.0, rg))
            and raises(ValueError, lambda: informative_attrition(np.array(["a", "b", "c"], dtype=object), 0.2, 1.0, rg))
            and raises(ValueError, lambda: informative_attrition(age, 0.2, float("nan"), rg)),
        "informative_attrition: removal probabilities match the exact odds (n=3, 20000 draws, within 4 standard errors)": bool(np.all(np.abs(p_emp - p_exact) < 4 * se)),
        "informative_attrition: exact count, direction follows strength, strength 0 is unbiased, missing values allowed": len(inf_keep) == 1400
            and dropped_mean(inf_keep) > age.mean() + 1.0 and dropped_mean(inf_neg) < age.mean() - 1.0 and abs(dropped_mean(inf_zero) - age.mean()) < 1.0
            and len(informative_attrition(age_nan, 0.3, 1.0, rg)) == 1400,
        "censor_trajectories: first visits only, labels cut, original untouched, n_points = T is a copy": t3.states.shape == (td.n, 3)
            and np.array_equal(t3.states, td.states[:, :3]) and t3.time_labels == td.time_labels[:3] and td.T == 4 and t3.meta["censored_to"] == 3
            and np.array_equal(censor_trajectories(td, 4).states, td.states) and censor_trajectories(td, 4).states is not td.states
            and raises(ValueError, lambda: censor_trajectories(td, 0)) and raises(ValueError, lambda: censor_trajectories(td, 5)) and raises(ValueError, lambda: censor_trajectories(td, 2.5)),
        "censored_eligible_mask: needs min(min_time_points, n_points) observed points": bool(np.array_equal(elig3, (t3.states >= 0).sum(axis=1) >= 3)) and 0 < elig3.sum() <= td.n,
        "match_clusters: hand example (0.25, 0.0, 0.5 of visits) and nearest-reference mapping": np.array_equal(m_h, [0, 1, 1]) and np.allclose(d_h, [0.25, 0.0, 0.5]),
        "match_clusters equals a brute-force Hamming (missing points, many-to-one, a lost point)": np.array_equal(m6, bm) and np.allclose(d6, bd) and len(set(m6.tolist())) < len(m6),
        "match_clusters under censoring truncates the reference medoids": np.array_equal(m6c, bmc) and np.allclose(d6c, bdc),
        "match_clusters does not depend on distance.name": np.array_equal(m6, m6o) and np.allclose(d6, d6o),
        "match_clusters rejects a visit-count mismatch and a bad n_points": raises(ValueError, lambda: match_clusters(ref6, new6[:, :3], cfg))
            and raises(ValueError, lambda: match_clusters(ref6, new6, cfg, n_points=9)) and raises(ValueError, lambda: match_clusters(ref6[0], new6, cfg)),
        "pathway_survival: within the threshold survives (boundary included), unmatched is NaN and not survived": np.array_equal(sv, [True, False, False])
            and np.isclose(md[0], 0.25) and np.isnan(md[1]) and np.isclose(md[2], 0.3),
        "reference clustering recovers the planted pathways (sanity of the fixture)": ari_planted > 0.7,
        "k-stability helper equals a manual run on the expanded individuals (scikit-learn ARI)": abs(a_val - b_val) < 1e-12 and np.isfinite(a_val),
        "k_selection_table: one row per candidate k, columns, reduction and sizes recorded": list(tab["k"]) == [int(x) for x in cfg.clustering.k_candidates]
            and {"silhouette", "separation_ratio", "min_cluster_size", "stability_ari_mean", "n_units_fit", "n_individuals_in_fit", "reduction"} <= set(tab.columns)
            and (tab["n_units_fit"] == plan.col_fit.u).all() and (tab["n_individuals_in_fit"] == plan.col_fit.n).all() and (tab["reduction"] == plan.mode_used).all(),
        "k_selection_table: stability in [-1, 1], reproducible, silhouette equals scikit-learn on the expanded individuals": tab["stability_ari_mean"].between(-1, 1).all()
            and tab.equals(tab2) and abs(tab.loc[tab.k == 2, "silhouette"].iloc[0] - sil_k2) < 1e-10,
        "v1.6 medoid candidates: the reference and every table row use fully observed medoids only": bool((ref.medoid_states >= 0).all())
            and (tab["medoid_min_observed_used"] == plan.col_fit.T).all() and (tab["n_candidate_units"] >= tab["k"]).all()
            and (tab["n_candidate_units"] == int((plan.col_fit.unique_states >= 0).all(axis=1).sum())).all(),
        "select_k on the table: a candidate k with a written reason that names the rule": int(k_chosen) in set(tab["k"]) and "silhouette" in k_reason,
        "select_k: smallest k within the margin of the best silhouette": k_m == 3 and "within the margin" in why_m,
        "select_k: unstable, small-cluster and wasted-medoid k are excluded with reasons (k=3, 4, 5 out; k=2 is outside the margin of k=6)": k_f == 6 and "stability ARI 0.300" in why_f
            and "below 2.0%" in why_f and "distance 0" in why_f,
        "select_k: nothing admissible gives a FALLBACK on the most stable k": k_n == 3 and why_n.startswith("FALLBACK") and raises(ValueError, lambda: select_k(mk([]), cfg_r)),
        "run_stability drops individuals first: one repeat equals the manual drop-collapse-cost-matrix-cluster-ARI chain": abs(res1.ari[0] - man_ari) < 1e-12
            and pl_r.n_individuals == len(kept) == int(round(0.8 * td.n)) and cost_changes,
        "run_stability censoring equals the manual chain and truncated eligibility": abs(res_c.ari[0] - man_ari_c) < 1e-12 and plc.n_individuals == len(kc) and res_c.level == 3.0,
        "run_stability returns a StabilityResult with one ARI per repeat and one survival row per pathway": all(isinstance(r, StabilityResult) and len(r.ari) == n
            and list(r.survival["pathway"]) == list(range(6)) and r.survival["survival_rate"].between(0, 1).all()
            for r, n in ((res_lo, 4), (res_hi, 4), (res_inf, 3), (res_cen2, 2), (res1, 1))),
        "run_stability is reproducible and ARI values are valid": np.array_equal(res_lo.ari, res_again.ari) and np.all(np.abs(res_lo.ari) <= 1.0),
        "planted structure survives mild loss: ARI at 10% loss is high and pathways survive": res_lo.ari.mean() > 0.7 and res_lo.survival["survival_rate"].mean() > 0.7,
        "heavier loss is not more stable than light loss (means, 4 repeats each)": res_hi.ari.mean() <= res_lo.ari.mean() + 0.05,
        "sampled reduction mode: runs and the repeat is built on the retained individuals": len(res_s.ari) == 2 and np.all(np.isfinite(res_s.ari)) and ref_s.plan.mode_used == "collapse_then_subsample",
        "stability_tables: one row per configured setting, a survival row per pathway": len(curves) == 4 + 4 + 2 and len(surv) == len(curves) * 6
            and list(curves["scheme"].unique()) == ["random", "informative", "censoring"] and curves["ari_mean"].between(-1, 1).all()
            and (curves["n_repeats"] == 4).all() and np.allclose(sorted(curves.loc[curves.scheme == "random", "level"]), [0.1, 0.2, 0.3, 0.4]),
        "stability_tables: retained individuals follow the level (random) and eligibility (censoring)": all(
            abs(r.n_retained_mean - (1 - r.level) * td.n) <= 1 for r in curves[curves.scheme != "censoring"].itertuples())
            and (curves.loc[curves.scheme == "censoring", "n_retained_mean"] <= td.n).all(),
        "stability_curves equals the first table": stability_curves(td, cfg_n, ref).equals(curves),
        "protected or unknown informative attribute is refused": raises(Exception, lambda: run_stability(td, cfg_sex, ref, "informative", 0.2, 1, rg))
            and raises(ConfigError, lambda: run_stability(td, cfg_nope, ref, "informative", 0.2, 1, rg)),
        "bad settings raise": raises(ValueError, lambda: run_stability(td, cfg, ref, "bogus", 0.2, 1, rg)) and raises(ValueError, lambda: run_stability(td, cfg, ref, "random", 0.0, 1, rg))
            and raises(ValueError, lambda: run_stability(td, cfg, ref, "random", 1.0, 1, rg)) and raises(ValueError, lambda: run_stability(td, cfg, ref, "censoring", 4, 1, rg))
            and raises(ValueError, lambda: run_stability(td, cfg, ref, "censoring", 2.5, 1, rg)) and raises(ValueError, lambda: run_stability(td, cfg, ref, "random", 0.2, 0, rg))
            and raises(ValueError, lambda: run_stability(td.subset(np.arange(100)), cfg, ref, "random", 0.2, 1, rg)),
        "tables are JSON-safe after NaN to None": all(json.dumps(t.astype(object).where(t.notna(), None).to_dict("records"), allow_nan=False) for t in (curves, surv, tab)),
    }
    for name, ok in checks.items():
        print(f"  demo check [{'ok' if ok else 'FAILED'}]: {name}")
    if not all(checks.values()):
        return 1
    print(f"Demo checks passed ({len(checks)}). All data above is SYNTHETIC or hand-built.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_demo())
