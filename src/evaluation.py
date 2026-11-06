"""Internal-validity measures for a partition of trajectories, computed from the precomputed distance matrix.

Why this file exists: a clustering algorithm always returns clusters. Whether they are worth reporting depends on
how well separated they are, and that has to be measured with the SAME distance that built them. The measures here
need only the distance matrix, the labels and the individual counts, so they work on unique sequences (collapsed)
exactly as on every individual, and they apply equally to the k-medoids pathways, the hierarchical comparison and
the employed-versus-not baseline.

Design choices worth defending in a viva:
  * The silhouette is weighted by the individual count of each unit (`sample_weight` is `freq`, never a survey
    weight) and is defined so that the collapsed calculation equals the calculation on every individual
    (INTERFACES section 5). With N_C the total count of cluster C: cohesion a(u) = sum_{v in C} f_v D[u,v] / (N_C - 1)
    (the other copies of u are in the sum at distance 0; u itself is not counted in the denominator), separation
    b(u) = min over other clusters of sum_{v in C'} f_v D[u,v] / N_C', s = (b - a) / max(a, b), and s = 0 when
    max(a, b) = 0 or when N_C = 1. A unit with freq > 1 alone in its cluster has N_C > 1, so a = 0. Overall and
    per-cluster means are weighted by f. The identity test (collapsed weighted = brute force on the expanded
    individuals = scikit-learn `silhouette_score(metric="precomputed")`) is run in the demo, including duplicates,
    singleton clusters and MISSING/LOST rows.
  * `pathway_separation` is a DESCRIPTIVE ratio, not a standard index: the mean distance between medoids divided by
    the mean within-cluster distance between distinct individuals. It is scale-free (a ratio of distances), but it
    has no null distribution, so it is for comparing partitions of the same data, not for deciding if clusters
    "exist". It also reports `n_zero_distance_medoid_pairs`: two medoids at distance 0 mean one medoid is wasted,
    which can happen with pairwise-available missing-data handling (distinct sequences can be at distance 0).
  * Davies-Bouldin and Calinski-Harabasz assume points in a Euclidean feature space. Trajectories under a sequence
    distance are not that, so by default they are reported as "not_applicable" with the reason. They are computed
    only when the caller passes a feature representation AND `evaluation.feature_representation` is declared in
    config (that declaration is where the justification is recorded and where `load_config` checks that no
    protected attribute is used). Protected role names in a DataFrame of features raise FairnessError here too.
    The weighted versions are the standard formulas with individual counts as weights, so they equal the
    textbook indices on the expanded individuals (checked against scikit-learn in the demo).
  * Everything returned by `evaluate_partition` is a plain, JSON-safe dict (no NaN: undefined values are None with a
    written reason), because the report is filled from saved results and never from numbers typed by hand.

Limits: the silhouette is computed on whatever distance is given. Under pairwise-available missing-data handling
the distance is not a metric (the triangle inequality can fail), so silhouette values should be read as a
description, not a test. In subsample modes the measures are computed on the FIT sample, and `evaluated_on` says so.
A high silhouette does not show that pathways are meaningful, and a low one does not show that they are not.

Dependency rule: imports only `config` and the shared types (so the distance-matrix helpers are re-written here
rather than imported from `clustering`). The smoke demo imports other modules inside the demo function.

Run the smoke demo with:  python -m src.evaluation
"""
from __future__ import annotations

import math
import time
import warnings
from typing import Any

import numpy as np
import pandas as pd

from .config import PROTECTED_ROLES, Config, ConfigError, FairnessError, assert_no_protected, load_config

__all__ = [
    "silhouette_precomputed",
    "silhouette_by_cluster",
    "brute_force_silhouette",
    "pathway_separation",
    "feature_based_indices",
    "evaluate_partition",
]

ROW_BLOCK = 256                          # rows of D multiplied at a time (bounds temporaries)
EVALUATED_ON = ("fit_sample", "all_units")


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


def _labels(labels: Any, m: int) -> tuple[np.ndarray, np.ndarray]:
    """(sorted distinct label values, 0..k-1 index of every unit's label)."""
    lab = np.asarray(labels)
    if lab.shape != (m,) or lab.dtype.kind not in "iu":
        raise ValueError(f"labels must be {m} integers, got shape {lab.shape} and dtype {lab.dtype}")
    if lab.min() < 0:
        raise ValueError("labels must be non-negative: drop excluded individuals (label -1) before evaluating")
    uniq, inv = np.unique(lab, return_inverse=True)
    return uniq, inv.reshape(-1)


def _weights(w: Any, m: int) -> np.ndarray:
    if w is None:
        return np.ones(m)
    w = np.asarray(w, dtype=np.float64)
    if w.shape != (m,) or not np.isfinite(w).all() or (w <= 0).any():
        raise ValueError(f"sample_weight (individual counts) must be {m} finite positive numbers")
    return w


