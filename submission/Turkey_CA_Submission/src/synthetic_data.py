"""Synthetic data for PIPELINE TESTING and planted-structure validation. It is never a result.

Why this file exists: before real PLFS files are available and verified, every later module still
has to be built and tested on data whose true structure is known. This module makes a long panel
in the raw-coded shape the real loader will produce, with a known set of planted pathways, so that
a clustering run can be scored against the truth (CHECKPOINT 2). Everything it returns is marked
`is_synthetic=True`, and every artifact derived from it must carry the SYNTHETIC tag
(`result_tag(True)`), because nothing here describes real people.

What it generates, from `config.yaml` only (`synthetic.*`, `states`, `unknown_codes`, `lost_codes`,
`time.n_points`):
  * `synthetic.planted`: pathways with a prevalence and a prototype state sequence. Pathway sizes
    are fixed by largest-remainder rounding of `prevalence * n`, so the planted share is exact and
    tests do not depend on sampling luck. Which person gets which pathway is shuffled.
  * `synthetic.noise`: probability that an observed time point is replaced by a state drawn
    uniformly from all K states. Because the draw can return the planted state, the effective
    change probability is noise * (K - 1) / K.
  * `synthetic.missing_rate`: probability that a time point is not observed. An unobserved point
    becomes, with fixed probabilities, no row at all (50%), a row carrying the unknown code (30%),
    or a row carrying a lost-to-follow-up code in the non-response column (20%). Dropout is NOT
    modelled as monotone here; attrition experiments belong to `stability.py`, which applies them
    to whatever data it is given.

Design choices worth defending in a viva:
  * Raw codes are taken from the config state mapping (the first raw code of each state), so the
    real mapping path in `trajectories.map_raw_to_state` is exercised, not bypassed. Codes are
    returned as text, as the real loader does.
  * Every person keeps at least one observed row, so the sample size of the panel equals `n`.
  * Sex, sector and weight are generated independently of the pathway, so a profiling test can
    verify that "no difference" is reported as no difference. Age is planted with a pathway-specific
    mean, so a profiling test can verify that a real difference is found. Sex is protected
    (profiling only) and is never an input of anything here.
  * All randomness comes from `make_rng(cfg, "synthetic/<seed_offset>")`: the same config and
    offset give the same data; a different offset gives an independent draw.

Run the smoke demo with:  python -m src.synthetic_data
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from . import TrajectoryData, LOST, MISSING, SYNTHETIC_LOST_CODE
from .config import Config, ConfigError, load_config, make_rng

__all__ = ["PlantedTruth", "demo_trajectory_data", "generate_synthetic", "PERSON_ID_FORMAT"]

PERSON_ID_FORMAT = "S{:06d}"            # labels[i] belongs to the person PERSON_ID_FORMAT.format(i)
P_ABSENT, P_UNKNOWN, P_LOST = 0.5, 0.3, 0.2   # split of unobserved points (sums to 1)
AGE_BASE, AGE_STEP, AGE_SD = 22.0, 2.0, 4.0   # planted age mean = AGE_BASE + AGE_STEP * pathway index
AGE_MIN, AGE_MAX = 18, 45
WEIGHT_SCALE, WEIGHT_SIGMA = 1000.0, 0.4      # synthetic weight = WEIGHT_SCALE * lognormal(0, SIGMA)


@dataclass
class PlantedTruth:
    """The structure hidden in a synthetic panel, for scoring recovery. Never used by any method."""

    labels: np.ndarray        # (n,) pathway index of each person; person i has id PERSON_ID_FORMAT.format(i)
    prototypes: np.ndarray    # (P,T) int8 planted state sequences
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.labels = np.asarray(self.labels, dtype=np.int64)
        self.prototypes = np.asarray(self.prototypes, dtype=np.int8)
        if self.labels.ndim != 1 or self.prototypes.ndim != 2:
            raise ValueError("labels must be (n,) and prototypes (P,T)")
        if self.labels.size and (self.labels.min() < 0 or self.labels.max() >= len(self.prototypes)):
            raise ValueError("labels refer to a pathway that does not exist")


# ---------------------------------------------------------------------------------------------
# Config reading
# ---------------------------------------------------------------------------------------------
def _state_setup(cfg: Config) -> tuple[list[str], list[str], str, str]:
    """State names, the first raw code of each state, the unknown code and the lost code (all text)."""
    d = cfg.to_dict()
    names = [s["name"] for s in d["states"]]
    codes = []
    for s in d["states"]:
        available = s.get("raw_codes") or s.get("synthetic_codes") or []
        if not available:
            raise ConfigError(f"state {s['name']!r} has no code for synthetic generation")
        codes.append(str(available[0]))
    if not d["unknown_codes"]:
        raise ConfigError("unknown_codes must hold at least one code for the generator")
    # The real PLFS mapping may correctly have no documented casualty code. Synthetic fixtures
    # still need LOST examples, so use an unmistakable generator-only sentinel in that case.
    lost_code = str(d["lost_codes"][0]) if d["lost_codes"] else SYNTHETIC_LOST_CODE
    return names, codes, str(d["unknown_codes"][0]), lost_code


def _planted_setup(cfg: Config, names: list[str]) -> tuple[list[str], np.ndarray, np.ndarray]:
    """Pathway names, prevalences and the prototype matrix, validated against the state list."""
    d = cfg.to_dict()
    T = int(d["time"]["n_points"])
    planted = d["synthetic"]["planted"]
    if not planted:
        raise ConfigError("synthetic.planted is empty: no pathways to plant")
    index = {nm: i for i, nm in enumerate(names)}
    pnames, prev, protos = [], [], []
    for p in planted:
        proto = list(p["prototype"])
        if len(proto) != T:
            raise ConfigError(f"planted pathway {p['name']!r}: prototype has {len(proto)} entries, "
                              f"time.n_points is {T}")
        bad = [x for x in proto if x not in index]
        if bad:
            raise ConfigError(f"planted pathway {p['name']!r}: unknown state name(s) {sorted(set(bad))}")
        pnames.append(str(p["name"]))
        prev.append(float(p["prevalence"]))
        protos.append([index[x] for x in proto])
    prev_a = np.asarray(prev, dtype=float)
    if np.any(prev_a < 0) or abs(prev_a.sum() - 1.0) > 1e-6:
        raise ConfigError(f"planted prevalences must be non-negative and sum to 1, got sum {prev_a.sum():.6f}")
    return pnames, prev_a, np.asarray(protos, dtype=np.int8)


def _sizes(prevalence: np.ndarray, n: int) -> np.ndarray:
    """Pathway sizes by largest-remainder rounding of prevalence * n (ties go to the lowest index)."""
    raw = prevalence * n
    sizes = np.floor(raw).astype(np.int64)
    short = n - int(sizes.sum())
    if short > 0:
        order = np.lexsort((np.arange(len(raw)), -(raw - sizes)))   # largest remainder first, then lowest index
        sizes[order[:short]] += 1
    return sizes


# ---------------------------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------------------------
def generate_synthetic(cfg: Config, n: int | None = None, missing_rate: float | None = None,
                       seed_offset: int = 0) -> tuple[pd.DataFrame, PlantedTruth]:
    """A raw-coded long panel with planted pathways, and the truth that made it.

    Columns: person_id, t, raw_status, nonresponse_code, weight, age, sex, sector, trained,
    is_synthetic. `trained` is "Y" for everyone: every synthetic person is a planted trainee.
    A missing record has no row; an unknown record has the unknown code in raw_status; a lost
    record has a missing raw_status and the lost code in nonresponse_code.
    """
    d = cfg.to_dict()
    syn = d["synthetic"]
    n = int(syn["n"] if n is None else n)
    miss = float(syn["missing_rate"] if missing_rate is None else missing_rate)
    noise = float(syn["noise"])
    if not 0.0 <= miss < 1.0:
        raise ValueError(f"missing_rate must lie in [0, 1), got {miss}")
    if not 0.0 <= noise <= 1.0:
        raise ValueError(f"synthetic.noise must lie in [0, 1], got {noise}")
    names, codes, unknown_code, lost_code = _state_setup(cfg)
    pnames, prevalence, protos = _planted_setup(cfg, names)
    P, T, K = len(pnames), protos.shape[1], len(names)
    if n < P:
        raise ValueError(f"n={n} is smaller than the number of planted pathways ({P})")
    rng = make_rng(cfg, f"synthetic/{int(seed_offset)}")

    # Planted pathway of each person: exact sizes, shuffled assignment.
    sizes = _sizes(prevalence, n)
    labels = rng.permutation(np.repeat(np.arange(P), sizes))
    true_states = protos[labels]                                     # (n,T), the noiseless truth
    flip = rng.random((n, T)) < noise
    states = np.where(flip, rng.integers(0, K, size=(n, T)), true_states)

    # Which points are unobserved, and in which way.
    unobs = rng.random((n, T)) < miss
    kind = rng.random((n, T))
    absent = unobs & (kind < P_ABSENT)
    unknown = unobs & (kind >= P_ABSENT) & (kind < P_ABSENT + P_UNKNOWN)
    lost = unobs & (kind >= P_ABSENT + P_UNKNOWN)
    empty = absent.all(axis=1)                                       # keep at least one observed row per person
    absent[empty, 0], unknown[empty, 0], lost[empty, 0] = False, False, False

    raw = np.array(codes, dtype=object)[states]
    raw[unknown] = unknown_code
    raw[lost] = None
    nonresp = np.full((n, T), None, dtype=object)
    nonresp[lost] = lost_code

    # Person-level attributes (age depends on the pathway; sex, sector and weight do not).
    age = np.clip(np.rint(rng.normal(AGE_BASE + AGE_STEP * labels, AGE_SD)), AGE_MIN, AGE_MAX).astype(int)
    sex = rng.choice(np.array(["M", "F"], dtype=object), size=n)
    sector = rng.choice(np.array(["U", "R"], dtype=object), size=n)
    weight = np.round(WEIGHT_SCALE * rng.lognormal(0.0, WEIGHT_SIGMA, size=n), 3)

    keep = ~absent
    person_idx, t_idx = np.nonzero(keep)                             # row-major: person, then time
    ids = np.array([PERSON_ID_FORMAT.format(i) for i in range(n)], dtype=object)
    long_df = pd.DataFrame({
        "person_id": ids[person_idx],
        "t": t_idx.astype(int),
        "raw_status": raw[person_idx, t_idx],
        "nonresponse_code": nonresp[person_idx, t_idx],
        "weight": weight[person_idx],
        "age": age[person_idx],
        "sex": sex[person_idx],
        "sector": sector[person_idx],
        "trained": "Y",
        "is_synthetic": True,
    })
    truth = PlantedTruth(
        labels=labels, prototypes=protos,
        params={"n": n, "T": T, "K": K, "noise": noise, "missing_rate": miss, "seed_offset": int(seed_offset),
                "pathway_names": pnames, "prevalence": prevalence.tolist(), "sizes": sizes.tolist(),
                "state_names": names, "id_format": PERSON_ID_FORMAT,
                "unobserved_split": {"absent": P_ABSENT, "unknown": P_UNKNOWN, "lost": P_LOST},
                "age_mean_by_pathway": [AGE_BASE + AGE_STEP * p for p in range(P)],
                "is_synthetic": True})
    return long_df, truth


def demo_trajectory_data(cfg: Config | None = None) -> TrajectoryData:
    """Twelve hand-built trainees in three groups, with a few MISSING and one LOST entry. Deterministic.

    Used by the preprocessing and missing_data smoke demos, so it needs no random draws and imports
    nothing later in the dependency order. Groups: stably in the first state; unemployed then
    employed; out of the labour force throughout. State indices are clipped to the configured K.
    """
    cfg = load_config() if cfg is None else cfg
    d = cfg.to_dict()
    names = [s["name"] for s in d["states"]]
    labels = list(d["time"]["labels"])
    T, K = len(labels), len(names)
    first, jobless, out = 0, min(3, K - 1), min(4, K - 1)
    half = max(1, T // 2)
    patterns = [[first] * T, [jobless] * half + [first] * (T - half), [out] * T]
    n = 12
    states = np.array([patterns[i % 3] for i in range(n)], dtype=np.int8)
    states[3, min(2, T - 1)] = MISSING          # one unknown or absent record
    states[7, 0] = MISSING
    states[11, T - 1] = LOST                    # one lost-to-follow-up record
    attrs = pd.DataFrame({
        "age": np.array([19, 22, 25, 28, 21, 24, 27, 30, 20, 23, 26, 29], dtype=float),
        "sex": ["F", "M"] * 6,
        "sector": ["U", "R", "U"] * 4,
    })
    return TrajectoryData(
        ids=np.array([f"D{i:02d}" for i in range(n)], dtype=object),
        states=states, time_labels=labels, state_names=names, attrs=attrs, weights=None,
        is_synthetic=True, meta={"source": "demo_trajectory_data", "groups": ["stable_first", "jobless_to_first", "out"]})


# ---------------------------------------------------------------------------------------------
# Smoke demo
# ---------------------------------------------------------------------------------------------
def _demo() -> int:
    cfg = load_config()
    df, truth = generate_synthetic(cfg)
    p = truth.params
    names, codes, unknown_code, lost_code = _state_setup(cfg)
    print("SYNTHETIC DEMONSTRATION - NOT PLFS RESULTS")
    print(f"rows={len(df)}  persons={df['person_id'].nunique()}  columns={list(df.columns)}")
    print(f"planted pathways: {dict(zip(p['pathway_names'], p['sizes']))}")

    # Rebuild states from the raw codes with a local mapping (the real mapper comes later).
    code_to_state = {c: i for i, c in enumerate(codes)}
    n, T = p["n"], p["T"]
    got = np.full((n, T), MISSING, dtype=np.int16)
    pid = df["person_id"].str[1:].astype(int).to_numpy()
    for r_p, r_t, r_raw in zip(pid, df["t"].to_numpy(), df["raw_status"].to_numpy()):
        if r_raw is not None and r_raw in code_to_state:
            got[r_p, r_t] = code_to_state[r_raw]
    observed = got >= 0
    agree = float((got[observed] == truth.prototypes[truth.labels][observed]).mean())
    expect = 1 - p["noise"] * (p["K"] - 1) / p["K"]
    n_unknown = int((df["raw_status"] == unknown_code).sum())
    n_lost = int((df["nonresponse_code"] == lost_code).sum())
    n_absent = n * T - len(df)
    unobs = (n_absent + n_unknown + n_lost) / (n * T)
    ages = np.array([df.loc[df["person_id"].str[1:].astype(int).isin(np.flatnonzero(truth.labels == k)), "age"].mean()
                     for k in range(len(p["sizes"]))])
    same_again, _ = generate_synthetic(cfg)
    other, _ = generate_synthetic(cfg, seed_offset=1)
    checks = {
        "every person has a row": df["person_id"].nunique() == n,
        "planted sizes exact": np.bincount(truth.labels, minlength=len(p["sizes"])).tolist() == p["sizes"],
        "sizes sum to n": sum(p["sizes"]) == n,
        f"state agreement near {expect:.3f} (got {agree:.3f})": abs(agree - expect) < 0.01,
        f"unobserved share near {p['missing_rate']:.2f} (got {unobs:.3f})": abs(unobs - p["missing_rate"]) < 0.01,
        "all three unobserved kinds occur": min(n_absent, n_unknown, n_lost) > 0,
        "lost rows have no raw status": bool(df.loc[df["nonresponse_code"] == lost_code, "raw_status"].isna().all()),
        "age rises with pathway index": bool(np.all(np.diff(ages) > 0)),
        "same seed reproduces exactly": df.equals(same_again),
        "other offset differs": not df.equals(other),
        "all rows flagged synthetic": bool(df["is_synthetic"].all()),
    }
    demo = demo_trajectory_data(cfg)
    checks["demo_trajectory_data builds"] = demo.n == 12 and demo.is_synthetic and (demo.states == LOST).sum() == 1
    for name, ok in checks.items():
        print(f"  demo check [{'ok' if ok else 'FAILED'}]: {name}")
    if not all(checks.values()):
        return 1
    print(f"Demo checks passed ({len(checks)}). All data above is SYNTHETIC.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_demo())
