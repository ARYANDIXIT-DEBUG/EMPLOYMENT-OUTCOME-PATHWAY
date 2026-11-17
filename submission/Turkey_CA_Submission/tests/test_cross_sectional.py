from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from run_pipeline import GateError, check_data_gate  # noqa: E402
from src.config import load_config  # noqa: E402
from src.cross_sectional import (CrossSectionError, check_cross_sectional_gate, estimate_cws,
                                 derive_employment_indicators, prepare_cross_section)  # noqa: E402


def config():
    return load_config()


def source():
    return pd.DataFrame({
        "qtr": ["Q1", "Q2", "Q3", "Q4", "Q1"], "visit": ["V1"] * 5,
        "sector": ["1", "2", "2", "1", "2"], "state": ["s"] * 5,
        "fsu": ["f1", "f2", "f3", "f4", "f5"], "sg_sb": ["1"] * 5,
        "stratum2": ["1"] * 5, "hh_no": ["1"] * 5, "person_no": ["1"] * 5,
        "age": [15, 59, 14, 30, 25], "b4q12": ["1", "1", "1", "6", "1"],
        "cws": [31, 82, 11, 91, None], "wt": [1000] * 5, "no_qtr": [4] * 5,
        "nss": [1, 1, 1, 1, 1], "nsc": [2, 1, 2, 2, 2],
    })


def test_cross_section_gate_is_separate_from_closed_longitudinal_gate():
    cfg = config()
    check_cross_sectional_gate(cfg)
    with pytest.raises(GateError, match="CHECKPOINT 1 is not recorded as PASSED"):
        check_data_gate(cfg)


def test_cohort_counts_and_weighted_cws_keep_missing_separate():
    cohort, summary = prepare_cross_section(config(), source())
    assert summary["source_rows"] == 5
    assert summary["eligible_rows"] == 3
    assert summary["excluded_by_cohort_rule"] == 2
    assert summary["outcome_missing_rows"] == 1
    assert summary["outcome_unclassified_rows"] == 0
    assert cohort["annual_weight"].tolist() == [1.25, 2.5, 1.25]
    result = estimate_cws(cohort)
    all_rows = result[result.sector == "all"].set_index("cws_group")
    assert all_rows.loc["employed", "n_unweighted"] == 1
    assert all_rows.loc["unemployed", "n_unweighted"] == 1
    assert all_rows.loc["out_of_labour_force", "n_unweighted"] == 0
    assert all_rows.loc["employed", "share_weighted_known_cws"] == pytest.approx(1.25 / 3.75)
    assert all_rows.loc["unemployed", "share_weighted_known_cws"] == pytest.approx(2.5 / 3.75)
    assert all_rows.loc["employed", "n_cws_missing_or_unclassified"] == 1
    indicators = derive_employment_indicators(result).set_index("sector")
    assert indicators.loc["all", "wpr_weighted"] == pytest.approx(1.25 / 5.0)
    assert indicators.loc["all", "ur_weighted"] == pytest.approx(2.5 / 3.75)
    assert indicators.loc["all", "lfpr_weighted"] == pytest.approx(3.75 / 5.0)


def test_unsupported_cws_is_not_silently_mapped_or_dropped():
    df = source()
    df.loc[1, "cws"] = 99
    with pytest.raises(CrossSectionError, match="outside documented broad groups"):
        prepare_cross_section(config(), df)


def test_annual_weight_applies_documented_combined_subsample_and_no_qtr_factors():
    df = source()
    df.loc[0, ["nss", "nsc", "no_qtr", "wt"]] = [2, 2, 4, 1200]
    df.loc[1, ["nss", "nsc", "no_qtr", "wt"]] = [2, 3, 3, 1200]
    cohort, summary = prepare_cross_section(config(), df)
    assert cohort["annual_weight"].tolist()[:2] == [3.0, 2.0]
    assert summary["combined_subsample_divisor_distribution"] == {"100.0": 1, "200.0": 2}


def test_missing_combined_weight_fields_fail_closed():
    df = source()
    df.loc[0, "nss"] = None
    with pytest.raises(CrossSectionError, match="missing/nonpositive NSS"):
        prepare_cross_section(config(), df)


def test_duplicate_official_record_key_is_rejected_without_dropping():
    df = source()
    df.loc[1, ["qtr", "sector", "state", "fsu", "sg_sb", "stratum2", "hh_no", "person_no"]] = \
        df.loc[0, ["qtr", "sector", "state", "fsu", "sg_sb", "stratum2", "hh_no", "person_no"]].to_numpy()
    with pytest.raises(CrossSectionError, match="record key has"):
        prepare_cross_section(config(), df)
