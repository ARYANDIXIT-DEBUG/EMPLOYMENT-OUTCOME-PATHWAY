"""The mandatory baseline: employed versus not employed at one reference visit, and how it compares with pathways.

Why this file exists: a clustering of trajectories is only worth reporting if it tells us something that
the simplest possible outcome measure does not. The simplest measure in this project is a two-class
partition of the same trainees: employed or not employed at one reference visit. This module defines that
partition (locked before the first clustering run), builds it for individuals and for collapsed units,
builds labelled sensitivity variants, and measures how the pathways relate to it.

Design choices worth defending in a viva:
  * The baseline is a function of ONE column of the state array: the state at `baseline.reference_visit`.
    "Employed" means the state is in `baseline.employed_states`; any other OBSERVED state is "not
    employed". MISSING, LOST and a sensitivity-policy "unobserved" state are never recoded into either
    class: they are unknown. `baseline.unknown_treatment` says what happens to them: `exclude` (label -1,
    counts reported) or `category` (an explicit third class, label 2). Missing is never silently called
    "not employed".
  * Because the baseline reads only one column of the trajectory, it is well defined for a collapsed unit
    (the reference state is part of the sequence), so `baseline_unit_labels` needs no individual data and
    equals the individual labels expanded through `col.inverse`.
  * The baseline sample is exactly the clustered trainees (`baseline.sample_rule: same_as_clustering`).
    `validate_baseline_definition` refuses a `td` that was not produced by the eligibility step. The only
    individuals removed on top of that are those whose reference-visit status is unknown (with
    `exclude`); `BaselineResult.eligible_mask` says who, and the comparison and the clustering metrics must
    be computed on that same subset for a like-for-like result.
  * Agreement between a baseline and pathways is NOT an independent validation. The baseline is defined from
    the same trajectories that are clustered, and when the reference visit is the last visit it is the final
    state of the trajectory itself, so some agreement is by construction. What the comparison is for is the
    opposite question: how much of the pathway structure is NOT explained by the final employment status.
    The result therefore reports agreement (ARI, NMI) and also what the baseline hides (pathways inside each
    class, entropy of the pathway mix per class, the share of pathway entropy left after knowing the class).
  * Agreement statistics are computed from the contingency table in this file, from the standard definitions,
    and are cross-checked in the demo against a brute-force pair count and scikit-learn. They count
    individuals. Survey weights are not used here (profiling reports weighted prevalence).
  * Sensitivity variants (`baseline.sensitivity_variants_def`) are labelled alternatives (another reference
    visit, another set of employed states, the other unknown treatment). They never replace the primary
    baseline. A variant that does not differ from the primary is an error, not a silent duplicate.
  * The lock: `baseline.locked` is set true before the first clustering run. `check_baseline_lock` keeps a
    small provenance record (`baseline_lock.json` in the results directory, no SYNTHETIC/real tag because it
    describes the configuration, not a result) and refuses a changed definition unless `baseline.change_log`
    has gained an entry with a date, a reason and the change. Only the presence of the entry can be checked,
    not its honesty.

Limits: one reference status is a snapshot, not a pathway; with about four monthly observations the baseline
and the pathways are both short-window summaries. The employed set ("wage_employment", "self_employment",
"unpaid_family_work" in the proposed config) is a PROPOSED definition that the user must confirm.

Dependency rule: imports only `config`, the shared types and numpy/pandas. `trajectories` is not needed here.
The smoke demo imports `synthetic_data` and `trajectories` inside the demo function.

Run the smoke demo with:  python -m src.baseline
"""
from __future__ import annotations

import hashlib
import json
import math
import tempfile
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from . import LOST, MISSING, BaselineResult, CollapsedTrajectories, TrajectoryData
from .config import Config, load_config, resolve_path

__all__ = [
    "BaselineError",
    "HIDDEN_MIN_SHARE",
    "validate_baseline_definition",
    "baseline_partition",
    "baseline_unit_labels",
    "sensitivity_variants",
    "compare_to_clustering",
    "check_baseline_lock",
]

CLASS_NAMES = {-1: "excluded", 0: "not_employed", 1: "employed", 2: "unknown"}
UNKNOWN_TREATMENTS = ("exclude", "category")
SAMPLE_RULES = ("same_as_clustering",)
VARIANT_KEYS = ("label", "reference_visit", "employed_states", "unknown_treatment")
HIDDEN_MIN_SHARE = 0.05      # PROPOSED: a pathway is "inside" a baseline class if it holds at least this share of the class
MINORITY_NOTE_SHARE = 0.05   # a baseline class below this share of the known individuals triggers a note
UNKNOWN_NOTE_SHARE = 0.20    # an unknown share above this triggers a note
LOCK_FILE = "baseline_lock.json"


class BaselineError(Exception):
    """The baseline definition contradicts the data or the config, or its lock was broken."""


# ---------------------------------------------------------------------------------------------
# Definition: parameters, validation, labels
# ---------------------------------------------------------------------------------------------
def _state_names(cfg: Config) -> list[str]:
    return [str(s["name"]) for s in cfg.to_dict()["states"]]


def _params(cfg: Config, override: dict[str, Any] | None = None) -> dict[str, Any]:
    """The effective definition: the config's baseline block, with a variant's overrides applied."""
    b = cfg.to_dict()["baseline"]
    p: dict[str, Any] = {
        "reference_visit": b["reference_visit"],
        "employed_states": list(b["employed_states"]),
        "unknown_treatment": b["unknown_treatment"],
        "sample_rule": b["sample_rule"],
    }
    for k, v in (override or {}).items():
        if k != "label":
            p[k] = list(v) if k == "employed_states" and isinstance(v, (list, tuple)) else v
    return p


