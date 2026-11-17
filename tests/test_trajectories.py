"""Tests for src/trajectories.py: raw codes to states, long panel to trajectories, collapsing, transitions.

Why these tests exist: every later number rests on the person-by-time state array. A wrong mapping of an unknown
code, a transition counted across a gap, or a collapse that merges different people would not crash anything; it
would quietly change the pathways. So each test below states a rule from the module docstring and checks it on a
tiny hand-built panel whose right answer can be worked out on paper.

All panels here are hand-written fixtures, or SYNTHETIC data from the generator used only to test the code. No
test uses real data and none reports a result.

Run:  python -m pytest tests/test_trajectories.py -q        (or:  python tests/test_trajectories.py)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import LOST, MISSING, SYNTHETIC_LOST_CODE                              # noqa: E402
from src.config import Config, ConfigError, FairnessError, load_config          # noqa: E402
from src.trajectories import (CollapseRefused, build_trajectories, collapse_trajectories, complete_case_mask,   # noqa: E402
                              expand_labels, identity_collapse, map_raw_to_state, sequence_strings,
                              transition_matrix, trajectory_summary)

_BASE_CFG = load_config()
# This module tests the defined-mapping state with a test-only code. It does not claim that
# the PLFS release documents this sentinel; the workspace config remains lost_codes_status=unresolved.
D = _BASE_CFG.to_dict()
D["lost_codes"] = [SYNTHETIC_LOST_CODE]
D["lost_codes_status"] = "documented"
CFG = Config(D, _BASE_CFG.root)
D = CFG.to_dict()
NAMES = [s["name"] for s in D["states"]]
K, T = len(NAMES), int(D["time"]["n_points"])
CODE = {n: str((s.get("raw_codes") or s.get("synthetic_codes"))[0]) for n, s in zip(NAMES, D["states"])}
UNK, LOSTC = str(D["unknown_codes"][0]), SYNTHETIC_LOST_CODE
W, S, U, X, O, E = (CODE[n] for n in ("wage_employment", "self_employment", "unpaid_family_work", "unemployed_seeking",
                                       "out_of_labour_force", "education_training"))


def panel(rows: dict[str, list], **extra: list) -> pd.DataFrame:
    """Long panel from {person: [raw code or None per time point, or 'skip' for no record]}; `extra` = per-person columns."""
    recs = []
    for p, seq in rows.items():
        for t, c in enumerate(seq):
            if c == "skip":
                continue
            r = {"person_id": p, "t": t, "raw_status": c}
            for k, v in extra.items():
                r[k] = v[list(rows).index(p)]
            recs.append(r)
    df = pd.DataFrame(recs)
    if any(str(x).startswith("SYNTHETIC:") for x in df.get("raw_status", pd.Series(dtype=str)).dropna()):
        df.attrs["is_synthetic"] = True
    return df


def with_distance(**kw):
    from src.config import Config
    return Config({**D, "distance": {**D["distance"], **kw}}, CFG.root)


# ---------------------------------------------------------------------------------------------
# map_raw_to_state
# ---------------------------------------------------------------------------------------------
def test_each_listed_code_maps_to_its_own_state_index():
    listed = [(i, str(c)) for i, state in enumerate(D["states"]) for c in state["raw_codes"]]
    out = map_raw_to_state(pd.Series([code for _, code in listed]), pd.Series([None] * len(listed), dtype="object"), CFG)
    assert out.tolist() == [i for i, _ in listed] and out.dtype == np.int8


def test_documented_cws_out_of_labour_force_range_includes_code_98_and_96():
    # PLFS 2023-24 Instruction Manual Vol. I §3.6.14 classifies all CWS codes 91–98 as out of LF.
    out = map_raw_to_state(pd.Series(["91", "96", "98", "99"]), pd.Series([None] * 4), CFG)
    assert out.tolist() == [NAMES.index("out_of_labour_force")] * 3 + [MISSING]


def test_91_to_98_individual_codes_are_not_given_invented_real_meanings():
    out = map_raw_to_state(pd.Series([str(i) for i in range(91, 99)]), pd.Series([None] * 8), CFG)
    assert out.tolist() == [NAMES.index("out_of_labour_force")] * 8
    assert "99" in D["unknown_codes"]


def test_documented_temporarily_absent_codes_follow_their_employment_group():
    # Instruction Manual Vol. I §§3.6.2 and 3.6.8: 61/62 are absent from self-employment work;
    # 71/72 are absent from regular salaried/wage work.
    out = map_raw_to_state(pd.Series(["61", "62", "71", "72"]), pd.Series([None] * 4), CFG)
    assert out.tolist() == [NAMES.index("self_employment")] * 2 + [NAMES.index("wage_employment")] * 2


def test_synthetic_only_education_state_does_not_map_real_cws_91():
    real = map_raw_to_state(pd.Series(["91"]), pd.Series([None]), CFG)
    synthetic = map_raw_to_state(pd.Series([CODE["education_training"]]), pd.Series([None]), CFG, synthetic=True)
    assert real.tolist() == [NAMES.index("out_of_labour_force")]
    assert synthetic.tolist() == [NAMES.index("education_training")]


def test_unknown_and_blank_are_missing_and_lost_code_is_lost():
    raw = pd.Series([UNK, None, np.nan, W, None])
    nr = pd.Series([None, None, None, None, LOSTC], dtype="object")
    assert map_raw_to_state(raw, nr, CFG).tolist() == [MISSING, MISSING, MISSING, 0, LOST]


def test_defined_lost_mapping_is_applied_and_recorded():
    df = panel({"a": [W, None, None, None]})
    df["nonresponse_code"] = [None, LOSTC, None, None]
    td = build_trajectories(df, CFG)
    assert td.states[0].tolist() == [0, LOST, MISSING, MISSING]
    assert td.meta["records_by_kind"]["lost"] == 1
    assert td.meta["lost_codes_status"] == "documented"


def test_documented_unavailable_lost_mapping_keeps_observation_missing_and_records_status():
    d = _BASE_CFG.to_dict()
    d["lost_codes"] = []
    d["lost_codes_status"] = "documented_unavailable"
    cfg = Config(d, _BASE_CFG.root)
    df = panel({"a": [W, None, "skip", "skip"]})
    td = build_trajectories(df, cfg)
    assert td.states[0].tolist() == [0, MISSING, MISSING, MISSING]
    assert td.meta["records_by_kind"]["lost"] == 0
    assert td.meta["lost_codes_status"] == "documented_unavailable"


def test_reserved_synthetic_lost_sentinel_never_enters_real_mapping():
    raw = pd.Series([None], dtype="object")
    nonresponse = pd.Series([SYNTHETIC_LOST_CODE], dtype="object")
    assert map_raw_to_state(raw, nonresponse, _BASE_CFG).tolist() == [MISSING]
    assert map_raw_to_state(raw, nonresponse, _BASE_CFG, synthetic=True).tolist() == [LOST]


def test_unlisted_code_raises_instead_of_guessing():
    with pytest.raises(ConfigError, match="in none of"):
        map_raw_to_state(pd.Series([W, "ZZ99"]), pd.Series([None, None], dtype="object"), CFG)


def test_record_with_valid_state_and_lost_code_is_contradictory():
    with pytest.raises(ValueError, match="both a valid status and a lost"):
        map_raw_to_state(pd.Series([W]), pd.Series([LOSTC]), CFG)


def test_length_mismatch_raises():
    with pytest.raises(ValueError, match="same length"):
        map_raw_to_state(pd.Series([W, S]), pd.Series([None], dtype="object"), CFG)


def test_integer_valued_floats_read_as_integers():
    """A numeric column holding NA is stored as float; 11.0 must equal '11'. Checked with a config whose codes are plain numbers."""
    from src.config import Config
    d = {**D, "states": [{**s, "raw_codes": [str(11 + i)]} for i, s in enumerate(D["states"])],
         "unknown_codes": ["99"], "lost_codes": ["98"], "lost_codes_status": "documented"}
    cfg = Config(d, CFG.root)
    out = map_raw_to_state(pd.Series([11.0, 12.0, 99.0, np.nan]), pd.Series([np.nan] * 4), cfg)
    assert out.tolist() == [0, 1, MISSING, MISSING]


# ---------------------------------------------------------------------------------------------
# build_trajectories
# ---------------------------------------------------------------------------------------------
def test_hand_built_panel_gives_the_expected_state_array():
    df = panel({"b": [W, W, O, O], "a": [E, X, W, UNK], "c": [S, None, "skip", W]})
    td = build_trajectories(df, CFG)
    assert list(td.ids) == ["a", "b", "c"]                                       # sorted string order
    assert td.states.tolist() == [[5, 3, 0, MISSING], [0, 0, 4, 4], [1, MISSING, MISSING, 0]]
    assert td.states.dtype == np.int8 and td.n == 3 and td.T == T


def test_a_pair_with_no_record_is_missing_not_a_state():
    td = build_trajectories(panel({"a": [W, "skip", "skip", W]}), CFG)
    assert td.states[0].tolist() == [0, MISSING, MISSING, 0]
    assert td.meta["n_cells_without_record"] == 2


def test_eligible_subset_reconciles_rows_and_all_cells():
    # a is eligible; b is excluded by selection. a has one observed, one explicit missing,
    # one no-record cell and one lost cell. Counts must describe a, not the source panel.
    df = panel({"a": [W, None, "skip", None], "b": [S, S, S, S]})
    df.loc[(df.person_id == "a") & (df.t == 3), "nonresponse_code"] = LOSTC
    source = build_trajectories(df, CFG)
    eligible = source.subset(np.array([True, False]))
    assert source.meta["n_persons"] == 2 and eligible.meta["n_persons"] == 1
    assert eligible.meta["n_records"] == 3
    assert eligible.meta["n_cells"] == 4
    assert eligible.meta["n_cells_without_record"] == 1
    assert eligible.meta["records_by_kind"] == {"state": 1, "missing_or_unknown": 1, "lost": 1}
    assert sum(eligible.meta["records_by_kind"].values()) == eligible.meta["n_records"]
    assert eligible.meta["n_cells_without_record"] + sum(eligible.meta["records_by_kind"].values()) == eligible.meta["n_cells"]


def test_synthetic_eligible_data_summary_reconciles_rows_and_cells():
    from run_pipeline import Pipeline

    df = panel({"a": [W, None, "skip", None], "b": [S, S, S, S]})
    df.loc[(df.person_id == "a") & (df.t == 3), "nonresponse_code"] = LOSTC
    df.attrs["is_synthetic"] = True
    source = build_trajectories(df, CFG)
    eligible = source.subset(np.array([True, False]))
    pipe = Pipeline(CFG, synthetic=True, quick=True, log=lambda _: None)
    pipe._cache["td"] = eligible
    pipe._cache["n_persons_panel"] = source.n
    summary = pipe.data_summary()
    assert summary["n_persons_in_panel"] == 2
    assert summary["n_trainees_analysed"] == 1
    assert summary["n_eligible_records"] == sum(summary["records_by_kind"].values()) == 3
    assert summary["n_eligible_cells"] == 4
    assert summary["n_eligible_cells_without_record"] == 1
    assert sum(summary["cells_by_kind"].values()) == summary["n_eligible_cells"]
    assert summary["cells_by_kind"] == {"observed": 1, "missing": 2, "lost": 1}


def test_lost_follow_up_is_kept_apart_from_missing():
    df = panel({"a": [W, W, None, None]})
    df["nonresponse_code"] = [None, None, LOSTC, LOSTC]
    td = build_trajectories(df, CFG)
    assert td.states[0].tolist() == [0, 0, LOST, LOST]
    assert td.meta["records_by_kind"]["lost"] == 2


def test_rejects_bad_panels():
    ok = panel({"a": [W, W, W, W]})
    with pytest.raises(ValueError, match="no rows"):
        build_trajectories(ok.iloc[0:0], CFG)
    with pytest.raises(ValueError, match="missing column"):
        build_trajectories(ok.drop(columns="raw_status"), CFG)
    with pytest.raises(ValueError, match="outside 0"):
        build_trajectories(ok.assign(t=ok["t"] + 1), CFG)                          # t = 4 is out of the window; never dropped silently
    with pytest.raises(ValueError, match="whole numbers"):
        build_trajectories(ok.assign(t=ok["t"] + 0.5), CFG)
    with pytest.raises(ValueError, match="duplicated"):
        build_trajectories(pd.concat([ok, ok.iloc[[0]]]), CFG)
    with pytest.raises(ValueError, match="person_id"):
        build_trajectories(ok.assign(person_id=[None, "a", "a", "a"]), CFG)


def test_attributes_take_first_nonmissing_value_in_time_order():
    df = panel({"a": [W, W, W, W]})
    df["sex"] = [None, "F", "M", "M"]
    td = build_trajectories(df, CFG)
    assert td.attrs.loc[0, "sex"] == "F"
    assert td.attrs.attrs["n_conflicting"]["sex"] == 1


def test_no_weights_without_verification():
    """Hand-made panel is not synthetic and the config weight column is unverified, so weights must be None, never guessed."""
    td = build_trajectories(panel({"a": [W, W, W, W]}), CFG)
    assert td.weights is None and td.is_synthetic is False


def test_synthetic_flag_comes_from_the_panel():
    df = panel({"a": [W, W, W, W]})
    df.attrs["is_synthetic"] = True
    assert build_trajectories(df, CFG).is_synthetic is True


def test_generator_data_round_trips_to_the_planted_row_codes():
    """Independent check on SYNTHETIC data: every non-missing cell must equal the config index of its own raw code."""
    from src.synthetic_data import generate_synthetic
    df, _ = generate_synthetic(CFG, n=300, seed_offset=3)
    td = build_trajectories(df, CFG)
    code_to_state = {c: i for i, c in enumerate(CODE.values())}
    pos = {p: i for i, p in enumerate(sorted(df["person_id"].astype(str).unique()))}
    ok = df[df["raw_status"].astype(str).isin(code_to_state)]
    expect = ok["raw_status"].astype(str).map(code_to_state).to_numpy()
    got = td.states[ok["person_id"].astype(str).map(pos).to_numpy(), ok["t"].to_numpy().astype(int)]
    assert td.is_synthetic and np.array_equal(expect, got)


# ---------------------------------------------------------------------------------------------
# Summaries, transitions, strings, masks
# ---------------------------------------------------------------------------------------------
def _td():
    return build_trajectories(panel({"a": [W, W, O, O], "b": [W, UNK, W, W], "c": [E, X, W, UNK], "d": [W, W, W, W]}), CFG)


def test_transitions_count_only_adjacent_observed_pairs():
    """b = W ? W W: the W->W across the gap is NOT a one-step move; only the last W->W counts."""
    td = build_trajectories(panel({"b": [W, UNK, W, W]}), CFG)
    probs, counts = transition_matrix(td)
    assert counts.sum() == 1 and counts[0, 0] == 1 and probs[0, 0] == 1.0


def test_transition_matrix_by_hand():
    td = _td()
    probs, counts = transition_matrix(td)
    # a: W>W, W>O, O>O ; b: W?, ?W, W>W ; c: E>X, X>W, W? ; d: W>W x3     (state ids: W0 O4 E5 X3)
    assert counts[0, 0] == 1 + 1 + 3 and counts[0, 4] == 1 and counts[4, 4] == 1 and counts[5, 3] == 1 and counts[3, 0] == 1
    assert counts.sum() == 3 + 1 + 2 + 3
    assert np.allclose(probs[0, 0] + probs[0, 4], 1.0)
    assert np.isnan(probs[1]).all()                                               # a state never left: undefined, not zero


def test_weighted_transitions_need_weights():
    with pytest.raises(ValueError, match="verified survey weights"):
        transition_matrix(_td(), weighted=True)


def test_summary_shares_are_of_the_observed():
    s = trajectory_summary(_td())
    assert list(s["n_observed"]) == [4, 3, 4, 3] and list(s["n_missing"]) == [0, 1, 0, 1]
    assert s.loc[1, "share_wage_employment"] == pytest.approx(2 / 3)               # visit_2: a, d are W of 3 observed (b missing)
    assert s.loc[0, "share_observed"] == 1.0


def test_sequence_strings_use_letters_question_mark_and_hash():
    df = panel({"a": [W, UNK, E, W]})
    df2 = panel({"b": [W, W, None, None]})
    df2["nonresponse_code"] = [None, None, LOSTC, LOSTC]
    both = pd.concat([df, df2])
    both.attrs["is_synthetic"] = True
    td = build_trajectories(both, CFG)
    assert sequence_strings(td) == ["A?FA", "AA##"]
    assert sequence_strings(td, np.array([1])) == ["AA##"]


def test_complete_case_mask_counts_observed_points_only():
    td = _td()
    assert complete_case_mask(td, 4).tolist() == [True, False, False, True]
    assert complete_case_mask(td, 3).tolist() == [True, True, True, True]
    assert complete_case_mask(td, 0).all()
    for bad in (-1, T + 1, 1.5):
        with pytest.raises(ValueError):
            complete_case_mask(td, bad)


# ---------------------------------------------------------------------------------------------
# Collapsing
# ---------------------------------------------------------------------------------------------
def test_collapse_merges_identical_rows_and_keeps_counts():
    td = build_trajectories(panel({"a": [W, W, O, O], "b": [W, W, O, O], "c": [E, X, W, W], "d": [W, W, O, O], "e": [E, X, W, W]}), CFG)
    col = collapse_trajectories(td, CFG)
    assert col.u == 2 and sorted(col.freq.tolist()) == [2, 3] and col.n == 5
    assert col.freq.sum() == td.n
    assert np.array_equal(col.unique_states[col.inverse], td.states)                # exact: expanding gives back every row


def test_collapse_does_not_merge_missing_with_a_state_or_lost():
    td = build_trajectories(panel({"a": [W, W, W, W], "b": [W, UNK, W, W], "c": [W, W, W, None]}), CFG)
    td.states[2, 3] = LOST
    assert collapse_trajectories(td, CFG).u == 3


def test_collapse_is_deterministic_and_lexicographic():
    td = build_trajectories(panel({"a": [O, O, O, O], "b": [W, W, W, W], "c": [E, E, E, E]}), CFG)
    col = collapse_trajectories(td, CFG)
    assert col.unique_states[:, 0].tolist() == sorted(col.unique_states[:, 0].tolist())


def test_collapse_subset_and_inverse_follow_idx():
    td = build_trajectories(panel({"a": [W, W, W, W], "b": [O, O, O, O], "c": [W, W, W, W]}), CFG)
    col = collapse_trajectories(td, CFG, np.array([2, 0]))
    assert col.u == 1 and col.n == 2 and col.freq.tolist() == [2]
    assert collapse_trajectories(td, CFG, np.array([True, True, False])).n == 2
    with pytest.raises(ValueError, match="empty"):
        collapse_trajectories(td, CFG, np.array([], dtype=int))


def test_categorical_attribute_input_keeps_people_with_different_attributes_apart():
    df = panel({"a": [W, W, W, W], "b": [W, W, W, W], "c": [W, W, W, W]}, sector=["urban", "rural", "urban"])
    td = build_trajectories(df, CFG)
    td.attrs["sector"] = td.attrs["sector"].astype(object)
    assert collapse_trajectories(td, CFG).u == 1                                   # attributes that are not distance inputs never block
    cfg = with_distance(attribute_inputs=["sector"])
    col = collapse_trajectories(td, cfg)
    assert col.u == 2 and col.attr_cols == ["sector"] and col.unique_attrs.shape == (2, 1)


def test_missing_category_is_its_own_explicit_label():
    df = panel({"a": [W, W, W, W], "b": [W, W, W, W]}, sector=["urban", None])
    td = build_trajectories(df, CFG)
    col = collapse_trajectories(td, with_distance(attribute_inputs=["sector"]))
    assert "<missing>" in set(col.unique_attrs[:, 0])


def test_numeric_attribute_input_refuses_to_collapse():
    df = panel({"a": [W, W, W, W], "b": [W, W, W, W]}, age=[30.0, 31.0])
    td = build_trajectories(df, CFG)
    with pytest.raises(CollapseRefused, match="subsample"):
        collapse_trajectories(td, with_distance(attribute_inputs=["age"]))


def test_protected_attribute_input_is_a_fairness_error():
    df = panel({"a": [W, W, W, W]}, sex=["F"])
    td = build_trajectories(df, CFG)
    with pytest.raises(FairnessError):
        collapse_trajectories(td, with_distance(attribute_inputs=["sex"]))


def test_unknown_attribute_input_column_raises():
    td = build_trajectories(panel({"a": [W, W, W, W]}), CFG)
    with pytest.raises(ValueError, match="not in the attributes"):
        collapse_trajectories(td, with_distance(attribute_inputs=["sector"]))


def test_identity_collapse_never_merges_and_keeps_order():
    td = build_trajectories(panel({"a": [W, W, W, W], "b": [W, W, W, W], "c": [O, O, O, O]}), CFG)
    col = identity_collapse(td, np.array([2, 0, 1]))
    assert col.u == 3 and col.freq.tolist() == [1, 1, 1] and col.inverse.tolist() == [0, 1, 2]
    assert col.unique_states[0].tolist() == td.states[2].tolist()
    assert col.attr_cols == [] and col.unique_attrs is None


def test_identity_collapse_carries_attribute_inputs_only_when_cfg_is_given():
    df = panel({"a": [W, W, W, W], "b": [W, W, W, W]}, age=[30.0, 31.0])
    td = build_trajectories(df, CFG)
    cfg = with_distance(attribute_inputs=["age"])
    assert identity_collapse(td).attr_cols == []
    assert identity_collapse(td, cfg=cfg).attr_cols == ["age"]                      # numeric values kept for a Gower-type distance


def test_expand_labels():
    td = build_trajectories(panel({"a": [W, W, W, W], "b": [O, O, O, O], "c": [W, W, W, W]}), CFG)
    col = collapse_trajectories(td, CFG)
    lab = np.array([10, 20])
    assert expand_labels(col, lab).tolist() == [lab[i] for i in col.inverse]
    with pytest.raises(ValueError, match="shape"):
        expand_labels(col, np.array([1, 2, 3]))


def test_collapse_of_generator_data_is_exact():
    from src.synthetic_data import generate_synthetic
    df, _ = generate_synthetic(CFG, n=500, seed_offset=8)
    td = build_trajectories(df, CFG)
    col = collapse_trajectories(td, CFG)
    assert col.u < td.n and col.freq.sum() == td.n
    assert np.array_equal(col.unique_states[col.inverse], td.states)
    assert len({tuple(r) for r in col.unique_states.tolist()}) == col.u              # no two units share a row


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
