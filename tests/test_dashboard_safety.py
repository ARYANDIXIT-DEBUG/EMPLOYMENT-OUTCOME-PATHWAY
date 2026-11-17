"""Dashboard uses saved results and keeps real views behind temporary-config gate checks."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard.app import (REAL, SYNTHETIC, available_tags, load_cross_sectional_saved,
                           real_gate_status, status_items)  # noqa: E402
from src.config import load_config  # noqa: E402
from src.report_builder import save_result  # noqa: E402


def _temp_cfg(tmp_path: Path, blocker: str | None = None):
    data = load_config().to_dict()
    data["data"].update({
        "plan": "A",
        "verified": True,
        "checkpoint1_status": "PASSED",
        "b4q12_permission_status": "CONFIRMED",  # test-only value; never written to project config
    })
    data["validation"].update({"data_integrity": "passed", "mappings": "validated", "linkage": "validated",
                                "permissions": "user_confirmed", "research_readiness": "passed"})
    data["lost_codes"] = ["TEST_ONLY_LOST_CODE"]
    data["lost_codes_status"] = "documented"
    data["data"]["schema"]["nonresponse_col"] = "TEST_ONLY_NONRESPONSE"
    data["trainee"]["timing_support"] = "dated"
    data["trainee"]["timing_evidence"]["status"] = "VERIFIED"
    if blocker == "checkpoint":
        data["data"]["checkpoint1_status"] = "FAILED"
    elif blocker == "permission":
        data["data"]["b4q12_permission_status"] = "UNRESOLVED"
    elif blocker == "lost_codes":
        data["lost_codes"] = []
        data["lost_codes_status"] = "unresolved"
    elif blocker == "timing":
        data["trainee"]["timing_support"] = "coarse_flag"
        data["trainee"]["timing_evidence"]["status"] = "UNVERIFIED"
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return load_config(path)


@pytest.mark.parametrize("blocker", ["checkpoint", "permission", "lost_codes", "timing"])
def test_dashboard_hides_saved_real_result_for_each_gate_failure(tmp_path, blocker):
    cfg = _temp_cfg(tmp_path, blocker)
    save_result("headline", {"is_synthetic": False, "n_individuals": 10}, cfg, False)
    save_result("headline", {"is_synthetic": True, "n_individuals": 10}, cfg, True)

    allowed, reason = real_gate_status(cfg)
    assert not allowed
    assert reason
    assert available_tags(cfg) == [SYNTHETIC]
    assert REAL not in available_tags(cfg)


def test_dashboard_allows_real_saved_result_only_when_temp_gate_passes(tmp_path):
    cfg = _temp_cfg(tmp_path)
    save_result("headline", {"is_synthetic": False, "n_individuals": 10}, cfg, False)
    assert real_gate_status(cfg) == (True, "All configured real-data gate checks pass.")
    assert available_tags(cfg) == [REAL]


def test_dashboard_status_shows_permission_lost_timing_and_weighting_state():
    cfg = load_config()
    statuses = dict(status_items(cfg))
    assert statuses["Checkpoint 1 — input verification"].startswith("Not passed;")
    assert statuses["Training-selection permission"] == "Confirmed by the user."
    assert statuses["Data integrity"].startswith("Preliminary audit passed;")
    assert statuses["CWS outcome mapping"].startswith("Broad work-status groups are documented;")
    assert statuses["Person linkage"].startswith("A respondent-linking rule exists,")
    assert statuses["Profiling scope"].startswith("Not reviewed;")
    assert statuses["Research readiness"].startswith("Blocked until")
    assert statuses["Follow-up loss codes"] == "No verified respondent-level loss mapping configured."
    assert "coarse timing evidence" in statuses["Training timing"]
    assert "not validated" in statuses["Longitudinal weighting"]
    assert statuses["Annual cross-sectional review"].startswith("Validated for descriptive annual estimates only")
    assert "NO_QTR" in statuses["Annual weight formula"]


def test_dashboard_reads_validated_cross_sectional_outputs_without_opening_longitudinal_gate():
    cfg = load_config()
    raw_perv1 = cfg.root / "data" / "raw" / "perv1.csv"
    if not raw_perv1.is_file():
        pytest.skip("Legacy PLFS test requires authentic data/raw/perv1.csv, which is not part of the active Turkey ISKUR project.")
    payload, estimates, indicators, note = load_cross_sectional_saved(cfg)
    assert payload is not None and estimates is not None and indicators is not None
    assert payload["is_synthetic"] is False
    assert payload["analysis_type"] == "cross_sectional_annual_cws_descriptive"
    assert any("no sample nonresponse/casualty field" in x for x in payload["limits"])
    assert len(estimates) == 9
    assert len(indicators) == 3
    assert (cfg.root / "outputs/cross_sectional/real/cws_weighted_shares.png").is_file()
    assert (cfg.root / "outputs/cross_sectional/real/employment_indicators.png").is_file()
    assert "hashes match" in note
    assert real_gate_status(cfg)[0] is False


def test_dashboard_cross_sectional_saved_view_respects_its_own_gate(tmp_path):
    data = load_config().to_dict()
    data["cross_sectional"]["status"] = "validation_pending"
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    payload, estimates, indicators, note = load_cross_sectional_saved(load_config(path))
    assert payload is None and estimates is None and indicators is None
    assert "not true/validated" in note
