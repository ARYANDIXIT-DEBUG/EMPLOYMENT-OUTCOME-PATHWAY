"""Tests for src/stability.py: ARI, attrition and censoring, matching pathways, surviving pathways, choosing k, repeats.

Why these tests exist: the stability numbers answer "would these pathways survive the data the programme really
gets?", and they are quoted next to the pathways. Several parts fail silently if wrong: an ARI that is not the
textbook ARI, an attrition scheme that removes the wrong number of people or the wrong kind of person, a survival
rule that is off by one visit, or a k-rule that quietly lets silhouette decide. Each test fixes one of those rules on a
case worked out on paper or against an independent reference (scikit-learn, exact probabilities, a brute-force match).

Hand-written fixtures, random arrays and SYNTHETIC generator data used only to test the code. Nothing here is a result.

Run:  python -m pytest tests/test_stability.py -q        (or:  python tests/test_stability.py)   (about 30 s)
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import adjusted_rand_score

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.clustering import cluster_full                                                  # noqa: E402
from src.config import Config, ConfigError, FairnessError, load_config, make_rng         # noqa: E402
from src.distances import build_distance, plan_reduction, substitution_cost_matrix       # noqa: E402
from src.stability import (adjusted_rand_index, censor_trajectories, censored_eligible_mask, informative_attrition,   # noqa: E402
                           match_clusters, pathway_survival, random_attrition, run_stability, select_k,
                           stability_tables)
from src.synthetic_data import generate_synthetic                                        # noqa: E402
from src.trajectories import build_trajectories                                          # noqa: E402

CFG = load_config()
D0 = CFG.to_dict()


def cfg_with(section: str, **kw) -> Config:
    return Config({**D0, section: {**D0[section], **kw}}, CFG.root)


# ---------------------------------------------------------------------------------------------
# Adjusted Rand index
# ---------------------------------------------------------------------------------------------
def test_ari_equals_scikit_learn_on_random_partitions():
    rg = np.random.default_rng(0)
    for _ in range(40):
        n = int(rg.integers(4, 80))
        a, b = rg.integers(0, int(rg.integers(1, 6)), n), rg.integers(0, int(rg.integers(1, 6)), n)
        assert adjusted_rand_index(a, b) == pytest.approx(adjusted_rand_score(a, b), abs=1e-12)


def test_ari_known_values():
    assert adjusted_rand_index([0, 0, 1, 1], [5, 5, 9, 9]) == 1.0                    # same partition, different label names
    assert adjusted_rand_index([0, 0, 1, 1], [0, 1, 0, 1]) == pytest.approx(-0.5)    # the classic worst case for 4 points
    assert adjusted_rand_index([0, 0, 0], [1, 1, 1]) == 1.0                          # both trivial in the same way: 1, as scikit-learn


def test_weighted_ari_equals_ari_on_expanded_individuals():
    rg = np.random.default_rng(1)
    for _ in range(20):
        m = int(rg.integers(3, 15))
        a, b, w = rg.integers(0, 4, m), rg.integers(0, 4, m), rg.integers(1, 6, m)
        assert adjusted_rand_index(a, b, w) == pytest.approx(adjusted_rand_score(np.repeat(a, w), np.repeat(b, w)), abs=1e-12)


def test_ari_bad_inputs():
    with pytest.raises(ValueError):
        adjusted_rand_index([0, 1], [0, 1, 1])
    with pytest.raises(ValueError, match="at least 2"):
        adjusted_rand_index([0], [0])
    for bad in ([1.5, 1], [-1, 1], [np.nan, 1]):
        with pytest.raises(ValueError, match="integer counts"):
            adjusted_rand_index([0, 1], [0, 1], bad)


# ---------------------------------------------------------------------------------------------
# Attrition
# ---------------------------------------------------------------------------------------------
def test_random_attrition_removes_exactly_the_stated_number_and_is_reproducible():
    keep = random_attrition(1000, 0.3, np.random.default_rng(1))
    assert len(keep) == 700 and len(set(keep)) == 700 and (np.diff(keep) > 0).all() and keep.min() >= 0 and keep.max() < 1000
    assert np.array_equal(keep, random_attrition(1000, 0.3, np.random.default_rng(1)))
    assert not np.array_equal(keep, random_attrition(1000, 0.3, np.random.default_rng(2)))


def test_attrition_always_leaves_someone_and_rejects_bad_arguments():
    assert len(random_attrition(3, 0.99, np.random.default_rng(0))) >= 1
    for n, frac in ((0, 0.1), (10, 1.0), (10, -0.1), (10, float("nan")), (2.5, 0.1)):
        with pytest.raises(ValueError):
            random_attrition(n, frac, np.random.default_rng(0))


def test_random_attrition_is_uniform():
    """Each individual should stay with probability 1 - frac. 20000 draws of n = 4, frac = 0.5: each stays about half the time."""
    stay = np.zeros(4)
    rg = np.random.default_rng(5)
    for _ in range(20000):
        stay[random_attrition(4, 0.5, rg)] += 1
    assert np.allclose(stay / 20000, 0.5, atol=0.02)


def test_informative_attrition_removes_the_requested_number_and_strength_zero_is_random():
    attr = np.arange(200.0)
    keep = informative_attrition(attr, 0.25, 1.0, np.random.default_rng(0))
    assert len(keep) == 150
    stay = np.zeros(200)
    rg = np.random.default_rng(1)
    for _ in range(600):
        stay[informative_attrition(attr, 0.5, 0.0, rg)] += 1
    assert abs(stay[:100].mean() - stay[100:].mean()) / 600 < 0.03                         # no dependence on the attribute at strength 0


def test_informative_attrition_direction_follows_the_sign_of_strength():
    attr = np.arange(100.0)
    hi = lo = 0.0
    rg = np.random.default_rng(2)
    for _ in range(300):
        k_pos = informative_attrition(attr, 0.4, 1.0, rg)
        k_neg = informative_attrition(attr, 0.4, -1.0, rg)
        hi += np.mean(k_pos)                                                               # mean index of those who STAY
        lo += np.mean(k_neg)
    assert hi / 300 < 49.5 < lo / 300                                                      # positive: high values leave, so stayers are lower; negative: reverse


def test_informative_attrition_matches_exact_probabilities_for_three_people():
    """n = 3, drop 1, strength 1: odds exp(-1), 1, exp(1). P(remove i) = w_i / sum w."""
    w = np.exp(np.array([-1.0, 0.0, 1.0]))
    expect = w / w.sum()
    removed = np.zeros(3)
    rg = np.random.default_rng(3)
    for _ in range(20000):
        keep = informative_attrition(np.array([1.0, 2.0, 3.0]), 1 / 3, 1.0, rg)
        removed[list(set(range(3)) - set(keep))[0]] += 1
    assert np.allclose(removed / 20000, expect, atol=0.015)


def test_informative_attrition_missing_attribute_is_neutral_and_non_numeric_is_refused():
    attr = np.array([1.0, np.nan, 3.0, 4.0, np.nan, 6.0])
    assert len(informative_attrition(attr, 0.5, 1.0, np.random.default_rng(0))) == 3
    with pytest.raises(ValueError, match="no numeric"):
        informative_attrition(np.array(["a", "b", "c"], dtype=object), 0.3, 1.0, np.random.default_rng(0))
    with pytest.raises(ValueError, match="finite"):
        informative_attrition(np.arange(5.0), 0.3, float("inf"), np.random.default_rng(0))


# ---------------------------------------------------------------------------------------------
# Censoring
# ---------------------------------------------------------------------------------------------
def _td(rows):
    codes = [str(s["raw_codes"][0]) for s in D0["states"]]
    recs = [{"person_id": f"p{i:03d}", "t": t, "raw_status": codes[v] if v >= 0 else str(D0["unknown_codes"][0])}
            for i, r in enumerate(rows) for t, v in enumerate(r)]
    return build_trajectories(pd.DataFrame(recs), CFG)


def test_censoring_keeps_the_first_visits_and_records_it():
    td = _td([[0, 1, 2, 3], [4, 4, 5, 5]])
    c = censor_trajectories(td, 2)
    assert c.states.tolist() == [[0, 1], [4, 4]] and c.time_labels == td.time_labels[:2]
    assert c.meta["censored_to"] == 2 and c.meta["censored_from"] == 4 and td.T == 4                    # the original is untouched
    for bad in (0, 5, True, 1.5):
        with pytest.raises(ValueError):
            censor_trajectories(td, bad)


def test_censored_eligibility_uses_the_configured_minimum():
    need = min(int(CFG.trainee.min_time_points), 2)
    td = _td([[0, 1, 2, 3], [0, -1, 2, 3], [-1, -1, 2, 3]])
    c = censor_trajectories(td, 2)
    observed = (c.states >= 0).sum(axis=1)
    assert censored_eligible_mask(c, CFG).tolist() == (observed >= need).tolist()
    assert censored_eligible_mask(c, CFG)[0]                                                  # a fully observed person is always eligible


# ---------------------------------------------------------------------------------------------
# Matching new medoids to reference medoids, and survival
# ---------------------------------------------------------------------------------------------
def brute_match(ref, new):
    """Plain Hamming over jointly observed visits, nearest reference medoid, lowest index on ties."""
    out_m, out_d = [], []
    for n in new:
        ds = []
        for r in ref:
            common = [t for t in range(len(n)) if n[t] >= 0 and r[t] >= 0]
            ds.append(np.mean([n[t] != r[t] for t in common]) if len(common) >= 2 else 1.0)
        out_m.append(int(np.argmin(ds)))
        out_d.append(min(ds))
    return np.array(out_m), np.array(out_d)


def test_match_clusters_equals_brute_force_and_many_new_may_share_a_reference():
    ref = np.array([[0, 0, 0, 0], [1, 1, 1, 1], [2, 2, 3, 3]], dtype=np.int8)
    new = np.array([[0, 0, 0, 1], [1, 1, 1, 1], [1, 1, 2, 1], [2, 2, 3, -1]], dtype=np.int8)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m, d = match_clusters(ref, new, CFG)
    bm, bd = brute_match(ref, new)
    assert np.array_equal(m, bm) and np.allclose(d, bd)
    assert m.tolist() == [0, 1, 1, 2]                                                      # two new medoids map to reference 1


def test_match_clusters_ties_go_to_the_lowest_reference_and_censoring_truncates_the_reference():
    ref = np.array([[0, 0, 1, 1], [0, 0, 2, 2]], dtype=np.int8)
    m, d = match_clusters(ref, np.array([[0, 0]], dtype=np.int8), CFG, n_points=2)         # identical on the first two visits for both
    assert m.tolist() == [0] and d.tolist() == [0.0]
    with pytest.raises(ValueError, match="n_points"):
        match_clusters(ref, np.array([[0, 0]], dtype=np.int8), CFG)                         # visit-count mismatch must name the fix
    with pytest.raises(ValueError):
        match_clusters(ref, np.array([[0, 0]], dtype=np.int8), CFG, n_points=9)


def test_match_uses_hamming_whatever_the_clustering_distance_is():
    ref = np.array([[0, 0, 0, 0], [1, 1, 1, 1]], dtype=np.int8)
    new = np.array([[0, 0, 0, 1]], dtype=np.int8)
    a, da = match_clusters(ref, new, CFG)
    b, db = match_clusters(ref, new, cfg_with("distance", name="optimal_matching"))
    assert np.array_equal(a, b) and np.allclose(da, db) and da[0] == 0.25


def test_pathway_survival_boundary_and_unmatched_pathways():
    survived, md = pathway_survival(np.array([0, 0, 2]), np.array([0.5, 0.25, 0.3]), 3, 0.25)
    assert survived.tolist() == [True, False, False]                                       # 0.25 exactly is inside the threshold; 0.3 is not
    assert md[0] == 0.25 and np.isnan(md[1]) and md[2] == 0.3                              # pathway 1 had no new medoid: NaN, and it did not survive


# ---------------------------------------------------------------------------------------------
# k selection
# ---------------------------------------------------------------------------------------------
def table(rows):
    cols = ["k", "silhouette", "stability_ari_mean", "n_small_clusters", "n_zero_distance_medoid_pairs", "note"]
    return pd.DataFrame([{**dict(zip(cols, r))} for r in rows], columns=cols)


def test_select_k_takes_the_smallest_admissible_k_within_the_margin():
    t = table([(2, 0.50, 0.9, 0, 0, None), (3, 0.69, 0.9, 0, 0, None), (4, 0.70, 0.8, 0, 0, None), (5, 0.55, 0.9, 0, 0, None)])
    k, reason = select_k(t, CFG)
    assert k == 3 and "silhouette alone did not decide" in reason                           # 0.70 - 0.02 = 0.68, so k = 3 (0.69) beats k = 4


def test_select_k_excludes_unstable_tiny_and_wasted_k_and_says_why():
    t = table([(2, 0.9, 0.3, 0, 0, None), (3, 0.8, 0.9, 1, 0, None), (4, 0.7, 0.9, 0, 1, None), (5, 0.6, 0.9, 0, 0, None), (6, 0.9, 0.9, 0, 0, "not fitted")])
    k, reason = select_k(t, CFG)
    assert k == 5
    assert "stability ARI" in reason and "below" in reason and "distance 0" in reason and "not fitted" in reason


def test_select_k_falls_back_to_the_most_stable_k_and_flags_it():
    t = table([(2, 0.9, 0.2, 0, 0, None), (3, 0.5, 0.4, 0, 0, None), (4, 0.6, 0.4, 0, 0, None)])
    k, reason = select_k(t, CFG)
    assert k == 3 and reason.startswith("FALLBACK:")                                       # tie on stability goes to the smaller k


def test_select_k_never_chooses_on_silhouette_alone():
    t = table([(2, 0.99, 0.1, 0, 0, None), (3, 0.40, 0.9, 0, 0, None)])
    assert select_k(t, CFG)[0] == 3


def test_select_k_bad_tables():
    with pytest.raises(ValueError):
        select_k(pd.DataFrame(), CFG)
    with pytest.raises(ValueError):
        select_k(pd.DataFrame({"k": [2]}), CFG)
    t = table([(2, np.nan, np.nan, 0, 0, None)])
    with pytest.raises(ValueError, match="nothing to select"):
        select_k(t, CFG)


# ---------------------------------------------------------------------------------------------
# run_stability end to end (SYNTHETIC, small)
# ---------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def world():
    df, truth = generate_synthetic(CFG, n=500, seed_offset=31)
    td = build_trajectories(df, CFG)
    plan = plan_reduction(td, CFG, make_rng(CFG, "t-plan"))
    sub = substitution_cost_matrix(td, CFG)
    D = build_distance(plan.col_fit, CFG, sub)
    ref = cluster_full(plan, D, CFG, 4, make_rng(CFG, "t-ref"), sub)
    return td, ref


def test_run_stability_shapes_ranges_and_reproducibility(world):
    td, ref = world
    a = run_stability(td, CFG, ref, "random", 0.2, 3, make_rng(CFG, "t-a"))
    b = run_stability(td, CFG, ref, "random", 0.2, 3, make_rng(CFG, "t-a"))
    assert a.ari.shape == (3,) and np.array_equal(a.ari, b.ari)
    assert ((a.ari >= -1) & (a.ari <= 1)).all()
    assert len(a.survival) == ref.fit_result.k and set(a.survival["survival_rate"]) <= {0.0, 1 / 3, 2 / 3, 1.0}


def test_more_loss_does_not_improve_agreement_on_average(world):
    td, ref = world
    lo = run_stability(td, CFG, ref, "random", 0.1, 4, make_rng(CFG, "t-lo")).ari.mean()
    hi = run_stability(td, CFG, ref, "random", 0.5, 4, make_rng(CFG, "t-hi")).ari.mean()
    assert lo >= hi - 0.05                                                                 # a loose guard: loss must not help, up to noise


def test_censoring_and_informative_schemes_run(world):
    td, ref = world
    c = run_stability(td, CFG, ref, "censoring", 3, 2, make_rng(CFG, "t-c"))
    i = run_stability(td, CFG, ref, "informative", 0.3, 2, make_rng(CFG, "t-i"))
    assert c.ari.shape == (2,) and i.ari.shape == (2,)


def test_run_stability_refuses_bad_settings(world):
    td, ref = world
    rg = np.random.default_rng(0)
    for scheme, level in (("bogus", 0.2), ("random", 0.0), ("random", 1.0), ("censoring", 4), ("censoring", 2.5)):
        with pytest.raises(ValueError):
            run_stability(td, CFG, ref, scheme, level, 1, rg)
    with pytest.raises(ValueError, match="n_repeats"):
        run_stability(td, CFG, ref, "random", 0.2, 0, rg)
    with pytest.raises(ValueError, match="pass the td"):
        run_stability(td.subset(np.arange(100)), CFG, ref, "random", 0.2, 1, rg)


def test_informative_loss_cannot_be_driven_by_a_protected_or_missing_attribute(world):
    td, ref = world
    rg = np.random.default_rng(0)
    with pytest.raises(FairnessError):
        run_stability(td, cfg_with("stability", informative={"attribute": "sex", "strength": 1.0}), ref, "informative", 0.2, 1, rg)
    with pytest.raises(ConfigError):
        run_stability(td, cfg_with("stability", informative={"attribute": "no_such_column", "strength": 1.0}), ref, "informative", 0.2, 1, rg)


def test_stability_tables_cover_every_configured_setting(world):
    td, ref = world
    cfg = cfg_with("stability", n_repeats=2)
    curves, surv = stability_tables(td, cfg, ref)
    n_loss, n_cens = len(D0["stability"]["random_loss"]), len(D0["stability"]["censor_points"])
    assert len(curves) == 2 * n_loss + n_cens and set(curves["scheme"]) == {"random", "informative", "censoring"}
    assert len(surv) == len(curves) * ref.fit_result.k
    assert (curves["n_repeats"] == 2).all() and (curves["ari_min"] <= curves["ari_mean"]).all()
    assert (curves.loc[curves["scheme"] == "censoring", "level_kind"] == "visits kept").all()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
