"""Quarter-aware PLFS person linkage tests using small synthetic tables only."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import Config, load_config  # noqa: E402
from src.data_audit import linkage_report  # noqa: E402
from src.data_loader import (SchemaError, classify_link_quality, identify_trainees, link_persons,
                             quarter_aware_link_keys)  # noqa: E402
from src.synthetic_data import generate_synthetic  # noqa: E402


def _cfg() -> Config:
    data = load_config().to_dict()
    data["data"]["files"] = [
        {"id": "perv1", "kind": "person", "role": "primary", "period": "V1"},
        {"id": "perrv", "kind": "person", "role": "primary", "period": "V2-V4"},
    ]
    data["data"]["schema"] = {
        "household_id": ["state", "fsu"], "person_id": "person_no",
        "visit": "visit", "month": None, "quarter": "qtr", "sector": "sector",
        "age": "age", "sex": "sex", "social_group": None, "religion": None,
        "weight": None, "status_col": "status", "nonresponse_col": None,
        "training_cols": [],
    }
    data["trainee"]["rules"] = {}
    data["time"]["n_points"] = 4
    return Config(data, load_config().root)


def _row(visit: str, quarter: str, *, age: int = 30, sex: str = "F", key: str = "A") -> dict:
    return {"state": "01", "fsu": key, "person_no": "1", "visit": visit,
            "qtr": quarter, "age": age, "sex": sex, "sector": "2", "status": "31",
            "stratum": "01", "sub_stratum": "1", "sub_sample": "1", "fod_sub_region": "01001"}


def _link(*rows: dict) -> pd.DataFrame:
    cfg = _cfg()
    present = {r["visit"] for r in rows}
    rows = (*rows, *(_row(f"V{i}", f"Q{i}", key=f"filler-{i}")
                     for i in range(1, 5) if f"V{i}" not in present))
    v1 = pd.DataFrame([r for r in rows if r["visit"] == "V1"])
    rv = pd.DataFrame([r for r in rows if r["visit"] != "V1"])
    return link_persons({"perv1": v1, "perrv": rv}, cfg)


def test_synthetic_trainee_selection_uses_generator_marker_not_real_plfs_rule():
    cfg = load_config()
    panel, _ = generate_synthetic(cfg, n=40)

    selected = identify_trainees(panel, cfg)

    assert selected["person_id"].nunique() == 40
    assert selected.attrs["trainee_variable"] == "trained"
    assert selected.attrs["trainee_codes_yes"] == ["Y"]


def test_same_sample_key_at_same_visit_in_different_quarters_stays_distinct():
    out = _link(_row("V2", "Q2"), _row("V2", "Q3", key="A"))
    at_v2 = out[out["t"] == 1]

    assert len(at_v2) == 2
    assert at_v2["person_id"].nunique() == 2
    assert out.attrs["quarter_aware_linking"] is True


def test_audit_and_loader_share_legacy_and_quarter_collision_counts():
    rows = [_row("V2", "Q2"), _row("V2", "Q3")]
    present = {r["visit"] for r in rows}
    rows += [_row(f"V{i}", f"Q{i}", key=f"filler-{i}")
             for i in range(1, 5) if f"V{i}" not in present]
    tables = {
        "perv1": pd.DataFrame([r for r in rows if r["visit"] == "V1"]),
        "perrv": pd.DataFrame([r for r in rows if r["visit"] != "V1"]),
    }
    cfg = _cfg()

    loaded = link_persons(tables, cfg)
    audited = linkage_report(tables, cfg)

    for field in (
        "legacy_key_visit_collision_groups", "legacy_key_visit_collision_excess_rows",
        "quarter_visit_collision_groups", "quarter_visit_collision_excess_rows",
    ):
        assert loaded.attrs[field] == audited[field]
    assert audited["legacy_key_visit_collision_groups"] == 1
    assert audited["legacy_key_visit_collision_excess_rows"] == 1
    assert audited["quarter_visit_collision_groups"] == 0
    assert audited["quarter_visit_collision_excess_rows"] == 0
    # Compatibility field remains present but null because row identity is not assessed here.
    assert audited["duplicate_key_time_pairs"] is None


def test_audit_pairwise_checks_report_design_sex_age_and_sensitivity_thresholds():
    first = _row("V1", "Q1")
    second = _row("V2", "Q2", age=34, sex="M")
    second["stratum"] = "02"
    rows = [first, second, _row("V3", "Q3", key="filler-3"), _row("V4", "Q4", key="filler-4")]
    tables = {
        "perv1": pd.DataFrame([r for r in rows if r["visit"] == "V1"]),
        "perrv": pd.DataFrame([r for r in rows if r["visit"] != "V1"]),
    }
    report = linkage_report(tables, _cfg())
    pair = next(r for r in report["pairwise_link_checks"]
                if r["cohort_quarter"] == "Q1" and r["visit_pair"] == "V1-V2")

    assert pair["candidate_keys_present_both_visits"] == 1
    assert pair["sex_changes"] == 1
    assert pair["design_mismatch_by_field"]["stratum"] == 1
    assert pair["design_mismatch_any"] == 1
    assert pair["raw_age_changes"] == 1
    assert pair["age_sensitivity_abs_delta_over_years"] == {"0": 1, "1": 1, "2": 1, "5": 0, "10": 0}
    assert "sensitivity-only" in pair["age_tolerance_status"]
    assert report["link_validity"]["keys_with_changing_design_by_field"]["stratum"] == 1
    assert report["link_validity"]["keys_with_any_design_field_change"] == 1
    assert report["link_validity"]["age_sensitivity_span_counts"] == {"0": 1, "1": 1, "2": 1, "5": 0, "10": 0}


def test_design_field_change_is_flagged_and_never_excluded():
    first, second = _row("V1", "Q1"), _row("V2", "Q2")
    second["sub_sample"] = "2"
    out = _link(first, second)
    linked = out[out["person_id"].str.contains("01\\|A\\|1\\|cohort=Q1", regex=True)]
    assert len(linked) == 2
    assert linked["link_quality_flag"].str.contains("design_fields_unassessed").all()
    assert linked["link_quality_flag"].str.contains("design_field_mismatch").all()
    assert out.attrs["n_records_excluded"] == 0


def test_repeated_key_quarter_visit_coordinate_is_retained_and_flagged():
    out = _link(_row("V2", "Q2"), _row("V2", "Q2"))
    collided = out[(out["t"] == 1) & out["person_id"].str.contains("cohort=Q1")]
    assert len(collided) == 2
    assert collided["link_quality_flag"].str.contains("same_key_quarter_visit_collision").all()
    assert out.attrs["n_records_excluded"] == 0


def test_sequential_quarters_link_to_one_v1_cohort_and_keep_visit_order():
    out = _link(_row("V1", "Q1"), _row("V2", "Q2", age=30),
                _row("V3", "Q3", age=31), _row("V4", "Q4", age=31))

    assert out["person_id"].nunique() == 1
    assert out["t"].tolist() == [0, 1, 2, 3]
    assert out["survey_quarter"].tolist() == ["Q1", "Q2", "Q3", "Q4"]
    assert out.attrs["n_linked_persons"] == 1


def test_nonsequential_quarter_does_not_create_a_cross_visit_match():
    out = _link(_row("V1", "Q1"), _row("V2", "Q3"))
    target = out[out["t"].isin([0, 1])]

    assert target["person_id"].nunique() == 2
    assert out.attrs["n_linked_persons"] == 0


@pytest.mark.parametrize("field,value,flag", [
    ("sex", "M", "sex_change_unresolved"),
    ("age", 34, "age_change_tolerance_unconfirmed"),
])
def test_sex_or_age_inconsistency_is_flagged_without_exclusion(field: str, value: str | int, flag: str):
    first, second = _row("V1", "Q1"), _row("V2", "Q2")
    second[field] = value
    out = _link(first, second)
    linked = out[out["person_id"].str.contains("01\\|A\\|1\\|cohort=Q1", regex=True)]
    assert len(linked) == 2
    assert linked["link_quality_flag"].str.contains(flag).all()
    assert out.attrs["n_records_excluded"] == 0


def test_unrecognized_quarter_label_fails_closed():
    out = _link(_row("V1", "FY23"))
    assert len(out) == 4
    assert out["link_quality_flag"].str.contains("incomplete_link_coordinates").any()
    assert out.attrs["n_records_excluded"] == 0


def test_flag_builder_labels_unassessed_evidence_explicitly():
    flag = classify_link_quality(sex_change=True, age_change=True)
    assert flag == (
        "unresolved_identity_semantics;design_fields_unassessed;sex_change_unresolved;"
        "age_change_tolerance_unconfirmed"
    )


def test_incomplete_key_record_is_preserved_with_flag():
    row = _row("V1", "Q1")
    row["state"] = None
    out = _link(row)
    flagged = out[out["link_quality_flag"].str.contains("incomplete_link_coordinates")]
    assert len(out) == 4
    assert len(flagged) == 1
    assert out.attrs["n_records_excluded"] == 0


def test_quarter_helper_strict_mode_still_rejects_invalid_quarter():
    frame = pd.DataFrame({"key": ["A"], "visit": ["V1"], "qtr": ["FY23"]})
    with pytest.raises(SchemaError, match="quarter.*Q1, Q2, Q3 or Q4"):
        quarter_aware_link_keys(frame, key_col="key", visit_col="visit", quarter_col="qtr")
