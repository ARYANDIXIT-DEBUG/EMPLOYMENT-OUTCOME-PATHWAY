"""Missing data: measure it, say what it can and cannot tell us, and test how much the answer depends on it.

Why this file exists: employment histories have holes (no record, status unknown, lost to follow-up),
and every way of handling a hole is an assumption about why it is there. The primary analysis makes
the least invasive one: states are NEVER imputed, and the distance between two sequences uses only
the time points observed in both (`missing.policy: pairwise_available`, implemented in distances.py).
This module (1) audits the missingness, (2) imputes person ATTRIBUTES only, per `missing.attr_handling`,
and (3) offers three stronger alternatives for SENSITIVITY runs, so the report can show whether the
pathways survive a change of assumption.

Design choices worth defending in a viva:
  * States are not imputed in the primary analysis. A guessed employment state is a fabricated
    outcome. The sensitivity policies below exist to measure how much such guesses would matter, not
    to replace the primary one:
      complete_cases_only  keep only persons observed at every time point (changes WHO is analysed);
      forward_fill         carry a person's last observed state forward over later MISSING or LOST
                           points (last observation carried forward; leading gaps stay unobserved);
      missing_as_state     treat "not observed" as one extra state named "unobserved" (MISSING and
                           LOST both map to it), so the distance compares gaps as if they were a state.
    `pairwise_available` is accepted as the reference policy and returns the data unchanged.
  * The audit reports what the data can show and is honest about what they cannot. It tests whether
    missingness depends on OBSERVED information (earlier state, attributes). A small p-value is
    evidence against "missing completely at random" (MCAR); a large one is not proof of MCAR, and
    "missing not at random" (MNAR, missingness depends on the unobserved value itself) cannot be
    tested from the observed data at all. With thousands of persons trivial associations become
    significant, so every test also reports an effect size and a Bonferroni-adjusted flag.
  * Little's MCAR test is not used: it assumes multivariate-normal numeric data, and state sequences
    are categorical.
  * Attribute tests respect the data-use assessment. On real data only variables listed in
    `profiling.permitted_vars` are tested against missingness; on synthetic data (where the MoSPI
    rider does not apply) every attribute is used. State-based tests use only employment states.
  * Attribute imputation never touches states, never imputes a protected variable differently from the
    others, and leaves a column that is entirely missing as missing (reported in `df.attrs`) instead
    of inventing a value.

Dependency rule: imports only `config` and the shared types. The smoke demo imports `synthetic_data`
inside the demo function.

Run the smoke demo with:  python -m src.missing_data
"""
from __future__ import annotations

from typing import Any, Callable

import numpy as np
import pandas as pd
from scipy import stats

from . import LOST, MISSING, TrajectoryData
from .config import Config, load_config

__all__ = [
    "STATE_POLICIES",
    "audit_missingness",
    "impute_attributes",
    "apply_state_policy",
    "sensitivity_analysis",
]

STATE_POLICIES = ("pairwise_available", "complete_cases_only", "forward_fill", "missing_as_state")
NUMERIC_IMPUTERS = ("median", "mean")
CATEGORICAL_IMPUTERS = ("unknown_category", "mode")
UNOBSERVED_STATE = "unobserved"
ALPHA = 0.05                 # family-wise level for the Bonferroni flag
MAX_PATTERNS = 10            # patterns listed in the audit
MIN_GROUP = 5                # smallest group size for a test to be run
NUMERIC_MIN_DISTINCT = 11    # an attribute with at least this many distinct values is treated as numeric


# ---------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------
def _clone(td: TrajectoryData, states: np.ndarray | None = None, state_names: list[str] | None = None,
           keep: np.ndarray | None = None, extra_meta: dict[str, Any] | None = None) -> TrajectoryData:
    """A new TrajectoryData sharing nothing mutable with `td`, optionally with new states, names or rows."""
    idx = np.arange(td.n) if keep is None else np.flatnonzero(np.asarray(keep))
    meta = dict(td.meta)
    meta.update(extra_meta or {})
    return TrajectoryData(
        ids=td.ids[idx].copy(),
        states=(td.states if states is None else states)[idx].copy(),
        time_labels=list(td.time_labels),
        state_names=list(td.state_names if state_names is None else state_names),
        attrs=td.attrs.iloc[idx].copy(),
        weights=None if td.weights is None else td.weights[idx].copy(),
        is_synthetic=td.is_synthetic,
        meta=meta,
    )


