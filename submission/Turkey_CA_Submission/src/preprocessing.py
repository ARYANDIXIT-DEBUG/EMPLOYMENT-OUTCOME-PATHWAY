"""Preprocessing: from the long panel to one clean trainee sample, before any trajectory is built.

Why this file exists: between "records linked into persons" (data_loader) and "one state sequence per
person" (trajectories) there are four small decisions that change every later number, so each is made
once, here, in the open: which time points count (the observation window), what a person's attributes
are (one value per person, not per record), how attributes are put on a common footing (scaling and
encoding), and who is eligible for the analysis (enough observed time points). Everything is driven by
config.yaml; nothing is assumed about the data.

Design choices worth defending in a viva:
  * Window. The window is exactly the `time.n_points` points the config declares. Records outside it
    are dropped and counted, never reassigned to another point, and a repeated (person, time point)
    pair is an error, because a trajectory with two values at one time point is not a trajectory.
  * One value per person. Attributes are taken from the person's FIRST non-missing record in time
    order ("age at first observation", for example). That is a convention, not a fact: it is stated
    in `attrs`, and persons whose record values disagree are counted rather than hidden.
  * No imputation here. Missing attribute values stay missing (numeric NaN, categorical code -1).
    Filling them is `missing_data.impute_attributes`, which follows `missing.attr_handling`, so the
    amount of missing data is still visible to the missingness audit.
  * Encoding is reversible and order-free. Categories get integer codes in sorted order and the
    mapping is stored in `df.attrs["encodings"]`. Protected columns (sex, social group, religion) are
    encoded like any other but listed in `df.attrs["protected_columns"]`, so a later guard can refuse
    them as clustering inputs; encoding them here does not make them inputs.
  * Eligibility counts OBSERVED states only. MISSING (no record or unknown) and LOST (lost to
    follow-up) do not count toward `trainee.min_time_points`, and nothing is imputed to reach it.
    This is the single sample every later step uses (baseline, clustering, stability, profiling).

Dependency rule: this module imports only `config` and the shared types. Its smoke demo imports
`synthetic_data` inside the demo function, as docs/INTERFACES.md section 1 prescribes for every demo.

Run the smoke demo with:  python -m src.preprocessing
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from . import TrajectoryData
from .config import PROTECTED_ROLES, Config, load_config

__all__ = [
    "select_observation_window",
    "build_attributes",
    "scale_numeric",
    "encode_attributes",
    "apply_eligibility",
    "ATTRIBUTE_COLUMNS",
]

ATTRIBUTE_COLUMNS = ("age", "sex", "sector", "social_group", "religion")   # long-panel role names (see data_loader)
LONG_REQUIRED = ("person_id", "t", "raw_status", "nonresponse_code", "weight")
SCALE_METHODS = ("zscore", "minmax", "robust", "none")


# ---------------------------------------------------------------------------------------------
# Observation window
# ---------------------------------------------------------------------------------------------
def select_observation_window(long_df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Keep records at time points 0..time.n_points-1, sorted by (person_id, t); report what was dropped.

    Raises ValueError if a required column is missing, `t` is not integer-valued, or a (person_id, t)
    pair repeats. Counts go to `df.attrs` (`n_records_outside_window`, `window`).
    """
    absent = [c for c in LONG_REQUIRED if c not in long_df.columns]
    if absent:
        raise ValueError(f"long panel lacks required column(s) {absent}")
    n_points = int(cfg.time.n_points)
    t = pd.to_numeric(long_df["t"], errors="coerce")
    if t.isna().any() or (t != np.floor(t)).any():
        raise ValueError("column 't' must hold whole numbers (time-point indices)")
    inside = t.between(0, n_points - 1)
    out = long_df.loc[inside].copy()
    out["t"] = t.loc[inside].astype("int64")
    n_dup = int(out.duplicated(["person_id", "t"]).sum())
    if n_dup:
        raise ValueError(f"{n_dup} (person_id, t) pair(s) occur more than once: not a valid long panel")
    out = out.sort_values(["person_id", "t"], kind="mergesort").reset_index(drop=True)
    out.attrs.update(long_df.attrs)
    out.attrs.update({
        "window": [0, n_points - 1],
        "n_records_outside_window": int((~inside).sum()),
        "n_persons_in_window": int(out["person_id"].nunique()),
        "n_records_in_window": int(len(out)),
    })
    return out