def _prepare(D: Any, labels: Any, sample_weight: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    D = _check_D(D)
    uniq, inv = _labels(labels, len(D))
    return D, uniq, inv, _weights(sample_weight, len(D))


def _cluster_sums(D: np.ndarray, inv: np.ndarray, f: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    """S[u, c] = sum_{v in cluster c} f_v D[u, v] (blockwise matrix product) and the cluster counts N_c."""
    m = len(D)
    M = np.zeros((m, k))
    M[np.arange(m), inv] = f
    S = np.empty((m, k))
    for i0 in range(0, m, ROW_BLOCK):
        i1 = min(i0 + ROW_BLOCK, m)
        S[i0:i1] = D[i0:i1] @ M
    return S, np.bincount(inv, weights=f, minlength=k)


def _py(x: Any) -> Any:
    """JSON-safe copy: numpy scalars to Python, NaN and inf to None, keys to text."""
    if isinstance(x, dict):
        return {str(k): _py(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_py(v) for v in x]
    if isinstance(x, np.ndarray):
        return _py(x.tolist())
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        return float(x) if math.isfinite(float(x)) else None
    if isinstance(x, (np.bool_,)):
        return bool(x)
    return x


def _count(x: float) -> int | float:
    return int(round(x)) if abs(x - round(x)) < 1e-9 else float(x)


# ---------------------------------------------------------------------------------------------
# Silhouette
# ---------------------------------------------------------------------------------------------
def _silhouette_units(D: np.ndarray, inv: np.ndarray, f: np.ndarray, k: int) -> np.ndarray:
    """Per-unit weighted silhouette s(u) under the rules in the module docstring (k >= 2)."""
    m = len(D)
    S, N = _cluster_sums(D, inv, f, k)
    idx = np.arange(m)
    own, n_own = S[idx, inv], N[inv]
    big = n_own > 1
    a = np.zeros(m)
    a[big] = own[big] / (n_own[big] - 1.0)
    other = S / N[None, :]
    other[idx, inv] = np.inf
    b = other.min(axis=1)
    top = np.maximum(a, b)
    s = np.zeros(m)
    ok = big & (top > 0)
    s[ok] = (b[ok] - a[ok]) / top[ok]
    return s


def silhouette_precomputed(D: np.ndarray, labels: np.ndarray, sample_weight: np.ndarray | None = None) -> tuple[float, np.ndarray]:
    """(overall weighted silhouette, per-unit silhouette) from a distance matrix, labels and individual counts.

    Rules (identical for the collapsed and the expanded calculation): N_C = total count of cluster C;
    a(u) = sum_{v in C} f_v D[u,v] / (N_C - 1); b(u) = min over other clusters C' of sum_{v in C'} f_v D[u,v] / N_C';
    s = (b - a) / max(a, b), 0 if max(a, b) = 0 or N_C = 1; overall = sum_u f_u s(u) / sum_u f_u. `sample_weight` is the
    individual count per unit (None = one each). Fewer than 2 clusters gives (NaN, array of NaN); `evaluate_partition`
    reports the reason. Values depend on the distance only through D, which must be symmetric with a zero diagonal.
    """
    D, uniq, inv, f = _prepare(D, labels, sample_weight)
    if len(uniq) < 2:
        return float("nan"), np.full(len(D), np.nan)
    s = _silhouette_units(D, inv, f, len(uniq))
    return float((f * s).sum() / f.sum()), s


def silhouette_by_cluster(D: np.ndarray, labels: np.ndarray, sample_weight: np.ndarray | None = None) -> pd.DataFrame:
    """Per-cluster table: cluster, n_units, n_individuals, share_of_individuals, mean_silhouette, share_negative.

    `mean_silhouette` = sum_{u in C} f_u s(u) / N_C and `share_negative` is the share of the cluster's individuals
    with s(u) < 0 (individuals who are on average closer to another cluster). Rows are in ascending label order;
    with fewer than 2 clusters the silhouette columns are NaN.
    """
    D, uniq, inv, f = _prepare(D, labels, sample_weight)
    k = len(uniq)
    _, s = silhouette_precomputed(D, labels, sample_weight) if k >= 2 else (None, np.full(len(D), np.nan))
    N = np.bincount(inv, weights=f, minlength=k)
    rows = []
    for c in range(k):
        mem = inv == c
        rows.append({
            "cluster": int(uniq[c]), "n_units": int(mem.sum()), "n_individuals": _count(N[c]),
            "share_of_individuals": float(N[c] / f.sum()),
            "mean_silhouette": float((f[mem] * s[mem]).sum() / N[c]) if k >= 2 else float("nan"),
            "share_negative": float(f[mem & (s < 0)].sum() / N[c]) if k >= 2 else float("nan"),
        })
    return pd.DataFrame(rows, columns=["cluster", "n_units", "n_individuals", "share_of_individuals", "mean_silhouette", "share_negative"])


def brute_force_silhouette(D: np.ndarray, labels: np.ndarray) -> float:
    """Reference silhouette, one individual at a time and unweighted: run it on the EXPANDED individuals.

    a(i) = mean distance to the other members of i's cluster (0 if it is alone: s = 0), b(i) = the lowest mean
    distance to any other cluster, s = (b - a) / max(a, b) with 0 if both are 0. Returns NaN for fewer than 2 clusters.
    Used only to test `silhouette_precomputed` (O(n^2) work, written independently of its matrix algebra).
    """
    D = _check_D(D)
    uniq, inv = _labels(labels, len(D))
    if len(uniq) < 2:
        return float("nan")
    total = 0.0
    for i in range(len(D)):
        same = inv == inv[i]
        if same.sum() == 1:
            continue                                     # a singleton cluster has s = 0
        a = D[i, same].sum() / (same.sum() - 1)
        b = min(D[i, inv == c].mean() for c in range(len(uniq)) if c != inv[i])
        top = max(a, b)
        total += 0.0 if top == 0 else (b - a) / top
    return float(total / len(D))


# ---------------------------------------------------------------------------------------------
# Separation
# ---------------------------------------------------------------------------------------------
def pathway_separation(D: np.ndarray, labels: np.ndarray, medoid_idx: np.ndarray, sample_weight: np.ndarray | None = None) -> dict[str, Any]:
    """How far apart the pathways are relative to how tight they are (descriptive, not a standard index).

    `labels` must use every value 0..k-1 and `medoid_idx[c]` is the medoid of label c (an index into D belonging to
    cluster c; anything else raises ValueError). Returns: `mean_between_medoid` (mean of D between the medoids over
    all pairs of clusters), `min_inter_medoid` (the smallest such distance), `n_zero_distance_medoid_pairs`
    (medoid pairs at distance exactly 0: a wasted medoid), `mean_within` (the mean distance between two DISTINCT
    individuals of the same cluster, pooled over clusters and weighted by individual counts; two copies of the same
    unit are two individuals at distance 0) and `separation_ratio` = mean_between_medoid / mean_within. Undefined
    values are None with `status` "not_defined" and a written `reason` (one cluster, no pair of individuals in one
    cluster, or mean_within = 0).
    """
    D, uniq, inv, f = _prepare(D, labels, sample_weight)
    k = len(uniq)
    if not np.array_equal(uniq, np.arange(k)):
        raise ValueError("labels must use every value 0..k-1")
    med = np.asarray(medoid_idx)
    if med.shape != (k,) or med.dtype.kind not in "iu" or med.min() < 0 or med.max() >= len(D):
        raise ValueError(f"medoid_idx must be {k} valid unit indices (one per label)")
    if not np.array_equal(inv[med], np.arange(k)):
        raise ValueError("medoid_idx[c] must belong to cluster c")
    out: dict[str, Any] = {"n_clusters": k, "mean_between_medoid": None, "min_inter_medoid": None, "n_zero_distance_medoid_pairs": None,
                           "mean_within": None, "separation_ratio": None, "status": "ok", "reason": None}
    reasons = []
    if k >= 2:
        iu = np.triu_indices(k, 1)
        between = D[np.ix_(med, med)][iu]
        out.update(mean_between_medoid=float(between.mean()), min_inter_medoid=float(between.min()),
                   n_zero_distance_medoid_pairs=int((between == 0).sum()))
    else:
        reasons.append("only one cluster, so there is no distance between medoids")
    S, N = _cluster_sums(D, inv, f, k)
    pairs = float((N * (N - 1.0) / 2.0).sum())
    if pairs > 0:
        out["mean_within"] = float((f * S[np.arange(len(D)), inv]).sum() / 2.0 / pairs)
    else:
        reasons.append("no cluster holds two individuals, so there is no within-cluster distance")
    if out["mean_between_medoid"] is not None and out["mean_within"] is not None:
        if out["mean_within"] > 0:
            out["separation_ratio"] = out["mean_between_medoid"] / out["mean_within"]
        else:
            reasons.append("mean within-cluster distance is 0, so the ratio is undefined")
    if out["separation_ratio"] is None:
        out["status"], out["reason"] = "not_defined", "; ".join(reasons)
    return out


# ---------------------------------------------------------------------------------------------
# Feature-based indices (only with a declared, justified representation)
# ---------------------------------------------------------------------------------------------
def feature_based_indices(features: Any, labels: np.ndarray, sample_weight: np.ndarray | None = None) -> dict[str, Any]:
    """Davies-Bouldin and Calinski-Harabasz, only when a feature representation is supplied; otherwise "not_applicable".

    `features` is None or an (m, p) numeric array / DataFrame, one row per unit. Both indices assume points in a
    Euclidean space; the weighted versions use individual counts as weights and equal the textbook formulas on the
    expanded individuals. A DataFrame whose column names include a protected role (sex, social_group, religion)
    raises FairnessError (`evaluate_partition` additionally checks the verified column names against the config).
    Returns {"status": "ok", "davies_bouldin", "calinski_harabasz", "n_features"}, or {"status": "not_applicable" |
    "not_defined", "reason": ...} (not defined for fewer than 2 clusters or when the individuals do not outnumber the clusters).
    """
    if features is None:
        return {"status": "not_applicable",
                "reason": "no feature representation of the trajectories was supplied: Davies-Bouldin and Calinski-Harabasz assume "
                          "points in a Euclidean feature space and are not defined for sequences compared by a sequence distance"}
    if isinstance(features, pd.DataFrame):
        bad = sorted(str(c) for c in features.columns if str(c).lower() in PROTECTED_ROLES)
        if bad:
            raise FairnessError(f"protected attribute(s) {bad} may not be used as input to feature_based_indices")
    X = np.asarray(features, dtype=np.float64)
    if X.ndim != 2 or X.shape[1] < 1:
        raise ValueError(f"features must be two-dimensional (units, features), got shape {X.shape}")
    if not np.isfinite(X).all():
        raise ValueError("features contain non-finite values")
    uniq, inv = _labels(labels, len(X))
    f = _weights(sample_weight, len(X))
    k, total = len(uniq), float(f.sum())
    if k < 2 or total <= k:
        return {"status": "not_defined", "reason": f"needs at least 2 clusters and more individuals ({total:g}) than clusters ({k})",
                "n_features": int(X.shape[1])}
    N = np.bincount(inv, weights=f, minlength=k)
    cent = np.zeros((k, X.shape[1]))
    np.add.at(cent, inv, X * f[:, None])
    cent /= N[:, None]
    grand = (X * f[:, None]).sum(axis=0) / total
    dist = np.sqrt(((X - cent[inv]) ** 2).sum(axis=1))
    within = float((f * dist ** 2).sum())
    between = float((N * ((cent - grand) ** 2).sum(axis=1)).sum())
    ch = 1.0 if within == 0.0 else between * (total - k) / (within * (k - 1.0))
    scat = np.bincount(inv, weights=f * dist, minlength=k) / N
    cd = np.sqrt(((cent[:, None, :] - cent[None, :, :]) ** 2).sum(-1))
    if np.allclose(scat, 0.0) or np.allclose(cd, 0.0):
        db = 0.0
    else:
        cd = np.where(cd == 0.0, np.inf, cd)
        np.fill_diagonal(cd, np.inf)
        ratio = (scat[:, None] + scat[None, :]) / cd
        np.fill_diagonal(ratio, -np.inf)
        db = float(ratio.max(axis=1).mean())
    return {"status": "ok", "davies_bouldin": db, "calinski_harabasz": float(ch), "n_features": int(X.shape[1])}


# ---------------------------------------------------------------------------------------------
# One call for everything
# ---------------------------------------------------------------------------------------------
def evaluate_partition(D: np.ndarray, labels: np.ndarray, cfg: Config, medoid_idx: np.ndarray | None = None, features: Any = None,
                       sample_weight: np.ndarray | None = None, evaluated_on: str = "fit_sample") -> dict[str, Any]:
    """All internal measures of one partition as a JSON-safe dict (works for pathways, the comparison method and the baseline).

    Keys: `evaluated_on` ("fit_sample" or "all_units"), `n_units`, `n_individuals`, `n_clusters`; `silhouette`
    ({overall, status, reason, per_cluster: [...], negative_share}); `separation` (see `pathway_separation`, or
    "not_applicable" if `medoid_idx` is None); `feature_indices` (Davies-Bouldin and Calinski-Harabasz, "not_applicable"
    unless features are supplied); `sizes` (individuals per cluster), `min_cluster_share`, and `small_clusters`, the
    labels whose share of individuals is below `clustering.min_cluster_frac`. Supplying `features` without
    `evaluation.feature_representation` declared in config raises ConfigError (the justification must be recorded);
    protected attributes raise FairnessError. Silhouette and separation are computed on the units given, weighted by
    individual counts, so pass the fit sample's matrix and `freq`, and say which in `evaluated_on`.
    """
    if evaluated_on not in EVALUATED_ON:
        raise ValueError(f"evaluated_on must be one of {EVALUATED_ON}, got {evaluated_on!r}")
    D, uniq, inv, f = _prepare(D, labels, sample_weight)
    k, m = len(uniq), len(D)
    if features is not None:
        if cfg.evaluation.feature_representation is None:
            raise ConfigError("features were supplied but evaluation.feature_representation is null: declare and justify the feature "
                              "representation in config.yaml before using Davies-Bouldin or Calinski-Harabasz")
        if isinstance(features, pd.DataFrame):
            assert_no_protected([str(c) for c in features.columns], cfg, "evaluate_partition")
    overall, per_unit = silhouette_precomputed(D, labels, sample_weight)
    table = silhouette_by_cluster(D, labels, sample_weight)
    if k >= 2:
        sil = {"overall": overall, "status": "ok", "reason": None, "per_cluster": table.to_dict("records"),
               "negative_share": float(f[per_unit < 0].sum() / f.sum())}
    else:
        sil = {"overall": None, "status": "not_defined", "reason": "the silhouette needs at least 2 clusters", "per_cluster": table.to_dict("records"),
               "negative_share": None}
    if medoid_idx is None:
        sep: dict[str, Any] = {"status": "not_applicable", "reason": "no medoids were supplied"}
    else:
        sep = pathway_separation(D, labels, medoid_idx, sample_weight)
    if features is None and cfg.evaluation.feature_representation is not None:
        feat: dict[str, Any] = {"status": "not_applicable", "reason": "a feature representation is declared in config but the caller supplied no features"}
    else:
        feat = feature_based_indices(features, labels, sample_weight)
        if feat["status"] == "not_applicable":
            feat["reason"] = "evaluation.feature_representation is null (no justified feature representation): " + feat["reason"]
    N = np.bincount(inv, weights=f, minlength=k)
    share = N / f.sum()
    min_frac = float(cfg.clustering.min_cluster_frac)
    result = {
        "evaluated_on": evaluated_on, "n_units": m, "n_individuals": _count(float(f.sum())), "n_clusters": k,
        "silhouette": sil, "separation": sep, "feature_indices": feat,
        "sizes": {int(uniq[c]): _count(N[c]) for c in range(k)},
        "min_cluster_share": float(share.min()), "min_cluster_frac": min_frac,
        "small_clusters": [int(uniq[c]) for c in range(k) if share[c] < min_frac],
    }
    return _py(result)


# ---------------------------------------------------------------------------------------------
# Smoke demo
# ---------------------------------------------------------------------------------------------
def _cfg_with(cfg: Config, section: str, **values: Any) -> Config:
    d = cfg.to_dict()
    return Config({**d, section: {**d[section], **values}}, cfg.root)


def _demo() -> int:
    import json

    from sklearn.metrics import calinski_harabasz_score, davies_bouldin_score, silhouette_samples, silhouette_score

    from . import TrajectoryData
    from .baseline import baseline_unit_labels
    from .clustering import cluster_full, medoids_from_labels
    from .distances import build_distance, plan_reduction
    from .synthetic_data import generate_synthetic
    from .trajectories import build_trajectories, collapse_trajectories, complete_case_mask

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

    # ----- hand-calculated silhouette: points 0, 1, 10 with counts 2, 1, 1; clusters {0,1} and {10}
    Dh = np.array([[0, 1, 10], [1, 0, 9], [10, 9, 0]], dtype=float)
    lab_h, f_h = np.array([0, 0, 1]), np.array([2.0, 1.0, 1.0])
    sh, su = silhouette_precomputed(Dh, lab_h, f_h)
    s_hand = np.array([0.95, 8 / 9, 0.0])
    # ----- identity test on a real distance matrix with duplicates, singleton clusters, MISSING and LOST rows
    names = list(cfg.to_dict()["states"])
    rows = [[0, 0, 1, 1], [0, 0, 1, 1], [0, 0, 1, 1], [3, 3, 4, 4], [3, 3, 4, 4], [3, -1, 4, 4], [5, 5, -2, -2], [5, 5, 5, 5],
            [2, 2, 2, -1], [0, -1, 1, 1], [0, 0, 0, 0], [4, 4, 4, 4]]
    td = TrajectoryData(np.array([f"i{j}" for j in range(len(rows))], dtype=object), np.array(rows, dtype=np.int8), list(cfg.time.labels),
                        [s["name"] for s in names], pd.DataFrame({"x": np.arange(len(rows))}), None, True)
    col = collapse_trajectories(td, cfg)
    with warnings.catch_warnings():                     # the sparse MISSING/LOST rows deliberately create undefined pairs
        warnings.simplefilter("ignore", UserWarning)
        Dc = build_distance(col, cfg)
    fc = col.freq.astype(float)
    inv = col.inverse
    Dexp = Dc[np.ix_(inv, inv)]
    rg = np.random.default_rng(3)
    ident_ok, worst = True, 0.0
    for trial in range(8):
        k = int(rg.integers(2, 5))
        lab_u = rg.integers(0, k, col.u)
        lab_u[:k] = np.arange(k)                        # every label used
        lab_u[-1] = k                                   # the last unit alone: a singleton cluster
        lab_e = lab_u[inv]
        sc, su_c = silhouette_precomputed(Dc, lab_u, fc)
        bf = brute_force_silhouette(Dexp, lab_e)
        sk = silhouette_score(Dexp, lab_e, metric="precomputed")
        sk_samples = silhouette_samples(Dexp, lab_e, metric="precomputed")
        per = silhouette_by_cluster(Dc, lab_u, fc)
        per_ok = all(abs(per.loc[per.cluster == c, "mean_silhouette"].iloc[0] - sk_samples[lab_e == c].mean()) < 1e-10 for c in np.unique(lab_u))
        unit_ok = np.allclose(su_c[inv], sk_samples, atol=1e-10, rtol=0)
        worst = max(worst, abs(sc - bf), abs(sc - sk))
        ident_ok &= abs(sc - bf) < 1e-10 and abs(sc - sk) < 1e-10 and per_ok and unit_ok
    n_dup = int((col.freq > 1).sum())
    # random Euclidean instances with weights
    ident2 = True
    for seed in range(6):
        g = np.random.default_rng(seed)
        P = g.normal(size=(30, 2))
        Dp = np.sqrt(((P[:, None] - P[None]) ** 2).sum(-1))
        fp = g.integers(1, 5, size=30)
        lp = g.integers(0, 4, size=30)
        lp[:4] = np.arange(4)
        ie = np.repeat(np.arange(30), fp)
        De = Dp[np.ix_(ie, ie)]
        ident2 &= abs(silhouette_precomputed(Dp, lp, fp.astype(float))[0] - silhouette_score(De, lp[ie], metric="precomputed")) < 1e-10
    # zero-distance twins in different clusters: a = b = 0 gives s = 0 like scikit-learn
    Dz = np.zeros((4, 4))
    lz = np.array([0, 0, 1, 1])
    one_cluster = silhouette_precomputed(Dh, np.zeros(3, dtype=np.int64), f_h)
    # ----- separation
    Dl = np.abs(np.array([0.0, 1.0, 10.0, 12.0])[:, None] - np.array([0.0, 1.0, 10.0, 12.0])[None])
    sep_l = pathway_separation(Dl, np.array([0, 0, 1, 1]), np.array([0, 2]))
    sep_w = pathway_separation(Dh, lab_h, np.array([0, 2]), f_h)
    sep_one = pathway_separation(Dh, np.zeros(3, dtype=np.int64), np.array([0]), f_h)
    sep_single = pathway_separation(Dh, np.array([0, 1, 2]), np.array([0, 1, 2]))
    Dtw = np.array([[0, 0, 5.0], [0, 0, 5.0], [5.0, 5.0, 0]])
    sep_tw = pathway_separation(Dtw, np.array([0, 1, 2]), np.array([0, 1, 2]))
    # brute force within/between on the expanded individuals (random weighted instance)
    g = np.random.default_rng(9)
    P = g.normal(size=(20, 2))
    Dp = np.sqrt(((P[:, None] - P[None]) ** 2).sum(-1))
    fp = g.integers(1, 4, size=20)
    lp = np.arange(20) % 3
    mp = np.array([int(np.flatnonzero(lp == c)[0]) for c in range(3)])
    ie = np.repeat(np.arange(20), fp)
    De, le = Dp[np.ix_(ie, ie)], lp[ie]
    w_sum, w_n = 0.0, 0
    for i in range(len(ie)):
        for j in range(i + 1, len(ie)):
            if le[i] == le[j]:
                w_sum += De[i, j]
                w_n += 1
    bt = [Dp[mp[a], mp[b]] for a in range(3) for b in range(a + 1, 3)]
    sep_r = pathway_separation(Dp, lp, mp, fp.astype(float))
    # ----- feature-based indices against scikit-learn on the expanded individuals
    Xf = g.normal(size=(20, 3)) + lp[:, None]
    fi = feature_based_indices(Xf, lp, fp.astype(float))
    Xe = Xf[ie]
    fi_same = feature_based_indices(Xf, lp, None)
    fi_none = feature_based_indices(None, lp)
    fi_one = feature_based_indices(Xf, np.zeros(20, dtype=np.int64))
    fi_const = feature_based_indices(np.vstack([np.zeros((10, 2)), np.zeros((10, 2))]), np.repeat([0, 1], 10))
    # ----- synthetic data end to end
    df, truth = generate_synthetic(cfg, n=1500, seed_offset=51)
    td_all = build_trajectories(df, cfg)
    tds = td_all.subset(complete_case_mask(td_all, int(cfg.trainee.min_time_points)))
    plan = plan_reduction(tds, cfg, np.random.default_rng(0))
    D = build_distance(plan.col_fit, cfg)
    ff = plan.col_fit.freq.astype(float)
    results = {}
    for k in (2, 3, 4, 6):
        full = cluster_full(plan, D, cfg, k, np.random.default_rng(k))
        results[k] = evaluate_partition(D, full.fit_result.labels, cfg, full.fit_result.medoid_idx, None, ff)
    ev6 = results[6]
    full6 = cluster_full(plan, D, cfg, 6, np.random.default_rng(6))
    lab6, med6 = full6.fit_result.labels, full6.fit_result.medoid_idx
    inv_f = plan.col_fit.inverse
    sil_e6 = silhouette_score(D[np.ix_(inv_f, inv_f)], lab6[inv_f], metric="precomputed")
    zero_pairs = int(sum(D[med6[a], med6[b]] == 0 for a in range(6) for b in range(a + 1, 6)))
    # baseline partition evaluated with the same matrix (as the orchestrator will do)
    bl = baseline_unit_labels(plan.col_fit, cfg)
    keep = bl >= 0
    Dk, fk, bk = D[np.ix_(keep, keep)], ff[keep], bl[keep]
    mb = medoids_from_labels(Dk, bk, fk)
    ev_b = evaluate_partition(Dk, bk, cfg, mb, None, fk)
    ib = np.repeat(np.arange(int(keep.sum())), plan.col_fit.freq[keep])
    sil_e_b = silhouette_score(Dk[np.ix_(ib, ib)], bk[ib], metric="precomputed")
    # config gating of features
    cfg_decl = _cfg_with(cfg, "evaluation", feature_representation={"name": "state_share_by_time", "justification": "demo only"})
    X_units = np.stack([(plan.col_fit.unique_states == s).mean(axis=1) for s in range(len(names))], axis=1)
    ev_feat = evaluate_partition(D, lab6, cfg_decl, med6, X_units, ff)
    Xi = X_units[inv_f]
    cfg_small = _cfg_with(cfg, "clustering", min_cluster_frac=0.5)
    ev_small = evaluate_partition(D, lab6, cfg_small, med6, None, ff)
    t0 = time.perf_counter()
    Dbig = np.abs(np.random.default_rng(1).normal(size=(2500, 1)) - np.random.default_rng(1).normal(size=(1, 2500)))
    Dbig = (Dbig + Dbig.T) / 2
    np.fill_diagonal(Dbig, 0)
    silhouette_precomputed(Dbig, np.random.default_rng(2).integers(0, 8, 2500))
    t_big = time.perf_counter() - t0
    print("k  silhouette  separation_ratio  min_inter_medoid  zero-distance medoid pairs  small clusters")
    for k, e in results.items():
        print(f"{k}  {e['silhouette']['overall']:.3f}       {e['separation']['separation_ratio']:.2f}              "
              f"{e['separation']['min_inter_medoid']:.3f}             {e['separation']['n_zero_distance_medoid_pairs']}                          {e['small_clusters']}")
    print(f"identity test: worst |collapsed - reference| = {worst:.2e} over 8 trials with {n_dup} duplicated units; 2500-unit silhouette {t_big:.2f}s")

    checks = {
        "hand calculation: s = [0.95, 8/9, 0] and overall 0.69722 (a unit alone with count 1 has s = 0)": np.allclose(su, s_hand, atol=1e-12) and abs(sh - 0.6972222222222222) < 1e-12,
        "identity test: collapsed weighted silhouette = brute force = scikit-learn (duplicates, singleton, MISSING and LOST rows)": ident_ok and n_dup >= 2
            and bool((td.states == -1).any()) and bool((td.states == -2).any()),
        "identity test: per-unit and per-cluster values equal scikit-learn on the expanded individuals": ident_ok,
        "identity test: random weighted Euclidean instances equal scikit-learn": ident2,
        "a = b = 0 gives s = 0, one cluster gives NaN": silhouette_precomputed(Dz, lz)[0] == _scikit_zero(Dz, lz) and math.isnan(one_cluster[0]) and np.isnan(one_cluster[1]).all(),
        "a unit with count > 1 alone in its cluster has a = 0 (not forced to s = 0)": silhouette_precomputed(Dh, np.array([0, 1, 1]), np.array([3.0, 1.0, 1.0]))[1][0] > 0.5,
        "separation by hand: within 1.5, between 10, ratio 6.667": abs(sep_l["mean_within"] - 1.5) < 1e-12 and abs(sep_l["mean_between_medoid"] - 10) < 1e-12
            and abs(sep_l["separation_ratio"] - 10 / 1.5) < 1e-12 and sep_l["min_inter_medoid"] == 10 and sep_l["n_zero_distance_medoid_pairs"] == 0,
        "separation: two copies of one unit are two individuals at distance 0 (within = 2/3)": abs(sep_w["mean_within"] - 2 / 3) < 1e-12,
        "separation equals the brute-force pair count on the expanded individuals": abs(sep_r["mean_within"] - w_sum / w_n) < 1e-10
            and abs(sep_r["mean_between_medoid"] - np.mean(bt)) < 1e-12 and abs(sep_r["min_inter_medoid"] - min(bt)) < 1e-12,
        "separation: undefined cases are None with a reason, not NaN": sep_one["status"] == "not_defined" and sep_one["mean_between_medoid"] is None
            and "one cluster" in sep_one["reason"] and sep_single["mean_within"] is None and "no cluster holds two" in sep_single["reason"],
        "separation: twin medoids at distance 0 are counted": sep_tw["n_zero_distance_medoid_pairs"] == 1 and sep_tw["min_inter_medoid"] == 0,
        "separation: a medoid outside its cluster raises": raises(ValueError, lambda: pathway_separation(Dl, np.array([0, 0, 1, 1]), np.array([2, 0])))
            and raises(ValueError, lambda: pathway_separation(Dl, np.array([0, 0, 2, 2]), np.array([0, 2]))) and raises(ValueError, lambda: pathway_separation(Dl, np.array([0, 0, 1, 1]), np.array([0])))
            and raises(ValueError, lambda: pathway_separation(Dl, np.array([0, 0, 1, 1]), np.array([0, 9]))),
        "DB and CH equal scikit-learn on the expanded individuals (weighted by counts)": fi["status"] == "ok" and abs(fi["davies_bouldin"] - davies_bouldin_score(Xe, le)) < 1e-10
            and abs(fi["calinski_harabasz"] - calinski_harabasz_score(Xe, le)) < 1e-8,
        "DB and CH unweighted equal scikit-learn; zero-scatter case follows scikit-learn": abs(fi_same["davies_bouldin"] - davies_bouldin_score(Xf, lp)) < 1e-10
            and abs(fi_same["calinski_harabasz"] - calinski_harabasz_score(Xf, lp)) < 1e-8 and fi_const["davies_bouldin"] == 0.0 and fi_const["calinski_harabasz"] == 1.0,
        "DB and CH: no features -> not_applicable with a reason; one cluster -> not_defined": fi_none["status"] == "not_applicable" and "Euclidean" in fi_none["reason"]
            and fi_one["status"] == "not_defined",
        "DB and CH: protected column names and non-finite features raise": raises(FairnessError, lambda: feature_based_indices(pd.DataFrame({"sex": np.arange(20.0)}), lp))
            and raises(ValueError, lambda: feature_based_indices(np.where(np.arange(40).reshape(20, 2) == 5, np.nan, 1.0), lp)),
        "evaluate_partition: result is JSON-safe (no NaN) for pathways and the baseline": all(json.dumps(e, allow_nan=False) for e in (*results.values(), ev_b, ev_feat)),
        "evaluate_partition: silhouette equals scikit-learn on the expanded individuals (pathways and baseline)": abs(ev6["silhouette"]["overall"] - sil_e6) < 1e-10
            and abs(ev_b["silhouette"]["overall"] - sil_e_b) < 1e-10,
        "evaluate_partition: sizes add up to the individuals and the fit sample is stated": ev6["n_individuals"] == int(plan.col_fit.freq.sum()) == sum(ev6["sizes"].values())
            and ev6["evaluated_on"] == "fit_sample" and ev6["n_units"] == plan.col_fit.u and ev_b["n_clusters"] == 2,
        "evaluate_partition: twin medoids are counted exactly": ev6["separation"]["n_zero_distance_medoid_pairs"] == zero_pairs,
        "evaluate_partition: small clusters flagged by clustering.min_cluster_frac": ev_small["small_clusters"] == [int(c) for c, n in ev_small["sizes"].items() if n / ev_small["n_individuals"] < 0.5]
            and len(ev_small["small_clusters"]) >= 1 and results[2]["small_clusters"] == [],
        "evaluate_partition: DB/CH not_applicable by default, computed only when declared in config and supplied": ev6["feature_indices"]["status"] == "not_applicable"
            and "evaluation.feature_representation is null" in ev6["feature_indices"]["reason"] and ev_feat["feature_indices"]["status"] == "ok"
            and abs(ev_feat["feature_indices"]["calinski_harabasz"] - calinski_harabasz_score(Xi, lab6[inv_f])) < 1e-6
            and raises(ConfigError, lambda: evaluate_partition(D, lab6, cfg, med6, X_units, ff)),
        "evaluate_partition: protected feature columns raise (role names and the config's verified names)": raises(FairnessError, lambda: evaluate_partition(
            D, lab6, cfg_decl, med6, pd.DataFrame({"religion": np.zeros(plan.col_fit.u)}), ff)),
        "evaluate_partition: one cluster gives silhouette None with a reason": evaluate_partition(Dh, np.zeros(3, dtype=np.int64), cfg, None, None, f_h)["silhouette"]["status"] == "not_defined"
            and evaluate_partition(Dh, np.zeros(3, dtype=np.int64), cfg, None, None, f_h)["silhouette"]["overall"] is None,
        "bad inputs raise": raises(ValueError, lambda: silhouette_precomputed(Dh, np.array([0, 1]), None)) and raises(ValueError, lambda: silhouette_precomputed(Dh, np.array([0, 1, -1])))
            and raises(ValueError, lambda: silhouette_precomputed(Dh, np.array([0.0, 1.0, 1.0]))) and raises(ValueError, lambda: silhouette_precomputed(Dh, lab_h, np.array([1.0, 0.0, 1.0])))
            and raises(ValueError, lambda: silhouette_precomputed(Dh + np.triu(np.ones((3, 3)), 1), lab_h)) and raises(ValueError, lambda: silhouette_precomputed(Dh * np.nan, lab_h))
            and raises(ValueError, lambda: evaluate_partition(Dh, lab_h, cfg, evaluated_on="somewhere")),
        "deterministic": evaluate_partition(D, lab6, cfg, med6, None, ff) == ev6,
    }
    for name, ok in checks.items():
        print(f"  demo check [{'ok' if ok else 'FAILED'}]: {name}")
    if not all(checks.values()):
        return 1
    print(f"Demo checks passed ({len(checks)}). All data above is SYNTHETIC or hand-built.")
    return 0


def _scikit_zero(D: np.ndarray, labels: np.ndarray) -> float:
    """Demo helper: scikit-learn's value for a tiny matrix whose silhouettes are all 0/0."""
    from sklearn.metrics import silhouette_score

    return float(silhouette_score(D, labels, metric="precomputed"))


if __name__ == "__main__":
    raise SystemExit(_demo())