def _check_params(p: dict[str, Any], T: int, names: list[str], where: str) -> None:
    rv = p["reference_visit"]
    if isinstance(rv, bool) or not isinstance(rv, (int, np.integer)) or not 0 <= int(rv) <= T - 1:
        raise BaselineError(f"{where}: reference_visit {rv!r} is not an integer inside the clustering window 0..{T - 1}")
    emp = p["employed_states"]
    if not isinstance(emp, list) or not emp or not all(isinstance(s, str) for s in emp):
        raise BaselineError(f"{where}: employed_states must be a non-empty list of state names")
    unknown = [s for s in emp if s not in names]
    if unknown:
        raise BaselineError(f"{where}: employed_states {unknown} are not declared states {names}")
    if len(set(emp)) != len(emp):
        raise BaselineError(f"{where}: employed_states lists a state twice")
    if len(set(emp)) >= len(names):
        raise BaselineError(f"{where}: employed_states covers every state, so no 'not employed' class can exist")
    if p["unknown_treatment"] not in UNKNOWN_TREATMENTS:
        raise BaselineError(f"{where}: unknown_treatment must be one of {UNKNOWN_TREATMENTS}, got {p['unknown_treatment']!r}")
    if p["sample_rule"] not in SAMPLE_RULES:
        raise BaselineError(f"{where}: sample_rule must be one of {SAMPLE_RULES}, got {p['sample_rule']!r}")


def _variant_params(cfg: Config, T: int, names: list[str]) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """(label, effective params, raw definition) for every configured variant; raises BaselineError on any problem."""
    defs = cfg.to_dict()["baseline"]["sensitivity_variants_def"]
    if not isinstance(defs, list):
        raise BaselineError("baseline.sensitivity_variants_def must be a list of {label, ...} mappings")
    primary = _params(cfg)
    out, seen = [], set()
    for i, d in enumerate(defs):
        if not isinstance(d, dict):
            raise BaselineError(f"sensitivity_variants_def[{i}] must be a mapping")
        label = d.get("label")
        if not isinstance(label, str) or not label.strip():
            raise BaselineError(f"sensitivity_variants_def[{i}] needs a non-empty text 'label'")
        if label == "primary" or label in seen:
            raise BaselineError(f"sensitivity variant label {label!r} is reserved or duplicated")
        seen.add(label)
        extra = sorted(set(d) - set(VARIANT_KEYS))
        if extra:
            raise BaselineError(f"sensitivity variant {label!r}: unknown key(s) {extra}; allowed: {list(VARIANT_KEYS)}")
        p = _params(cfg, d)
        _check_params(p, T, names, f"sensitivity variant {label!r}")
        same = (p["reference_visit"] == primary["reference_visit"] and set(p["employed_states"]) == set(primary["employed_states"])
                and p["unknown_treatment"] == primary["unknown_treatment"])
        if same:
            raise BaselineError(f"sensitivity variant {label!r} does not differ from the primary baseline")
        out.append((label, p, d))
    return out


def _check_sample(td: TrajectoryData, cfg: Config) -> None:
    """The baseline must run on the clustered (eligible) trainees, not on a different set of people."""
    min_pts = int(cfg.trainee.min_time_points)
    elig = td.meta.get("eligibility")
    if elig is not None:
        if int(elig.get("min_time_points", -1)) != min_pts:
            raise BaselineError(f"td was made eligible with min_time_points={elig.get('min_time_points')} but the config says "
                                f"{min_pts}: the baseline would run on a different sample than the clustering")
        return
    n_bad = int(((td.states >= 0).sum(axis=1) < min_pts).sum())
    if n_bad:
        raise BaselineError(f"{n_bad} individuals have fewer than trainee.min_time_points={min_pts} observed points and td carries no "
                            "eligibility record: apply preprocessing.apply_eligibility first so the baseline uses the clustered sample")


def _check_names(td_names: list[str], cfg_names: list[str]) -> None:
    if list(td_names[:len(cfg_names)]) != cfg_names:
        raise BaselineError(f"td.state_names {list(td_names)} do not start with the configured states {cfg_names}")


def _labels_from_codes(s: np.ndarray, employed_codes: list[int], K: int, unknown_treatment: str) -> np.ndarray:
    """Baseline labels for an array of state codes at the reference visit (codes >= K are policy states: unknown)."""
    s = np.asarray(s)
    observed = (s >= 0) & (s < K)
    labels = np.full(s.shape, -1 if unknown_treatment == "exclude" else 2, dtype=np.int64)
    emp = observed & np.isin(s, employed_codes)
    labels[emp] = 1
    labels[observed & ~emp] = 0
    return labels


def validate_baseline_definition(cfg: Config, td: TrajectoryData) -> list[str]:
    """Check the baseline definition against `td`; raise BaselineError on any contradiction, else return notes.

    Contradictions (raised): reference visit outside the window of `td` (also when `td` was censored),
    employed_states not declared, duplicated, empty or covering every state, bad unknown_treatment or
    sample_rule, `td` states not starting with the configured states, `td` not being the eligible trainee
    sample (see module docstring), and any sensitivity variant that is malformed or identical to the
    primary. Notes (returned, non-fatal) say how to read the result: reference visit at the first or last
    visit, a large unknown share, a very small class.
    """
    names = _state_names(cfg)
    p = _params(cfg)
    _check_params(p, td.T, names, "baseline")
    _check_names(td.state_names, names)
    _check_sample(td, cfg)
    _variant_params(cfg, td.T, names)
    rv, K = int(p["reference_visit"]), len(names)
    notes: list[str] = []
    if rv == td.T - 1:
        notes.append("The reference visit is the last visit, so the baseline label is the final state of the trajectory itself: some "
                     "agreement with the pathways is by construction. Read it as 'how much history does final status leave out', "
                     "not as validation.")
    if rv == 0 and td.T > 1:
        notes.append("The reference visit is the first visit: the baseline ignores everything after the first observation.")
    s = td.states[:, rv]
    n_unknown = int(((s < 0) | (s >= K)).sum())
    if td.n and n_unknown / td.n > UNKNOWN_NOTE_SHARE:
        notes.append(f"{n_unknown} of {td.n} individuals ({n_unknown / td.n:.0%}) have no observed state at the reference visit; "
                     f"they are handled as '{p['unknown_treatment']}'.")
    known = s[(s >= 0) & (s < K)]
    if known.size:
        share_emp = float(np.isin(known, [names.index(x) for x in p["employed_states"]]).mean())
        if min(share_emp, 1 - share_emp) < MINORITY_NOTE_SHARE:
            notes.append(f"One baseline class holds under {MINORITY_NOTE_SHARE:.0%} of the individuals with a known reference status "
                         f"(employed share {share_emp:.1%}); agreement statistics are then uninformative.")
    return notes


