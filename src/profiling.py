"""Describe the pathways: how big they are, what they look like over time, and who is in them.

Why this file exists: a clustering is only useful to the programme if each group can be read as a story ("most of
this group were unemployed at the first visit and in wage work by the last"). This module turns labelled
trajectories into plain descriptive tables, and gives each pathway a name that is built from those tables and from
nothing else. It runs on EXPANDED individuals (every person has a label), never on collapsed units, so the
attribute columns of the trainees are available.

Design choices worth defending in a viva:
  * Profiling is descriptive, never inferential. No test, p-value or "driver" claim is made: with k pathways and
    several attributes, any comparison would be a multiple-comparison fishing trip, and the pathways were chosen
    to differ on state sequences in the first place. Tables carry the observed counts so a reader can judge noise.
  * The attributes shown are exactly `profiling.permitted_vars` (the list the data-use assessment allows) and no
    others. Protected roles (sex, social group, religion) MAY appear here, because describing who is in a pathway
    is the fairness check; they are blocked only as clustering inputs (config and distances enforce that).
    Identifier roles (person_id, household_id) are refused: they identify people and describe nobody.
  * State shares use observed cells only. A MISSING or LOST cell is reported separately and is never turned into a
    state. A pathway that is mostly unobserved at one visit says so (`share_missing_cells`, `share_lost_cells`).
  * "Modal state" at a visit is the most common observed state among the pathway's members at that visit (ties go
    to the lower state index). It is a summary, not a member: use the medoid for a real sequence.
  * Weights: survey weights are used only when `profiling.weighted` is true, and then only if the trajectory data
    carry verified weights (otherwise ConfigError, never a silent fallback to unweighted). Counts are never
    weighted. Weighted prevalence is NaN, with a note, when no verified weights exist. Medians are always
    unweighted and the column name says so; weighted medians are not offered.
  * Names (`name_pathways`) come from three computed numbers only: the modal state at the first visit, the modal
    state at the last visit, and the share of members whose observed states never change. The cut-off
    `STABLE_MIN_SHARE` (0.5) is PROPOSED. A name is a label for a pattern, not an explanation of why it happened.
    The same names are used in the report and the dashboard; nothing is renamed by hand.

Limits: profiles describe the sample the clustering was run on; with about four monthly visits the "first" and
"last" visit are close in time, so a name such as "unemployed seeking to wage employment" describes a short
window, not a career. Small pathways give noisy attribute shares; read `n_individuals` first.

Dependency rule: imports `config` and the shared types only. The smoke demo imports later-delivered helpers
(`synthetic_data`, `preprocessing`, `trajectories`) inside the demo function only.

Run the smoke demo with:  python -m src.profiling
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from . import LOST, MISSING, TrajectoryData
from .config import Config, ConfigError, load_config

__all__ = [
    "STABLE_MIN_SHARE",
    "pathway_prevalence",
    "permitted_profile_vars",
    "pathway_profiles",
    "state_composition_by_time",
    "name_pathways",
]

STABLE_MIN_SHARE = 0.5          # PROPOSED: a pathway is called "stable" if at least this share of members never change state
_IDENTIFIER_ROLES = ("person_id", "household_id")
_MAX_LEVELS = 30                # a categorical attribute with more levels is an identifier in disguise


# ---------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------
def _check_labels(td: TrajectoryData, full_labels: Any) -> tuple[np.ndarray, np.ndarray]:
    """Return (labels as int array, sorted pathway ids). Every individual must have a non-negative label."""
    lab = np.asarray(full_labels)
    if lab.ndim != 1 or lab.shape[0] != td.n:
        raise ValueError(f"full_labels must have one entry per individual ({td.n}), got shape {lab.shape}")
    if not np.issubdtype(lab.dtype, np.integer):
        if not np.all(np.isfinite(lab.astype(np.float64))) or np.any(lab != np.round(lab)):
            raise ValueError("full_labels must be integers")
    lab = lab.astype(np.int64)
    if lab.size == 0 or lab.min() < 0:
        raise ValueError("every individual needs a pathway label >= 0 (unassigned individuals cannot be profiled)")
    return lab, np.unique(lab)


def _weights_for_profiles(td: TrajectoryData, cfg: Config) -> tuple[np.ndarray, bool]:
    """(weights, weighted). Weighted only if profiling.weighted is true; then verified weights are mandatory."""
    if not bool(cfg.profiling.weighted):
        return np.ones(td.n), False
    if td.weights is None:
        raise ConfigError("profiling.weighted is true but the trajectory data carry no verified weights")
    w = np.asarray(td.weights, dtype=np.float64)
    if w.shape != (td.n,) or not np.all(np.isfinite(w)) or np.any(w < 0) or w.sum() <= 0:
        raise ConfigError("profiling.weighted is true but the weights are not finite, non-negative and positive in total")
    return w, True


def _wshare(mask: np.ndarray, denom_mask: np.ndarray, w: np.ndarray) -> float:
    """Weighted share of `mask` among `denom_mask` (NaN when the denominator is empty)."""
    d = float(w[denom_mask].sum())
    return float(w[mask & denom_mask].sum() / d) if d > 0 else float("nan")


def _pretty(name: str) -> str:
    return name.replace("_", " ")


# ---------------------------------------------------------------------------------------------
# Prevalence
# ---------------------------------------------------------------------------------------------
def pathway_prevalence(td: TrajectoryData, full_labels: Any) -> pd.DataFrame:
    """One row per pathway: pathway, n_individuals, prevalence_unweighted, prevalence_weighted, weight_note.

    `prevalence_unweighted` is the share of individuals. `prevalence_weighted` is the share of the summed survey
    weight, and is NaN (with a note) when `td.weights` is None (no verified weight) or not usable. Counts are never
    weighted. Raises ValueError for labels of the wrong length or negative labels.
    """
    lab, ids = _check_labels(td, full_labels)
    counts = np.array([(lab == p).sum() for p in ids], dtype=np.int64)
    prev = counts / float(td.n)
    nan = float("nan")
    note = "no verified survey weight: weighted prevalence not reported"
    wprev = np.full(len(ids), nan)
    if td.weights is not None:
        w = np.asarray(td.weights, dtype=np.float64)
        if w.shape == (td.n,) and np.all(np.isfinite(w)) and np.all(w >= 0) and w.sum() > 0:
            wprev = np.array([w[lab == p].sum() for p in ids]) / float(w.sum())
            note = "weighted by the verified survey weight; counts are unweighted"
        else:
            note = "survey weights are present but not usable (non-finite, negative or all zero): weighted prevalence not reported"
    return pd.DataFrame({"pathway": ids.astype(np.int64), "n_individuals": counts, "prevalence_unweighted": prev,
                         "prevalence_weighted": wprev, "weight_note": note})


# ---------------------------------------------------------------------------------------------
# Attributes
# ---------------------------------------------------------------------------------------------
def permitted_profile_vars(cfg: Config) -> list[str]:
    """The attributes that may be shown per pathway: `profiling.permitted_vars`, in order, without duplicates.

    The list is driven by docs/DATA_USE_ASSESSMENT.md. Protected roles are allowed here (describing who is in a
    pathway is the fairness check); identifier roles are refused with ConfigError. An empty list means no
    attribute profiling yet.
    """
    out: list[str] = []
    for v in cfg.profiling.permitted_vars:
        v = str(v)
        if v in _IDENTIFIER_ROLES:
            raise ConfigError(f"profiling.permitted_vars may not contain the identifier role {v!r}")
        if v not in out:
            out.append(v)
    return out


def _attribute_columns(td: TrajectoryData, mask: np.ndarray, w: np.ndarray, variables: list[str],
                       levels: dict[str, list[str]]) -> dict[str, float]:
    """Attribute statistics of the members selected by `mask` (numeric: n_missing, mean, median; categorical: n_missing, shares)."""
    out: dict[str, float] = {}
    wp = w[mask]
    for v in variables:
        col = td.attrs[v].iloc[np.flatnonzero(mask)]
        if v in levels:                                          # categorical
            s = col.astype(object).where(col.notna(), None)
            have = np.array([x is not None for x in s], dtype=bool)
            txt = np.array([str(x) if x is not None else "" for x in s], dtype=object)
            out[f"{v}__n_missing"] = float((~have).sum())
            den = float(wp[have].sum())
            for lev in levels[v]:
                out[f"{v}={lev}"] = float(wp[have & (txt == lev)].sum() / den) if den > 0 else float("nan")
        else:                                                    # numeric
            x = pd.to_numeric(col, errors="coerce").to_numpy(dtype=np.float64)
            have = np.isfinite(x)
            out[f"{v}__n_missing"] = float((~have).sum())
            den = float(wp[have].sum())
            out[f"{v}__mean"] = float((wp[have] * x[have]).sum() / den) if den > 0 else float("nan")
            out[f"{v}__median_unweighted"] = float(np.median(x[have])) if have.any() else float("nan")
    return out


def _levels(td: TrajectoryData, variables: list[str]) -> dict[str, list[str]]:
    """Levels of each categorical permitted variable (numeric ones are absent from the result). Validates columns."""
    levels: dict[str, list[str]] = {}
    for v in variables:
        if v not in td.attrs.columns:
            raise ConfigError(f"profiling.permitted_vars lists {v!r}, which is not a column of the trainee attributes {list(td.attrs.columns)}")
        col = td.attrs[v]
        if pd.api.types.is_numeric_dtype(col) and not pd.api.types.is_bool_dtype(col):
            continue
        lev = sorted({str(x) for x in col.dropna()})
        if len(lev) > _MAX_LEVELS:
            raise ConfigError(f"attribute {v!r} has {len(lev)} levels (more than {_MAX_LEVELS}): it looks like an identifier, not a profile variable")
        levels[v] = lev
    return levels


# ---------------------------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------------------------
def pathway_profiles(td: TrajectoryData, full_labels: Any, cfg: Config) -> pd.DataFrame:
    """One row per pathway with the numbers `name_pathways` and the report use. All statistics are descriptive.

    State columns: `n_individuals`, `prevalence`, `mean_observed_visits`, `share_missing_cells`, `share_lost_cells`
    (shares of all cells), `share_<state>` (share of OBSERVED cells in each state), `modal_path` (modal observed state
    at each visit joined by " > ", "-" if nobody was observed), `modal_first`, `modal_last`, `employed_first`,
    `employed_last`, `employed_change` (share in `baseline.employed_states` among those observed at the first and the
    last visit), `share_stable` (members with at least 2 observed visits whose observed states never change, as a
    share of such members), `mean_switches` (average number of changes between consecutive observed visits).
    Attribute columns, for each variable in `permitted_profile_vars`: `<v>__n_missing`; numeric `<v>__mean` and
    `<v>__median_unweighted`; categorical `<v>=<level>` (share among members with a value). Weighted statistics only
    when `profiling.weighted` is true (verified weights required). `DataFrame.attrs` records `weighted` and
    `variables`. Raises ValueError for bad labels and ConfigError for unusable attribute or weight settings.
    """
    lab, ids = _check_labels(td, full_labels)
    w, weighted = _weights_for_profiles(td, cfg)
    variables = permitted_profile_vars(cfg)
    levels = _levels(td, variables)
    names = list(td.state_names)
    employed = [names.index(s) for s in cfg.baseline.employed_states]
    S, T = td.states, td.T
    rows = []
    for p in ids:
        m = lab == p
        Sp, wp = S[m], w[m]
        obs = Sp >= 0
        row: dict[str, Any] = {"pathway": int(p), "n_individuals": int(m.sum()), "prevalence": float(m.sum() / td.n)}
        wsum = float(wp.sum())
        row["mean_observed_visits"] = float((wp * obs.sum(axis=1)).sum() / wsum) if wsum > 0 else float("nan")
        cells = wsum * T
        row["share_missing_cells"] = float((wp[:, None] * (Sp == MISSING)).sum() / cells) if cells > 0 else float("nan")
        row["share_lost_cells"] = float((wp[:, None] * (Sp == LOST)).sum() / cells) if cells > 0 else float("nan")
        obs_w = float((wp[:, None] * obs).sum())
        for j, nm in enumerate(names):
            row[f"share_{nm}"] = float((wp[:, None] * (Sp == j)).sum() / obs_w) if obs_w > 0 else float("nan")
        modal: list[int] = []
        for t in range(T):
            cnt = np.array([(wp * (Sp[:, t] == j)).sum() for j in range(len(names))])
            modal.append(int(np.argmax(cnt)) if cnt.sum() > 0 else -1)
        row["modal_path"] = " > ".join(names[j] if j >= 0 else "-" for j in modal)
        row["modal_first"] = names[modal[0]] if modal[0] >= 0 else None
        row["modal_last"] = names[modal[-1]] if modal[-1] >= 0 else None
        emp = {}
        for tag, t in (("first", 0), ("last", T - 1)):
            ot = obs[:, t]
            isemp = np.isin(Sp[:, t], employed)
            emp[tag] = _wshare(isemp, ot, wp)
            row[f"employed_{tag}"] = emp[tag]
        row["employed_change"] = emp["last"] - emp["first"]
        n_obs = obs.sum(axis=1)
        last = np.full(len(Sp), -1, dtype=np.int64)
        switches = np.zeros(len(Sp))
        for t in range(T):
            o = obs[:, t]
            switches += (o & (last >= 0) & (Sp[:, t] != last))
            last = np.where(o, Sp[:, t], last)
        two = n_obs >= 2
        row["share_stable"] = _wshare(switches == 0, two, wp)
        row["mean_switches"] = float((wp[two] * switches[two]).sum() / wp[two].sum()) if wp[two].sum() > 0 else float("nan")
        row.update(_attribute_columns(td, m, w, variables, levels))
        rows.append(row)
    out = pd.DataFrame(rows)
    out.attrs["weighted"] = weighted
    out.attrs["variables"] = variables
    return out


def state_composition_by_time(td: TrajectoryData, full_labels: Any) -> pd.DataFrame:
    """Long table, one row per pathway x visit x state: how the pathway's members are spread over the states at each visit.

    Columns: pathway, time, time_label, state, n (individuals in that state at that visit), n_observed (individuals
    observed at that visit), n_missing, n_lost, share_of_observed (n / n_observed, NaN when nobody is observed).
    MISSING and LOST are counted in their own columns and are never states. Counts are unweighted. For the whole
    sample, call it with all labels equal to 0. Raises ValueError for bad labels.
    """
    lab, ids = _check_labels(td, full_labels)
    rows = []
    for p in ids:
        Sp = td.states[lab == p]
        for t in range(td.T):
            col = Sp[:, t]
            n_obs, n_mis, n_lost = int((col >= 0).sum()), int((col == MISSING).sum()), int((col == LOST).sum())
            for j, nm in enumerate(td.state_names):
                n = int((col == j).sum())
                rows.append({"pathway": int(p), "time": t, "time_label": td.time_labels[t], "state": nm, "n": n,
                             "n_observed": n_obs, "n_missing": n_mis, "n_lost": n_lost,
                             "share_of_observed": n / n_obs if n_obs > 0 else float("nan")})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------------------------
def name_pathways(profile_df: pd.DataFrame, cfg: Config) -> dict[int, str]:
    """Name every pathway from computed statistics only: `modal_first`, `modal_last` and `share_stable`.

    Pattern: "P<id>: stable <state>" if the first and last modal states are equal and `share_stable` is at least
    STABLE_MIN_SHARE (0.5, PROPOSED); "P<id>: varied, starting and ending in <state>" if they are equal but fewer
    members are stable; "P<id>: <first state> to <last state>" otherwise; "P<id>: not enough observations" if a
    modal state is undefined. The id prefix keeps names unique. `cfg` is accepted for interface symmetry; the names
    do not depend on it. A name labels a pattern, it does not explain it. Raises ValueError if columns are missing.
    """
    need = {"pathway", "modal_first", "modal_last", "share_stable"}
    if profile_df.empty or not need <= set(profile_df.columns):
        raise ValueError(f"profile_df must be non-empty with columns {sorted(need)}")
    out: dict[int, str] = {}
    for r in profile_df.itertuples(index=False):
        p = int(r.pathway)
        first, last = r.modal_first, r.modal_last
        if first is None or last is None or (isinstance(first, float) and np.isnan(first)) or (isinstance(last, float) and np.isnan(last)):
            out[p] = f"P{p}: not enough observations"
        elif first == last:
            stable = r.share_stable
            if np.isfinite(stable) and stable >= STABLE_MIN_SHARE:
                out[p] = f"P{p}: stable {_pretty(first)}"
            else:
                out[p] = f"P{p}: varied, starting and ending in {_pretty(first)}"
        else:
            out[p] = f"P{p}: {_pretty(first)} to {_pretty(last)}"
    return out


# ---------------------------------------------------------------------------------------------
# Smoke demo
# ---------------------------------------------------------------------------------------------
def _cfg_with(cfg: Config, section: str, **values: Any) -> Config:
    d = cfg.to_dict()
    return Config({**d, section: {**d[section], **values}}, cfg.root)


def _demo() -> int:
    import json

    from .preprocessing import apply_eligibility
    from .synthetic_data import generate_synthetic
    from .trajectories import build_trajectories

    cfg = load_config()
    print("SYNTHETIC DEMONSTRATION - NOT PLFS RESULTS")

    def raises(exc: type, fn: Any) -> bool:
        try:
            fn()
        except exc:
            return True
        except Exception:
            return False
        return False

    # ----- hand-built fixture: 7 individuals, 2 pathways, 4 visits, state indices as in config (0 wage, 3 unemployed, 4 out)
    st = np.array([
        [3, 3, 0, 0],      # pathway 0: unemployed -> wage
        [3, 3, 0, 0],
        [3, -1, 0, 0],
        [3, 3, 3, 0],
        [0, 0, 0, 0],      # pathway 1: stable wage
        [0, 0, -1, 0],
        [4, 4, 4, -2],     # pathway 1: out of labour force, then lost at the last visit
    ], dtype=np.int8)
    attrs = pd.DataFrame({"person_id": [f"H{i}" for i in range(7)], "age": [20.0, 30.0, np.nan, 40.0, 25.0, 35.0, 50.0],
                          "sex": ["F", "M", "F", None, "M", "M", "F"], "sector": ["R", "R", "U", "U", "R", "U", "U"]})
    wts = np.array([1.0, 2.0, 1.0, 4.0, 1.0, 2.0, 3.0])
    names_all = [s["name"] for s in cfg.to_dict()["states"]]
    td_h = TrajectoryData(ids=np.array([f"H{i}" for i in range(7)]), states=st, time_labels=list(cfg.time.labels),
                          state_names=names_all, attrs=attrs, weights=wts, is_synthetic=True, meta={})
    td_h0 = TrajectoryData(ids=td_h.ids, states=st, time_labels=list(cfg.time.labels), state_names=names_all,
                           attrs=attrs, weights=None, is_synthetic=True, meta={})
    lab_h = np.array([0, 0, 0, 0, 1, 1, 1])
    n_many = 40
    td_many = TrajectoryData(ids=np.array([f"M{i}" for i in range(n_many)]), states=np.tile(st[:1], (n_many, 1)), time_labels=list(cfg.time.labels),
                             state_names=names_all, attrs=pd.DataFrame({"person_id": [f"M{i}" for i in range(n_many)], "code": [f"c{i}" for i in range(n_many)]}),
                             weights=None, is_synthetic=True, meta={})
    cfg_v = _cfg_with(cfg, "profiling", permitted_vars=["age", "sex", "sector"], weighted=False)
    cfg_w = _cfg_with(cfg, "profiling", permitted_vars=["age", "sex", "sector"], weighted=True)

    prev_h, prev_h0 = pathway_prevalence(td_h, lab_h), pathway_prevalence(td_h0, lab_h)
    prof = pathway_profiles(td_h, lab_h, cfg_v).set_index("pathway")
    prof_w = pathway_profiles(td_h, lab_h, cfg_w).set_index("pathway")
    comp = state_composition_by_time(td_h, lab_h)
    nm_h = name_pathways(pathway_profiles(td_h, lab_h, cfg_v), cfg_v)
    wage, unemp = names_all[0], names_all[3]

    # ----- synthetic planted structure
    df, truth = generate_synthetic(cfg, n=1500, seed_offset=71)
    td = apply_eligibility(build_trajectories(df, cfg), cfg)
    pid = np.array([int(x[1:]) for x in td.ids])
    planted = truth.labels[pid]
    cfg_s = _cfg_with(cfg, "profiling", permitted_vars=["age", "sex", "sector"], weighted=False)
    prof_s = pathway_profiles(td, planted, cfg_s)
    nm_s = name_pathways(prof_s, cfg_s)
    comp_s = state_composition_by_time(td, planted)
    prev_s = pathway_prevalence(td, planted)
    print(prof_s[["pathway", "n_individuals", "modal_path", "share_stable", "employed_first", "employed_last"]].round(3).to_string(index=False))
    for p, n in nm_s.items():
        print(f"  {n}")

    ps = prof_s.set_index("pathway")
    sectors = td.attrs["sector"].to_numpy()
    checks = {
        "prevalence: counts, shares sum to 1, unweighted counts when weighted": list(prev_h["n_individuals"]) == [4, 3]
            and np.isclose(prev_h["prevalence_unweighted"].sum(), 1.0) and np.allclose(prev_h["prevalence_unweighted"], [4 / 7, 3 / 7]),
        "prevalence: weighted share equals the hand value (pathway 0: 8 of 14)": np.allclose(prev_h["prevalence_weighted"], [8 / 14, 6 / 14])
            and "weighted" in prev_h["weight_note"].iloc[0],
        "prevalence: NaN with a note when no verified weights": prev_h0["prevalence_weighted"].isna().all() and "no verified" in prev_h0["weight_note"].iloc[0],
        "prevalence: bad labels raise": raises(ValueError, lambda: pathway_prevalence(td_h, lab_h[:-1])) and raises(ValueError, lambda: pathway_prevalence(td_h, np.array([0, 0, 0, 0, 1, 1, -1])))
            and raises(ValueError, lambda: pathway_prevalence(td_h, lab_h + 0.5)),
        "composition: counts per pathway, visit and state equal the hand values": int(comp.query("pathway==0 and time==0 and state==@unemp")["n"].iloc[0]) == 4
            and int(comp.query("pathway==0 and time==3 and state==@wage")["n"].iloc[0]) == 4
            and int(comp.query("pathway==1 and time==2 and state==@wage")["n"].iloc[0]) == 1,
        "composition: missing and lost are reported apart and never become states": int(comp.query("pathway==1 and time==3")["n_lost"].iloc[0]) == 1
            and int(comp.query("pathway==0 and time==1")["n_missing"].iloc[0]) == 1 and int(comp.query("pathway==0 and time==1")["n_observed"].iloc[0]) == 3,
        "composition: shares of observed sum to 1 wherever someone is observed": bool(np.allclose(
            comp.groupby(["pathway", "time"])["share_of_observed"].sum(), 1.0)),
        "profile: state shares, modal path and employed shares equal hand values": np.isclose(prof.loc[0, f"share_{wage}"], 7 / 15)
            and prof.loc[0, "modal_path"] == f"{unemp} > {unemp} > {wage} > {wage}" and prof.loc[0, "modal_first"] == unemp
            and prof.loc[0, "modal_last"] == wage and np.isclose(prof.loc[0, "employed_first"], 0.0) and np.isclose(prof.loc[0, "employed_last"], 1.0)
            and np.isclose(prof.loc[0, "employed_change"], 1.0),
        "profile: missing and lost cell shares": np.isclose(prof.loc[0, "share_missing_cells"], 1 / 16) and np.isclose(prof.loc[1, "share_lost_cells"], 1 / 12)
            and np.isclose(prof.loc[1, "mean_observed_visits"], (4 + 3 + 3) / 3),
        "profile: stable share and switches (a gap is not a change)": np.isclose(prof.loc[1, "share_stable"], 1.0) and np.isclose(prof.loc[0, "share_stable"], 0.0)
            and np.isclose(prof.loc[0, "mean_switches"], 1.0),
        "profile: numeric attribute mean, unweighted median, missing count": np.isclose(prof.loc[0, "age__mean"], 30.0) and np.isclose(prof.loc[0, "age__median_unweighted"], 30.0)
            and prof.loc[0, "age__n_missing"] == 1 and np.isclose(prof.loc[1, "age__mean"], 110 / 3),
        "profile: categorical shares among members with a value, missing counted": np.isclose(prof.loc[0, "sex=F"], 2 / 3) and np.isclose(prof.loc[0, "sex=M"], 1 / 3)
            and prof.loc[0, "sex__n_missing"] == 1 and np.isclose(prof.loc[1, "sector=U"], 2 / 3),
        "profile: weighted statistics use the verified weights (and only then)": np.isclose(prof_w.loc[0, "age__mean"], (20 * 1 + 30 * 2 + 40 * 4) / 7)
            and np.isclose(prof_w.loc[0, f"share_{wage}"], 12 / 31) and prof_w.attrs["weighted"] is True and prof.attrs["weighted"] is False
            and np.isclose(prof.loc[0, f"share_{wage}"], 7 / 15),
        "weighted profiling without verified weights is refused": raises(ConfigError, lambda: pathway_profiles(td_h0, lab_h, cfg_w)),
        "attributes: protected roles may be profiled, identifiers and unknown columns are refused": permitted_profile_vars(_cfg_with(cfg, "profiling", permitted_vars=["sex", "age", "sex"])) == ["sex", "age"]
            and raises(ConfigError, lambda: permitted_profile_vars(_cfg_with(cfg, "profiling", permitted_vars=["person_id"])))
            and raises(ConfigError, lambda: pathway_profiles(td_h, lab_h, _cfg_with(cfg, "profiling", permitted_vars=["no_such_column"], weighted=False))),
        "attributes: no permitted variables means state columns only": not any("__" in c or "=" in c for c in pathway_profiles(td_h, lab_h, cfg).columns),
        "attributes: an identifier-like categorical column (more than 30 levels) is refused": raises(ConfigError, lambda: pathway_profiles(
            td_many, np.zeros(n_many, dtype=int), _cfg_with(cfg, "profiling", permitted_vars=["code"], weighted=False))),
        "names: hand fixture gives the expected labels": nm_h == {0: f"P0: {unemp.replace('_', ' ')} to {wage.replace('_', ' ')}", 1: f"P1: stable {wage.replace('_', ' ')}"},
        "names: equal modal states but few stable members are 'varied'": name_pathways(pd.DataFrame({"pathway": [3], "modal_first": [wage], "modal_last": [wage], "share_stable": [0.2]}), cfg)[3].startswith("P3: varied")
            and name_pathways(pd.DataFrame({"pathway": [3], "modal_first": [None], "modal_last": [wage], "share_stable": [0.2]}), cfg)[3].endswith("not enough observations")
            and raises(ValueError, lambda: name_pathways(pd.DataFrame({"pathway": [1]}), cfg)),
        "planted pathways: prevalence equals the planted counts": list(prev_s["n_individuals"]) == list(np.bincount(planted)),
        "planted pathways are named by their pattern (stable wage, unemployed to wage, wage to exit, stable out of labour force)":
            nm_s[0] == "P0: stable wage employment" and nm_s[2] == "P2: unemployed seeking to wage employment"
            and nm_s[3] == "P3: wage employment to out of labour force" and nm_s[4] == "P4: stable out of labour force",
        "planted pathways: employed share rises for unemployed-to-wage and stays high for stable wage": ps.loc[2, "employed_first"] < 0.3 and ps.loc[2, "employed_last"] > 0.7
            and ps.loc[0, "employed_first"] > 0.8 and ps.loc[4, "employed_last"] < 0.2,
        "planted pathways: attribute shares equal a direct pandas computation": all(
            abs(ps.loc[p, "sector=U"] - (sectors[planted == p] == "U").mean()) < 1e-12 for p in ps.index),
        "planted pathways: composition counts add up to the cells observed": int(comp_s.groupby(["pathway", "time"])["n"].sum().sum()) == int((td.states >= 0).sum()),
        "tables are JSON-safe after NaN to None": all(json.dumps(t.astype(object).where(t.notna(), None).to_dict("records"), allow_nan=False)
                                                      for t in (prev_h, prof.reset_index(), comp, prof_s)),
    }
    for name, ok in checks.items():
        print(f"  demo check [{'ok' if ok else 'FAILED'}]: {name}")
    if not all(checks.values()):
        return 1
    print(f"Demo checks passed ({len(checks)}). All data above is SYNTHETIC or hand-built.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_demo())