def _is_numeric_attr(s: pd.Series) -> bool:
    return (pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s)
            and s.nunique(dropna=True) >= NUMERIC_MIN_DISTINCT)


def _f(x: Any) -> float | None:
    x = float(x)
    return None if not np.isfinite(x) else x


def _chi2(table: np.ndarray) -> tuple[float, float, float] | None:
    """(statistic, p, Cramer's V) for a contingency table, or None when it cannot be tested."""
    table = table[table.sum(axis=1) > 0][:, table.sum(axis=0) > 0]
    if table.shape[0] < 2 or table.shape[1] < 2:
        return None
    chi2, p, _, _ = stats.chi2_contingency(table, correction=False)
    n = table.sum()
    v = float(np.sqrt(chi2 / (n * (min(table.shape) - 1)))) if n else float("nan")
    return float(chi2), float(p), v


def _attribute_columns(td: TrajectoryData, cfg: Config) -> tuple[list[str], str]:
    """Attributes allowed in missingness tests, and the reason."""
    cols = [c for c in td.attrs.columns if c != "person_id"]
    if td.is_synthetic:
        return cols, "synthetic data: the MoSPI data-use rider does not apply, all attributes are used"
    permitted = [str(v) for v in (cfg.get("profiling.permitted_vars") or [])]
    allowed = [c for c in cols if c in permitted]
    if not allowed:
        return [], ("profiling.permitted_vars is empty or matches no attribute, so no attribute is tested against "
                    "missingness (see docs/DATA_USE_ASSESSMENT.md); state-based tests were still run")
    return allowed, "only variables in profiling.permitted_vars are used"


