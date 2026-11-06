"""Shared constants and data types for the employment-pathways project.

Why this file exists: every module passes the same few objects around (trajectories, collapsed
trajectories, reduction plans, clustering results). Defining them once, here, keeps the file
list exactly as specified and prevents circular imports, because this file imports only numpy
and pandas. The shapes below are the binding contract in docs/INTERFACES.md section 3.

Design choices worth defending in a viva:
  * Three different things are kept apart in the state array: observed states (0..K-1),
    MISSING (no record or unknown) and LOST (lost to follow-up, only where the data records it).
  * `freq` (individuals represented by one unique sequence) and survey `weights` are separate
    fields with separate checks, so one can never be silently used as the other.
  * Every dataclass validates its own invariants on creation, so a malformed object fails loudly
    at the place it is built instead of corrupting a metric three modules later.
  * `is_synthetic` has no default: a caller must say whether data is synthetic.

Run the smoke demo with:  python src/__init__.py
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

__all__ = [
    "MISSING",
    "LOST",
    "SYNTHETIC_LOST_CODE",
    "TrajectoryData",
    "CollapsedTrajectories",
    "ReductionPlan",
    "ClusterResult",
    "FullClustering",
    "BaselineResult",
    "StabilityResult",
]

MISSING: int = -1  # no record, or status unknown / not reported
LOST: int = -2  # lost to follow-up; used only where a non-response or casualty code is recorded
SYNTHETIC_LOST_CODE: str = "SYNTHETIC_LOST"  # generator-only sentinel; never a real-data code

_REDUCTION_MODES = ("collapse", "subsample", "collapse_then_subsample")
_CLUSTER_METHODS = ("kmedoids", "hierarchical")
_STABILITY_SCHEMES = ("random", "informative", "censoring")


def _as_index(idx: Any, n: int) -> np.ndarray:
    """Turn a boolean mask or an integer array into a validated int64 index array."""
    arr = np.asarray(idx)
    if arr.dtype == bool:
        if arr.shape != (n,):
            raise ValueError(f"boolean mask must have shape ({n},), got {arr.shape}")
        return np.flatnonzero(arr).astype(np.int64)
    arr = arr.astype(np.int64, copy=False).ravel()
    if arr.size and (arr.min() < 0 or arr.max() >= n):
        raise IndexError(f"index out of range for {n} rows")
    return arr


@dataclass
class TrajectoryData:
    """One row per trainee, one column per time point.

    states: int8 (n,T). Values 0..K-1 are observed outcome states (order = state_names),
        MISSING (-1) is no record or unknown, LOST (-2) is lost to follow-up.
    attrs: person-level attributes aligned to ids by position (profiling and eligibility only).
    weights: verified survey weight per person, or None when no weight has been verified.
    """

    ids: np.ndarray
    states: np.ndarray
    time_labels: list[str]
    state_names: list[str]
    attrs: pd.DataFrame
    weights: np.ndarray | None
    is_synthetic: bool
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.ids = np.asarray(self.ids)
        if self.ids.ndim != 1:
            raise ValueError("ids must be one-dimensional")
        states = np.asarray(self.states)
        if states.ndim != 2:
            raise ValueError("states must be two-dimensional (n, T)")
        if states.dtype != np.int8:
            if states.size and (states.min() < -128 or states.max() > 127):
                raise ValueError("state codes do not fit in int8")
            states = states.astype(np.int8)
        self.states = states
        n, t = states.shape
        if len(self.ids) != n:
            raise ValueError(f"ids has {len(self.ids)} rows but states has {n}")
        if len(self.time_labels) != t:
            raise ValueError(f"time_labels has {len(self.time_labels)} entries but T = {t}")
        k = len(self.state_names)
        if states.size and (states.min() < LOST or states.max() > k - 1):
            raise ValueError(f"state codes must lie in [{LOST}, {k - 1}] for {k} named states")
        if not isinstance(self.attrs, pd.DataFrame) or len(self.attrs) != n:
            raise ValueError("attrs must be a DataFrame with one row per id")
        self.attrs = self.attrs.reset_index(drop=True)
        if self.weights is not None:
            w = np.asarray(self.weights, dtype=np.float64)
            if w.shape != (n,):
                raise ValueError(f"weights must have shape ({n},), got {w.shape}")
            if not np.all(np.isfinite(w)) or np.any(w < 0):
                raise ValueError("survey weights must be finite and non-negative")
            self.weights = w
        self.is_synthetic = bool(self.is_synthetic)

    @property
    def n(self) -> int:
        """Number of individuals."""
        return int(self.states.shape[0])

    @property
    def T(self) -> int:
        """Number of time points."""
        return int(self.states.shape[1])

    def subset(self, idx: Any) -> "TrajectoryData":
        """Rows selected by an integer index array or a boolean mask, as a new TrajectoryData."""
        sel = _as_index(idx, self.n)
        meta = dict(self.meta)
        meta.setdefault("subset_of_n", self.n)
        return TrajectoryData(
            ids=self.ids[sel],
            states=self.states[sel],
            time_labels=list(self.time_labels),
            state_names=list(self.state_names),
            attrs=self.attrs.iloc[sel],
            weights=None if self.weights is None else self.weights[sel],
            is_synthetic=self.is_synthetic,
            meta=meta,
        )


@dataclass
class CollapsedTrajectories:
    """Unique trajectories with the number of individuals each one represents.

    The collapse key is the states plus the distance attribute inputs (attr_cols), so two
    individuals share a unit only if they are identical on every distance input.
    freq counts individuals. It is never a survey weight.
    """

    unique_states: np.ndarray
    freq: np.ndarray
    inverse: np.ndarray
    attr_cols: list[str]
    unique_attrs: np.ndarray | None

    def __post_init__(self) -> None:
        us = np.asarray(self.unique_states)
        if us.ndim != 2:
            raise ValueError("unique_states must be two-dimensional (u, T)")
        self.unique_states = us.astype(np.int8, copy=False)
        u = us.shape[0]
        self.freq = np.asarray(self.freq).astype(np.int64, copy=False)
        self.inverse = np.asarray(self.inverse).astype(np.int64, copy=False)
        if self.freq.shape != (u,):
            raise ValueError(f"freq must have shape ({u},), got {self.freq.shape}")
        if u and self.freq.min() < 1:
            raise ValueError("every unique row must represent at least one individual")
        if self.inverse.ndim != 1 or (self.inverse.size and (self.inverse.min() < 0 or self.inverse.max() >= u)):
            raise ValueError("inverse must map every individual to a valid unique row")
        if not np.array_equal(np.bincount(self.inverse, minlength=u), self.freq):
            raise ValueError("freq must equal the number of individuals mapped to each unique row")
        self.attr_cols = list(self.attr_cols)
        if self.attr_cols:
            if self.unique_attrs is None or np.asarray(self.unique_attrs).shape != (u, len(self.attr_cols)):
                raise ValueError("unique_attrs must have shape (u, len(attr_cols)) when attr_cols is set")
            self.unique_attrs = np.asarray(self.unique_attrs)
        elif self.unique_attrs is not None:
            raise ValueError("unique_attrs must be None when attr_cols is empty")

    @property
    def u(self) -> int:
        """Number of unique rows (units)."""
        return int(self.unique_states.shape[0])

    @property
    def n(self) -> int:
        """Number of individuals represented."""
        return int(self.inverse.shape[0])

    @property
    def T(self) -> int:
        """Number of time points."""
        return int(self.unique_states.shape[1])


@dataclass
class ReductionPlan:
    """Decision made BEFORE any distance matrix exists: which units the matrix is built on."""

    mode_requested: str
    mode_used: str
    col_all: CollapsedTrajectories
    col_fit: CollapsedTrajectories
    fit_unit_idx: np.ndarray | None
    n_individuals: int
    n_units_all: int
    n_units_fit: int
    est_peak_mb: float
    cap_mb: float
    max_n: int
    reason: str

    def __post_init__(self) -> None:
        for name in ("mode_requested", "mode_used"):
            if getattr(self, name) not in _REDUCTION_MODES:
                raise ValueError(f"{name} must be one of {_REDUCTION_MODES}")
        if self.n_individuals != self.col_all.n:
            raise ValueError("n_individuals must equal col_all.n")
        if self.n_units_all != self.col_all.u:
            raise ValueError("n_units_all must equal col_all.u")
        if self.n_units_fit != self.col_fit.u:
            raise ValueError("n_units_fit must equal col_fit.u")
        if self.fit_unit_idx is None:
            if self.col_fit.u != self.col_all.u:
                raise ValueError("fit_unit_idx may be None only when every unit is in the fit set")
        else:
            self.fit_unit_idx = np.asarray(self.fit_unit_idx).astype(np.int64, copy=False)
            if self.fit_unit_idx.shape != (self.col_fit.u,):
                raise ValueError("fit_unit_idx must have one entry per fit unit")
            if self.fit_unit_idx.size and (
                self.fit_unit_idx.min() < 0 or self.fit_unit_idx.max() >= self.col_all.u
            ):
                raise ValueError("fit_unit_idx points outside col_all")


@dataclass
class ClusterResult:
    """Result of one clustering over the rows of one distance matrix."""

    labels: np.ndarray
    medoid_idx: np.ndarray
    k: int
    cost: float
    method: str
    converged: bool
    n_iter: int

    def __post_init__(self) -> None:
        self.labels = np.asarray(self.labels).astype(np.int64, copy=False)
        self.medoid_idx = np.asarray(self.medoid_idx).astype(np.int64, copy=False)
        if self.method not in _CLUSTER_METHODS:
            raise ValueError(f"method must be one of {_CLUSTER_METHODS}")
        if self.k < 1 or self.medoid_idx.shape != (self.k,):
            raise ValueError("medoid_idx must have exactly k entries")
        if self.labels.size and (self.labels.min() < 0 or self.labels.max() >= self.k):
            raise ValueError("labels must lie in [0, k-1]")


@dataclass
class FullClustering:
    """A clustering extended from the fit set to every unit and every individual."""

    plan: ReductionPlan
    fit_result: ClusterResult
    unit_labels: np.ndarray
    full_labels: np.ndarray
    medoid_states: np.ndarray
    medoid_attrs: np.ndarray | None

    def __post_init__(self) -> None:
        self.unit_labels = np.asarray(self.unit_labels).astype(np.int64, copy=False)
        self.full_labels = np.asarray(self.full_labels).astype(np.int64, copy=False)
        self.medoid_states = np.asarray(self.medoid_states).astype(np.int8, copy=False)
        col_all = self.plan.col_all
        if self.unit_labels.shape != (col_all.u,):
            raise ValueError("unit_labels must have one entry per unit in plan.col_all")
        if self.full_labels.shape != (col_all.n,):
            raise ValueError("full_labels must have one entry per individual")
        if not np.array_equal(self.full_labels, self.unit_labels[col_all.inverse]):
            raise ValueError("full_labels must equal unit_labels[col_all.inverse]")
        if self.medoid_states.shape != (self.fit_result.k, col_all.T):
            raise ValueError("medoid_states must have shape (k, T)")


@dataclass
class BaselineResult:
    """Employed-versus-not partition of the same trainees.

    labels: -1 = excluded, 0 = not employed, 1 = employed, and 2 = unknown, which exists only
    when baseline.unknown_treatment is "category" (an explicit third class instead of exclusion).
    """

    labels: np.ndarray
    eligible_mask: np.ndarray
    counts: dict[str, int]
    definition: dict[str, Any]
    label: str
    is_sensitivity: bool

    def __post_init__(self) -> None:
        self.labels = np.asarray(self.labels).astype(np.int64, copy=False)
        self.eligible_mask = np.asarray(self.eligible_mask, dtype=bool)
        if self.labels.shape != self.eligible_mask.shape or self.labels.ndim != 1:
            raise ValueError("labels and eligible_mask must be one-dimensional and the same length")
        if self.labels.size and (self.labels.min() < -1 or self.labels.max() > 2):
            raise ValueError("baseline labels must be in {-1, 0, 1, 2}")
        if not np.array_equal(self.eligible_mask, self.labels != -1):
            raise ValueError("eligible_mask must be exactly (labels != -1)")
        self.is_sensitivity = bool(self.is_sensitivity)


@dataclass
class StabilityResult:
    """Adjusted Rand index per repeat and per-pathway survival for one attrition setting."""

    scheme: str
    level: float
    ari: np.ndarray
    survival: pd.DataFrame

    def __post_init__(self) -> None:
        if self.scheme not in _STABILITY_SCHEMES:
            raise ValueError(f"scheme must be one of {_STABILITY_SCHEMES}")
        self.ari = np.asarray(self.ari, dtype=np.float64)
        if self.ari.ndim != 1:
            raise ValueError("ari must be one-dimensional (one value per repeat)")


if __name__ == "__main__":
    # Smoke demo: build a tiny TrajectoryData, collapse it by hand, and show the invariants hold.
    states = np.array(
        [[0, 0, 1, 1], [0, 0, 1, 1], [2, 2, MISSING, 2], [2, 2, MISSING, 2], [1, LOST, LOST, LOST]],
        dtype=np.int8,
    )
    td = TrajectoryData(
        ids=np.array(["a", "b", "c", "d", "e"]),
        states=states,
        time_labels=["t0", "t1", "t2", "t3"],
        state_names=["wage", "self", "oolf"],
        attrs=pd.DataFrame({"age": [21, 22, 23, 24, 25]}),
        weights=None,
        is_synthetic=True,
        meta={"note": "hand-built demo, not a result"},
    )
    uniq, first, inverse = np.unique(td.states, axis=0, return_index=True, return_inverse=True)
    col = CollapsedTrajectories(
        unique_states=uniq,
        freq=np.bincount(inverse.ravel()),
        inverse=inverse.ravel(),
        attr_cols=[],
        unique_attrs=None,
    )
    print(f"TrajectoryData: n={td.n}, T={td.T}, synthetic={td.is_synthetic}")
    print(f"Collapsed: u={col.u} unique rows, freq={col.freq.tolist()}, individuals={col.n}")
    print(f"Subset of 2 rows -> n={td.subset([0, 4]).n}, mask subset -> n={td.subset(td.states[:, 0] == 2).n}")
    for label, bad in {
        "freq that is not the individual count": lambda: CollapsedTrajectories(
            uniq, col.freq + 1, inverse.ravel(), [], None
        ),
        "state code outside the declared states": lambda: TrajectoryData(
            td.ids, states + 5, td.time_labels, td.state_names, td.attrs, None, True
        ),
    }.items():
        try:
            bad()
        except ValueError as exc:
            print(f"Rejected as expected ({label}): {exc}")
