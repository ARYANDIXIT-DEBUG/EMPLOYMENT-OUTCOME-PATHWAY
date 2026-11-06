"""Tests for src/evaluation.py: weighted silhouette, pathway separation, feature indices, evaluate_partition.

Why these tests exist: the silhouette is the number most likely to be quoted in the report, and it is computed here
by matrix algebra on COLLAPSED units weighted by how many people each unit stands for. The promise (INTERFACES
section 5) is that this equals the textbook silhouette on every individual. If that identity broke, the reported
silhouette would depend on how much the data happened to collapse, and nothing would crash. So the central tests
expand the collapsed units back into individuals and compare against (a) a slow one-person-at-a-time reference and
(b) scikit-learn, neither of which share the module's algebra.

Hand-written fixtures and random matrices only. Nothing here is a result.

Run:  python -m pytest tests/test_evaluation.py -q        (or:  python tests/test_evaluation.py)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import calinski_harabasz_score, davies_bouldin_score, silhouette_score

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import Config, ConfigError, FairnessError, load_config          # noqa: E402
from src.evaluation import (brute_force_silhouette, evaluate_partition, feature_based_indices,     # noqa: E402
                            pathway_separation, silhouette_by_cluster, silhouette_precomputed)

CFG = load_config()
D0 = CFG.to_dict()


def cfg_eval(**kw) -> Config:
    return Config({**D0, "evaluation": {**D0["evaluation"], **kw}}, CFG.root)


def random_problem(m=40, k=3, seed=0, dup=True):
    """Symmetric zero-diagonal matrix from random points, labels, and individual counts (some > 1)."""
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(m, 3)) + rng.integers(0, k, size=(m, 1)) * 1.5
    D = np.sqrt(((X[:, None] - X[None]) ** 2).sum(-1))
    labels = rng.integers(0, k, size=m)
    labels[:k] = np.arange(k)
    f = rng.integers(1, 5, size=m) if dup else np.ones(m, dtype=int)
    return X, D, labels, f


def expand(D, labels, f):
    idx = np.repeat(np.arange(len(f)), f)
    return D[np.ix_(idx, idx)], labels[idx], idx


# ---------------------------------------------------------------------------------------------
# Silhouette
# ---------------------------------------------------------------------------------------------
def test_silhouette_by_hand_on_four_points():
    """Two tight pairs far apart. Points 0,1 at 0 and 1; points 2,3 at 10 and 11 on a line.
    a(0)=1, b(0)=mean(10,11)=10.5 -> s=(10.5-1)/10.5 ; a(1)=1, b(1)=mean(9,10)=9.5 -> s=(9.5-1)/9.5 ; symmetric for 2,3."""
    x = np.array([0.0, 1.0, 10.0, 11.0])
    D = np.abs(x[:, None] - x[None])
    overall, s = silhouette_precomputed(D, np.array([0, 0, 1, 1]))
    expect = [(10.5 - 1) / 10.5, (9.5 - 1) / 9.5, (9.5 - 1) / 9.5, (10.5 - 1) / 10.5]
    assert np.allclose(s, expect) and overall == pytest.approx(np.mean(expect))


@pytest.mark.parametrize("seed", range(5))
def test_collapsed_weighted_silhouette_equals_expanded_individuals(seed):
    """The identity the design rests on, against the one-person-at-a-time reference AND scikit-learn."""
    _, D, labels, f = random_problem(seed=seed)
    overall, _ = silhouette_precomputed(D, labels, f)
    De, le, _ = expand(D, labels, f)
    assert overall == pytest.approx(brute_force_silhouette(De, le), abs=1e-12)
    assert overall == pytest.approx(silhouette_score(De, le, metric="precomputed"), abs=1e-12)


def test_per_unit_silhouette_of_duplicate_copies_is_identical():
    _, D, labels, f = random_problem(seed=9)
    _, s = silhouette_precomputed(D, labels, f)
    De, le, idx = expand(D, labels, f)
    from sklearn.metrics import silhouette_samples
    se = silhouette_samples(De, le, metric="precomputed")
    assert np.allclose(se, s[idx], atol=1e-12)


def test_unit_with_many_copies_alone_in_its_cluster_has_zero_cohesion_distance_not_zero_silhouette():
    """A unit with freq 3 alone in its cluster: N_C = 3 > 1, copies are at distance 0, so a = 0 and s = 1 (not 0)."""
    x = np.array([0.0, 5.0, 6.0])
    D = np.abs(x[:, None] - x[None])
    _, s = silhouette_precomputed(D, np.array([0, 1, 1]), np.array([3, 1, 1]))
    assert s[0] == pytest.approx(1.0)


def test_singleton_cluster_of_one_individual_scores_zero():
    x = np.array([0.0, 5.0, 6.0])
    D = np.abs(x[:, None] - x[None])
    _, s = silhouette_precomputed(D, np.array([0, 1, 1]))
    assert s[0] == 0.0


def test_all_identical_points_give_zero_not_nan():
    D = np.zeros((4, 4))
    overall, s = silhouette_precomputed(D, np.array([0, 0, 1, 1]))
    assert overall == 0.0 and (s == 0).all()


def test_fewer_than_two_clusters_is_nan_and_reported_as_not_defined():
    D = np.abs(np.arange(4.0)[:, None] - np.arange(4.0)[None])
    overall, s = silhouette_precomputed(D, np.zeros(4, dtype=int))
    assert np.isnan(overall) and np.isnan(s).all()
    r = evaluate_partition(D, np.zeros(4, dtype=int), CFG)
    assert r["silhouette"]["status"] == "not_defined" and r["silhouette"]["overall"] is None
    assert "at least 2" in r["silhouette"]["reason"]


def test_silhouette_by_cluster_table():
    _, D, labels, f = random_problem(seed=2)
    t = silhouette_by_cluster(D, labels, f)
    overall, _ = silhouette_precomputed(D, labels, f)
    assert list(t["cluster"]) == [0, 1, 2]
    assert t["share_of_individuals"].sum() == pytest.approx(1.0) and t["n_individuals"].sum() == f.sum()
    assert (t["mean_silhouette"] * t["share_of_individuals"]).sum() == pytest.approx(overall)   # per-cluster means recombine to the overall
    assert ((t["share_negative"] >= 0) & (t["share_negative"] <= 1)).all()


def test_bad_matrices_and_labels_are_refused():
    D = np.abs(np.arange(4.0)[:, None] - np.arange(4.0)[None])
    asym = D.copy()
    asym[0, 1] += 1
    for bad in (asym, D + 1.0 - np.eye(4) * 0 + np.eye(4), np.full((4, 4), np.nan), D[:3, :4]):
        with pytest.raises(ValueError):
            silhouette_precomputed(bad, np.array([0, 0, 1, 1]))
    with pytest.raises(ValueError):
        silhouette_precomputed(D, np.array([0, 0, 1]))                                   # wrong label length
    with pytest.raises(ValueError):
        silhouette_precomputed(D, np.array([0, 0, 1, 1]), np.array([1, 1, 0, 0]))        # a zero individual count is not allowed


# ---------------------------------------------------------------------------------------------
# Separation
# ---------------------------------------------------------------------------------------------
def test_separation_by_hand():
    """Points 0,1 | 10,11 with medoids 0 and 10: between = 10; within pairs (0,1) and (10,11) are both 1 -> ratio 10."""
    x = np.array([0.0, 1.0, 10.0, 11.0])
    D = np.abs(x[:, None] - x[None])
    r = pathway_separation(D, np.array([0, 0, 1, 1]), np.array([0, 2]))
    assert r["mean_between_medoid"] == 10.0 and r["min_inter_medoid"] == 10.0 and r["mean_within"] == 1.0
    assert r["separation_ratio"] == 10.0 and r["n_zero_distance_medoid_pairs"] == 0 and r["status"] == "ok"


def test_separation_counts_copies_as_individuals_at_distance_zero():
    """Unit 0 stands for 3 people, unit 1 for 1: pairs in the cluster = 6, only the 3 cross pairs are at distance 1."""
    D = np.array([[0.0, 1.0, 9.0], [1.0, 0.0, 9.0], [9.0, 9.0, 0.0]])
    r = pathway_separation(D, np.array([0, 0, 1]), np.array([0, 2]), np.array([3, 1, 1]))
    assert r["mean_within"] == pytest.approx(3 * 1.0 / 6)                                # 3 copy-copy pairs at 0, 3 copy-other pairs at 1: 3/6


def test_wasted_medoid_is_reported():
    D = np.zeros((4, 4))
    D[0, 2] = D[2, 0] = D[1, 3] = D[3, 1] = D[0, 3] = D[3, 0] = D[1, 2] = D[2, 1] = 0.0
    D[0, 1] = D[1, 0] = 0.5
    r = pathway_separation(D, np.array([0, 0, 1, 1]), np.array([0, 2]))
    assert r["n_zero_distance_medoid_pairs"] == 1


def test_separation_undefined_cases_have_reasons_not_numbers():
    D = np.abs(np.arange(3.0)[:, None] - np.arange(3.0)[None])
    one = pathway_separation(D, np.zeros(3, dtype=int), np.array([0]))
    assert one["status"] == "not_defined" and one["separation_ratio"] is None and "one cluster" in one["reason"]
    singles = pathway_separation(D, np.array([0, 1, 2]), np.array([0, 1, 2]))
    assert singles["status"] == "not_defined" and "no cluster holds two" in singles["reason"]
    zero = pathway_separation(np.zeros((4, 4)), np.array([0, 0, 1, 1]), np.array([0, 2]))
    assert zero["separation_ratio"] is None and "is 0" in zero["reason"]


def test_separation_validates_medoids_and_labels():
    D = np.abs(np.arange(4.0)[:, None] - np.arange(4.0)[None])
    lab = np.array([0, 0, 1, 1])
    for bad in (np.array([0]), np.array([0, 5]), np.array([2, 0]), np.array([0.0, 2.0]), np.array([-1, 2])):
        with pytest.raises(ValueError):
            pathway_separation(D, lab, bad)
    with pytest.raises(ValueError, match="0..k-1"):
        pathway_separation(D, np.array([0, 0, 2, 2]), np.array([0, 2]))


# ---------------------------------------------------------------------------------------------
# Feature-based indices
# ---------------------------------------------------------------------------------------------
def test_feature_indices_not_applicable_without_features():
    r = feature_based_indices(None, np.array([0, 1]))
    assert r["status"] == "not_applicable" and "Euclidean" in r["reason"]


@pytest.mark.parametrize("seed", range(3))
def test_weighted_feature_indices_equal_scikit_learn_on_expanded_individuals(seed):
    X, _, labels, f = random_problem(seed=seed)
    r = feature_based_indices(X, labels, f)
    Xe, le = np.repeat(X, f, axis=0), np.repeat(labels, f)
    assert r["status"] == "ok"
    assert r["davies_bouldin"] == pytest.approx(davies_bouldin_score(Xe, le), rel=1e-9)
    assert r["calinski_harabasz"] == pytest.approx(calinski_harabasz_score(Xe, le), rel=1e-9)


def test_feature_indices_not_defined_cases_and_bad_input():
    X = np.random.default_rng(0).normal(size=(4, 2))
    assert feature_based_indices(X, np.zeros(4, dtype=int))["status"] == "not_defined"
    assert feature_based_indices(X, np.array([0, 1, 2, 3]))["status"] == "not_defined"        # as many clusters as individuals
    with pytest.raises(ValueError, match="non-finite"):
        feature_based_indices(np.array([[np.nan, 1.0]] * 4), np.array([0, 0, 1, 1]))
    with pytest.raises(ValueError, match="two-dimensional"):
        feature_based_indices(np.arange(4.0), np.array([0, 0, 1, 1]))


def test_protected_feature_columns_are_a_fairness_error():
    df = pd.DataFrame({"sex": [0, 1, 0, 1], "x": [1.0, 2.0, 3.0, 4.0]})
    with pytest.raises(FairnessError):
        feature_based_indices(df, np.array([0, 0, 1, 1]))


# ---------------------------------------------------------------------------------------------
# evaluate_partition
# ---------------------------------------------------------------------------------------------
def test_evaluate_partition_is_complete_json_safe_and_consistent():
    _, D, labels, f = random_problem(seed=4)
    med = np.array([int(np.flatnonzero(labels == c)[0]) for c in range(3)])
    r = evaluate_partition(D, labels, CFG, medoid_idx=med, sample_weight=f)
    json.dumps(r, allow_nan=False)                                                         # no NaN or infinity anywhere
    assert r["evaluated_on"] == "fit_sample" and r["n_units"] == len(D) and r["n_individuals"] == int(f.sum()) and r["n_clusters"] == 3
    assert r["silhouette"]["overall"] == pytest.approx(silhouette_precomputed(D, labels, f)[0])
    assert sum(r["sizes"].values()) == f.sum() and r["separation"]["status"] in ("ok", "not_defined")
    assert r["feature_indices"]["status"] == "not_applicable" and "feature_representation is null" in r["feature_indices"]["reason"]
    assert r["min_cluster_share"] == pytest.approx(min(r["sizes"].values()) / f.sum())


def test_separation_not_applicable_without_medoids():
    _, D, labels, _ = random_problem(seed=1)
    assert evaluate_partition(D, labels, CFG)["separation"]["status"] == "not_applicable"


def test_small_clusters_use_the_configured_fraction():
    D = np.abs(np.arange(101.0)[:, None] - np.arange(101.0)[None])
    labels = np.zeros(101, dtype=int)
    labels[100] = 1                                                                        # one person of 101 is below 2%
    r = evaluate_partition(D, labels, CFG)
    assert r["small_clusters"] == [1] and r["min_cluster_frac"] == D0["clustering"]["min_cluster_frac"]


def test_features_need_a_declared_representation():
    X, D, labels, f = random_problem(seed=6)
    with pytest.raises(ConfigError, match="feature_representation"):
        evaluate_partition(D, labels, CFG, features=X, sample_weight=f)
    r = evaluate_partition(D, labels, cfg_eval(feature_representation="demo only"), features=X, sample_weight=f)
    assert r["feature_indices"]["status"] == "ok"
    df = pd.DataFrame(X, columns=["sex", "b", "c"])
    with pytest.raises(FairnessError):
        evaluate_partition(D, labels, cfg_eval(feature_representation="demo only"), features=df, sample_weight=f)


def test_evaluated_on_is_validated_and_recorded():
    _, D, labels, _ = random_problem(seed=1)
    assert evaluate_partition(D, labels, CFG, evaluated_on="all_units")["evaluated_on"] == "all_units"
    with pytest.raises(ValueError, match="evaluated_on"):
        evaluate_partition(D, labels, CFG, evaluated_on="somewhere")


def test_counts_must_be_finite_and_positive():
    """The module cannot tell a survey weight from an individual count (any positive number is a valid weight in the
    formula), so keeping survey weights out is the CALLER's job: the pipeline passes `freq` only. What it does refuse
    is a count that would make the formula meaningless."""
    _, D, labels, _ = random_problem(m=10, seed=3, dup=False)
    for bad in (np.zeros(10), -np.ones(10), np.full(10, np.nan), np.ones(9)):
        with pytest.raises(ValueError, match="sample_weight"):
            silhouette_precomputed(D, labels, bad)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
