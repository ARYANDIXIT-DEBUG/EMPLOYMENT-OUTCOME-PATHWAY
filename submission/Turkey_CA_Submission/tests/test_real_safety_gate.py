"""Fail-closed real-data gate checks using isolated temporary config copies only."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from run_pipeline import EXIT_GATE, GateError, check_data_gate, run  # noqa: E402
from src.config import ConfigError, load_config  # noqa: E402


def _temporary_config(tmp_path: Path, **overrides):
    """Write test-only gate conditions to tmp_path; never touch the workspace config."""
    data = load_config().to_dict()
    data["data"].update({
        "plan": "A",
        "verified": True,
        "checkpoint1_status": "PASSED",
        "b4q12_permission_status": "CONFIRMED",  # test fixture only, not a project permission decision
    })
    data["validation"].update({"data_integrity": "passed", "mappings": "validated", "linkage": "validated",
                                "permissions": "user_confirmed", "research_readiness": "passed"})
    data["lost_codes"] = ["TEST_ONLY_LOST_CODE"]  # synthetic gate fixture, not a claimed PLFS code
    data["lost_codes_status"] = "documented"  # fully-cleared gate fixture only
    data["data"]["schema"]["nonresponse_col"] = "TEST_ONLY_NONRESPONSE"
    data["trainee"]["timing_support"] = "dated"
    data["trainee"]["timing_evidence"]["status"] = "VERIFIED"
    for section, values in overrides.items():
        if section == "lost_codes":
            data[section] = values
        elif section == "lost_codes_status":
            data[section] = values
        elif section == "timing_support":
            data["trainee"]["timing_support"] = values
        elif section == "timing_status":
            data["trainee"]["timing_evidence"]["status"] = values
        elif section == "nonresponse_col":
            data["data"]["schema"]["nonresponse_col"] = values
        else:
            data["data"][section] = values
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return load_config(config_path)


@pytest.mark.parametrize(("override", "message"), [
    ({"checkpoint1_status": "FAILED"}, "CHECKPOINT 1 is not recorded as PASSED"),
    ({"b4q12_permission_status": "UNRESOLVED"}, "permission to select the sample using b4q12 is not confirmed"),
    ({"lost_codes": [], "lost_codes_status": "unresolved"}, "lost_codes_status is unresolved"),
    ({"nonresponse_col": None}, "data.schema.nonresponse_col is unset"),
    ({"timing_support": "coarse_flag", "timing_status": "UNVERIFIED"}, "training timing is not documented and verified"),
])
def test_each_unmet_real_data_safety_condition_refuses_pipeline_run(tmp_path, override, message):
    cfg = _temporary_config(tmp_path, **override)
    logs: list[str] = []
    assert run(cfg, ["build"], synthetic=False, log=logs.append) == EXIT_GATE
    assert any("REFUSED" in line and message in line for line in logs)


def test_isolated_fully_cleared_gate_fixture_passes_checks(tmp_path):
    cfg = _temporary_config(tmp_path)
    check_data_gate(cfg)


def test_documented_unavailable_mapping_is_a_safe_resolved_gate_state(tmp_path):
    cfg = _temporary_config(tmp_path, lost_codes=[], lost_codes_status="documented_unavailable", nonresponse_col=None)
    check_data_gate(cfg)


def test_unresolved_lost_mapping_blocks_real_data_gate(tmp_path):
    cfg = _temporary_config(tmp_path, lost_codes=[], lost_codes_status="unresolved")
    with pytest.raises(GateError, match="lost_codes_status is unresolved"):
        check_data_gate(cfg)


@pytest.mark.parametrize(("field", "status", "message"), [
    ("mappings", "unresolved", "validation.mappings is not passed/validated"),
    ("linkage", "failed", "validation.linkage is not passed/validated"),
    ("permissions", "unresolved", "validation.permissions is not confirmed"),
])
def test_unresolved_validation_status_blocks_gate(tmp_path, field, status, message):
    data = load_config().to_dict()
    data["validation"].update({"data_integrity": "passed", "mappings": "validated", "linkage": "validated",
                               "permissions": "user_confirmed", "research_readiness": "passed"})
    data["validation"][field] = status
    data["data"].update({"checkpoint1_status": "PASSED", "b4q12_permission_status": "user_confirmed"})
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    cfg = load_config(path)
    with pytest.raises(GateError, match=message):
        check_data_gate(cfg)


def test_current_workspace_config_fails_closed_at_unresolved_checkpoint_status():
    cfg = load_config()
    with pytest.raises(GateError, match="CHECKPOINT 1 is not recorded as PASSED"):
        check_data_gate(cfg)


def test_dated_timing_cannot_be_declared_without_verified_evidence(tmp_path):
    data = load_config().to_dict()
    data["trainee"]["timing_support"] = "dated"
    data["trainee"]["timing_evidence"]["status"] = "UNVERIFIED"
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    with pytest.raises(ConfigError, match="timing_evidence.status is not VERIFIED"):
        load_config(path)