# ---------------------------------------------------------------------------------------------
# Person-level attributes
# ---------------------------------------------------------------------------------------------
def build_attributes(long_df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """One row per person: the first non-missing value, in time order, of each attribute column present.

    Columns: `person_id`, then those of age, sex, sector, social_group, religion that the long panel has.
    Rows are sorted by person_id (string order), the order `build_trajectories` uses for its ids, so
    the result lines up with `TrajectoryData.ids` by position. Missing values stay missing. The number
    of persons whose records disagree on a categorical attribute, or whose age differs between
    records, is stored in `df.attrs["n_conflicting"]`.
    """
    if "person_id" not in long_df.columns or "t" not in long_df.columns:
        raise ValueError("long panel needs 'person_id' and 't'")
    cols = [c for c in ATTRIBUTE_COLUMNS if c in long_df.columns]
    ordered = long_df.sort_values(["person_id", "t"], kind="mergesort")
    grouped = ordered.groupby("person_id", sort=True)
    out = pd.DataFrame({"person_id": grouped.size().index.astype(str)})
    conflicts: dict[str, int] = {}
    for c in cols:
        first = grouped[c].first()                                  # first NON-missing value per person
        out[c] = first.to_numpy()
        if c == "age":
            out[c] = pd.to_numeric(out[c], errors="coerce").astype("float64")
            conflicts[c] = int(((grouped[c].max() - grouped[c].min()) > 0).sum())
        else:
            conflicts[c] = int((grouped[c].nunique(dropna=True) > 1).sum())
    out.attrs.update({
        "first_nonmissing_rule": "value at the person's earliest record with a non-missing value",
        "n_persons": int(len(out)),
        "n_conflicting": conflicts,
        "n_missing": {c: int(out[c].isna().sum()) for c in cols},
    })
    return out


def scale_numeric(df: pd.DataFrame, cols: list[str], method: str) -> tuple[pd.DataFrame, dict]:
    """Rescale numeric columns; returns (scaled copy, parameters per column). Missing values stay missing.

    zscore: (x - mean) / sd (sample sd, ddof=1). minmax: (x - min) / (max - min). robust: (x - median) / IQR.
    none: unchanged. A constant column has no spread; it becomes 0 and is flagged "constant" in the
    parameters. The parameters let a caller invert the transform or apply it to new data.
    """
    if method not in SCALE_METHODS:
        raise ValueError(f"method must be one of {SCALE_METHODS}, got {method!r}")
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"columns not in the frame: {missing}")
    out = df.copy()
    params: dict[str, dict[str, Any]] = {}
    for c in cols:
        if not pd.api.types.is_numeric_dtype(df[c]) or pd.api.types.is_bool_dtype(df[c]):
            raise ValueError(f"column {c!r} is not numeric and cannot be scaled")
        x = df[c].astype("float64")
        if method == "none" or x.notna().sum() == 0:
            params[c] = {"method": method, "constant": False, "n_valid": int(x.notna().sum())}
            out[c] = x
            continue
        if method == "zscore":
            centre, spread = float(x.mean()), float(x.std(ddof=1)) if x.notna().sum() > 1 else 0.0
        elif method == "minmax":
            centre, spread = float(x.min()), float(x.max() - x.min())
        else:
            q1, q3 = float(x.quantile(0.25)), float(x.quantile(0.75))
            centre, spread = float(x.median()), q3 - q1
        const = not np.isfinite(spread) or spread == 0.0
        out[c] = 0.0 if const else (x - centre) / spread
        out.loc[x.isna(), c] = np.nan
        params[c] = {"method": method, "centre": centre, "spread": spread, "constant": bool(const),
                     "n_valid": int(x.notna().sum())}
    out.attrs.update(df.attrs)
    return out, params