# ---------------------------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------------------------
def audit_missingness(td: TrajectoryData, cfg: Config) -> dict:
    """How much is missing, in what patterns, and is it plausibly random? Returns a JSON-ready dict.

    Cells: observed (state 0..K-1), MISSING (no record or unknown) and LOST (lost to follow-up) are
    counted separately. Patterns are strings over o (observed), m (MISSING), l (LOST), one letter per
    time point. Dropout is "monotone" if, once a person is unobserved, they stay unobserved.
    Tests (all on observed information; none can detect MNAR):
      * missingness at time t among persons observed at t-1, against the state at t-1 (chi-square);
      * "any unobserved point" against each allowed attribute (Mann-Whitney U for numeric, chi-square
        for categorical), with effect sizes (Cohen's d, Cramer's V).
    The verdict uses a Bonferroni-adjusted level over all tests run and is worded to avoid claiming MCAR.
    """
    S = td.states
    n, T = S.shape
    obs, mis, lost = S >= 0, S == MISSING, S == LOST
    n_cells = S.size
    cells = {
        "observed": int(obs.sum()), "missing": int(mis.sum()), "lost": int(lost.sum()),
        "share_observed": float(obs.mean()), "share_missing": float(mis.mean()), "share_lost": float(lost.mean()),
    }
    by_time = [{"time_label": td.time_labels[t], "n_observed": int(obs[:, t].sum()),
                "share_missing": float(mis[:, t].mean()), "share_lost": float(lost[:, t].mean())} for t in range(T)]
    n_obs = obs.sum(axis=1)
    hist = {str(k): int((n_obs == k).sum()) for k in range(T + 1)}

    letters = np.where(obs, "o", np.where(mis, "m", "l"))
    pat = pd.Series(["".join(r) for r in letters]).value_counts()
    patterns = [{"pattern": p, "n": int(c), "share": float(c / n)} for p, c in pat.head(MAX_PATTERNS).items()]

    any_un = ~obs.all(axis=1)
    first_un = np.where(~obs, np.arange(T), T).min(axis=1)
    suffix = np.array([(not obs[i, first_un[i]:].any()) if any_un[i] else False for i in range(n)])
    dropout = {
        "n_with_any_unobserved": int(any_un.sum()),
        "n_monotone_dropout": int(suffix.sum()),
        "n_intermittent": int((any_un & ~suffix).sum()),
        "n_unobserved_at_first_point": int((~obs[:, 0]).sum()),
        "n_never_observed": int((n_obs == 0).sum()),
    }

    tests: list[dict[str, Any]] = []
    for t in range(1, T):
        at_risk = obs[:, t - 1]
        if at_risk.sum() < 2 * MIN_GROUP:
            continue
        went_un = ~obs[at_risk, t]
        prev = S[at_risk, t - 1]
        states_seen = np.unique(prev)
        table = np.array([[int(((prev == s) & ~went_un).sum()), int(((prev == s) & went_un).sum())] for s in states_seen])
        res = _chi2(table)
        if res is not None:
            tests.append({"test": f"unobserved at {td.time_labels[t]} vs state at {td.time_labels[t - 1]}",
                          "kind": "state_dependence", "method": "chi-square", "n": int(at_risk.sum()),
                          "statistic": _f(res[0]), "p_value": _f(res[1]), "effect_size": _f(res[2]), "effect_name": "cramers_v",
                          "missing_rate_by_previous_state": {td.state_names[int(s)]: float(table[i, 1] / table[i].sum())
                                                            for i, s in enumerate(states_seen)}})
    cols, why = _attribute_columns(td, cfg)
    if 0 < any_un.sum() < n:
        for c in cols:
            s = td.attrs[c]
            if _is_numeric_attr(s):
                a, b = s[any_un].dropna().to_numpy(float), s[~any_un].dropna().to_numpy(float)
                if min(len(a), len(b)) < MIN_GROUP:
                    continue
                u = stats.mannwhitneyu(a, b, alternative="two-sided")
                sd = np.sqrt(((len(a) - 1) * a.var(ddof=1) + (len(b) - 1) * b.var(ddof=1)) / (len(a) + len(b) - 2))
                tests.append({"test": f"any unobserved point vs {c}", "kind": "attribute", "method": "Mann-Whitney U",
                              "n": int(len(a) + len(b)), "statistic": _f(u.statistic), "p_value": _f(u.pvalue),
                              "effect_size": _f((a.mean() - b.mean()) / sd) if sd > 0 else None, "effect_name": "cohens_d"})
            else:
                col = s.astype("string").fillna("<missing>")
                cats = sorted(col.unique())
                table = np.array([[int(((col == k) & any_un).sum()), int(((col == k) & ~any_un).sum())] for k in cats])
                res = _chi2(table)
                if res is not None:
                    tests.append({"test": f"any unobserved point vs {c}", "kind": "attribute", "method": "chi-square",
                                  "n": int(n), "statistic": _f(res[0]), "p_value": _f(res[1]), "effect_size": _f(res[2]),
                                  "effect_name": "cramers_v"})
    m = len(tests)
    for tst in tests:
        tst["p_bonferroni"] = None if tst["p_value"] is None else min(1.0, tst["p_value"] * m)
        tst["significant_after_bonferroni"] = bool(tst["p_bonferroni"] is not None and tst["p_bonferroni"] < ALPHA)
    flagged = [t["test"] for t in tests if t["significant_after_bonferroni"]]
    if m == 0:
        verdict = "not assessable: no test could be run (too few persons, no variation, or no permitted attribute)"
    elif flagged:
        verdict = ("evidence against MCAR: missingness is related to observed information (" + "; ".join(flagged[:5])
                   + "). Consistent with MAR or MNAR; MNAR cannot be tested from the observed data")
    else:
        verdict = ("no evidence against MCAR in the tests run. This does not prove MCAR, and MNAR cannot be "
                   "tested from the observed data")
    return {
        "is_synthetic": bool(td.is_synthetic),
        "n_individuals": int(n), "n_time_points": int(T), "n_cells": int(n_cells),
        "cells": cells, "by_time": by_time,
        "observed_points_histogram": hist, "share_complete_cases": float((n_obs == T).mean()),
        "n_distinct_patterns": int(len(pat)), "patterns": patterns, "dropout": dropout,
        "attribute_tests_note": why,
        "tests": tests, "n_tests": int(m), "alpha": ALPHA, "bonferroni_threshold": float(ALPHA / m) if m else None,
        "verdict": verdict,
        "limits": ("Tests use observed information only. Large samples make small associations significant, so read "
                   "the effect sizes. No test here can establish MCAR or rule out MNAR."),
        "primary_policy": str(cfg.missing.policy),
    }


