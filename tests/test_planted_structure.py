"""Planted-structure tests: can the whole analysis find structure it was given, and does it stay quiet when there is none?

Why this file exists: unit tests show each part does what it says. They do not show that the parts, chained, find
real structure, or that the pipeline would NOT invent structure in noise. On SYNTHETIC data the truth is known, so
both can be checked: (1) recovery, with the planted pathways found at the planted k; (2) a null, where there is
nothing to find and the measures must say so; (3) known hard cases, where the right behaviour is to fail in the
way the documentation says it fails.

What passing here means, and does not mean: the code can find clear, planted structure. It says nothing about
real trainees, and the thresholds below are deliberately loose guards (the synthetic pathways are easy by design),
not performance claims. Recovery on real data will be harder and unscored: there is no truth to compare with.

All data here is SYNTHETIC, made only to test the pipeline.

Run:  python -m pytest tests/test_planted_structure.py -q        (or:  python tests/test_planted_structure.py)   (a few seconds)
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.baseline import baseline_partition, compare_to_clustering                         # noqa: E402
from src.clustering import cluster_full                                                    # noqa: E402
from src.config import Config, load_config, make_rng                                       # noqa: E402
from src.distances import build_distance, plan_reduction, substitution_cost_matrix         # noqa: E402
from src.evaluation import evaluate_partition                                              # noqa: E402
from src.preprocessing import apply_eligibility                                            # noqa: E402
from src.profiling import pathway_profiles                                                 # noqa: E402
from src.stability import adjusted_rand_index, match_clusters, run_stability               # noqa: E402
from src.synthetic_data import generate_synthetic                                          # noqa: E402
from src.trajectories import build_trajectories                                            # noqa: E402

CFG = load_config()
D0 = CFG.to_dict()
PLANTED = D0["synthetic"]["planted"]
P = len(PLANTED)
NAMES = [s["name"] for s in D0["states"]]


def with_synthetic(**kw) -> Config:
    return Config({**D0, "synthetic": {**D0["synthetic"], **kw}}, CFG.root)


def planted_by_individual(td, truth) -> np.ndarray:
    """Planted pathway of each individual in td order (ids are 'S<number>' and sorted as strings)."""
    return truth.labels[np.array([int(x[1:]) for x in td.ids])]


def fit(cfg: Config, n: int, k: int, seed_offset: int, tag: str):
    df, truth = generate_synthetic(cfg, n=n, seed_offset=seed_offset)
    td = apply_eligibility(build_trajectories(df, CFG), CFG)                               # the one trainee sample, as in the pipeline
    plan = plan_reduction(td, CFG, make_rng(CFG, f"{tag}-plan"))
    sub = substitution_cost_matrix(td, CFG)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        D = build_distance(plan.col_fit, CFG, sub)
        ref = cluster_full(plan, D, CFG, k, make_rng(CFG, f"{tag}-ref"), sub)
    return td, truth, plan, D, ref


@pytest.fixture(scope="module")
def easy():
    return fit(CFG, 1500, P, 41, "easy")


# ---------------------------------------------------------------------------------------------
# The generator itself
# ---------------------------------------------------------------------------------------------
def test_planted_sizes_are_exact_and_follow_the_configured_prevalence(easy):
    td, truth, *_ = easy
    sizes = np.bincount(truth.labels, minlength=P)
    assert sizes.sum() == 1500 and all(abs(sizes[i] - round(p["prevalence"] * 1500)) <= 1 for i, p in enumerate(PLANTED))


def test_synthetic_data_is_labelled_synthetic_everywhere(easy):
    td, *_ = easy
    assert td.is_synthetic is True


# ---------------------------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------------------------
def test_planted_pathways_are_recovered_at_the_planted_k(easy):
    td, truth, plan, D, ref = easy
    ari = adjusted_rand_index(planted_by_individual(td, truth), ref.full_labels)
    assert ari > 0.8, f"planted structure not recovered (ARI {ari:.2f})"


def test_every_planted_pathway_has_a_medoid_close_to_its_prototype(easy):
    """Matching uses plain Hamming: each planted prototype must have some found medoid within one visit in four."""
    td, truth, plan, D, ref = easy
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        mapping, dist = match_clusters(truth.prototypes, ref.medoid_states, CFG)
    # mapping[i] is the planted pathway nearest to found medoid i
    assert set(mapping[dist <= 0.25]) == set(range(P)), f"planted pathways with no close medoid: {sorted(set(range(P)) - set(mapping[dist <= 0.25]))}"


def test_found_pathways_have_the_planted_sizes_roughly(easy):
    td, truth, plan, D, ref = easy
    found = np.sort(np.bincount(ref.full_labels, minlength=P)) / td.n
    planted = np.sort(np.bincount(truth.labels, minlength=P)) / td.n
    assert np.abs(found - planted).max() < 0.05


def test_collapsing_does_not_change_the_answer():
    """Same data, collapsed versus one unit per person (subsample mode with everyone fitting): same grouping, up to label names."""
    df, truth = generate_synthetic(CFG, n=400, seed_offset=43)
    td = build_trajectories(df, CFG)
    sub = substitution_cost_matrix(td, CFG)
    out = []
    for mode in ("collapse", "subsample"):
        cfg = Config({**D0, "distance": {**D0["distance"], "reduction": mode, "max_n": 3000}}, CFG.root)
        plan = plan_reduction(td, cfg, make_rng(CFG, "col-plan"))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            D = build_distance(plan.col_fit, cfg, sub)
            out.append(cluster_full(plan, D, cfg, P, make_rng(CFG, "col-ref"), sub).full_labels)
    assert adjusted_rand_index(out[0], out[1]) > 0.95


# ---------------------------------------------------------------------------------------------
# Honesty checks: noise, nothing-to-find, known hard case
# ---------------------------------------------------------------------------------------------
def test_more_noise_means_worse_recovery_and_a_lower_silhouette():
    low = fit(with_synthetic(noise=0.05), 800, P, 44, "lo")
    high = fit(with_synthetic(noise=0.55), 800, P, 44, "hi")
    ari = [adjusted_rand_index(planted_by_individual(td, tr), ref.full_labels) for td, tr, _, _, ref in (low, high)]
    sil = [evaluate_partition(D, ref.fit_result.labels, CFG, sample_weight=plan.col_fit.freq)["silhouette"]["overall"] for _, _, plan, D, ref in (low, high)]
    assert ari[0] > ari[1] + 0.2 and sil[0] > sil[1] + 0.1


def test_structureless_data_scores_much_lower_than_structured_data(easy):
    """Every cell an independent uniform draw: nothing to find. The clustering still returns k groups (an algorithm
    always does), so what must differ is the evidence: silhouette far below the planted case, and low stability."""
    td0, truth0, plan0, D0m, ref0 = easy
    rng = np.random.default_rng(7)
    rows = rng.integers(0, len(NAMES), size=(600, 4))
    codes = [str(s["raw_codes"][0]) for s in D0["states"]]
    df = pd.DataFrame([{"person_id": f"P{i:04d}", "t": t, "raw_status": codes[v]} for i, r in enumerate(rows) for t, v in enumerate(r)])
    td = build_trajectories(df, CFG)
    plan = plan_reduction(td, CFG, make_rng(CFG, "null-plan"))
    sub = substitution_cost_matrix(td, CFG)
    D = build_distance(plan.col_fit, CFG, sub)
    ref = cluster_full(plan, D, CFG, P, make_rng(CFG, "null-ref"), sub)
    s_null = evaluate_partition(D, ref.fit_result.labels, CFG, sample_weight=plan.col_fit.freq)["silhouette"]["overall"]
    s_real = evaluate_partition(D0m, ref0.fit_result.labels, CFG, sample_weight=plan0.col_fit.freq)["silhouette"]["overall"]
    assert s_null < 0.3 and s_real > s_null + 0.3
    stab = run_stability(td, CFG, ref, "random", 0.3, 3, make_rng(CFG, "null-st")).ari.mean()
    stab_real = run_stability(td0, CFG, ref0, "random", 0.3, 3, make_rng(CFG, "easy-st")).ari.mean()
    assert stab < stab_real - 0.2


def test_two_pathways_identical_on_the_first_visits_cannot_be_told_apart_by_censoring(easy):
    """Planted pathways 'stable_wage' and 'wage_to_exit' both start W,W. Truncated to two visits they are the same
    sequence, so at least one reference pathway must fail to survive censoring to 2 visits: this is the documented
    behaviour, not a bug. Random loss of 10% must not do that."""
    td, truth, plan, D, ref = easy
    cen = run_stability(td, CFG, ref, "censoring", 2, 2, make_rng(CFG, "cen2"))
    rnd = run_stability(td, CFG, ref, "random", 0.1, 2, make_rng(CFG, "rnd10"))
    assert cen.survival["survival_rate"].min() == 0.0
    assert rnd.survival["survival_rate"].min() > 0.0


# ---------------------------------------------------------------------------------------------
# The baseline and profiling on planted data
# ---------------------------------------------------------------------------------------------
def test_employed_vs_not_baseline_agrees_with_pathways_less_than_pathways_agree_with_the_truth(easy):
    """The baseline has only two groups, so it cannot reproduce six planted pathways. The comparison must show that."""
    td, truth, plan, D, ref = easy
    base = baseline_partition(td, CFG)
    planted = planted_by_individual(td, truth)
    ok = base.eligible_mask
    ari_base_vs_planted = adjusted_rand_index(planted[ok], base.labels[ok])
    ari_path_vs_planted = adjusted_rand_index(planted, ref.full_labels)
    assert ari_base_vs_planted < 0.5 < ari_path_vs_planted
    cmp = compare_to_clustering(base, ref.full_labels, td, CFG)
    assert cmp["n_pathways_spanning_classes"] >= 1                                         # at least one pathway holds both employed and not-employed people


def test_profiling_finds_a_planted_age_difference_and_no_sex_difference(easy):
    td, truth, plan, D, ref = easy
    cfg = Config({**D0, "profiling": {**D0["profiling"], "permitted_vars": ["age", "sex"]}}, CFG.root)
    prof = pathway_profiles(td, ref.full_labels, cfg)
    planted = planted_by_individual(td, truth)
    # planted age mean = 22 + 2 * planted index; map each found pathway to its majority planted pathway
    main = [int(np.bincount(planted[ref.full_labels == j], minlength=P).argmax()) for j in range(len(prof))]
    found_age = prof["age__mean"].to_numpy()
    expect_age = np.array([22.0 + 2.0 * m for m in main])
    assert np.abs(found_age - expect_age).max() < 1.5
    assert found_age.max() - found_age.min() > 4                                           # a real difference is visible
    # Sex was generated independently of pathway. Shares still wobble with pathway size, so the guard scales with it:
    # every pathway's share must lie within 4 binomial standard errors of the overall share.
    n = prof["n_individuals"].to_numpy(dtype=float)
    sex_cols = [c for c in prof.columns if c.startswith("sex=")]
    assert sex_cols
    for c in sex_cols:
        overall = float((prof[c] * n).sum() / n.sum())
        se = np.sqrt(overall * (1 - overall) / n)
        assert (np.abs(prof[c].to_numpy() - overall) < 4 * se).all(), f"{c} differs by pathway beyond sampling noise"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