def _partition(td: TrajectoryData, cfg: Config, p: dict[str, Any], label: str, is_sens: bool, names: list[str],
               overrides: dict[str, Any] | None = None) -> BaselineResult:
    K = len(names)
    rv = int(p["reference_visit"])
    codes = [names.index(x) for x in p["employed_states"]]
    s = td.states[:, rv]
    labels = _labels_from_codes(s, codes, K, p["unknown_treatment"])
    miss, lost, policy = int((s == MISSING).sum()), int((s == LOST).sum()), int((s >= K).sum())
    n_unknown = miss + lost + policy
    counts = {
        "n_total": int(td.n),
        "n_employed": int((labels == 1).sum()),
        "n_not_employed": int((labels == 0).sum()),
        "n_unknown": n_unknown,
        "n_unknown_missing": miss,
        "n_unknown_lost": lost,
        "n_unknown_policy_state": policy,
        "n_excluded": int((labels == -1).sum()),
        "n_eligible": int((labels != -1).sum()),
    }
    emp_txt = ", ".join(p["employed_states"])
    unk_txt = "excluded (-1)" if p["unknown_treatment"] == "exclude" else "a separate 'unknown' class (2)"
    definition = {
        "rule": (f"state at {td.time_labels[rv]} ({cfg.time.reference_period}) in [{emp_txt}] -> employed (1); any other observed state -> "
                 f"not employed (0); no observed state (MISSING, LOST or an 'unobserved' policy state) -> {unk_txt}"),
        "reference_visit": rv,
        "reference_label": str(td.time_labels[rv]),
        "reference_period": str(cfg.time.reference_period),
        "employed_states": list(p["employed_states"]),
        "not_employed_states": [x for x in names if x not in p["employed_states"]],
        "unknown_treatment": p["unknown_treatment"],
        "sample_rule": p["sample_rule"],
        "label_codes": {str(k): v for k, v in CLASS_NAMES.items()},
    }
    if is_sens:
        primary = _params(cfg)
        definition["differs_from_primary"] = sorted(
            k for k in ("reference_visit", "employed_states", "unknown_treatment")
            if (set(p[k]) != set(primary[k]) if k == "employed_states" else p[k] != primary[k]))
    return BaselineResult(labels=labels, eligible_mask=labels != -1, counts=counts, definition=definition,
                          label=label, is_sensitivity=is_sens)


def baseline_partition(td: TrajectoryData, cfg: Config) -> BaselineResult:
    """The locked primary baseline for every individual of `td`: label 1 employed, 0 not employed, -1 excluded (or 2 unknown).

    Validates first (see `validate_baseline_definition`; contradictions raise BaselineError). Reads only the
    state at `baseline.reference_visit`. `counts` always holds n_total, n_employed, n_not_employed,
    n_unknown, n_unknown_missing, n_unknown_lost, n_unknown_policy_state (codes beyond the configured
    states, created by the 'missing_as_state' sensitivity policy; never counted as observed), n_excluded
    and n_eligible, with employed + not employed + unknown = total.
    """
    validate_baseline_definition(cfg, td)
    return _partition(td, cfg, _params(cfg), "primary", False, _state_names(cfg))


def baseline_unit_labels(col: CollapsedTrajectories, cfg: Config) -> np.ndarray:
    """(u,) baseline label of every unique sequence, with the same codes as `BaselineResult.labels`.

    Well defined because the reference state is part of the sequence. Expanding with `col.inverse` gives
    exactly `baseline_partition(td, cfg).labels` for the individuals the collapse was made from.
    """
    names = _state_names(cfg)
    p = _params(cfg)
    _check_params(p, col.T, names, "baseline")
    codes = [names.index(x) for x in p["employed_states"]]
    return _labels_from_codes(col.unique_states[:, int(p["reference_visit"])], codes, len(names), p["unknown_treatment"])


def sensitivity_variants(cfg: Config, td: TrajectoryData) -> dict[str, BaselineResult]:
    """Labelled alternative baselines from `baseline.sensitivity_variants_def` (empty dict if none are configured).

    Each variant overrides `reference_visit`, `employed_states` and/or `unknown_treatment` of the primary
    definition; it is returned with its label, `is_sensitivity=True` and `definition['differs_from_primary']`.
    The primary baseline is never changed. Malformed, reserved-label, duplicated or primary-identical
    variants raise BaselineError.
    """
    validate_baseline_definition(cfg, td)
    names = _state_names(cfg)
    return {label: _partition(td, cfg, p, label, True, names) for label, p, _ in _variant_params(cfg, td.T, names)}


# ---------------------------------------------------------------------------------------------
# Comparison with pathways
# ---------------------------------------------------------------------------------------------
def _comb2(x: int) -> int:
    return x * (x - 1) // 2


def _ari(C: np.ndarray) -> float:
    """Adjusted Rand index from a contingency table, in exact integer arithmetic (same convention as scikit-learn)."""
    tp = sum(_comb2(int(v)) for v in C.ravel())
    sa = sum(_comb2(int(v)) for v in C.sum(axis=1))
    sb = sum(_comb2(int(v)) for v in C.sum(axis=0))
    tot = _comb2(int(C.sum()))
    fn, fp = sa - tp, sb - tp
    tn = tot - tp - fn - fp
    if fn == 0 and fp == 0:
        return 1.0
    return 2 * (tp * tn - fn * fp) / ((tp + fn) * (fn + tn) + (tp + fp) * (fp + tn))


