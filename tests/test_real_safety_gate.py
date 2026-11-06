"""Fail-closed real-data gate checks using isolated temporary config copies only."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from run_pipeline import EXIT_GATE, GateError, check_data_gate, run  # noqa: E402
from src.config import load_config  # noqa: E402


def _temporary_config(tmp_path: Path, **overrides):
    """Write test-only gate conditions to tmp_path; never touch the workspace config."""
    data = load_config().to_dict()
    data["data"].update({
        "plan": "A",
        "verified": True,
        "checkpoint1_status": "PASSED",
        "b4q12_permission_status": "CONFIRMED",  # test fixture only, not a project permission decision
    })
    data["lost_codes"] = ["TEST_ONLY_LOST_CODE"]  # synthetic gate fixture, not a claimed PLFS code
    data["data"]["schema"]["nonresponse_col"] = "TEST_ONLY_NONRESPONSE"
    data["trainee"]["timing_support"] = "dated"
    data["trainee"]["timing_evidence"]["status"] = "VERIFIED"
    for section, values in overrides.items():
        if section == "lost_codes":
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
    ({"lost_codes": []}, "lost_codes is empty"),
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


def test_current_workspace_config_fails_closed_at_unresolved_checkpoint_status():
    cfg = load_config()
    with pytest.raises(GateError, match="CHECKPOINT 1 is not recorded as PASSED"):
        check_data_gate(cfg)