# ---------------------------------------------------------------------------------------------
# Attributes
# ---------------------------------------------------------------------------------------------
def impute_attributes(attrs: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Fill missing person attributes per `missing.attr_handling`; states are never touched.

    numeric: "median" (default) or "mean". categorical: "unknown_category" keeps missing as its own
    explicit category ("<unknown>" for text, the code -1 for columns made by `encode_attributes`), or
    "mode" fills with the most frequent value. A column is categorical if it is non-numeric, is listed
    in `attrs.attrs["categorical_columns"]`, or has fewer than 11 distinct values. A column that is
    entirely missing is left as it is and listed in `attrs.attrs["not_imputable"]`. The counts filled
    per column are in `attrs.attrs["imputed"]`. Raises ValueError for an unknown method name.
    """
    handling = cfg.get("missing.attr_handling") or {}
    num_m = str(handling.get("numeric", "median"))
    cat_m = str(handling.get("categorical", "unknown_category"))
    if num_m not in NUMERIC_IMPUTERS:
        raise ValueError(f"missing.attr_handling.numeric must be one of {NUMERIC_IMPUTERS}, got {num_m!r}")
    if cat_m not in CATEGORICAL_IMPUTERS:
        raise ValueError(f"missing.attr_handling.categorical must be one of {CATEGORICAL_IMPUTERS}, got {cat_m!r}")
    out = attrs.copy()
    declared_cat = set(attrs.attrs.get("categorical_columns", []))
    imputed: dict[str, int] = {}
    stuck: list[str] = []
    for c in attrs.columns:
        if c == "person_id":
            continue
        s = attrs[c]
        is_cat = c in declared_cat or not _is_numeric_attr(s)
        encoded = c in declared_cat and pd.api.types.is_integer_dtype(s)
        miss = (s == -1) if encoded else s.isna()
        n_miss = int(miss.sum())
        if n_miss == 0:
            imputed[c] = 0
            continue
        if n_miss == len(s):
            stuck.append(c)
            imputed[c] = 0
            continue
        if is_cat:
            if cat_m == "mode":
                fill = s[~miss].mode().iloc[0]
                out[c] = s.where(~miss, fill)
            elif encoded:
                pass                                                  # -1 already is the explicit "unknown" category
            else:
                out[c] = s.astype(object).where(~s.isna(), "<unknown>")
        else:
            fill = s.median() if num_m == "median" else s.mean()
            out[c] = s.fillna(fill)
        imputed[c] = n_miss          # for "unknown_category" these are relabelled as a category rather than filled
    out.attrs.update(attrs.attrs)
    out.attrs.update({"imputed": imputed, "not_imputable": stuck,
                      "attr_handling_used": {"numeric": num_m, "categorical": cat_m}})
    return out


# ---------------------------------------------------------------------------------------------
# State policies (sensitivity runs only)
# ---------------------------------------------------------------------------------------------
def apply_state_policy(td: TrajectoryData, policy: str, cfg: Config) -> TrajectoryData:
    """Return a new TrajectoryData with a stronger missing-state assumption. SENSITIVITY RUNS ONLY.

    pairwise_available: unchanged (the primary policy; distances use jointly observed points).
    complete_cases_only: keep persons observed at all T points; raises ValueError if none.
    forward_fill: replace MISSING or LOST by the person's most recent observed state; points before
        the first observed state stay as they were.
    missing_as_state: add a state named "unobserved" (code K); MISSING and LOST both become K.
    `meta["missing_policy"]` records the policy and what it changed. The input is never modified.
    """
    if policy not in STATE_POLICIES:
        raise ValueError(f"policy must be one of {STATE_POLICIES}, got {policy!r}")
    S, K = td.states, len(td.state_names)
    info: dict[str, Any] = {"policy": policy, "n_before": int(td.n), "cells_unobserved_before": int((S < 0).sum())}
    if policy == "pairwise_available":
        info.update(n_after=int(td.n), cells_changed=0)
        return _clone(td, extra_meta={"missing_policy": info})
    if policy == "complete_cases_only":
        keep = (S >= 0).all(axis=1)
        if not keep.any():
            raise ValueError("complete_cases_only leaves nobody: no person is observed at every time point")
        info.update(n_after=int(keep.sum()), cells_changed=0)
        return _clone(td, keep=keep, extra_meta={"missing_policy": info})
    if policy == "forward_fill":
        out = S.astype(np.int16).copy()
        carry = np.full(td.n, -1, dtype=np.int16)
        for t in range(td.T):
            col = out[:, t]
            seen = col >= 0
            carry = np.where(seen, col, carry)
            fill = (~seen) & (carry >= 0)
            out[fill, t] = carry[fill]
        changed = int((out != S).sum())
        info.update(n_after=int(td.n), cells_changed=changed, cells_unobserved_after=int((out < 0).sum()))
        return _clone(td, states=out.astype(np.int8), extra_meta={"missing_policy": info})
    # missing_as_state
    if UNOBSERVED_STATE in td.state_names:
        raise ValueError(f"a state named {UNOBSERVED_STATE!r} already exists")
    out = np.where(S < 0, K, S).astype(np.int8)
    info.update(n_after=int(td.n), cells_changed=int((S < 0).sum()), new_state=UNOBSERVED_STATE, new_state_code=K)
    return _clone(td, states=out, state_names=list(td.state_names) + [UNOBSERVED_STATE],
                  extra_meta={"missing_policy": info})


def sensitivity_analysis(td: TrajectoryData, cfg: Config, policies: list[str] | None,
                         run_fn: Callable[[TrajectoryData], dict[str, float]]) -> pd.DataFrame:
    """Run `run_fn` on the data under the primary policy and under each listed policy; compare.

    `policies` empty or None means `missing.sensitivity_policies` from config. The first row is the
    primary policy (`missing.policy`) on unchanged data and is the reference: for every metric `m`
    returned by `run_fn`, column `delta_m` is the policy's value minus the reference. If `run_fn`
    raises for a policy, the row keeps the error text in `error` and the run continues, so one
    failure cannot hide the others. Columns: policy, is_primary, n_individuals,
    share_cells_unobserved, <metrics>, delta_<metrics>, error.
    """
    primary = str(cfg.missing.policy)
    wanted = list(policies) if policies else [str(p) for p in (cfg.get("missing.sensitivity_policies") or [])]
    for p in [primary] + wanted:
        if p not in STATE_POLICIES:
            raise ValueError(f"policy must be one of {STATE_POLICIES}, got {p!r}")
    order = [primary] + [p for p in dict.fromkeys(wanted) if p != primary]
    rows: list[dict[str, Any]] = []
    for pol in order:
        row: dict[str, Any] = {"policy": pol, "is_primary": pol == primary, "error": None}
        try:
            data = apply_state_policy(td, pol, cfg)
            row["n_individuals"] = int(data.n)
            row["share_cells_unobserved"] = float((data.states < 0).mean())
            for k, v in run_fn(data).items():
                row[k] = float(v)
        except Exception as exc:                                      # recorded, not hidden
            row["error"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)
    df = pd.DataFrame(rows)
    ref = df.iloc[0]
    metric_cols = [c for c in df.columns if c not in ("policy", "is_primary", "error", "n_individuals", "share_cells_unobserved")]
    for c in metric_cols:
        df[f"delta_{c}"] = df[c] - ref[c]
    return df


# ---------------------------------------------------------------------------------------------
# Smoke demo
# ---------------------------------------------------------------------------------------------
def _demo_td(cfg: Config, df: pd.DataFrame, truth: Any, extra_missing: str | None = None, seed: int = 0) -> TrajectoryData:
    """SYNTHETIC trajectories from a synthetic long panel, mapped with a local code table (demo only).

    extra_missing: None | "state" (after the 'unemployed_seeking' state, the next point is dropped with
    probability 0.6) | "age" (persons older than 30 lose each point with probability 0.35). These plant
    non-random missingness for the audit to find.
    """
    d = cfg.to_dict()
    names = [s["name"] for s in d["states"]]
    code = {str(s["raw_codes"][0]): i for i, s in enumerate(d["states"])}
    n, T = truth.params["n"], truth.params["T"]
    S = np.full((n, T), MISSING, dtype=np.int8)
    pid = df["person_id"].str[1:].astype(int).to_numpy()
    lost_code = str(d["lost_codes"][0])
    for p, t, raw, nr in zip(pid, df["t"].to_numpy(), df["raw_status"].to_numpy(), df["nonresponse_code"].to_numpy()):
        if nr is not None and str(nr) == lost_code:
            S[p, t] = LOST
        elif raw is not None and str(raw) in code:
            S[p, t] = code[str(raw)]
    attrs = df.drop_duplicates("person_id").sort_values("person_id")[["person_id", "age", "sex", "sector"]].reset_index(drop=True)
    rng = np.random.default_rng(seed)
    if extra_missing == "state":
        jobless = names.index("unemployed_seeking")
        for t in range(1, T):
            hit = (S[:, t - 1] == jobless) & (rng.random(n) < 0.6)
            S[hit, t] = MISSING
    elif extra_missing == "age":
        old = attrs["age"].to_numpy() > 30
        S[old[:, None] & (rng.random((n, T)) < 0.35)] = MISSING
    return TrajectoryData(ids=attrs["person_id"].to_numpy(dtype=object), states=S, time_labels=list(d["time"]["labels"]),
                          state_names=names, attrs=attrs, weights=None, is_synthetic=True,
                          meta={"source": "missing_data demo"})


def _demo() -> int:
    from .synthetic_data import demo_trajectory_data, generate_synthetic

    cfg = load_config()
    print("SYNTHETIC DEMONSTRATION - NOT PLFS RESULTS")
    df, truth = generate_synthetic(cfg, n=2000, seed_offset=5)
    td = _demo_td(cfg, df, truth)
    rep = audit_missingness(td, cfg)
    print(f"audit (plain synthetic): missing={rep['cells']['share_missing']:.3f} lost={rep['cells']['share_lost']:.3f} "
          f"complete_cases={rep['share_complete_cases']:.3f} tests={rep['n_tests']}")
    print(f"  verdict: {rep['verdict']}")
    rep_state = audit_missingness(_demo_td(cfg, df, truth, "state"), cfg)
    rep_age = audit_missingness(_demo_td(cfg, df, truth, "age"), cfg)
    print(f"audit (planted state-dependent): {rep_state['verdict'][:90]}...")
    print(f"audit (planted age-dependent):   {rep_age['verdict'][:90]}...")

    # attributes
    attrs = td.attrs.copy()
    attrs.loc[attrs.index[:40], "age"] = np.nan
    attrs.loc[attrs.index[40:70], "sector"] = None
    imp = impute_attributes(attrs, cfg)
    imp_mode = impute_attributes(attrs, Config({**cfg.to_dict(), "missing": {**cfg.to_dict()["missing"],
                                                "attr_handling": {"numeric": "mean", "categorical": "mode"}}}, cfg.root))

    # state policies on a small hand-built set with known answers
    small = demo_trajectory_data(cfg)
    cc, ff, ms, pw = (apply_state_policy(small, p, cfg) for p in ("complete_cases_only", "forward_fill", "missing_as_state", "pairwise_available"))
    employed = [i for i, s in enumerate(cfg.to_dict()["states"]) if s["name"] in cfg.to_dict()["baseline"]["employed_states"]]
    sens = sensitivity_analysis(td, cfg, None, lambda d: {
        "employed_share_of_observed": float(np.isin(d.states[d.states >= 0], employed).mean())})
    print(sens[["policy", "is_primary", "n_individuals", "share_cells_unobserved", "employed_share_of_observed",
                "delta_employed_share_of_observed"]].round(4).to_string(index=False))

    plain_flags = [t["test"] for t in rep["tests"] if t["significant_after_bonferroni"]]
    checks = {
        "cell shares sum to 1": abs(rep["cells"]["share_observed"] + rep["cells"]["share_missing"] + rep["cells"]["share_lost"] - 1) < 1e-12,
        "unobserved share near the generator's rate": abs(1 - rep["cells"]["share_observed"] - 0.10) < 0.02,
        "plain synthetic: no evidence against MCAR": not plain_flags,
        "planted state dependence is detected": any(t["kind"] == "state_dependence" and t["significant_after_bonferroni"] for t in rep_state["tests"]),
        "planted age dependence is detected": any(t["test"].endswith("age") and t["significant_after_bonferroni"] for t in rep_age["tests"]),
        "patterns listed and sum correctly": sum(p["n"] for p in rep["patterns"]) <= td.n and rep["n_distinct_patterns"] >= len(rep["patterns"]),
        "audit is JSON-ready": isinstance(__import__("json").dumps(rep, allow_nan=False), str),
        "real data with empty permitted_vars skips attribute tests": audit_missingness(
            TrajectoryData(td.ids, td.states, td.time_labels, td.state_names, td.attrs, None, False, {}), cfg)["n_tests"] ==
            sum(1 for t in rep["tests"] if t["kind"] == "state_dependence"),
        "median fills age": imp["age"].isna().sum() == 0 and abs(imp.loc[0, "age"] - attrs["age"].median()) < 1e-9,
        "unknown_category keeps a labelled category": (imp.loc[40, "sector"] == "<unknown>") and imp.attrs["imputed"]["sector"] == 30,
        "mode fills sector": (imp_mode["sector"] == "<unknown>").sum() == 0 and imp_mode["sector"].isna().sum() == 0,
        "imputation leaves the input alone": attrs["age"].isna().sum() == 40,
        "complete_cases keeps only fully observed": cc.n == int((small.states >= 0).all(axis=1).sum()) == 9 and (cc.states >= 0).all(),
        "forward_fill fills inner gaps, not leading": ff.states[3, 2] == small.states[3, 1] and ff.states[7, 0] == MISSING
                                                       and ff.states[11, 3] == small.states[11, 2],
        "missing_as_state adds one state": ms.state_names[-1] == UNOBSERVED_STATE and (ms.states >= 0).all() and ms.states[3, 2] == len(small.state_names),
        "pairwise_available is an unchanged copy": (pw.states == small.states).all() and pw.states is not small.states,
        "policies never modify the input": (small.states[3, 2] == MISSING) and len(small.state_names) == 6,
        "sensitivity: primary first, deltas zero": bool(sens.iloc[0]["is_primary"]) and sens.iloc[0]["delta_employed_share_of_observed"] == 0,
        "sensitivity: all policies run": sens["error"].isna().all() and len(sens) == 4,
    }
    for name, ok in checks.items():
        print(f"  demo check [{'ok' if ok else 'FAILED'}]: {name}")
    if not all(checks.values()):
        return 1
    print(f"Demo checks passed ({len(checks)}). All data above is SYNTHETIC.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_demo())
