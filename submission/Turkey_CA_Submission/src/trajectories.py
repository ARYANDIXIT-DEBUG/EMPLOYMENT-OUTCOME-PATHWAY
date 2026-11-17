"""Trajectories: turn a long panel of raw survey records into one row of states per person, and collapse identical rows.

Why this file exists: everything after it (distances, clustering, baseline, profiling) works on a
person-by-time array of integer states. This is the only place where raw survey codes become states,
so the rules for doing that are strict and are all read from `config.yaml`, never from memory.

Design choices worth defending in a viva:
  * One mapping, read from config. A raw status code becomes a state only if it appears in
    `states[].raw_codes`. A code in `unknown_codes` becomes MISSING. A non-response code in
    `lost_codes` becomes LOST. A blank becomes MISSING. A code that is in none of the lists RAISES
    (ConfigError): guessing a state for an unlisted code would fabricate an outcome, and a release
    whose code list differs from the config must stop the run, not be absorbed.
  * A record that carries both a valid state and a lost code is contradictory. It raises ValueError.
    Choosing either side would be a silent assumption.
  * A (person, time) pair that has no record at all is MISSING. Persons are the sorted unique person
    ids, in string order, the same order `preprocessing.build_attributes` uses, so ids, states and
    attrs line up by position. Time comes only from the `t` column (0..T-1); out-of-window records are
    an error here (use `preprocessing.select_observation_window` first), never silently dropped.
  * Transitions are counted only between ADJACENT time points that are both observed. A step across a
    gap is not a one-step transition, so it is not counted. Nothing here treats usual, subsidiary and
    current weekly status as consecutive steps: the long panel carries one status column.
  * Two counts stay apart. `collapse_*` produces `freq` (individuals per unique row). Survey weights
    stay in `TrajectoryData.weights`. Neither is ever substituted for the other.
  * Survey weights are attached only when they are verified (real data: `data.verified` and a
    `data.schema.weight` column; synthetic data: the generator's weight). A person's weight is the value
    at their earliest record with a non-missing weight; how many persons have varying weights is
    reported in `meta`, because the revisit multiplier is unverified.
  * Collapsing is exact: two individuals share a unit only if they are identical on every distance
    input (states, plus categorical attributes if `distance.attribute_inputs` lists any). A numeric
    attribute input cannot be collapsed (nearly every person would be unique), so collapse raises
    CollapseRefused and the orchestrator falls back to subsampling. Attributes that are NOT distance
    inputs never block collapsing.

Dependency rule: imports only `config` and the shared types. The smoke demo imports `synthetic_data`
inside the demo function.

Run the smoke demo with:  python -m src.trajectories
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from . import LOST, MISSING, SYNTHETIC_LOST_CODE, CollapsedTrajectories, TrajectoryData
from .config import Config, ConfigError, assert_no_protected, load_config

__all__ = [
    "CollapseRefused",
    "map_raw_to_state",
    "build_trajectories",
    "trajectory_summary",
    "transition_matrix",
    "sequence_strings",
    "complete_case_mask",
    "collapse_trajectories",
    "identity_collapse",
    "expand_labels",
]

ATTRIBUTE_COLUMNS = ("age", "sex", "sector", "social_group", "religion")   # long-panel role names
MISSING_LABEL = "<missing>"          # explicit category for a missing categorical attribute in a collapse key
MISSING_CHAR, LOST_CHAR = "?", "#"   # sequence_strings legend: states are letters A, B, C ...


class CollapseRefused(Exception):
    """Collapsing is not possible for the configured distance inputs (a numeric attribute is one of them)."""


# ---------------------------------------------------------------------------------------------
# Raw code -> state
# ---------------------------------------------------------------------------------------------
def _one_code(x: Any) -> str | None:
    """A raw code as comparable text: integer-valued floats lose '.0', everything is stripped, blank is None."""
    if x is None or (not isinstance(x, str) and pd.isna(x)):
        return None
    if isinstance(x, (float, np.floating)) and float(x).is_integer():
        return str(int(x))
    s = str(x).strip()
    return s or None


def _code_text(s: pd.Series) -> pd.Series:
    """Series of raw codes as text (object dtype, fresh 0..m-1 index), with None where missing or blank."""
    codes, uniq = pd.factorize(pd.Series(s).reset_index(drop=True))
    table = np.empty(len(uniq) + 1, dtype=object)
    for i, u in enumerate(uniq):
        table[i] = _one_code(u)
    table[-1] = None                                   # factorize marks NA as -1, which indexes this last slot
    return pd.Series(table[codes], dtype="object")


def _code_tables(cfg: Config, *, synthetic: bool = False) -> tuple[list[str], dict[str, int], set[str], set[str]]:
    """State names, code -> state index, unknown codes, lost codes, all as comparable text. Raises on overlaps."""
    d = cfg.to_dict()
    names = [s["name"] for s in d["states"]]
    to_state: dict[str, int] = {}
    for i, s in enumerate(d["states"]):
        codes = list(s.get("raw_codes") or [])
        if synthetic:
            codes.extend(s.get("synthetic_codes") or [])
        for c in codes:
            key = _one_code(c)
            if key is None:
                raise ConfigError(f"state {s['name']!r} has a blank raw code")
            if key in to_state:
                raise ConfigError(f"raw code {key!r} is listed for both {names[to_state[key]]!r} and {s['name']!r}")
            to_state[key] = i
    unknown = {k for k in (_one_code(c) for c in d.get("unknown_codes") or []) if k is not None}
    lost = {k for k in (_one_code(c) for c in d.get("lost_codes") or []) if k is not None}
    both = sorted(unknown & set(to_state))
    if both:
        raise ConfigError(f"code(s) {both} are listed both as a state and as unknown_codes")
    return names, to_state, unknown, lost


def map_raw_to_state(raw: pd.Series, nonresponse: pd.Series, cfg: Config, *, synthetic: bool = False) -> np.ndarray:
    """Raw status codes and non-response codes to state codes (int8). The mapping comes from config only.

    Rules, in this order, per record:
      * `nonresponse` in `lost_codes` -> LOST (-2);
      * `raw` in some `states[].raw_codes` -> that state's index;
      * `raw` in `unknown_codes`, or blank/NA -> MISSING (-1);
      * `raw` in none of the lists -> ConfigError (the config's code lists do not cover the data);
      * a record that is both a valid state and lost -> ValueError (contradictory, not resolved here).
    Codes are compared as text after stripping, and integer-valued floats are read as integers
    (11.0 == "11"), because a numeric column that holds NA is stored as float.
    """
    if len(raw) != len(nonresponse):
        raise ValueError(f"raw ({len(raw)}) and nonresponse ({len(nonresponse)}) must have the same length")
    _, to_state, unknown, lost_codes = _code_tables(cfg, synthetic=synthetic)
    if synthetic and not lost_codes:
        lost_codes = {SYNTHETIC_LOST_CODE}
    r = _code_text(raw)
    nr = _code_text(nonresponse)
    code = r.map(to_state)
    is_state = code.notna().to_numpy()
    is_unknown = r.isin(list(unknown)).to_numpy()
    is_lost = nr.isin(list(lost_codes)).to_numpy()
    unmapped = r.notna().to_numpy() & ~is_state & ~is_unknown
    if unmapped.any():
        top = r[unmapped].value_counts().head(10)
        shown = ", ".join(f"{k!r} x{v}" for k, v in top.items())
        raise ConfigError(
            f"{int(unmapped.sum())} record(s) have a raw status code that is in none of states[].raw_codes or "
            f"unknown_codes: {shown}. Add each code to the right list in config.yaml after checking the "
            "questionnaire for this release; the pipeline will not guess.")
    clash = is_state & is_lost
    if clash.any():
        raise ValueError(f"{int(clash.sum())} record(s) carry both a valid status and a lost-to-follow-up code; "
                         "resolve this in the data before building trajectories")
    out = np.full(len(r), MISSING, dtype=np.int8)
    out[is_state] = code[is_state].astype(np.int64).to_numpy()
    out[is_lost] = LOST
    return out


# ---------------------------------------------------------------------------------------------
# Long panel -> TrajectoryData
# ---------------------------------------------------------------------------------------------
def _is_synthetic(long_df: pd.DataFrame) -> bool:
    flag = long_df.attrs.get("is_synthetic")
    if "is_synthetic" in long_df.columns:
        col = long_df["is_synthetic"].astype(bool)
        if col.nunique() > 1:
            raise ValueError("the long panel mixes synthetic and real rows; they must never be combined")
        col_val = bool(col.iloc[0])
        if flag is not None and bool(flag) != col_val:
            raise ValueError("long_df.attrs['is_synthetic'] and the 'is_synthetic' column disagree")
        return col_val
    return bool(flag) if flag is not None else False


def _person_attributes(long_df: pd.DataFrame, person_code: np.ndarray, t: np.ndarray, ids: np.ndarray) -> pd.DataFrame:
    """One row per person (order of `ids`): the first non-missing value in time order of each attribute column."""
    cols = [c for c in ATTRIBUTE_COLUMNS if c in long_df.columns]
    n = len(ids)
    frame = pd.DataFrame({"_p": person_code, "_t": t})
    for c in cols:
        frame[c] = long_df[c].to_numpy()
    grouped = frame.sort_values(["_p", "_t"], kind="mergesort").groupby("_p", sort=True)
    out = pd.DataFrame({"person_id": ids.astype(str)})
    conflicts: dict[str, int] = {}
    for c in cols:
        out[c] = grouped[c].first().reindex(range(n)).to_numpy()
        if c == "age":
            out[c] = pd.to_numeric(out[c], errors="coerce").astype("float64")
            conflicts[c] = int(((grouped[c].max() - grouped[c].min()) > 0).sum())
        else:
            conflicts[c] = int((grouped[c].nunique(dropna=True) > 1).sum())
    out.attrs.update({
        "first_nonmissing_rule": "value at the person's earliest record with a non-missing value",
        "n_persons": int(n), "n_conflicting": conflicts,
        "n_missing": {c: int(out[c].isna().sum()) for c in cols},
    })
    return out


def _person_weights(long_df: pd.DataFrame, cfg: Config, synthetic: bool, person_code: np.ndarray,
                    t: np.ndarray, n: int) -> tuple[np.ndarray | None, dict[str, Any]]:
    """Verified survey weight per person, or None, with a note on why."""
    d = cfg.to_dict()
    if synthetic:
        usable = "weight" in long_df.columns and long_df["weight"].notna().any()
        why = "synthetic weight column" if usable else "no weight column in the synthetic panel"
    else:
        configured = (d.get("data", {}).get("schema", {}) or {}).get("weight")
        verified = bool(d.get("data", {}).get("verified"))
        usable = bool(configured) and verified
        why = ("verified weight column" if usable else
               "weights not attached: data.schema.weight is unset or data.verified is false")
    if not usable:
        return None, {"weights_attached": False, "weights_note": why}
    if "weight" not in long_df.columns:
        raise ValueError("weights are configured but the long panel has no 'weight' column")
    w = pd.DataFrame({"_p": person_code, "_t": t, "w": pd.to_numeric(long_df["weight"], errors="coerce").to_numpy()})
    g = w.sort_values(["_p", "_t"], kind="mergesort").groupby("_p", sort=True)["w"]
    first = g.first().reindex(range(n))
    if first.isna().any():
        raise ValueError(f"{int(first.isna().sum())} person(s) have no non-missing survey weight; weights are "
                         "configured as verified, so this must be resolved rather than filled")
    varies = int(((g.max() - g.min()) > 0).sum())
    return first.to_numpy(dtype=np.float64), {
        "weights_attached": True, "weights_note": why,
        "weight_rule": "weight at the person's earliest record with a non-missing weight",
        "n_weight_varies_within_person": varies,
    }


def build_trajectories(long_df: pd.DataFrame, cfg: Config) -> TrajectoryData:
    """Long panel (one row per person and time point) to `TrajectoryData` (one row of states per person).

    Needs columns `person_id`, `t` (integer 0..T-1, T = time.n_points) and `raw_status`; a
    `nonresponse_code` column is used if present. Raises ValueError for an empty panel, a missing
    column, a non-integer or out-of-window `t`, a missing person id, or a duplicated (person, t).
    Persons are the sorted unique ids (string order); (person, t) pairs with no record are MISSING.
    `attrs` holds the same columns as `preprocessing.build_attributes`; `weights` follows the rule in
    the module docstring. `meta` counts records by kind so the report can say how much was unknown or lost.
    """
    d = cfg.to_dict()
    T = int(d["time"]["n_points"])
    labels = list(d["time"]["labels"])
    names = [s["name"] for s in d["states"]]
    need = [c for c in ("person_id", "t", "raw_status") if c not in long_df.columns]
    if need:
        raise ValueError(f"long panel is missing column(s) {need}")
    if len(long_df) == 0:
        raise ValueError("long panel has no rows")
    if long_df["person_id"].isna().any():
        raise ValueError("long panel has records without a person_id")
    t_num = pd.to_numeric(long_df["t"], errors="coerce")
    if t_num.isna().any() or not np.all(t_num.to_numpy() == np.round(t_num.to_numpy())):
        raise ValueError("column 't' must hold whole numbers (time index 0..T-1) with no blanks")
    t = t_num.to_numpy().astype(np.int64)
    if t.min() < 0 or t.max() >= T:
        raise ValueError(f"column 't' has values outside 0..{T - 1} (time.n_points={T}); apply "
                         "preprocessing.select_observation_window first, records are never dropped silently here")
    pid = long_df["person_id"].astype(str).to_numpy()
    ids, person_code = np.unique(pid, return_inverse=True)
    person_code = person_code.reshape(-1)
    n = len(ids)
    n_dup = int(pd.DataFrame({"p": person_code, "t": t}).duplicated().sum())
    if n_dup:
        raise ValueError(f"{n_dup} duplicated (person, time) record(s); a person has one record per time point")

    nonresp = long_df["nonresponse_code"] if "nonresponse_code" in long_df.columns else pd.Series(
        [None] * len(long_df), index=long_df.index, dtype="object")
    synthetic = _is_synthetic(long_df)
    mapped = map_raw_to_state(long_df["raw_status"], nonresp, cfg, synthetic=synthetic)
    states = np.full((n, T), MISSING, dtype=np.int8)
    states[person_code, t] = mapped
    recorded_mask = np.zeros((n, T), dtype=bool)
    recorded_mask[person_code, t] = True

    attrs = _person_attributes(long_df, person_code, t, ids)
    weights, wmeta = _person_weights(long_df, cfg, synthetic, person_code, t, n)
    meta: dict[str, Any] = {
        "source": "build_trajectories",
        "n_records": int(len(long_df)),
        "n_persons": int(n),
        "n_cells": int(n * T),
        "n_cells_without_record": int(n * T - len(long_df)),
        "records_by_kind": {"state": int((mapped >= 0).sum()), "missing_or_unknown": int((mapped == MISSING).sum()),
                            "lost": int((mapped == LOST).sum())},
        "lost_codes_status": str(d.get("lost_codes_status", "unresolved")),
        "mapping_rules": "lost_codes -> LOST; states[].raw_codes -> state; unknown_codes or blank -> MISSING; "
                         "any other code raises; a pair with no record is MISSING",
        **wmeta,
    }
    return TrajectoryData(ids=ids.astype(object), states=states, time_labels=labels, state_names=names,
                          attrs=attrs, weights=weights, is_synthetic=synthetic, meta=meta, recorded_mask=recorded_mask)


# ---------------------------------------------------------------------------------------------
# Descriptive summaries
# ---------------------------------------------------------------------------------------------
def trajectory_summary(td: TrajectoryData) -> pd.DataFrame:
    """One row per time point: how many are observed, missing, lost, and the state mix among the observed.

    Columns: time_label, n_individuals, n_observed, n_missing, n_lost, share_observed, then for each
    state `n_<state>` and `share_<state>` (share of the OBSERVED at that time point). If survey weights
    exist, `wshare_<state>` gives the survey-weighted share of the observed. Shares of observed
    ignore the unobserved, so read them next to `share_observed`.
    """
    S, n = td.states, td.n
    rows = []
    for t in range(td.T):
        col = S[:, t]
        obs = col >= 0
        n_obs = int(obs.sum())
        row: dict[str, Any] = {
            "time_label": td.time_labels[t], "n_individuals": n, "n_observed": n_obs,
            "n_missing": int((col == MISSING).sum()), "n_lost": int((col == LOST).sum()),
            "share_observed": n_obs / n if n else float("nan"),
        }
        w_obs = float(td.weights[obs].sum()) if td.weights is not None else 0.0
        for k, name in enumerate(td.state_names):
            m = col == k
            row[f"n_{name}"] = int(m.sum())
            row[f"share_{name}"] = float(m.sum() / n_obs) if n_obs else float("nan")
            if td.weights is not None:
                row[f"wshare_{name}"] = float(td.weights[m].sum() / w_obs) if w_obs > 0 else float("nan")
        rows.append(row)
    return pd.DataFrame(rows)


def transition_matrix(td: TrajectoryData, weighted: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """(probabilities, counts), both (K,K): moves from the state at time t (row) to the state at t+1 (column).

    Only adjacent time points that are BOTH observed count: a step over a gap is not a one-step move,
    so it is skipped. `counts` is float64: person counts, or survey-weight totals when `weighted=True`
    (raises ValueError if the data have no verified weights). A row with no transitions has NaN
    probabilities (undefined, not zero); the distance module decides how to treat it.
    """
    K = len(td.state_names)
    S = td.states
    if weighted and td.weights is None:
        raise ValueError("weighted=True needs verified survey weights, but this data has none")
    if td.T < 2:
        counts = np.zeros((K, K))
    else:
        a, b = S[:, :-1], S[:, 1:]
        ok = (a >= 0) & (b >= 0)
        w = np.broadcast_to((td.weights if weighted else np.ones(td.n))[:, None], a.shape)[ok]
        flat = a[ok].astype(np.int64) * K + b[ok].astype(np.int64)
        counts = np.bincount(flat, weights=w, minlength=K * K).reshape(K, K).astype(np.float64)
    rows = counts.sum(axis=1, keepdims=True)
    probs = np.full((K, K), np.nan)
    np.divide(counts, rows, out=probs, where=rows > 0)
    return probs, counts


def sequence_strings(td: TrajectoryData, idx: np.ndarray | None = None) -> list[str]:
    """Each trajectory as a string: state k is the k-th capital letter (A, B, C, ...), `?` is MISSING, `#` is LOST.

    Example with 4 time points: `DDAA` (state 3 twice, then state 0 twice), `DD?A` (one unknown point).
    `idx` selects individuals (integer array or boolean mask) in the order given. Needs at most 26 states.
    The letter-to-name key is `td.state_names` in order.
    """
    K = len(td.state_names)
    if K > 26:
        raise ValueError(f"sequence_strings supports at most 26 states, got {K}")
    sel = _select(idx, td.n)
    lut = np.array([chr(65 + k) for k in range(K)] + [LOST_CHAR, MISSING_CHAR])      # code -2 -> LOST_CHAR, -1 -> MISSING_CHAR
    return ["".join(lut[row]) for row in td.states[sel].astype(np.int64)]


def complete_case_mask(td: TrajectoryData, min_points: int) -> np.ndarray:
    """Boolean (n,): persons with at least `min_points` OBSERVED time points (states 0..K-1; MISSING and LOST do not count).

    Raises ValueError unless min_points is a whole number in 0..T. This is the same rule as
    `preprocessing.apply_eligibility`.
    """
    if int(min_points) != min_points or not 0 <= min_points <= td.T:
        raise ValueError(f"min_points must be a whole number in 0..{td.T}, got {min_points!r}")
    return (td.states >= 0).sum(axis=1) >= int(min_points)


# ---------------------------------------------------------------------------------------------
# Collapsing identical trajectories
# ---------------------------------------------------------------------------------------------
def _select(idx: Any, n: int) -> np.ndarray:
    """int64 positions from None (all), a boolean mask or an integer array, validated against n."""
    if idx is None:
        return np.arange(n, dtype=np.int64)
    arr = np.asarray(idx)
    if arr.dtype == bool:
        if arr.shape != (n,):
            raise ValueError(f"boolean mask must have shape ({n},), got {arr.shape}")
        return np.flatnonzero(arr).astype(np.int64)
    arr = arr.astype(np.int64, copy=False).ravel()
    if arr.size and (arr.min() < 0 or arr.max() >= n):
        raise IndexError(f"index out of range for {n} individuals")
    return arr


def _is_discrete(td: TrajectoryData, col: str) -> bool:
    """Categorical or discrete code column? Non-numeric, boolean, or declared by `encode_attributes`."""
    s = td.attrs[col]
    declared = set(td.attrs.attrs.get("categorical_columns", [])) | set(td.attrs.attrs.get("encodings", {}))
    return (not pd.api.types.is_numeric_dtype(s)) or pd.api.types.is_bool_dtype(s) or col in declared


def _attribute_inputs(td: TrajectoryData, cfg: Config | None, sel: np.ndarray) -> tuple[list[str], np.ndarray | None, list[str]]:
    """(columns, object array (m,A), numeric columns) for `distance.attribute_inputs`, or ([], None, [])."""
    if cfg is None:
        return [], None, []
    cols = [str(c) for c in (cfg.get("distance.attribute_inputs") or [])]
    if not cols:
        return [], None, []
    assert_no_protected(cols, cfg, "trajectory collapse (distance.attribute_inputs)")
    absent = [c for c in cols if c not in td.attrs.columns]
    if absent:
        raise ValueError(f"distance.attribute_inputs names column(s) {absent} that are not in the attributes")
    numeric = [c for c in cols if not _is_discrete(td, c)]
    values = np.empty((len(sel), len(cols)), dtype=object)
    for j, c in enumerate(cols):
        s = td.attrs[c].iloc[sel]
        v = s.astype(object).to_numpy().copy()
        if c not in numeric:
            v[pd.isna(v)] = MISSING_LABEL                 # a missing category is its own explicit category
        values[:, j] = v
    return cols, values, numeric


def collapse_trajectories(td: TrajectoryData, cfg: Config, idx: np.ndarray | None = None) -> CollapsedTrajectories:
    """Collapse individuals with identical distance inputs into unique rows with a count (`freq`).

    Key = states plus `distance.attribute_inputs`: empty -> states only; all categorical or discrete ->
    the attributes join the key and are kept in `unique_attrs` (a missing category is the label
    "<missing>"); any numeric attribute -> CollapseRefused (the orchestrator then subsamples). Protected
    attributes in the inputs raise FairnessError. `idx` selects individuals (mask or integer positions);
    `inverse[i]` is the unit of individual `idx[i]`. Unique rows come in lexicographic order of the key,
    so the result is deterministic. `freq` counts individuals and is never a survey weight.
    """
    sel = _select(idx, td.n)
    if sel.size == 0:
        raise ValueError("cannot collapse an empty selection")
    cols, values, numeric = _attribute_inputs(td, cfg, sel)
    if numeric:
        raise CollapseRefused(f"distance.attribute_inputs contains numeric attribute(s) {numeric}: nearly every "
                              "person would be unique, so collapsing cannot reduce the problem; subsample instead")
    parts = [td.states[sel].astype(np.int64)]
    for j in range(len(cols)):
        codes, _ = pd.factorize(pd.Series(values[:, j], dtype="object"), sort=False)
        parts.append(codes.astype(np.int64).reshape(-1, 1))
    key = np.concatenate(parts, axis=1)
    uniq, first, inverse = np.unique(key, axis=0, return_index=True, return_inverse=True)
    inverse = inverse.reshape(-1)
    return CollapsedTrajectories(
        unique_states=uniq[:, :td.T].astype(np.int8),
        freq=np.bincount(inverse, minlength=len(uniq)),
        inverse=inverse,
        attr_cols=cols,
        unique_attrs=None if not cols else values[first],
    )


def identity_collapse(td: TrajectoryData, idx: np.ndarray | None = None, cfg: Config | None = None) -> CollapsedTrajectories:
    """Every selected individual is its own unit: freq = 1, inverse = arange(m), rows in the order of `idx`.

    Used by subsampling, where identical rows are NOT merged. If `cfg` is given and
    `distance.attribute_inputs` is non-empty, the attributes are carried in `attr_cols` and
    `unique_attrs` (numeric columns keep their values, so a Gower-type distance can use them; a missing
    category is "<missing>"). Without `cfg`, no attributes are carried, so pass `cfg` whenever
    attribute inputs are configured; otherwise they would be silently absent from the distance.
    """
    sel = _select(idx, td.n)
    cols, values, _ = _attribute_inputs(td, cfg, sel)
    m = len(sel)
    return CollapsedTrajectories(
        unique_states=td.states[sel].copy(), freq=np.ones(m, dtype=np.int64), inverse=np.arange(m, dtype=np.int64),
        attr_cols=cols, unique_attrs=None if not cols else values,
    )


def expand_labels(col: CollapsedTrajectories, unit_labels: np.ndarray) -> np.ndarray:
    """Labels per unit to labels per individual: `unit_labels[col.inverse]`. Raises ValueError on a wrong length."""
    ul = np.asarray(unit_labels)
    if ul.shape != (col.u,):
        raise ValueError(f"unit_labels must have shape ({col.u},), got {ul.shape}")
    return ul[col.inverse]


# ---------------------------------------------------------------------------------------------
# Smoke demo
# ---------------------------------------------------------------------------------------------
def _config_with(cfg: Config, **distance: Any) -> Config:
    d = cfg.to_dict()
    return Config({**d, "distance": {**d["distance"], **distance}}, cfg.root)


def _demo() -> int:
    from .config import FairnessError
    from .synthetic_data import generate_synthetic

    cfg = load_config()
    d = cfg.to_dict()
    print("SYNTHETIC DEMONSTRATION - NOT PLFS RESULTS")
    df, truth = generate_synthetic(cfg, n=600, seed_offset=21)
    td = build_trajectories(df, cfg)
    K, T = len(td.state_names), td.T

    # Independent re-derivation, row by row, from the config code table (slow but obviously correct).
    code = {str((s.get("raw_codes") or s.get("synthetic_codes") or [None])[0]): i
            for i, s in enumerate(d["states"])}
    code.pop("None", None)
    unk = str(d["unknown_codes"][0])
    lost_c = str(d["lost_codes"][0]) if d["lost_codes"] else SYNTHETIC_LOST_CODE
    pos = {pid: i for i, pid in enumerate(sorted(df["person_id"].unique()))}
    ref = np.full((len(pos), T), MISSING, dtype=np.int64)
    for p, t, r, nr in zip(df["person_id"], df["t"], df["raw_status"], df["nonresponse_code"]):
        if nr is not None and str(nr) == lost_c:
            ref[pos[p], t] = LOST
        elif r is not None and str(r) != unk:
            ref[pos[p], t] = code[str(r)]

    summ = trajectory_summary(td)
    print(summ[["time_label", "n_observed", "n_missing", "n_lost", "share_observed"]].round(3).to_string(index=False))
    probs, counts = transition_matrix(td)
    seqs = sequence_strings(td, np.arange(5))
    print(f"first sequences: {seqs}  (letters A..{chr(64 + K)} = {td.state_names})")

    # Hand-built data with known answers for transitions, collapse and sequence strings.
    S = np.array([[0, 1, 1, 2], [0, 1, 1, 2], [0, MISSING, 1, 2], [2, 2, LOST, LOST], [1, 1, 1, 1], [1, 1, 1, 1]], dtype=np.int8)
    attrs = pd.DataFrame({"sector": ["U", "R", "R", "U", "R", "R"], "age": [20.0, 21, 22, 23, 24, 25],
                          "sex": list("MFMFMF")})
    names3 = ["a", "b", "c"]
    hand = TrajectoryData(np.array([f"h{i}" for i in range(6)], dtype=object), S, ["t0", "t1", "t2", "t3"], names3,
                          attrs, np.array([1.0, 2, 3, 4, 5, 6]), True, {"source": "hand-built"})
    hp, hc = transition_matrix(hand)
    hpw, hcw = transition_matrix(hand, weighted=True)
    col0 = collapse_trajectories(hand, cfg)                                              # states only
    cfg_sec = _config_with(cfg, attribute_inputs=["sector"])
    col_sec = collapse_trajectories(hand, cfg_sec)
    cfg_age = _config_with(cfg, attribute_inputs=["age"])
    cfg_sex = _config_with(cfg, attribute_inputs=["sex"])
    ident = identity_collapse(hand, np.array([5, 0, 3]))
    ident_age = identity_collapse(hand, None, cfg_age)
    sub = collapse_trajectories(hand, cfg, idx=np.array([0, 1, 4, 5]))

    nowt = TrajectoryData(hand.ids, hand.states, hand.time_labels, hand.state_names, hand.attrs, None, True)

    def raises(exc: type, fn: Any) -> bool:
        try:
            fn()
        except exc:
            return True
        except Exception:
            return False
        return False

    one = df.iloc[:6].copy()
    bad_code = one.copy(); bad_code.loc[bad_code.index[0], "raw_status"] = "NOT_A_CODE"
    clash = one.copy(); clash.loc[clash.index[0], "nonresponse_code"] = lost_c; clash.loc[clash.index[0], "raw_status"] = str(d["states"][0]["raw_codes"][0])
    dup = pd.concat([one, one.iloc[:1]], ignore_index=True)
    far = one.copy(); far.loc[far.index[0], "t"] = T
    mixed = df.iloc[:6].copy(); mixed["is_synthetic"] = [True, True, True, False, False, False]
    float_codes = Config({**d, "states": [{**s, "raw_codes": [float(i + 1)]} for i, s in enumerate(d["states"])],
                          "unknown_codes": [99], "lost_codes": [97], "lost_codes_status": "documented"}, cfg.root)
    mapped = map_raw_to_state(pd.Series([1.0, 2.0, np.nan, 99.0, "  3 ", None]), pd.Series([None, None, None, None, None, 97.0]), float_codes)

    checks = {
        "ids are the sorted unique person ids": list(td.ids) == sorted(df["person_id"].unique()) and td.n == truth.params["n"],
        "states equal the independent row-by-row mapping": np.array_equal(td.states.astype(np.int64), ref),
        "cells without a record are MISSING": int((td.states == MISSING).sum()) >= int(td.meta["n_cells_without_record"]),
        "record counts add up": sum(td.meta["records_by_kind"].values()) == len(df) and td.meta["n_cells"] - td.meta["n_cells_without_record"] == len(df),
        "attrs aligned to ids": list(td.attrs["person_id"]) == list(td.ids) and td.attrs.shape[0] == td.n,
        "synthetic flag and weights carried": td.is_synthetic and td.weights is not None and td.weights.shape == (td.n,),
        "summary rows add up": ((summ["n_observed"] + summ["n_missing"] + summ["n_lost"]) == td.n).all(),
        "transition counts equal adjacent observed pairs": counts.sum() == sum(int(((td.states[:, t] >= 0) & (td.states[:, t + 1] >= 0)).sum()) for t in range(T - 1)),
        "transition rows sum to 1 (or are NaN)": all(np.isnan(r).all() or abs(r.sum() - 1) < 1e-12 for r in probs),
        "hand counts: gap is skipped, lost is skipped": hc[0, 1] == 2 and hc[1, 1] == 8 and hc[1, 2] == 3 and hc[2, 2] == 1 and hc.sum() == 14,
        "hand weighted counts use person weights": abs(hcw[0, 1] - (1 + 2)) < 1e-12 and abs(hcw[1, 2] - (1 + 2 + 3)) < 1e-12 and abs(hcw[2, 2] - 4) < 1e-12,
        "weighted transitions without weights raise": raises(ValueError, lambda: transition_matrix(nowt, weighted=True)),
        "sequence strings use letters, ? and #": sequence_strings(hand) == ["ABBC", "ABBC", "A?BC", "CC##", "BBBB", "BBBB"],
        "sequence strings honour idx": sequence_strings(hand, np.array([3, 0])) == ["CC##", "ABBC"],
        "complete_case_mask matches observed counts": complete_case_mask(hand, 4).tolist() == [True, True, False, False, True, True]
                                                       and complete_case_mask(hand, 2).all(),
        "complete_case_mask rejects bad thresholds": raises(ValueError, lambda: complete_case_mask(hand, 5)) and raises(ValueError, lambda: complete_case_mask(hand, 1.5)),
        "collapse (states only): 4 units, freq 2,1,1,2": col0.u == 4 and sorted(col0.freq.tolist()) == [1, 1, 2, 2] and col0.attr_cols == [],
        "collapse invariants": np.array_equal(col0.unique_states[col0.inverse], hand.states) and col0.n == hand.n,
        "collapse is exact on a real-size panel": (lambda c: np.array_equal(c.unique_states[c.inverse], td.states)
                                                   and c.freq.sum() == td.n)(collapse_trajectories(td, cfg)),
        "collapse with a categorical attribute splits units": col_sec.u == 5 and col_sec.attr_cols == ["sector"]
                                                              and col_sec.unique_attrs.shape == (5, 1),
        "attribute key is exact": all((col_sec.unique_attrs[col_sec.inverse, 0] == hand.attrs["sector"].to_numpy())),
        "numeric attribute input -> CollapseRefused": raises(CollapseRefused, lambda: collapse_trajectories(hand, cfg_age)),
        "protected attribute input -> FairnessError": raises(FairnessError, lambda: collapse_trajectories(hand, cfg_sex))
                                                       and raises(FairnessError, lambda: identity_collapse(hand, None, cfg_sex)),
        "collapse on a subset maps to idx positions": sub.n == 4 and sub.u == 2 and sub.freq.tolist() == [2, 2]
                                                      and np.array_equal(sub.unique_states[sub.inverse], hand.states[[0, 1, 4, 5]]),
        "identity collapse keeps order, freq 1": ident.u == 3 and (ident.freq == 1).all() and np.array_equal(ident.inverse, [0, 1, 2])
                                                 and np.array_equal(ident.unique_states, hand.states[[5, 0, 3]]),
        "identity collapse carries numeric attributes when cfg is given": ident_age.attr_cols == ["age"]
                                                                          and ident_age.unique_attrs.shape == (6, 1)
                                                                          and ident_age.unique_attrs[2, 0] == 22.0,
        "identity collapse with no attribute inputs carries none": ident.attr_cols == [] and ident.unique_attrs is None,
        "expand_labels = unit_labels[inverse]": np.array_equal(expand_labels(col0, np.arange(col0.u) * 10), (np.arange(col0.u) * 10)[col0.inverse])
                                                and raises(ValueError, lambda: expand_labels(col0, np.arange(col0.u + 1))),
        "unlisted raw code raises ConfigError": raises(ConfigError, lambda: build_trajectories(bad_code, cfg)),
        "valid status plus lost code raises": raises(ValueError, lambda: build_trajectories(clash, cfg)),
        "duplicate (person, t) raises": raises(ValueError, lambda: build_trajectories(dup, cfg)),
        "t outside the window raises": raises(ValueError, lambda: build_trajectories(far, cfg)),
        "mixed synthetic and real rows raise": raises(ValueError, lambda: build_trajectories(mixed, cfg)),
        "float codes, blanks, unknown and lost map correctly": mapped.tolist() == [0, 1, MISSING, MISSING, 2, LOST],
        "mapping dtype is int8": mapped.dtype == np.int8 and td.states.dtype == np.int8,
    }
    for name, ok in checks.items():
        print(f"  demo check [{'ok' if ok else 'FAILED'}]: {name}")
    if not all(checks.values()):
        return 1
    print(f"Demo checks passed ({len(checks)}). All data above is SYNTHETIC or hand-built.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_demo())