def _entropy(counts: np.ndarray) -> float:
    c = np.asarray(counts, dtype=np.float64)
    c = c[c > 0]
    if c.size == 0:
        return 0.0
    p = c / c.sum()
    return float(-(p * np.log(p)).sum())


def _agreement(C: np.ndarray) -> dict[str, float | None]:
    """ARI, NMI (arithmetic-mean normalisation) and the entropy decomposition of a contingency table, in nats."""
    n = float(C.sum())
    h_b, h_p = _entropy(C.sum(axis=1)), _entropy(C.sum(axis=0))
    h_j = _entropy(C.ravel())
    pij = C / n
    pi, pj = pij.sum(axis=1, keepdims=True), pij.sum(axis=0, keepdims=True)
    nz = pij > 0
    mi = float(max(0.0, (pij[nz] * np.log(pij[nz] / (pi @ pj)[nz])).sum()))
    norm = (h_b + h_p) / 2.0
    nmi = 1.0 if (h_b == 0.0 and h_p == 0.0) else float(min(1.0, max(0.0, mi / norm)))
    return {
        "ari": float(_ari(C)), "nmi": nmi, "mutual_information": mi,
        "h_baseline": h_b, "h_pathways": h_p, "h_joint": h_j,
        "h_pathways_given_baseline": max(0.0, h_j - h_b), "h_baseline_given_pathways": max(0.0, h_j - h_p),
        "unexplained_pathway_entropy_share": None if h_p == 0.0 else max(0.0, h_j - h_b) / h_p,
    }


