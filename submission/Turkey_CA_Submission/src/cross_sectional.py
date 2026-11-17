"""First-visit, annual CWS estimates for respondents reporting formal vocational training.

This is a separate cross-sectional route. It does not call or change the longitudinal linker or gate.
No clustering is performed: CWS is one categorical outcome, not a defensible multi-feature clustering space.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import matplotlib.pyplot as plt

from .config import Config, ConfigError, load_config
from .data_loader import load_raw_tables

CWS_EMPLOYED_CODES = {11, 12, 21, 31, 41, 42, 51, 61, 62, 71, 72}
UNEMPLOYED = {81, 82}
OUT_OF_LF = set(range(91, 99))
OUTCOME = {**{x: "employed" for x in CWS_EMPLOYED_CODES}, **{x: "unemployed" for x in UNEMPLOYED},
           **{x: "out_of_labour_force" for x in OUT_OF_LF}}


class CrossSectionError(RuntimeError):
    """Cross-sectional analysis is not validated or the input does not match the frozen design."""


def check_cross_sectional_gate(cfg: Config) -> None:
    """Fail closed unless the distinct cross-sectional design and user-confirmed selection are enabled."""
    d = cfg.to_dict()
    cs = d.get("cross_sectional", {})
    if cs.get("enabled") is not True or cs.get("status") != "validated":
        raise CrossSectionError("cross_sectional.enabled/status are not true/validated")
    if d.get("validation", {}).get("cross_sectional_readiness") != "passed_descriptive_only":
        raise CrossSectionError("cross-sectional descriptive validation has not passed")
    if str(d.get("data", {}).get("b4q12_permission_status", "")).lower() != "user_confirmed":
        raise CrossSectionError("b4q12 selection permission is not user_confirmed")
    if cs.get("training_code") != "1" or cs.get("age_min") != 15 or cs.get("age_max") != 59:
        raise CrossSectionError("the frozen cohort definition is not the documented formal-training age 15–59 cohort")
    if cs.get("weight_formula") != "mult / (100 if nss == nsc else 200) / no_qtr":
        raise CrossSectionError("the documented annual weight formula is not configured")
    if cs.get("outcome_scope") != "CWS broad groups only":
        raise CrossSectionError("the outcome mapping scope is not the documented CWS broad groups")


def _numeric(series: pd.Series, name: str) -> pd.Series:
    out = pd.to_numeric(series, errors="coerce")
    bad = series.notna() & out.isna()
    if bad.any():
        raise CrossSectionError(f"{name} has {int(bad.sum())} nonnumeric nonmissing values")
    return out


def prepare_cross_section(cfg: Config, frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Validate first-visit source rows, select the frozen cohort, and retain all rows in summary counts."""
    required = {"qtr", "visit", "sector", "age", "b4q12", "cws", "wt", "no_qtr", "nss", "nsc"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise CrossSectionError(f"perv1 canonical fields missing: {missing}")
    if set(frame["visit"].dropna().astype(str).unique()) != {"V1"}:
        raise CrossSectionError("perv1 input contains unexpected visit values")
    qtrs = set(frame["qtr"].dropna().astype(str).unique())
    if not qtrs <= {"Q1", "Q2", "Q3", "Q4"}:
        raise CrossSectionError(f"unexpected quarter values: {sorted(qtrs - {'Q1','Q2','Q3','Q4'})}")
    if frame["qtr"].isna().any() or frame["visit"].isna().any():
        raise CrossSectionError("quarter/visit coordinates are missing")
    record_key = ["qtr", "visit", "sector", "state", "fsu", "sg_sb", "stratum2", "hh_no", "person_no"]
    missing_key = [x for x in record_key if x not in frame]
    if missing_key:
        raise CrossSectionError(f"official first-visit record-key fields missing from canonical frame: {missing_key}")
    if frame[record_key].isna().any().any():
        raise CrossSectionError("first-visit official record key contains missing components")
    if frame.duplicated(record_key).any():
        raise CrossSectionError(f"first-visit official record key has {int(frame.duplicated(record_key).sum())} collisions")

    age = _numeric(frame["age"], "age")
    training = frame["b4q12"].astype("string").str.strip()
    sector = frame["sector"].astype("string").str.strip()
    cws = _numeric(frame["cws"], "CWS")
    mult = _numeric(frame["wt"], "MULT")
    no_qtr = _numeric(frame["no_qtr"], "NO_QTR")
    nss = _numeric(frame["nss"], "NSS")
    nsc = _numeric(frame["nsc"], "NSC")
    eligible = age.between(15, 59).fillna(False) & training.eq("1").fillna(False)
    out = frame.loc[eligible].copy().reset_index(drop=True)
    out["_age"] = age.loc[eligible].to_numpy()
    out["_sector"] = sector.loc[eligible].to_numpy()
    out["_cws"] = cws.loc[eligible].to_numpy()
    out["_mult"] = mult.loc[eligible].to_numpy()
    out["_no_qtr"] = no_qtr.loc[eligible].to_numpy()
    out["_nss"] = nss.loc[eligible].to_numpy()
    out["_nsc"] = nsc.loc[eligible].to_numpy()

    invalid_sector = ~out["_sector"].isin(["1", "2"])
    if invalid_sector.any():
        raise CrossSectionError(f"eligible records contain {int(invalid_sector.sum())} unsupported sector values")
    if out["_mult"].isna().any() or (out["_mult"] <= 0).any():
        raise CrossSectionError("eligible records contain missing/nonpositive MULT")
    for col in ("_no_qtr", "_nss", "_nsc"):
        if out[col].isna().any() or (out[col] <= 0).any():
            raise CrossSectionError(f"eligible records contain missing/nonpositive {col[1:].upper()}")
    out["subsample_divisor"] = out["_nss"].eq(out["_nsc"]).map({True: 100.0, False: 200.0})
    out["annual_weight"] = out["_mult"] / out["subsample_divisor"] / out["_no_qtr"]
    if (out["annual_weight"] <= 0).any():
        raise CrossSectionError("annual weight must be positive")

    code = out["_cws"]
    out["cws_group"] = code.map(OUTCOME)
    out["cws_unclassified"] = code.notna() & out["cws_group"].isna()
    out["cws_missing"] = code.isna()
    # Current PLFS sample check: all eligible outcome codes must be within documented broad groups.
    if out["cws_unclassified"].any():
        vals = sorted(code[out["cws_unclassified"]].dropna().unique().tolist())
        raise CrossSectionError(f"eligible cohort contains CWS codes outside documented broad groups: {vals}")
    if out["cws_missing"].any():
        # Keep records and make the missing denominator explicit; never recode to unemployment.
        pass

    summary = {
        "source_rows": int(len(frame)), "eligible_rows": int(len(out)),
        "excluded_by_cohort_rule": int(len(frame) - len(out)),
        "eligible_by_quarter": {str(k): int(v) for k, v in out["qtr"].value_counts().sort_index().items()},
        "eligible_by_sector": {str(k): int(v) for k, v in out["_sector"].value_counts().sort_index().items()},
        "outcome_missing_rows": int(out["cws_missing"].sum()),
        "outcome_unclassified_rows": int(out["cws_unclassified"].sum()),
        "no_qtr_distribution": {str(k): int(v) for k, v in out["_no_qtr"].value_counts().sort_index().items()},
        "combined_subsample_divisor_distribution": {
            str(k): int(v) for k, v in out["subsample_divisor"].value_counts().sort_index().items()
        },
    }
    return out, summary


def estimate_cws(frame: pd.DataFrame) -> pd.DataFrame:
    """Unweighted sample counts and documented annual-weighted status shares by sector and combined."""
    rows = []
    groups = [("all", frame), *[(str(s), frame[frame["_sector"] == str(s)]) for s in ("1", "2")]]
    for sector, sub in groups:
        known = sub[~sub["cws_missing"] & ~sub["cws_unclassified"]]
        known_weight = float(known["annual_weight"].sum())
        total_weight = float(sub["annual_weight"].sum())
        for status in ("employed", "unemployed", "out_of_labour_force"):
            selected = known[known["cws_group"] == status]
            rows.append({
                "sector": sector, "cws_group": status,
                "n_unweighted": int(len(selected)), "n_known_cws": int(len(known)),
                "share_unweighted_known_cws": float(len(selected) / len(known)) if len(known) else None,
                "weighted_estimated_count": float(selected["annual_weight"].sum()),
                "share_weighted_known_cws": float(selected["annual_weight"].sum() / known_weight) if known_weight else None,
                "weighted_estimated_total_eligible": total_weight,
                "n_cws_missing_or_unclassified": int(len(sub) - len(known)),
                "weight_formula": "MULT / (100 if NSS == NSC else 200) / NO_QTR",
            })
    return pd.DataFrame(rows)


def derive_employment_indicators(estimates: pd.DataFrame) -> pd.DataFrame:
    """Derive CWS WPR, LFPR and UR for the selected trained subpopulation."""
    rows = []
    for sector, sub in estimates.groupby("sector", sort=False):
        values = sub.set_index("cws_group")
        emp = float(values.loc["employed", "weighted_estimated_count"])
        unemp = float(values.loc["unemployed", "weighted_estimated_count"])
        total = float(values.loc["employed", "weighted_estimated_total_eligible"])
        n_emp = int(values.loc["employed", "n_unweighted"])
        n_unemp = int(values.loc["unemployed", "n_unweighted"])
        n_total = int(values.loc["employed", "n_known_cws"] + values.loc["employed", "n_cws_missing_or_unclassified"])
        labor_weight = emp + unemp
        rows.append({
            "sector": sector,
            "n_unweighted": n_total,
            "weighted_population_estimate": total,
            "weighted_employed_estimate": emp,
            "weighted_unemployed_estimate": unemp,
            "wpr_weighted": emp / total if total else None,
            "lfpr_weighted": labor_weight / total if total else None,
            "ur_weighted": unemp / labor_weight if labor_weight else None,
            "wpr_unweighted": n_emp / n_total if n_total else None,
            "lfpr_unweighted": (n_emp + n_unemp) / n_total if n_total else None,
            "ur_unweighted": n_unemp / (n_emp + n_unemp) if n_emp + n_unemp else None,
            "denominator_missing_or_unclassified": int(values.loc["employed", "n_cws_missing_or_unclassified"]),
        })
    return pd.DataFrame(rows)


def save_figures(estimates: pd.DataFrame, indicators: pd.DataFrame, out_dir: Path) -> None:
    """Write standalone figures from the saved summary tables."""
    labels = {"all": "Combined", "1": "Rural", "2": "Urban"}
    order = ["all", "1", "2"]
    cws = estimates.pivot(index="sector", columns="cws_group", values="share_weighted_known_cws").reindex(order)
    cws = cws[["employed", "unemployed", "out_of_labour_force"]]
    ax = cws.plot(kind="bar", stacked=True, figsize=(8.5, 5.2),
                  color=["#176B5B", "#D28A28", "#667085"], width=0.68)
    ax.set_xticklabels([labels[x] for x in cws.index], rotation=0)
    ax.set_ylabel("Weighted share of known CWS")
    ax.set_xlabel("")
    ax.set_ylim(0, 1)
    ax.set_title("Annual CWS distribution in the selected training cohort")
    ax.legend(["Employed", "Unemployed", "Out of labour force"], title="CWS group", frameon=False,
              loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=3)
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    plt.savefig(out_dir / "cws_weighted_shares.png", dpi=180, bbox_inches="tight")
    plt.close()

    ind = indicators.set_index("sector").reindex(order)
    ax = ind[["wpr_weighted", "lfpr_weighted", "ur_weighted"]].plot(
        kind="bar", figsize=(8.5, 5.2), color=["#176B5B", "#4677A8", "#D28A28"], width=0.68
    )
    ax.set_xticklabels([labels[x] for x in ind.index], rotation=0)
    ax.set_ylabel("Weighted rate")
    ax.set_xlabel("")
    ax.set_ylim(0, 1)
    ax.set_title("Employment indicators in the selected training cohort")
    ax.legend(["WPR", "LFPR", "UR"], frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=3)
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    plt.savefig(out_dir / "employment_indicators.png", dpi=180, bbox_inches="tight")
    plt.close()


def run_cross_section(cfg: Config, *, out_dir: Path | None = None) -> dict[str, Any]:
    """Run the cross-sectional descriptive estimator after its own validation gate; no clustering."""
    check_cross_sectional_gate(cfg)
    tables = load_raw_tables(cfg)
    frame = tables.get("perv1")
    if frame is None:
        raise CrossSectionError("configured perv1 file was not loaded")
    cohort, summary = prepare_cross_section(cfg, frame)
    estimates = estimate_cws(cohort)
    indicators = derive_employment_indicators(estimates)
    data_config = cfg.to_dict()["data"]
    source_id = cfg.to_dict()["cross_sectional"]["observation_file"]
    data_path = cfg.root / next(x["path"] for x in data_config["files"] if x["id"] == source_id)
    config_path = cfg.root / "config.yaml"
    code_path = Path(__file__).resolve()
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    payload = {
        "analysis_type": "cross_sectional_annual_cws_descriptive",
        "is_synthetic": False,
        "research_question": "Annual CWS employment-indicator distribution at first visit among people aged 15–59 reporting formal vocational/technical training.",
        "cohort": "perv1 V1; age 15–59; b4q12 code 1; rural and urban",
        "summary": summary,
        "estimates": estimates.to_dict(orient="records"),
        "employment_indicators": indicators.to_dict(orient="records"),
        "weight": "annual weight = MULT / (100 if NSS == NSC else 200) / NO_QTR, Catalogue 213 rider §§B (combined subsamples and annual estimate)",
        "cws_mapping": "11–72 employed; 81/82 unemployed; 91–98 out of labour force; blank remains missing; any other code remains unclassified",
        "provenance": {"input_file": str(data_path.relative_to(cfg.root)), "input_sha256": sha(data_path),
                       "config_sha256": sha(config_path), "code_file": str(code_path.relative_to(cfg.root)),
                       "code_sha256": sha(code_path), "seed": None, "randomness": "none"},
        "limits": ["Cross-sectional first-visit estimates; no person linking, transitions, or pathways.",
                   "Descriptive association only; no causal training effect.",
                   "No demographic profiling or occupational clustering was performed.",
                   "CWS missing/unclassified outcomes are retained and reported separately, never assigned to unemployment.",
                   "The perv1 file has no sample nonresponse/casualty field; the published multiplier is used without an inferred separate nonresponse adjustment."],
    }
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        estimates.to_csv(out_dir / "cws_estimates.csv", index=False)
        indicators.to_csv(out_dir / "employment_indicators.csv", index=False)
        save_figures(estimates, indicators, out_dir)
        (out_dir / "cross_sectional_summary.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def main() -> int:
    cfg = load_config()
    result = run_cross_section(cfg, out_dir=cfg.root / "outputs" / "cross_sectional" / "real")
    print(json.dumps(result["summary"], indent=2))
    print(f"Saved cross-sectional estimates to {cfg.root / 'outputs' / 'cross_sectional' / 'real'}")
    return 0


if __name__ == "__main__":
    main()
