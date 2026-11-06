"""Tests for src/distances.py: substitution costs, dynamic Hamming, optimal matching, memory plan, extension to medoids.

Why these tests exist: the distance is the definition of "similar pathway". A distance that is not symmetric, that
treats a missing visit as a real state, or that quietly builds a matrix larger than memory allows would not crash
in an obvious way; it would give wrong clusters or kill the run late. Each test fixes a property that must hold,
and the numeric ones are checked against a short, independent, pure-Python reference written in this file (not
imported from the module), on rows small enough to verify on paper.

Hand-written fixtures, plus SYNTHETIC generator data used only to test the code. Nothing here is a result.

Run:  python -m pytest tests/test_distances.py -q        (or:  python tests/test_distances.py)
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import CollapsedTrajectories, LOST                                   # noqa: E402
from src.config import Config, ConfigError, FairnessError, load_config        # noqa: E402
from src.distances import (MemoryCapError, build_distance, distance_to_medoids, dynamic_hamming_matrix,      # noqa: E402
                           effective_max_units, estimate_matrix_mb, hamming_matrix, optimal_matching_matrix,
                           plan_reduction, substitution_cost_matrix)
from src.trajectories import build_trajectories, collapse_trajectories, identity_collapse   # noqa: E402

CFG = load_config()
D = CFG.to_dict()


def cfg_with(**distance) -> Config:
    return Config({**D, "distance": {**D["distance"], **distance}}, CFG.root)


def col_of(rows: list[list[int]], freq: list[int] | None = None) -> CollapsedTrajectories:
    S = np.array(rows, dtype=np.int8)
    f = np.ones(len(S), dtype=np.int64) if freq is None else np.array(freq)
    return CollapsedTrajectories(S, f, np.repeat(np.arange(len(S)), f), [], None)


def ref_hamming(a, b, C, mo=2):
    """Independent reference: mean substitution cost over jointly observed points; too few common points -> max cost."""
    if list(a) == list(b):
        return 0.0
    common = [t for t in range(len(a)) if a[t] >= 0 and b[t] >= 0]
    if len(common) < mo:
        return float(C.max())
    return sum(C[a[t], b[t]] for t in common) / len(common)


def ref_om(a, b, C, indel):
    x, y = [int(s) for s in a if s >= 0], [int(s) for s in b if s >= 0]
    M = [[0.0] * (len(y) + 1) for _ in range(len(x) + 1)]
    for i in range(len(x) + 1):
        for j in range(len(y) + 1):
            M[i][j] = indel * max(i, j) if i == 0 or j == 0 else min(M[i - 1][j] + indel, M[i][j - 1] + indel,
                                                                      M[i - 1][j - 1] + C[x[i - 1], y[j - 1]])
    longest = max(len(x), len(y))
    return 0.0 if longest == 0 else M[-1][-1] / longest


# A fixed small cost matrix over 3 states: 0-1 close, 2 far from both.
C3 = np.array([[0.0, 0.5, 2.0], [0.5, 0.0, 1.5], [2.0, 1.5, 0.0]])


# ---------------------------------------------------------------------------------------------
# Memory arithmetic
# ---------------------------------------------------------------------------------------------
def test_estimate_matrix_mb_formula():
    assert estimate_matrix_mb(1024, cfg_with(peak_factor=2.0)) == pytest.approx(2.0 * 1024 * 1024 * 8 / 2 ** 20)


def test_effective_max_units_is_the_largest_that_fits_the_cap():
    cfg = cfg_with(max_n=10 ** 6, max_matrix_mb=64, peak_factor=2.0)
    m = effective_max_units(cfg)
    assert estimate_matrix_mb(m, cfg) <= 64 < estimate_matrix_mb(m + 1, cfg)
    assert effective_max_units(cfg_with(max_n=50, max_matrix_mb=512)) == 50           # max_n binds when it is smaller


# ---------------------------------------------------------------------------------------------
# Substitution costs
# ---------------------------------------------------------------------------------------------
def _td(rows):
    from src.trajectories import build_trajectories as bt
    codes = [str(s["raw_codes"][0]) for s in D["states"]]
    recs = [{"person_id": f"p{i:03d}", "t": t, "raw_status": codes[v] if v >= 0 else str(D["unknown_codes"][0])}
            for i, r in enumerate(rows) for t, v in enumerate(r)]
    return bt(pd.DataFrame(recs), CFG)


def test_trate_costs_by_hand():
    """Rows 0>1 x3 and 1>0 x1 and 2>2 x1: p(0->1)=1, p(1->0)=1 (1 has one outgoing move, to 0), p(2->2)=1."""
    td = _td([[0, 1, 0, 0], [0, 1, 1, 1]][:1] + [[2, 2, 2, 2]])
    C = substitution_cost_matrix(td, cfg_with(substitution="trate"))
    assert C[0, 1] == pytest.approx(2.0 - (1 / 2 + 1.0))                              # p(0->1)=1/2 (0>1, 0>0), p(1->0)=1
    assert C[0, 2] == 2.0 and C[1, 2] == 2.0                                          # states that never exchange people are at the maximum
    assert np.array_equal(C, C.T) and (np.diag(C) == 0).all() and C.min() >= 0 and C.max() <= 2.0


def test_costs_ignore_steps_across_missing():
    """0 ? 1: the 0->1 jump skips a gap, so it is not a transition and must not make 0 and 1 close."""
    C = substitution_cost_matrix(_td([[0, -1, 1, 1]]), cfg_with(substitution="trate"))
    assert C[0, 1] == 2.0


def test_constant_costs_and_bad_kind():
    td = _td([[0, 1, 2, 3]])
    C = substitution_cost_matrix(td, cfg_with(substitution="constant"))
    K = len(td.state_names)
    assert np.array_equal(C, 1.0 - np.eye(K))
    with pytest.raises(ConfigError):
        substitution_cost_matrix(td, cfg_with(substitution="banana"))


def test_collapsed_estimate_equals_individual_estimate():
    """Weighting unique rows by freq must reproduce the individual-level costs (collapsing changes nothing)."""
    from src.distances import _costs_from_collapsed
    from src.synthetic_data import generate_synthetic
    df, _ = generate_synthetic(CFG, n=400, seed_offset=5)
    td = build_trajectories(df, CFG)
    assert np.allclose(substitution_cost_matrix(td, CFG), _costs_from_collapsed(collapse_trajectories(td, CFG), CFG))


# ---------------------------------------------------------------------------------------------
# Dynamic Hamming and plain Hamming
# ---------------------------------------------------------------------------------------------
ROWS = np.array([[0, 0, 1, 2], [0, 1, 1, 2], [2, 2, 2, 2], [0, -1, 1, -1], [-1, -1, -1, 2], [0, 0, 1, 2]], dtype=np.int8)


def test_dynamic_hamming_matches_reference_pair_by_pair():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        Dm = dynamic_hamming_matrix(ROWS, C3, None, "pairwise_available", 2, 4)
    for i in range(len(ROWS)):
        for j in range(len(ROWS)):
            assert Dm[i, j] == pytest.approx(ref_hamming(ROWS[i], ROWS[j], C3)), (i, j)


def test_matrix_is_symmetric_with_zero_diagonal_and_identical_rows_at_zero():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        Dm = dynamic_hamming_matrix(ROWS, C3, None, "pairwise_available", 2, 3)
    assert np.array_equal(Dm, Dm.T) and (np.diag(Dm) == 0).all()
    assert Dm[0, 5] == 0.0                                                            # rows 0 and 5 are identical


def test_block_size_does_not_change_the_answer():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        a = dynamic_hamming_matrix(ROWS, C3, None, "pairwise_available", 2, 1)
        b = dynamic_hamming_matrix(ROWS, C3, None, "pairwise_available", 2, 100)
    assert np.array_equal(a, b)


def test_too_little_overlap_is_maximally_dissimilar_and_warns():
    with pytest.warns(UserWarning):
        Dm = dynamic_hamming_matrix(ROWS, C3, None, "pairwise_available", 2, 4)
    assert Dm[3, 4] == C3.max()                                                       # row 3 and row 4 share no observed visit


def test_a_missing_visit_is_not_treated_as_a_state():
    """Row [0,-1,1,-1] against [0,0,1,2]: only visits 0 and 2 are compared (cost 0 each), so the distance is 0."""
    a = np.array([[0, -1, 1, -1], [0, 0, 1, 2]], dtype=np.int8)
    assert dynamic_hamming_matrix(a, C3, None, "pairwise_available", 2, 2)[0, 1] == 0.0


def test_lost_follow_up_is_not_a_state_either():
    a = np.array([[0, 1, LOST, LOST], [0, 1, 2, 2]], dtype=np.int8)
    assert dynamic_hamming_matrix(a, C3, None, "pairwise_available", 2, 2)[0, 1] == 0.0


def test_time_weights_change_the_mean():
    a = np.array([[0, 2], [0, 0]], dtype=np.int8)
    eq = dynamic_hamming_matrix(a, C3, None, "pairwise_available", 1, 2)[0, 1]
    w = dynamic_hamming_matrix(a, C3, np.array([1.0, 3.0]), "pairwise_available", 1, 2)[0, 1]
    assert eq == pytest.approx(1.0) and w == pytest.approx(1.5)                       # (0*1 + 2*3)/4 = 1.5


def test_bad_inputs_raise():
    with pytest.raises(ValueError):
        dynamic_hamming_matrix(ROWS, C3[:2, :2], None, "pairwise_available", 2, 3)    # cost matrix too small for the codes
    asym = C3.copy()
    asym[0, 1] = 0.7
    with pytest.raises(ValueError, match="symmetric"):
        dynamic_hamming_matrix(ROWS, asym, None, "pairwise_available", 2, 3)
    with pytest.raises(ValueError):
        dynamic_hamming_matrix(ROWS, C3, None, "no_such_policy", 2, 3)


def test_plain_hamming_is_share_of_differing_jointly_observed_points():
    a = np.array([[0, 1, 2, 2], [0, 2, 2, -1]], dtype=np.int8)
    assert hamming_matrix(a, "pairwise_available", 2, 2)[0, 1] == pytest.approx(1 / 3)


# ---------------------------------------------------------------------------------------------
# Optimal matching
# ---------------------------------------------------------------------------------------------
OMROWS = np.array([[0, 1, 2, 2], [0, 2, 2, 2], [1, -1, 1, -1], [-1, -1, -1, -1], [-1, -1, -1, -1], [2, 1, 0, 0]], dtype=np.int8)


def test_optimal_matching_matches_reference_dynamic_programme():
    Dm = optimal_matching_matrix(OMROWS, C3, 1.0, "pairwise_available", 3)
    for i in range(len(OMROWS)):
        for j in range(len(OMROWS)):
            assert Dm[i, j] == pytest.approx(ref_om(OMROWS[i], OMROWS[j], C3, 1.0)), (i, j)
    assert np.array_equal(Dm, Dm.T) and (np.diag(Dm) == 0).all()


def test_optimal_matching_empty_rows_and_bad_indel():
    Dm = optimal_matching_matrix(OMROWS, C3, 1.0, "pairwise_available", 3)
    assert Dm[3, 4] == 0.0 and Dm[3, 0] == 1.0                                        # empty vs empty 0; empty vs observed = indel
    for bad in (0.0, -1.0, float("nan")):
        with pytest.raises(ValueError, match="indel"):
            optimal_matching_matrix(OMROWS, C3, bad, "pairwise_available", 3)


# ---------------------------------------------------------------------------------------------
# build_distance
# ---------------------------------------------------------------------------------------------
def test_build_distance_uses_trate_costs_estimated_from_the_units():
    from src.distances import _costs_from_collapsed
    col = col_of([[0, 0, 1, 1], [0, 1, 1, 1], [2, 2, 2, 2], [0, 0, 0, 1]])
    Dm = build_distance(col, CFG)
    C = _costs_from_collapsed(col, CFG)
    for i in range(4):
        for j in range(4):
            assert Dm[i, j] == pytest.approx(ref_hamming(col.unique_states[i], col.unique_states[j], C))


def test_passing_sub_cost_overrides_the_estimate():
    col = col_of([[0, 0, 1, 1], [0, 1, 1, 1], [2, 2, 2, 2]])
    K = len(D["states"])
    const = 1.0 - np.eye(K)
    Dm = build_distance(col, CFG, const)
    assert Dm[0, 2] == pytest.approx(1.0) and Dm[0, 1] == pytest.approx(1 / 4)


def test_unknown_distance_name_is_refused_by_config_validation():
    """The refusal lives in config validation (load time). `_spec_for` itself falls back to dynamic Hamming for an
    unrecognised name, so a Config built by hand around load_config would not be stopped there; real runs always load."""
    from src.config import _validate
    bad = {**D, "distance": {**D["distance"], "name": "euclidean"}}
    assert any("distance.name" in e for e in _validate(bad))
    assert not any("distance.name" in e for e in _validate(D))


def test_memory_cap_refuses_before_allocating():
    col = col_of([[i % 6, (i // 6) % 6, (i // 36) % 6, (i // 216) % 6] for i in range(50)])
    with pytest.raises(MemoryCapError, match="reduce the units"):
        build_distance(col, cfg_with(max_n=10))
    with pytest.raises(MemoryCapError):
        build_distance(col, cfg_with(max_matrix_mb=0.001))


def test_protected_attribute_input_is_refused_at_runtime():
    S = np.array([[0, 0, 1, 1], [0, 1, 1, 1]], dtype=np.int8)
    col = CollapsedTrajectories(S, np.ones(2, dtype=np.int64), np.arange(2), ["sex"], np.array([["F"], ["M"]], dtype=object))
    with pytest.raises(FairnessError):
        build_distance(col, CFG)


def test_attribute_inputs_join_as_gower_features():
    S = np.array([[0, 0, 1, 1], [0, 0, 1, 1], [0, 0, 1, 1]], dtype=np.int8)
    attrs = np.array([["urban"], ["rural"], ["urban"]], dtype=object)
    col = CollapsedTrajectories(S, np.ones(3, dtype=np.int64), np.arange(3), ["sector"], attrs)
    Dm = build_distance(col, cfg_with(attribute_inputs=["sector"]))
    # identical states -> state distance 0; one differing categorical attribute out of T + A = 5 features
    assert Dm[0, 2] == 0.0 and Dm[0, 1] == pytest.approx(1 / 5) and np.array_equal(Dm, Dm.T)


def test_collapsing_does_not_change_distances_between_people():
    """Distance between two individuals read through the collapsed matrix equals the one from the uncollapsed rows."""
    from src.synthetic_data import generate_synthetic
    df, _ = generate_synthetic(CFG, n=300, seed_offset=11)
    td = build_trajectories(df, CFG)
    col = collapse_trajectories(td, CFG)
    C = substitution_cost_matrix(td, CFG)
    Dc = build_distance(col, CFG, C)
    ident = identity_collapse(td, np.arange(60))
    Di = build_distance(ident, CFG, C)
    inv = col.inverse[:60]
    assert np.allclose(Di, Dc[np.ix_(inv, inv)])


# ---------------------------------------------------------------------------------------------
# distance_to_medoids
# ---------------------------------------------------------------------------------------------
def test_distance_to_medoids_equals_the_matching_columns_of_the_matrix():
    col = col_of([[0, 0, 1, 1], [0, 1, 1, 1], [2, 2, 2, 2], [0, 0, 0, 1], [2, 2, 1, 1]])
    C = 1.0 - np.eye(len(D["states"]))
    Dm = build_distance(col, CFG, C)
    med = [1, 2]
    Dx = distance_to_medoids(col, col.unique_states[med], CFG, sub_cost=C)
    assert np.allclose(Dx, Dm[:, med])
    assert np.allclose(distance_to_medoids(col, col.unique_states[med], CFG, idx=np.array([3, 0]), sub_cost=C), Dm[[3, 0]][:, med])
    mask = np.array([True, False, False, True, False])
    assert distance_to_medoids(col, col.unique_states[med], CFG, idx=mask, sub_cost=C).shape == (2, 2)


def test_distance_to_medoids_bad_inputs():
    col = col_of([[0, 0, 1, 1], [0, 1, 1, 1]])
    with pytest.raises(ValueError, match="time points"):
        distance_to_medoids(col, np.array([[0, 0, 1]], dtype=np.int8), CFG)
    with pytest.raises(IndexError):
        distance_to_medoids(col, col.unique_states[:1], CFG, idx=np.array([5]))


# ---------------------------------------------------------------------------------------------
# plan_reduction
# ---------------------------------------------------------------------------------------------
def _td_random(n, seed=0):
    rng = np.random.default_rng(seed)
    rows = rng.integers(0, 6, size=(n, 4)).tolist()
    return _td(rows)


def test_collapse_mode_fits_or_raises():
    td = _td([[0, 0, 1, 1]] * 30 + [[2, 2, 2, 2]] * 20)
    plan = plan_reduction(td, cfg_with(reduction="collapse"), np.random.default_rng(0))
    assert plan.mode_used == "collapse" and plan.col_fit.u == 2 and plan.col_all.n == td.n
    big = _td_random(200)
    with pytest.raises(MemoryCapError):
        plan_reduction(big, cfg_with(reduction="collapse", max_n=20), np.random.default_rng(0))


def test_subsample_mode_draws_at_most_the_limit_and_is_reproducible():
    td = _td_random(200)
    cfg = cfg_with(reduction="subsample", max_n=40)
    p1 = plan_reduction(td, cfg, np.random.default_rng(7))
    p2 = plan_reduction(td, cfg, np.random.default_rng(7))
    assert p1.mode_used == "subsample" and p1.col_fit.u == 40 and p1.col_all.n == td.n
    assert np.array_equal(p1.col_fit.unique_states, p2.col_fit.unique_states)


def test_subsample_takes_everyone_when_n_fits():
    td = _td_random(30)
    plan = plan_reduction(td, cfg_with(reduction="subsample", max_n=100), np.random.default_rng(0))
    assert plan.col_fit.u == 30


def test_collapse_then_subsample_collapses_when_it_fits_and_samples_when_not():
    td = _td([[0, 0, 1, 1]] * 30 + [[2, 2, 2, 2]] * 20)
    p = plan_reduction(td, cfg_with(reduction="collapse_then_subsample", max_n=10), np.random.default_rng(0))
    assert p.mode_used == "collapse"
    big = _td_random(400)
    cfg = cfg_with(reduction="collapse_then_subsample", max_n=25)
    q = plan_reduction(big, cfg, np.random.default_rng(3))
    assert q.mode_used != "collapse" and 1 <= q.col_fit.u <= 25
    assert q.col_all.n == big.n and len(q.fit_unit_idx) == q.col_fit.u


def test_plan_reduction_builds_no_matrix_and_fit_matrix_is_buildable():
    td = _td_random(300)
    cfg = cfg_with(reduction="collapse_then_subsample", max_n=60)
    plan = plan_reduction(td, cfg, np.random.default_rng(1))
    Dm = build_distance(plan.col_fit, cfg)
    assert Dm.shape == (plan.col_fit.u, plan.col_fit.u)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