def _clean(x: Any) -> Any:
    """JSON-safe copy: numpy scalars to Python, NaN and inf to None, keys to text."""
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, np.ndarray):
        return _clean(x.tolist())
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        return None if not math.isfinite(float(x)) else float(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    return x


def compare_to_clustering(base: BaselineResult, full_labels: np.ndarray, td: TrajectoryData, cfg: Config) -> dict[str, Any]:
    """How the pathways in `full_labels` relate to the baseline classes, over the baseline-eligible individuals.

    `full_labels` is the (n,) pathway label of every individual of `td` (`FullClustering.full_labels`).
    Only individuals with `base.eligible_mask` are compared; their number and the number excluded are
    reported, and the clustering metrics must be recomputed on that same subset by the caller. Individuals
    are counted, survey weights are not used. The returned plain dict (JSON-safe) holds:
      * `contingency` (baseline class x pathway counts), `ari`, `nmi` (arithmetic-mean normalisation);
      * `entropy`: H(baseline), H(pathways), H(pathways | baseline), H(baseline | pathways), mutual information, in nats;
      * `unexplained_pathway_entropy_share` = H(pathways | baseline) / H(pathways): 1 means the baseline says nothing
        about the pathway, 0 means the baseline fixes the pathway (None when there is a single pathway);
      * `by_class`: per baseline class the pathway counts and shares, entropy of the pathway mix, the effective number
        of pathways exp(entropy), and the pathways "hidden inside" the class, meaning those holding at least
        `HIDDEN_MIN_SHARE` of the class (a PROPOSED threshold, returned as `hidden_min_share`);
      * `by_pathway`: per pathway its counts per class, dominant class, purity, and whether it spans classes
        (at least two classes each holding at least `HIDDEN_MIN_SHARE` of the pathway);
      * `notes`: how to read the numbers (including that agreement is partly by construction).
    """
    fl = np.asarray(full_labels)
    if fl.ndim != 1 or len(fl) != td.n or base.labels.shape != (td.n,):
        raise BaselineError(f"full_labels ({fl.shape}), base.labels ({base.labels.shape}) and td ({td.n} individuals) must all have one entry per individual")
    if fl.dtype.kind not in "iu":
        if fl.dtype.kind == "f" and np.isfinite(fl).all() and np.array_equal(fl, np.floor(fl)):
            fl = fl.astype(np.int64)
        else:
            raise BaselineError("full_labels must be integer pathway labels")
    mask = base.eligible_mask
    if not mask.any():
        raise BaselineError("no individual is baseline-eligible: nothing to compare")
    if fl[mask].min() < 0:
        raise BaselineError("pathway labels must be non-negative for every compared individual")
    b, p = base.labels[mask], fl[mask].astype(np.int64)
    classes, paths = np.unique(b), np.unique(p)
    bi, pi = np.searchsorted(classes, b), np.searchsorted(paths, p)
    C = np.bincount(bi * len(paths) + pi, minlength=len(classes) * len(paths)).reshape(len(classes), len(paths)).astype(np.int64)
    n = int(C.sum())
    ag = _agreement(C)
    n_paths = len(paths)

    by_class: dict[str, Any] = {}
    for r, code in enumerate(classes):
        row = C[r]
        h = _entropy(row)
        share = row / row.sum()
        hidden = [int(paths[j]) for j in np.argsort(-share, kind="stable") if share[j] >= HIDDEN_MIN_SHARE]
        by_class[CLASS_NAMES[int(code)]] = {
            "code": int(code), "n": int(row.sum()), "share_of_compared": float(row.sum() / n),
            "pathway_counts": {str(int(paths[j])): int(row[j]) for j in range(n_paths) if row[j] > 0},
            "pathway_shares": {str(int(paths[j])): float(share[j]) for j in range(n_paths) if row[j] > 0},
            "entropy_nats": h, "entropy_normalised": None if n_paths < 2 else h / math.log(n_paths),
            "effective_n_pathways": float(math.exp(h)),
            "hidden_pathways": hidden, "n_hidden_pathways": len(hidden),
        }
    by_path: dict[str, Any] = {}
    n_span = 0
    for j, pid in enumerate(paths):
        col = C[:, j]
        share = col / col.sum()
        dom = int(np.argmax(col))
        spans = int((share >= HIDDEN_MIN_SHARE).sum()) >= 2
        n_span += int(spans)
        by_path[str(int(pid))] = {
            "n": int(col.sum()), "class_counts": {CLASS_NAMES[int(classes[r])]: int(col[r]) for r in range(len(classes)) if col[r] > 0},
            "class_shares": {CLASS_NAMES[int(classes[r])]: float(share[r]) for r in range(len(classes)) if col[r] > 0},
            "dominant_class": CLASS_NAMES[int(classes[dom])], "purity": float(share[dom]), "spans_classes": spans,
        }

    notes = ["Agreement counts individuals; survey weights are not used here.",
             "The baseline is defined from the same trajectories that are clustered, so agreement is not independent validation."]
    if base.definition.get("reference_visit") == td.T - 1:
        notes.append("The reference visit is the last visit: the baseline label is the final state of the trajectory, so part of the "
                     "agreement is by construction. The informative numbers are the ones about what the baseline hides.")
    if len(classes) < 2:
        notes.append("Only one baseline class occurs among the compared individuals: ARI and NMI are degenerate.")
    if n_paths < 2:
        notes.append("Only one pathway occurs among the compared individuals: ARI and NMI are degenerate.")
    n_excl = int((~mask).sum())
    if n_excl:
        notes.append(f"{n_excl} individuals are excluded (unknown at the reference visit); clustering metrics must be recomputed on the "
                     "same compared individuals for a like-for-like comparison.")
    result = {
        "label": base.label, "is_sensitivity": base.is_sensitivity, "is_synthetic": bool(td.is_synthetic),
        "definition": base.definition, "counts": base.counts,
        "n_compared": n, "n_excluded": n_excl, "weights_used": False,
        "contingency": {"rows": [CLASS_NAMES[int(c)] for c in classes], "row_codes": [int(c) for c in classes],
                        "cols": [int(x) for x in paths], "counts": C.tolist()},
        "ari": ag["ari"], "nmi": ag["nmi"], "nmi_normalisation": "arithmetic mean of the two entropies",
        "entropy": {"unit": "nats", **{k: ag[k] for k in ("h_baseline", "h_pathways", "h_joint", "h_pathways_given_baseline",
                                                           "h_baseline_given_pathways", "mutual_information")}},
        "unexplained_pathway_entropy_share": ag["unexplained_pathway_entropy_share"],
        "hidden_min_share": HIDDEN_MIN_SHARE,
        "n_pathways": n_paths, "n_pathways_spanning_classes": n_span,
        "by_class": by_class, "by_pathway": by_path, "notes": notes,
    }
    return _clean(result)


# ---------------------------------------------------------------------------------------------
# Lock
# ---------------------------------------------------------------------------------------------
def _lock_core(cfg: Config) -> tuple[dict[str, Any], str]:
    p = _params(cfg)
    core = {"reference_visit": p["reference_visit"], "employed_states": sorted(p["employed_states"]),
            "unknown_treatment": p["unknown_treatment"], "sample_rule": p["sample_rule"]}
    return core, hashlib.sha256(json.dumps(core, sort_keys=True).encode("utf-8")).hexdigest()


def check_baseline_lock(cfg: Config) -> None:
    """Enforce that the baseline definition is fixed before clustering and changes only with a logged reason.

    Call it before the first clustering run. Behaviour:
      * `baseline.locked` false: once real data is verified (`data.verified` true and `data.plan` set) this raises
        BaselineError; otherwise (synthetic development) it only warns with a UserWarning.
      * locked and no record yet: writes `<results_dir>/baseline_lock.json` (definition, SHA-256, number of
        change-log entries) and returns. This is the one side effect of this function.
      * locked, same definition: returns (the record's entry count follows a growing change log); a SHORTER change log
        raises BaselineError.
      * locked, changed definition: raises BaselineError unless `baseline.change_log` has more entries than at the last
        record, in which case the record is updated and its history extended. Whether the entry's text is honest
        cannot be checked, only that it exists.
    """
    b = cfg.to_dict()["baseline"]
    real = bool(cfg.get("data.verified", False)) and str(cfg.get("data.plan", "UNSET")) != "UNSET"
    if not b["locked"]:
        if real:
            raise BaselineError("baseline.locked is false but the data are verified: set baseline.locked: true before any clustering run")
        warnings.warn("baseline.locked is false: the baseline definition can still change. Lock it before the first real clustering run.",
                      UserWarning, stacklevel=2)
        return
    core, digest = _lock_core(cfg)
    n_log = len(b["change_log"])
    path = resolve_path(cfg, "results_dir") / LOCK_FILE
    entry = {"definition_sha256": digest, "definition": core, "n_change_log_entries": n_log}
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({**entry, "history": [entry]}, indent=2, sort_keys=True), encoding="utf-8")
        return
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
        old_digest, old_n = str(rec["definition_sha256"]), int(rec["n_change_log_entries"])
        history = list(rec["history"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise BaselineError(f"{path} is unreadable or malformed ({exc}); restore it or delete it deliberately and record why in the change log") from exc
    if n_log < old_n:
        raise BaselineError(f"baseline.change_log has {n_log} entries but the lock record saw {old_n}: change-log entries must not be removed")
    if digest == old_digest:
        if n_log != old_n:
            rec["n_change_log_entries"] = n_log
            path.write_text(json.dumps(rec, indent=2, sort_keys=True), encoding="utf-8")
        return
    if n_log == old_n:
        raise BaselineError("the baseline definition changed after it was locked (see baseline_lock.json) but baseline.change_log has no new entry: "
                            "add {date, reason, change} to baseline.change_log")
    rec.update(entry)
    rec["history"] = history + [entry]
    path.write_text(json.dumps(rec, indent=2, sort_keys=True), encoding="utf-8")


# ---------------------------------------------------------------------------------------------
# Smoke demo
# ---------------------------------------------------------------------------------------------
def _cfg_with(cfg: Config, **baseline: Any) -> Config:
    d = cfg.to_dict()
    return Config({**d, "baseline": {**d["baseline"], **baseline}}, cfg.root)


def _brute_ari(a: np.ndarray, b: np.ndarray) -> float:
    """Adjusted Rand index by counting every pair of individuals (reference implementation)."""
    tp = fp = fn = tn = 0
    for i in range(len(a)):
        for j in range(i + 1, len(a)):
            sa, sb = a[i] == a[j], b[i] == b[j]
            tp += sa and sb
            fn += sa and not sb
            fp += (not sa) and sb
            tn += (not sa) and (not sb)
    if fn == 0 and fp == 0:
        return 1.0
    return 2 * (tp * tn - fn * fp) / ((tp + fn) * (fn + tn) + (tp + fp) * (fp + tn))


def _demo() -> int:
    from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score

    from .synthetic_data import generate_synthetic
    from .trajectories import build_trajectories, collapse_trajectories, complete_case_mask

    cfg = load_config()
    print("SYNTHETIC DEMONSTRATION - NOT PLFS RESULTS")
    names = _state_names(cfg)
    T = cfg.time.n_points

    def raises(fn: Any) -> bool:
        try:
            fn()
        except BaselineError:
            return True
        except Exception:
            return False
        return False

    def hand_td(rows: list[list[int]], state_names: list[str] | None = None, meta: dict | None = None) -> TrajectoryData:
        n = len(rows)
        return TrajectoryData(np.array([f"h{i}" for i in range(n)], dtype=object), np.array(rows, dtype=np.int8),
                              list(cfg.time.labels), list(state_names or names), pd.DataFrame({"x": np.arange(n)}), None, True,
                              meta or {})

    # --- hand fixture: employed codes are 0 (wage), 1 (self), 2 (unpaid family work); reference visit = 3
    rows = [[3, 3, 0, 0], [0, 0, 4, 4], [1, 1, 1, -1], [2, 2, 2, -2], [5, 5, 5, 5], [0, 0, -1, 2]]
    td_h = hand_td(rows)
    r_h = baseline_partition(td_h, cfg)
    r_cat = baseline_partition(td_h, _cfg_with(cfg, unknown_treatment="category"))
    td_pol = hand_td([[0, 0, 0, 6], [0, 0, 0, 3], [1, 1, 1, 1]], names + ["unobserved"])
    r_pol = baseline_partition(td_pol, cfg)
    notes_last = validate_baseline_definition(cfg, td_h)
    notes_first = validate_baseline_definition(_cfg_with(cfg, reference_visit=0), td_h)

    # --- synthetic data: eligible trainees
    df, truth = generate_synthetic(cfg, n=1500, seed_offset=41)
    td_all = build_trajectories(df, cfg)
    td = td_all.subset(complete_case_mask(td_all, int(cfg.trainee.min_time_points)))
    res = baseline_partition(td, cfg)
    col = collapse_trajectories(td, cfg)
    unit_lab = baseline_unit_labels(col, cfg)
    s_ref = td.states[:, cfg.baseline.reference_visit]
    emp_codes = [names.index(x) for x in cfg.baseline.employed_states]
    slow = np.array([(-1 if v < 0 else (1 if v in emp_codes else 0)) for v in s_ref])
    pid = np.array([int(x[1:]) for x in td.ids])
    planted = truth.labels[pid]
    cmp_planted = compare_to_clustering(res, planted, td, cfg)
    m = res.eligible_mask
    proto_emp = np.array([1 if truth.prototypes[k, cfg.baseline.reference_visit] in emp_codes else 0 for k in range(len(truth.prototypes))])
    dom_ok = all(cmp_planted["by_pathway"][str(k)]["dominant_class"] == ("employed" if proto_emp[k] else "not_employed")
                 for k in range(len(truth.prototypes)) if str(k) in cmp_planted["by_pathway"])

    # --- variants
    cfg_var = _cfg_with(cfg, sensitivity_variants_def=[
        {"label": "first_visit", "reference_visit": 0},
        {"label": "wage_only", "employed_states": ["wage_employment"]},
        {"label": "unknown_as_class", "unknown_treatment": "category"}])
    var = sensitivity_variants(cfg_var, td)
    var_ok = (list(var) == ["first_visit", "wage_only", "unknown_as_class"] and all(v.is_sensitivity for v in var.values())
              and var["first_visit"].definition["differs_from_primary"] == ["reference_visit"]
              and var["wage_only"].definition["differs_from_primary"] == ["employed_states"]
              and var["unknown_as_class"].counts["n_excluded"] == 0 and not res.is_sensitivity and res.label == "primary"
              and sensitivity_variants(cfg, td) == {})

    def bad_variant(*defs: dict) -> bool:
        return raises(lambda: sensitivity_variants(_cfg_with(cfg, sensitivity_variants_def=list(defs)), td))

    # --- comparison fixture with hand-computed values
    b_lab = np.array([1] * 6 + [0] * 4 + [-1] * 2)
    pw = np.array([0, 0, 1, 1, 2, 2, 3, 3, 3, 4, 0, 1])
    td_c = hand_td([[0, 0, 0, 0]] * 12)
    base_c = BaselineResult(b_lab, b_lab != -1, {}, {"reference_visit": 3}, "primary", False)
    cmp_c = compare_to_clustering(base_c, pw, td_c, cfg)
    bb, pp = b_lab[:10], pw[:10]
    Ch = np.array([[0, 0, 0, 3, 1], [2, 2, 2, 0, 0]])
    h_pg = 0.4 * (-(0.75 * math.log(0.75) + 0.25 * math.log(0.25))) + 0.6 * math.log(3)
    h_p = -sum(c / 10 * math.log(c / 10) for c in [2, 2, 2, 3, 1])
    p_perfect = np.where(b_lab >= 0, b_lab, 0)
    cmp_perfect = compare_to_clustering(base_c, p_perfect, td_c, cfg)
    rng = np.random.default_rng(5)
    rb = rng.integers(0, 2, 2000)
    base_r = BaselineResult(rb, np.ones(2000, bool), {}, {"reference_visit": 3}, "primary", False)
    cmp_rand = compare_to_clustering(base_r, rng.integers(0, 5, 2000), hand_td([[0, 0, 0, 0]] * 2000), cfg)
    one_b = BaselineResult(np.ones(5, np.int64), np.ones(5, bool), {}, {"reference_visit": 3}, "primary", False)
    cmp_one = compare_to_clustering(one_b, np.zeros(5, np.int64), hand_td([[0, 0, 0, 0]] * 5), cfg)
    cmp_half = compare_to_clustering(one_b, np.array([0, 0, 1, 1, 1]), hand_td([[0, 0, 0, 0]] * 5), cfg)
    ncmp = cmp_planted["n_compared"]
    sk_b, sk_p = res.labels[m], planted[m]

    # --- lock
    with tempfile.TemporaryDirectory() as tmp:
        d = cfg.to_dict()
        d["baseline"]["locked"] = True
        cfg_l = Config(d, Path(tmp))
        lock_path = Path(tmp) / cfg_l.paths.results_dir / LOCK_FILE
        with warnings.catch_warnings(record=True) as w_unlocked:
            warnings.simplefilter("always")
            check_baseline_lock(_cfg_with(Config(d, Path(tmp)), locked=False))
        check_baseline_lock(cfg_l)
        rec1 = json.loads(lock_path.read_text())
        check_baseline_lock(cfg_l)
        same_ok = json.loads(lock_path.read_text()) == rec1
        cfg_chg = _cfg_with(cfg_l, reference_visit=2)
        no_log = raises(lambda: check_baseline_lock(cfg_chg))
        log = [{"date": "2026-10-26", "reason": "instructor asked for visit 3", "change": "reference_visit 3 -> 2"}]
        cfg_chg_log = _cfg_with(cfg_l, reference_visit=2, change_log=log)
        check_baseline_lock(cfg_chg_log)
        rec2 = json.loads(lock_path.read_text())
        shrunk = raises(lambda: check_baseline_lock(_cfg_with(cfg_l, reference_visit=2, change_log=[])))
        back = raises(lambda: check_baseline_lock(cfg_l))               # reverting the definition also needs a new entry
        lock_path.write_text("{not json")
        corrupt = raises(lambda: check_baseline_lock(cfg_l))
        real_cfg = Config({**d, "data": {**d["data"], "verified": True, "plan": "A"}, "baseline": {**d["baseline"], "locked": False}}, Path(tmp))
        real_unlocked = raises(lambda: check_baseline_lock(real_cfg))

    expanded_ok = np.array_equal(unit_lab[col.inverse], res.labels)
    json_ok = True
    try:
        json.dumps(cmp_planted, allow_nan=False)
        json.dumps(cmp_c, allow_nan=False)
    except (TypeError, ValueError):
        json_ok = False
    print(f"individuals={td.n}; counts={res.counts}")
    print(f"planted pathways vs baseline: ARI={cmp_planted['ari']:.3f} NMI={cmp_planted['nmi']:.3f} "
          f"unexplained pathway entropy={cmp_planted['unexplained_pathway_entropy_share']:.3f} "
          f"spanning pathways={cmp_planted['n_pathways_spanning_classes']}/{cmp_planted['n_pathways']}")

    checks = {
        "hand fixture: labels [1,0,-1,-1,0,1] (missing and lost are never 'not employed')": _res_eq(r_h.labels, [1, 0, -1, -1, 0, 1]),
        "hand fixture: counts add up and split missing from lost": r_h.counts == {
            "n_total": 6, "n_employed": 2, "n_not_employed": 2, "n_unknown": 2, "n_unknown_missing": 1, "n_unknown_lost": 1,
            "n_unknown_policy_state": 0, "n_excluded": 2, "n_eligible": 4},
        "hand fixture: eligible_mask is labels != -1": np.array_equal(r_h.eligible_mask, r_h.labels != -1),
        "unknown as category: labels [1,0,2,2,0,1] and nobody excluded": _res_eq(r_cat.labels, [1, 0, 2, 2, 0, 1]) and r_cat.counts["n_excluded"] == 0
            and r_cat.counts["n_eligible"] == 6,
        "policy 'unobserved' state is unknown, not an observed outcome": _res_eq(r_pol.labels, [-1, 0, 1]) and r_pol.counts["n_unknown_policy_state"] == 1,
        "definition text names the visit, period and states": all(s in r_h.definition["rule"] for s in ("visit_4", "CWS", "wage_employment"))
            and r_h.definition["not_employed_states"] == ["unemployed_seeking", "out_of_labour_force", "education_training"],
        "notes: last-visit warning present, first-visit warning only for visit 0": any("last visit" in x for x in notes_last)
            and not any("last visit" in x for x in notes_first) and any("first visit" in x for x in notes_first),
        "synthetic: labels equal a slow row-by-row reference": np.array_equal(res.labels, slow),
        "synthetic: unit labels expanded through inverse equal individual labels": expanded_ok,
        "synthetic: counts consistent": res.counts["n_employed"] + res.counts["n_not_employed"] + res.counts["n_unknown"] == td.n
            and res.counts["n_eligible"] == int(m.sum()),
        "variants: labelled, flagged, differ as declared, primary untouched": var_ok,
        "variants: malformed or primary-identical definitions raise": bad_variant({"label": "x", "reference_visit": 3})
            and bad_variant({"label": "primary", "reference_visit": 0}) and bad_variant({"label": "a", "reference_visit": 0}, {"label": "a", "reference_visit": 1})
            and bad_variant({"label": "x", "colour": 1}) and bad_variant({"reference_visit": 0}) and bad_variant({"label": "x", "reference_visit": 9})
            and bad_variant({"label": "x", "employed_states": ["no_such_state"]}),
        "contradictions raise: window, all-employed, unknown state, sample rule, unknown_treatment": all(
            raises(lambda kw=kw: baseline_partition(td_h, _cfg_with(cfg, **kw))) for kw in (
                {"reference_visit": 4}, {"reference_visit": -1}, {"employed_states": list(names)}, {"employed_states": ["typo"]},
                {"employed_states": []}, {"employed_states": ["wage_employment", "wage_employment"]}, {"sample_rule": "everyone"},
                {"unknown_treatment": "impute"})),
        "contradictions raise: td is not the eligible sample, or state names differ": raises(lambda: baseline_partition(hand_td([[0, -1, -1, 0]]), cfg))
            and raises(lambda: baseline_partition(hand_td(rows, list(reversed(names))), cfg))
            and raises(lambda: baseline_partition(hand_td(rows, meta={"eligibility": {"min_time_points": 2}}), cfg)),
        "eligibility record from preprocessing is accepted": baseline_partition(hand_td([[0, -1, -1, 0]], meta={"eligibility": {"min_time_points": 3}}), cfg).counts["n_total"] == 1,
        "baseline_unit_labels refuses a reference visit outside the units": raises(lambda: baseline_unit_labels(col, _cfg_with(cfg, reference_visit=T))),
        "ARI equals the brute-force pair count and scikit-learn": abs(cmp_c["ari"] - _brute_ari(bb, pp)) < 1e-12 and abs(cmp_c["ari"] - adjusted_rand_score(bb, pp)) < 1e-12
            and abs(cmp_planted["ari"] - adjusted_rand_score(sk_b, sk_p)) < 1e-12,
        "NMI equals scikit-learn (arithmetic mean)": abs(cmp_c["nmi"] - normalized_mutual_info_score(bb, pp)) < 1e-12
            and abs(cmp_planted["nmi"] - normalized_mutual_info_score(sk_b, sk_p)) < 1e-12,
        "contingency equals the hand count": cmp_c["contingency"]["rows"] == ["not_employed", "employed"] and cmp_c["contingency"]["cols"] == [0, 1, 2, 3, 4]
            and np.array_equal(np.array(cmp_c["contingency"]["counts"]), Ch) and cmp_c["n_compared"] == 10 and cmp_c["n_excluded"] == 2,
        "entropy decomposition equals the hand calculation": abs(cmp_c["entropy"]["h_pathways_given_baseline"] - h_pg) < 1e-12
            and abs(cmp_c["entropy"]["h_pathways"] - h_p) < 1e-12 and abs(cmp_c["unexplained_pathway_entropy_share"] - h_pg / h_p) < 1e-12
            and abs(cmp_c["entropy"]["mutual_information"] - (h_p - h_pg)) < 1e-12,
        "hidden pathways inside each class (hand): not employed {3,4}, employed {0,1,2}": cmp_c["by_class"]["not_employed"]["hidden_pathways"] == [3, 4]
            and sorted(cmp_c["by_class"]["employed"]["hidden_pathways"]) == [0, 1, 2]
            and abs(cmp_c["by_class"]["employed"]["effective_n_pathways"] - 3.0) < 1e-12 and cmp_c["n_pathways_spanning_classes"] == 0,
        "perfect nesting: baseline fixes the pathway, ARI and NMI are 1": abs(cmp_perfect["ari"] - 1) < 1e-12 and abs(cmp_perfect["nmi"] - 1) < 1e-12
            and cmp_perfect["entropy"]["h_pathways_given_baseline"] < 1e-12 and cmp_perfect["unexplained_pathway_entropy_share"] < 1e-12,
        "independent labels: ARI and NMI near 0, almost all pathway entropy unexplained": abs(cmp_rand["ari"]) < 0.02 and cmp_rand["nmi"] < 0.01
            and cmp_rand["unexplained_pathway_entropy_share"] > 0.99,
        "degenerate partitions: one class and one pathway give 1, one pathway and two groups give 0": cmp_one["ari"] == 1.0 and cmp_one["nmi"] == 1.0
            and any("degenerate" in x for x in cmp_one["notes"]) and cmp_half["nmi"] == 0.0 and cmp_half["ari"] == adjusted_rand_score([1] * 5, [0, 0, 1, 1, 1]),
        "comparison runs on baseline-eligible individuals only": ncmp == int(m.sum()) and cmp_planted["n_excluded"] == td.n - int(m.sum()),
        "planted pathways: each dominant class matches its prototype's reference state": dom_ok,
        "comparison result is JSON-safe (no NaN)": json_ok,
        "comparison input errors raise": raises(lambda: compare_to_clustering(res, planted[:-1], td, cfg))
            and raises(lambda: compare_to_clustering(res, planted.astype(float) + 0.5, td, cfg))
            and raises(lambda: compare_to_clustering(res, -np.ones(td.n, np.int64), td, cfg))
            and raises(lambda: compare_to_clustering(BaselineResult(-np.ones(3, np.int64), np.zeros(3, bool), {}, {}, "p", False), np.zeros(3, np.int64), hand_td([[0, 0, 0, 0]] * 3), cfg)),
        "lock: unlocked synthetic run only warns": len(w_unlocked) == 1 and "locked is false" in str(w_unlocked[0].message),
        "lock: first locked call writes the record, a second identical call changes nothing": rec1["history"][0]["n_change_log_entries"] == 0 and same_ok,
        "lock: a changed definition without a new log entry raises": no_log,
        "lock: a changed definition with a log entry is accepted and recorded": rec2["definition"]["reference_visit"] == 2 and len(rec2["history"]) == 2
            and rec2["n_change_log_entries"] == 1,
        "lock: shrinking the change log, reverting without an entry, or a corrupt record raise": shrunk and back and corrupt,
        "lock: unlocked baseline with verified real data raises": real_unlocked,
    }
    for name, ok in checks.items():
        print(f"  demo check [{'ok' if ok else 'FAILED'}]: {name}")
    if not all(checks.values()):
        return 1
    print(f"Demo checks passed ({len(checks)}). All data above is SYNTHETIC or hand-built.")
    return 0


def _res_eq(a: np.ndarray, b: list[int]) -> bool:
    """Demo helper: labels equal a plain list."""
    return list(np.asarray(a).tolist()) == b


if __name__ == "__main__":
    raise SystemExit(_demo())