def encode_attributes(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Turn every non-numeric attribute column into integer codes; missing becomes -1; numeric columns stay.

    Codes follow the sorted order of the observed categories (compared as text). The mapping is in
    `df.attrs["encodings"]` ({column: [category for code 0, category for code 1, ...]}), and -1 always
    means missing, never a category. `person_id` is passed through. `df.attrs["protected_columns"]`
    lists the encoded columns that are protected roles; encoding them does not make them inputs.
    The categorical missing-value policy of config (`missing.attr_handling.categorical`) is only
    recorded here; it is applied by `missing_data.impute_attributes`.
    """
    out = df.copy()
    encodings: dict[str, list[str]] = {}
    numeric_cols, cat_cols = [], []
    for c in df.columns:
        if c == "person_id":
            continue
        s = df[c]
        if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
            numeric_cols.append(c)
            continue
        text = s.astype("string")
        cats = sorted(text.dropna().unique())
        index = {cat: i for i, cat in enumerate(cats)}
        out[c] = text.map(index).fillna(-1).astype("int32")
        encodings[c] = [str(x) for x in cats]
        cat_cols.append(c)
    out.attrs.update(df.attrs)
    out.attrs.update({
        "encodings": encodings,
        "numeric_columns": numeric_cols,
        "categorical_columns": cat_cols,
        "missing_code": -1,
        "protected_columns": [c for c in cat_cols + numeric_cols if c in PROTECTED_ROLES],
        "categorical_missing_policy_declared": cfg.get("missing.attr_handling.categorical"),
    })
    return out


# ---------------------------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------------------------
def apply_eligibility(td: TrajectoryData, cfg: Config) -> TrajectoryData:
    """The one trainee sample for every later step: persons with at least `trainee.min_time_points` observed states.

    Observed means a state code in 0..K-1. MISSING and LOST do not count. Raises ValueError if the
    threshold is outside 1..T or nobody is eligible. The returned object's `meta["eligibility"]` holds
    the counts before and after and the histogram of observed time points, so the report can say how
    many people each step removed.
    """
    min_pts = int(cfg.trainee.min_time_points)
    if not 1 <= min_pts <= td.T:
        raise ValueError(f"trainee.min_time_points={min_pts} must lie in 1..{td.T} (the number of time points)")
    n_obs = (td.states >= 0).sum(axis=1)
    keep = n_obs >= min_pts
    if not keep.any():
        raise ValueError(f"no person has {min_pts} or more observed time points: nobody is eligible")
    out = td.subset(keep)
    out.meta["eligibility"] = {
        "min_time_points": min_pts,
        "rule": "observed states only; MISSING and LOST do not count; nothing is imputed to reach the threshold",
        "n_before": int(td.n),
        "n_after": int(out.n),
        "n_removed": int(td.n - out.n),
        "observed_points_histogram_before": {str(k): int((n_obs == k).sum()) for k in range(td.T + 1)},
    }
    return out


# ---------------------------------------------------------------------------------------------
# Smoke demo
# ---------------------------------------------------------------------------------------------
def _demo() -> int:
    import copy

    from .synthetic_data import PERSON_ID_FORMAT, demo_trajectory_data, generate_synthetic

    cfg = load_config()
    print("SYNTHETIC DEMONSTRATION - NOT PLFS RESULTS")
    df, truth = generate_synthetic(cfg, n=600, seed_offset=11)
    # Add records outside the window and a missing age, to exercise the window and the first-non-missing rule.
    extra = df.iloc[:3].copy()
    extra["t"] = [4, 5, -1]
    noisy = pd.concat([df, extra], ignore_index=True)
    first_person = df["person_id"].iloc[0]
    noisy.loc[(noisy["person_id"] == first_person) & (noisy["t"] == df.loc[df["person_id"] == first_person, "t"].min()), "age"] = np.nan

    win = select_observation_window(noisy, cfg)
    attrs = build_attributes(win, cfg)
    enc = encode_attributes(attrs, cfg)
    scaled, params = scale_numeric(attrs, ["age"], "zscore")
    mm, mm_params = scale_numeric(attrs, ["age"], "minmax")
    print(f"window: records={len(win)} persons={win['person_id'].nunique()} outside={win.attrs['n_records_outside_window']}")
    print(f"attributes: columns={list(attrs.columns)} conflicts={attrs.attrs['n_conflicting']}")
    print(f"encodings: {enc.attrs['encodings']}  protected={enc.attrs['protected_columns']}")

    truth_age = df.drop_duplicates("person_id").set_index("person_id")["age"]
    ages = attrs.set_index("person_id")["age"]
    others = [p for p in ages.index if p != first_person]
    cfg_hi = copy.deepcopy(cfg.to_dict())
    cfg_hi["trainee"]["min_time_points"] = 4
    from .config import Config
    td = demo_trajectory_data(cfg)
    kept3 = apply_eligibility(td, cfg)           # min_time_points = 3 from config
    kept4 = apply_eligibility(td, Config(cfg_hi, cfg.root))
    checks = {
        "records outside the window dropped and counted": win.attrs["n_records_outside_window"] == 3 and len(win) == len(df),
        "sorted by person then time": bool((win.sort_values(["person_id", "t"]).index == win.index).all()),
        "one row per person, sorted by id": list(attrs["person_id"]) == sorted(attrs["person_id"].unique()) and len(attrs) == 600,
        "age taken from the first non-missing record": bool(np.allclose(ages.loc[others], truth_age.loc[others]) and
                                                           ages.loc[first_person] == df.loc[df["person_id"] == first_person, "age"].iloc[0]),
        "no conflicting attribute values in clean data": sum(attrs.attrs["n_conflicting"].values()) == 0,
        "categorical codes decode to the original values": all(
            (np.array(enc.attrs["encodings"][c], dtype=object)[enc[c].to_numpy()] == attrs[c].astype(str).to_numpy()).all()
            for c in ("sex", "sector")),
        "protected columns are listed, not removed": enc.attrs["protected_columns"] == ["sex"] and "sex" in enc.columns,
        "zscore mean 0 and sd 1": abs(scaled["age"].mean()) < 1e-9 and abs(scaled["age"].std(ddof=1) - 1) < 1e-9,
        "minmax spans 0..1": abs(mm["age"].min()) < 1e-12 and abs(mm["age"].max() - 1) < 1e-12,
        "scaling does not touch the input": attrs["age"].max() > 5,
        "eligibility keeps persons with >= 3 observed": kept3.n == 12 and kept3.meta["eligibility"]["n_removed"] == 0,
        "eligibility drops MISSING and LOST holders at 4": kept4.n == 9 and kept4.meta["eligibility"]["n_removed"] == 3,
        "id format unchanged": win["person_id"].iloc[0] == PERSON_ID_FORMAT.format(0) or win["person_id"].str.startswith("S").all(),
    }
    for name, ok in checks.items():
        print(f"  demo check [{'ok' if ok else 'FAILED'}]: {name}")
    if not all(checks.values()):
        return 1
    print(f"Demo checks passed ({len(checks)}). All data above is SYNTHETIC.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_demo())
