"""Data feasibility audit (the gate, CHECKPOINT 1): can these files support trajectories at all?

Why this file exists: the project is only valid if the same person is seen at two or more time
points through a verified linking key, and if trainees can be identified. No amount of modelling
can fix a file that cannot support that, so this audit runs first on the REAL files and reports
facts, not guesses. Every file fact (columns, codes, reference periods, designs) comes from
config.yaml, which you verify against the official data dictionary; this file never assumes a
PLFS column name, code or visit structure. It also never prints a record or an identifier, only
counts.

What it reports: linkage rate and time points per person, link-validity checks (is the key
unique within a time point, do sex and age stay consistent along a link), sector and period
coverage, the size of the trainee subgroup under each trainee definition and how many survive
linkage, training-variable code lists and their universe, missingness, and non-response codes.

Layout format (config data.layouts.<file id>), read by `read_table`:
    format: csv | fixed_width        encoding: utf-8        sep: ","  (csv only)
    chunksize: 200000                (optional)
    columns:
      <column name>:                 # the name used everywhere else (data.schema, trainee rules)
        source: <header name>        # csv only; defaults to the column name
        start: 1, end: 3             # fixed_width only; 1-based, inclusive byte positions
        dtype: str | int | float     # default str (codes are kept as text so "01" stays "01")
        label: "<verbatim text from the data dictionary>"     # used to find what a variable refers to
        codes: {<code>: <meaning>}   # optional, from the dictionary
        na_codes: [<code>, ...]      # optional: codes that mean "not applicable"
        refers_to: [<item>, ...]     # optional: what the dictionary says it refers to
`data.schema.household_id` and `person_id` may each be one column or a list of columns; the
linking key is the tuple of all of them. The time point of a record is the value of the
`data.schema.visit` column (or `month` if there is no visit column) when the file has it,
otherwise the file's declared `period`.

Design choices worth defending in a viva:
  * Records are never pooled across designs. If the primary person files declare more than one
    design_id (for example before and after the 2025 PLFS redesign), linkage and trainee counts
    are reported separately for each design, because pooling them would invent trajectories.
  * Linking validity is TESTED, not assumed: a key that repeats within one time point is not a
    person key, and a link along which sex flips or age jumps is probably a mis-link. Sex is used
    here only to validate links; it is never a profile or clustering input.
  * Every training variable is reported file by file with its exact code list, because code
    lists differ between releases. `refers_to_ambiguous` is True when the label points to more
    than one item (for example a vocational course or an exam course) or to nothing at all, so a
    completion flag is never treated as dating vocational training without confirmation.
  * Codes are compared as text, and only an empty field counts as blank, so a real code such as
    "NA" is never silently turned into missing.
  * Counts are computed on declared columns only, in chunks, so large files stay within memory.

Run from the project root:
    python -m src.data_audit --config config.yaml     # audit real files, write the JSON result
    python -m src.data_audit --demo                   # smoke demo on a tiny SYNTHETIC dataset
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import Config, ConfigError, load_config, make_rng, resolve_path, result_tag

__all__ = [
    "read_table",
    "file_hashes",
    "check_schema",
    "design_report",
    "linkage_report",
    "coverage_report",
    "training_variable_report",
    "trainee_report",
    "missingness_report",
    "nonresponse_report",
    "run_audit",
    "format_audit",
    "main",
]

DEFAULT_CHUNKSIZE = 200_000
AGE_BANDS: list[tuple[str, float, float]] = [
    ("0-14", 0, 14), ("15-29", 15, 29), ("30-44", 30, 44), ("45-59", 45, 59), ("60+", 60, 1e9),
]
MAX_AGE_DIFF = 1.0          # legacy proposal only; not applied without an official documented tolerance
MAX_CODES_LISTED = 500      # cap on distinct codes stored per variable
BLANK = "<blank>"


# ---------------------------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------------------------
def _clean(df: pd.DataFrame) -> pd.DataFrame:
    """Trim whitespace; an empty field becomes missing. Nothing else is treated as missing."""
    for col in df.columns:
        s = df[col].astype("string").str.strip()
        df[col] = s.mask((s == "").fillna(False).astype(bool))
    return df


def read_table(path: Path, layout: dict) -> pd.DataFrame:
    """Read ONLY the declared columns of one file, in chunks, as text (numbers where dtype says so).

    csv: header names come from `source`. fixed_width: `start`/`end` are 1-based inclusive byte
    positions. Raises FileNotFoundError or ValueError with a message saying what to fix.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"data file not found: {path}")
    cols = layout.get("columns") or {}
    if not cols:
        raise ValueError("layout declares no columns")
    fmt = str(layout.get("format", "")).lower()
    encoding = layout.get("encoding", "utf-8")
    chunksize = int(layout.get("chunksize", DEFAULT_CHUNKSIZE))
    names = list(cols)
    specs = {n: (cols[n] or {}) for n in names}
    na_kw = dict(keep_default_na=False, na_values=[""])

    if fmt == "csv":
        sep = layout.get("sep", ",")
        sources = {n: specs[n].get("source") or n for n in names}
        header = pd.read_csv(path, sep=sep, encoding=encoding, nrows=0, dtype=str)
        missing = sorted({s for s in sources.values() if s not in header.columns})
        if missing:
            raise ValueError(f"{path.name}: header lacks columns {missing}; found {list(header.columns)[:15]}")
        unique_sources = list(dict.fromkeys(sources.values()))
        reader = pd.read_csv(path, sep=sep, encoding=encoding, dtype=str, usecols=unique_sources,
                             chunksize=chunksize, **na_kw)
        chunks = [pd.DataFrame({n: ch[sources[n]] for n in names}) for ch in reader]
    elif fmt == "fixed_width":
        colspecs = []
        for n in names:
            s, e = specs[n].get("start"), specs[n].get("end")
            if not (isinstance(s, int) and isinstance(e, int) and 1 <= s <= e):
                raise ValueError(f"column {n!r}: fixed_width needs integer start <= end (1-based inclusive)")
            colspecs.append((s - 1, e))
        reader = pd.read_fwf(path, colspecs=colspecs, names=names, header=None, dtype=str,
                             encoding=encoding, chunksize=chunksize, **na_kw)
        chunks = list(reader)
    else:
        raise ValueError(f"layout format must be 'csv' or 'fixed_width', got {fmt!r}")

    df = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame({n: [] for n in names})
    df = _clean(df)
    for n in names:
        if str(specs[n].get("dtype", "str")).lower() in ("int", "float", "numeric"):
            df[n] = pd.to_numeric(df[n], errors="coerce").astype("float64")
    return df


def file_hashes(cfg: Config) -> dict[str, str]:
    """SHA-256 of every configured data file (or "MISSING"), keyed by file id."""
    out: dict[str, str] = {}
    for entry in cfg.to_dict()["data"]["files"]:
        path = cfg.root / entry["path"]
        if not path.is_file():
            out[entry["id"]] = "MISSING"
            continue
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
        out[entry["id"]] = h.hexdigest()
    return out


# ---------------------------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------------------------
def _entries(cfg: Config) -> list[dict[str, Any]]:
    return cfg.to_dict()["data"]["files"]


def _schema(cfg: Config) -> dict[str, Any]:
    return cfg.to_dict()["data"]["schema"]


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


def _time_col(schema: dict[str, Any]) -> str | None:
    cols = _as_list(schema.get("visit")) or _as_list(schema.get("month"))
    return cols[0] if cols else None


def _key_cols(schema: dict[str, Any]) -> list[str]:
    return _as_list(schema.get("household_id")) + _as_list(schema.get("person_id"))


def _person_tables(tables: dict[str, pd.DataFrame], cfg: Config, primary_only: bool = True,
                   design: str | None = None) -> list[tuple[dict[str, Any], pd.DataFrame]]:
    out = []
    for e in _entries(cfg):
        if e.get("kind") != "person":
            continue
        if primary_only and e.get("role", "primary") != "primary":
            continue
        if design is not None and str(e.get("design_id")) != design:
            continue
        if e["id"] in tables:
            out.append((e, tables[e["id"]]))
    return out


def _primary_designs(tables: dict[str, pd.DataFrame], cfg: Config) -> list[str]:
    """Distinct design ids among the primary person files that were read (records are never pooled across them)."""
    return sorted({str(e.get("design_id")) for e, _ in _person_tables(tables, cfg)})


def _sorted_labels(labels: Any) -> list[str]:
    labels = [str(x) for x in labels]
    try:
        return sorted(labels, key=float)
    except ValueError:
        return sorted(labels)


def _make_key(df: pd.DataFrame, cols: list[str]) -> pd.Series:
    key = None
    bad = pd.Series(False, index=df.index)
    for c in cols:
        s = df[c]
        bad = bad | s.isna()
        s = s.astype(str)
        key = s if key is None else key + "|" + s
    return key.mask(bad)


def _counts(s: pd.Series, cap: int = MAX_CODES_LISTED) -> dict[str, int]:
    vc = s.value_counts(dropna=False)
    out: dict[str, int] = {}
    for k, v in vc.items():
        out[BLANK if pd.isna(k) else str(k)] = int(v)
        if len(out) >= cap:
            break
    return out


def _person_frame(tables: dict[str, pd.DataFrame], cfg: Config, design: str | None = None
                  ) -> tuple[pd.DataFrame, list[str]]:
    """One row per record of the primary person files (of one design if given): link key, time label,
    file id, age, sex, sector."""
    schema = _schema(cfg)
    issues: list[str] = []
    key_cols = _key_cols(schema)
    tcol = _time_col(schema)
    age_col = (_as_list(schema.get("age")) or [None])[0]
    sex_col = (_as_list(schema.get("sex")) or [None])[0]
    sec_col = (_as_list(schema.get("sector")) or [None])[0]
    quarter_col = (_as_list(schema.get("quarter")) or [None])[0]
    if not key_cols:
        issues.append("neither data.schema.household_id nor data.schema.person_id is set: no linking key, "
                      "so linkage cannot be assessed")
    parts = []
    for entry, df in _person_tables(tables, cfg, design=design):
        absent = [c for c in key_cols if c not in df.columns]
        if absent or not key_cols:
            if absent:
                issues.append(f"file {entry['id']}: key column(s) {absent} not in the table")
            continue
        if tcol and tcol in df.columns:
            t = df[tcol].astype("string").fillna("UNKNOWN")
        else:
            t = pd.Series(str(entry.get("period") or "UNKNOWN"), index=df.index, dtype="string")
            if not entry.get("period"):
                issues.append(f"file {entry['id']}: no time column and no declared period; "
                              "its records get the time label UNKNOWN")
        part = pd.DataFrame({
            "key": _make_key(df, key_cols),
            "t": t.astype(str),
            "file_id": entry["id"],
            "age": pd.to_numeric(df[age_col], errors="coerce") if age_col and age_col in df.columns else np.nan,
            "sex": df[sex_col].astype("string") if sex_col and sex_col in df.columns else pd.NA,
            "sector": df[sec_col].astype("string") if sec_col and sec_col in df.columns else pd.NA,
        })
        if quarter_col:
            if quarter_col in df.columns:
                part["quarter"] = df[quarter_col].astype("string")
            else:
                issues.append(f"file {entry['id']}: configured quarter column {quarter_col!r} is not in the table")
                part["quarter"] = pd.Series(pd.NA, index=df.index, dtype="string")
        parts.append(part)
    if not parts:
        return pd.DataFrame(columns=["key", "t", "file_id", "age", "sex", "sector"]), issues
    return pd.concat(parts, ignore_index=True), issues


# ---------------------------------------------------------------------------------------------
# Schema and design
# ---------------------------------------------------------------------------------------------
def check_schema(tables: dict[str, pd.DataFrame], cfg: Config) -> list[str]:
    """Loud, specific messages about every mismatch between config.yaml and the tables read."""
    msgs: list[str] = []
    data = cfg.to_dict()
    schema, entries = data["data"]["schema"], data["data"]["files"]
    layouts = data["data"]["layouts"] or {}
    if not entries:
        msgs.append("data.files is empty: nothing to audit. Fill data.files and data.layouts first.")
    for e in entries:
        if e["id"] not in layouts:
            msgs.append(f"file {e['id']}: no layout under data.layouts.{e['id']}")
        elif e["id"] not in tables:
            msgs.append(f"file {e['id']}: could not be read (see 'read_errors' in the audit)")
    if not data["data"]["verified"]:
        msgs.append("data.verified is false: the mapping in config.yaml is not yet attested by you")
    placeholders = [str(c) for s in data["states"] for c in s["raw_codes"] if str(c).startswith("UNVERIFIED:")]
    placeholders += [str(c) for k in ("unknown_codes", "lost_codes") for c in data[k] if str(c).startswith("UNVERIFIED:")]
    if placeholders:
        msgs.append(f"{len(placeholders)} raw code(s) in states/unknown_codes/lost_codes are still "
                    "'UNVERIFIED:' placeholders: map the real codes from the data dictionary")
    for role in ("person_id", "household_id", "status_col"):
        if not _as_list(schema.get(role)):
            msgs.append(f"data.schema.{role} is not set")
    if not _time_col(schema):
        msgs.append("neither data.schema.visit nor data.schema.month is set: time points come from each "
                    "file's declared period")
    if not _as_list(schema.get("weight")):
        msgs.append("data.schema.weight is not set: prevalence will be unweighted only (set it only after you "
                    "verify which multiplier applies to revisit records)")
    if not _as_list(schema.get("nonresponse_col")):
        msgs.append("data.schema.nonresponse_col is not set: no record can be classified as lost to follow-up, "
                    "so the LOST code will not be used")
    all_cols = set().union(*[set(df.columns) for df in tables.values()]) if tables else set()
    for role, value in schema.items():
        for col in _as_list(value):
            if tables and col not in all_cols:
                msgs.append(f"data.schema.{role}: column {col!r} is in none of the tables read")
    person = _person_tables(tables, cfg, primary_only=False)
    for e, df in person:
        for col in _as_list(schema.get("status_col")):
            if col not in df.columns:
                msgs.append(f"file {e['id']}: status_col {col!r} is not in this person file")
    # status codes present in the data but not mapped in config
    status_cols = _as_list(schema.get("status_col"))
    if status_cols and person:
        known = {str(c) for s in data["states"] for c in s["raw_codes"]}
        known |= {str(c) for c in data["unknown_codes"]} | {str(c) for c in data["lost_codes"]}
        seen: dict[str, int] = {}
        for e, df in person:
            if status_cols[0] in df.columns:
                for k, v in _counts(df[status_cols[0]]).items():
                    if k != BLANK:
                        seen[k] = seen.get(k, 0) + v
        unmapped = {k: v for k, v in seen.items() if k not in known and not k.startswith("UNVERIFIED:")}
        if unmapped:
            top = dict(sorted(unmapped.items(), key=lambda kv: -kv[1])[:20])
            msgs.append(f"status codes in the data but NOT mapped in config (code: records): {top}")
        never = sorted(k for k in known if k not in seen and not k.startswith("UNVERIFIED:"))
        if never and seen:
            msgs.append(f"codes mapped in config that never occur in the status column: {never[:20]}")
    return msgs


def design_report(cfg: Config) -> dict[str, Any]:
    """What config DECLARES about each file's release, design, period and sector. Not verified here."""
    data = cfg.to_dict()["data"]
    files = [{k: e.get(k) for k in ("id", "kind", "role", "release_id", "design_id", "period", "sector")}
             for e in data["files"]]
    primary = [f for f in files if (f["role"] or "primary") == "primary"]
    designs = sorted({str(f["design_id"]) for f in primary})
    mixed = len(designs) > 1
    justified = bool(data["design_mix_justification"])
    notes = []
    if any(f["design_id"] in (None, "") for f in files):
        notes.append("some files have no design_id: declare it from the official documentation")
    if mixed and not justified:
        notes.append(f"primary files span {len(designs)} designs {designs} and no design_mix_justification "
                     "is recorded: verify_design_compatibility will refuse this at load time")
    return {"files": files, "primary_designs": designs, "mixed_designs": mixed,
            "mix_justification_present": justified, "declared_period": data["period"],
            "declared_sector_coverage": data["sector_coverage"], "notes": notes,
            "caveat": "declared in config.yaml by you; this audit does not verify them"}


# ---------------------------------------------------------------------------------------------
# Linkage and coverage
# ---------------------------------------------------------------------------------------------
def _linkage(frame: pd.DataFrame, issues: list[str], cfg: Config) -> dict[str, Any]:
    n_points = int(cfg.time.n_points)
    min_pts = int(cfg.trainee.min_time_points)
    out: dict[str, Any] = {"issues": list(issues), "expected_time_points": n_points, "min_time_points": min_pts,
                           "duplicate_key_time_pairs": None}
    if frame.empty:
        out["status"] = "no_data"
        return out
    out["n_records"] = int(len(frame))
    has_key = frame["key"].notna()
    out["n_records_missing_key"] = int((~has_key).sum())
    f = frame[has_key].copy()
    if f.empty:
        out["status"] = "no_data"
        return out
    schema = cfg.to_dict()["data"]["schema"]
    quarter_col = (_as_list(schema.get("quarter")) or [None])[0]
    if quarter_col and "quarter" in f.columns:
        # Import lazily: data_loader reuses this module's schema/table helpers.
        # Both audit and loader therefore use one implementation of the cohort rule.
        from .data_loader import quarter_aware_link_keys

        f, collisions = quarter_aware_link_keys(
            f, key_col="key", visit_col="t", quarter_col="quarter", n_points=n_points, strict=False,
        )
        out.update(collisions)
        if collisions["quarter_link_issues"]:
            out["issues"].extend(collisions["quarter_link_issues"])
        out["quarter_aware_linking"] = True
        f["key"] = f["_quarter_link_key"]
        f = f[f["key"].notna()].copy()
    else:
        legacy_sizes = f.groupby(["key", "t"], dropna=False).size()
        legacy_groups = legacy_sizes[legacy_sizes > 1]
        out["legacy_key_visit_collision_groups"] = int(len(legacy_groups))
        out["legacy_key_visit_collision_excess_rows"] = int((legacy_groups - 1).sum())
    if f.empty:
        out["status"] = "no_data"
        return out
    if (f["t"] == "UNKNOWN").any():
        out["issues"].append(f"{int((f['t'] == 'UNKNOWN').sum())} records have no time label (UNKNOWN)")
    per_key = f.groupby("key")["t"].nunique()
    n_keys = int(len(per_key))
    hist = per_key.value_counts().sort_index()
    out.update({
        "status": "ok",
        "n_person_keys": n_keys,
        "time_points_per_person": {str(int(k)): int(v) for k, v in hist.items()},
        "n_linked_2plus": int((per_key >= 2).sum()),
        "linkage_rate_2plus": float((per_key >= 2).mean()),
        "share_at_min_time_points": float((per_key >= min_pts).mean()),
        "share_full_window": float((per_key >= n_points).mean()),
        "mean_time_points": float(per_key.mean()),
    })
    if out.get("quarter_visit_collision_excess_rows", 0) > 0:
        out["issues"].append(f"{out['quarter_visit_collision_excess_rows']} excess row(s) in quarter-aware key coordinates")
    elif not out.get("quarter_aware_linking") and out.get("legacy_key_visit_collision_excess_rows", 0) > 0:
        out["issues"].append(f"{out['legacy_key_visit_collision_excess_rows']} excess row(s) in legacy key/time coordinates")
    labels = _sorted_labels(f["t"].unique())
    first = labels[0]
    keys_first = set(f.loc[f["t"] == first, "key"])
    ret = {}
    for lab in labels:
        seen = f.loc[(f["t"] == lab) & f["key"].isin(keys_first), "key"].nunique()
        ret[lab] = float(seen / len(keys_first)) if keys_first else None
    out["time_labels_sorted"] = labels
    out["time_label_order_rule"] = "numeric if every label is numeric, otherwise alphabetical: verify"
    out["retention_from_first_label"] = ret
    linked = per_key.index[per_key >= 2]
    lk = f[f["key"].isin(linked)]
    checks: dict[str, Any] = {"n_linked_keys_checked": int(len(linked))}
    if lk["sex"].notna().any():
        checks["keys_with_changing_sex"] = int((lk.groupby("key")["sex"].nunique() > 1).sum())
    if lk["age"].notna().any():
        span = lk.groupby("key")["age"].agg(["min", "max"]).dropna()
        checks["keys_with_any_age_change"] = int(((span["max"] - span["min"]) > 0).sum())
        checks["keys_with_age_span_over_limit"] = None
        checks["age_span_limit_years"] = None
        checks["age_tolerance_status"] = "unconfirmed: official documentation unavailable"
    if lk["sector"].notna().any():
        checks["keys_with_changing_sector"] = int((lk.groupby("key")["sector"].nunique() > 1).sum())
    out["link_validity"] = checks
    out["link_validity_note"] = ("a high count of changing sex or large age spans means the key joins different "
                                 "people; sex is used here to validate links only")
    if f["sector"].notna().any():
        agg = f.groupby("key").agg(sector=("sector", "first"), npts=("t", "nunique"))
        out["linkage_by_first_sector"] = {
            str(sec): {"n_keys": int(len(g)), "share_linked_2plus": float((g["npts"] >= 2).mean())}
            for sec, g in agg.groupby("sector")
        }
    return out


def linkage_report(tables: dict[str, pd.DataFrame], cfg: Config) -> dict[str, Any]:
    """Linkage rate across time points, time points per person, and link-validity checks.

    Records are never pooled across designs: if the primary person files declare more than one
    design_id, each design is reported separately under "by_design" (status "multiple_designs").
    """
    designs = _primary_designs(tables, cfg)
    if len(designs) <= 1:
        out = _linkage(*_person_frame(tables, cfg), cfg)
        out["design_id"] = designs[0] if designs else None
        return out
    return {"status": "multiple_designs", "designs": designs,
            "issues": [f"primary person files span {len(designs)} designs {designs}: records are NOT pooled "
                       "across designs, each design is reported separately"],
            "by_design": {d: {**_linkage(*_person_frame(tables, cfg, d), cfg), "design_id": d} for d in designs}}


def coverage_report(tables: dict[str, pd.DataFrame], cfg: Config) -> dict[str, Any]:
    """Per-file record counts, time labels and sector codes, against what config declares."""
    schema = _schema(cfg)
    tcol = _time_col(schema)
    sec_col = (_as_list(schema.get("sector")) or [None])[0]
    files, all_t, all_sec = [], set(), set()
    for e in _entries(cfg):
        df = tables.get(e["id"])
        if df is None:
            files.append({"file_id": e["id"], "status": "not_read"})
            continue
        row: dict[str, Any] = {"file_id": e["id"], "kind": e.get("kind"), "role": e.get("role", "primary"),
                               "release_id": e.get("release_id"), "design_id": e.get("design_id"),
                               "declared_period": e.get("period"), "declared_sector": e.get("sector"),
                               "n_records": int(len(df))}
        if tcol and tcol in df.columns:
            row["time_source"] = f"column:{tcol}"
            row["time_labels"] = _counts(df[tcol])
        else:
            row["time_source"] = "declared_period" if e.get("period") else "none"
            row["time_labels"] = {str(e.get("period")): int(len(df))} if e.get("period") else {}
        if sec_col and sec_col in df.columns:
            row["sector_codes"] = _counts(df[sec_col])
            all_sec |= set(row["sector_codes"]) - {BLANK}
        all_t |= set(row["time_labels"])
        files.append(row)
    notes = []
    declared = cfg.data.sector_coverage
    if all_sec:
        notes.append(f"{len(all_sec)} distinct sector code(s) observed {sorted(all_sec)}; declared sector_coverage "
                     f"is {declared!r}: confirm the codes match it using the data dictionary")
    elif declared:
        notes.append("no sector column was read, so declared sector coverage cannot be checked")
    return {"files": files, "time_labels_overall": _sorted_labels(all_t), "sector_codes_overall": sorted(all_sec),
            "declared_period": cfg.data.period, "declared_sector_coverage": declared, "notes": notes}


# ---------------------------------------------------------------------------------------------
# Training variables and trainees
# ---------------------------------------------------------------------------------------------
_REF_RE = re.compile(
    r"\b(col(?:umn)?s?|items?|q(?:uestions?)?s?)\.?\s*(\d+(?:\s*(?:,|/|&|and|or)\s*"
    r"(?:(?:col(?:umn)?s?|items?|q(?:uestions?)?s?)\.?\s*)?\d+)*)", re.IGNORECASE)


_VOC_RE = re.compile(r"\b(vocational|technical)\b", re.IGNORECASE)
_EXAM_RE = re.compile(r"\b(entrance|exams?|examinations?|coaching|competitive|higher education)\b", re.IGNORECASE)


def _refs_from_label(label: str | None, other_columns: list[str], own: str) -> list[str]:
    """Items or columns a label points to ("col 17 or col 18" gives col:17 and col:18), plus declared column names."""
    refs: list[str] = []
    if label:
        for m in _REF_RE.finditer(label):
            kind = m.group(1).lower()
            kind = "col" if kind.startswith("col") else "item" if kind.startswith("item") else "q"
            refs += [f"{kind}:{n}" for n in re.findall(r"\d+", m.group(2))]
        for other in other_columns:
            if other != own and re.search(rf"(?<![A-Za-z0-9_]){re.escape(other)}(?![A-Za-z0-9_])", label, re.IGNORECASE):
                refs.append(f"column:{other}")
    return sorted(set(refs))


def _band(age: pd.Series) -> pd.Series:
    edges = [AGE_BANDS[0][1] - 0.5] + [b[2] + 0.5 for b in AGE_BANDS[:-1]] + [1e9]
    return pd.cut(age, bins=edges, labels=[b[0] for b in AGE_BANDS])


def training_variable_report(tables: dict[str, pd.DataFrame], cfg: Config) -> pd.DataFrame:
    """Per person file and training variable: presence, exact code list, label, what it refers to, universe.

    Nothing carries across releases: every file is reported on its own. `refers_to_ambiguous` is True
    when the label (or config) points to two or more items, or to nothing, so a completion flag is
    not treated as dating vocational training until the questionnaire says what it refers to.
    """
    data = cfg.to_dict()
    schema, layouts = data["data"]["schema"], data["data"]["layouts"] or {}
    tvars = _as_list(schema.get("training_cols"))
    for rule in ((data["trainee"].get("rules") or {}).values()):   # a variable named in a trainee rule is always reported
        rv = (rule or {}).get("variable")
        if rv and rv not in tvars:
            tvars.append(str(rv))
    age_col = (_as_list(schema.get("age")) or [None])[0]
    cols = ["file_id", "release_id", "design_id", "variable", "present", "label_text", "refers_to_from_label",
            "refers_to_from_config", "refers_to_ambiguous", "ambiguity_reason", "n_total", "n_blank",
            "n_declared_na", "n_valid", "share_valid", "n_distinct_codes", "code_counts", "na_codes_declared",
            "valid_by_age_band", "code_by_age_band", "declared_code_meanings", "not_applicable_note"]
    rows: list[dict[str, Any]] = []
    for e in _entries(cfg):
        if e.get("kind") != "person":
            continue
        df = tables.get(e["id"])
        layout_cols = (layouts.get(e["id"]) or {}).get("columns") or {}
        for var in tvars:
            row: dict[str, Any] = {c: None for c in cols}
            row.update(file_id=e["id"], release_id=e.get("release_id"), design_id=e.get("design_id"),
                       variable=var, present=bool(df is not None and var in df.columns))
            spec = layout_cols.get(var) or {}
            row["label_text"] = spec.get("label")
            row["refers_to_from_label"] = _refs_from_label(spec.get("label"), tvars, var)
            row["refers_to_from_config"] = _as_list(spec.get("refers_to"))
            refs = set(row["refers_to_from_label"]) | set(row["refers_to_from_config"])
            label = spec.get("label") or ""
            mixed = bool(_VOC_RE.search(label) and _EXAM_RE.search(label))
            if not refs and not mixed:
                row["refers_to_ambiguous"] = True
                row["ambiguity_reason"] = ("no label text or refers_to declared: what this variable refers to "
                                           "cannot be established; read the questionnaire")
            elif len(refs) >= 2:
                row["refers_to_ambiguous"] = True
                row["ambiguity_reason"] = (f"points to {len(refs)} items {sorted(refs)}; the audit cannot tell "
                                           "whether they are the same kind of course (e.g. vocational vs exam); "
                                           "confirm in the questionnaire")
            elif mixed:
                row["refers_to_ambiguous"] = True
                row["ambiguity_reason"] = ("the label mentions both vocational/technical and entrance/exam courses: "
                                           "it may not date vocational training; confirm in the questionnaire")
            else:
                row["refers_to_ambiguous"] = False
                row["ambiguity_reason"] = f"single reference {sorted(refs)}; still confirm in the questionnaire"
            row["declared_code_meanings"] = spec.get("codes")
            na_codes = [str(c) for c in spec["na_codes"]] if spec.get("na_codes") is not None else None
            row["na_codes_declared"] = na_codes
            row["not_applicable_note"] = (
                "na_codes declared in the layout" if na_codes is not None else
                "not_applicable coding NOT declared (layout column has no na_codes): the audit does not infer it; "
                "see code_by_age_band and the questionnaire")
            if row["present"]:
                s = df[var]
                n_blank = int(s.isna().sum())
                n_na = int(s.isin(na_codes).sum()) if na_codes else 0
                n_total = int(len(s))
                row.update(n_total=n_total, n_blank=n_blank, n_declared_na=n_na, n_valid=n_total - n_blank - n_na,
                           share_valid=(n_total - n_blank - n_na) / n_total if n_total else None)
                vc = _counts(s)
                row["n_distinct_codes"] = int(s.nunique(dropna=True))
                row["code_counts"] = vc
                if age_col and age_col in df.columns:
                    band = _band(pd.to_numeric(df[age_col], errors="coerce"))
                    valid = s.notna() & ~s.isin(na_codes or [])
                    row["valid_by_age_band"] = {
                        str(b): {"n_records": int((band == b).sum()), "n_valid": int((valid & (band == b)).sum())}
                        for b in [x[0] for x in AGE_BANDS]
                    }
                    ct = pd.crosstab(s.fillna(BLANK), band)
                    row["code_by_age_band"] = {str(c): {str(b): int(ct.loc[c, b]) for b in ct.columns}
                                               for c in list(ct.index)[:MAX_CODES_LISTED]}
            rows.append(row)
    return pd.DataFrame(rows, columns=cols, dtype=object)


def _trainee_one(tables: dict[str, pd.DataFrame], cfg: Config, design: str | None) -> dict[str, Any]:
    """Trainee counts for the primary person files of ONE design (or all of them when design is None)."""
    data = cfg.to_dict()
    schema = data["data"]["schema"]
    trainee = data["trainee"]
    min_pts, n_points = int(trainee["min_time_points"]), int(cfg.time.n_points)
    frame, issues = _person_frame(tables, cfg, design)
    per_key = frame[frame["key"].notna()].groupby("key")["t"].nunique() if not frame.empty else pd.Series(dtype=int)
    tv = training_variable_report(tables, cfg)
    out: dict[str, Any] = {
        "declared_definition": trainee["definition"],
        "timing_support": trainee["timing_support"],
        "post_training_wording_allowed": trainee["timing_support"] == "dated",
        "wording": ("ever-trained persons, as flagged by the declared training variable (when the training "
                    "happened relative to the observed outcomes is unknown)"
                    if trainee["timing_support"] == "none" else
                    "timing support declared in config: " + str(trainee["timing_support"])
                    + (" (a coarse flag is not a completion date; post-training wording stays blocked)"
                       if trainee["timing_support"] == "coarse_flag" else "")),
        "definitions": {},
    }
    key_cols, tcol = _key_cols(schema), _time_col(schema)
    for dname in ("ever_trained", "recent_completion"):
        rule = (trainee["rules"] or {}).get(dname) or {}
        var, yes = rule.get("variable"), rule.get("codes_yes")
        res: dict[str, Any] = {"declared": dname == trainee["definition"], "variable": var, "codes_yes": yes}
        if not var or not yes:
            res.update(supported=False, reason="rule not set in config (trainee.rules." + dname + ")")
            out["definitions"][dname] = res
            continue
        yes_s = [str(c) for c in yes]
        parts = []
        for entry, df in _person_tables(tables, cfg, design=design):
            if var in df.columns and key_cols and all(c in df.columns for c in key_cols):
                if tcol and tcol in df.columns:
                    t = df[tcol].astype("string").fillna("UNKNOWN").astype(str)
                else:
                    t = pd.Series(str(entry.get("period") or "UNKNOWN"), index=df.index)
                parts.append(pd.DataFrame({"key": _make_key(df, key_cols), "t": t, "val": df[var]}))
        if not parts:
            res.update(supported=False, reason=f"variable {var!r} not found in any primary person file")
            out["definitions"][dname] = res
            continue
        v = pd.concat(parts, ignore_index=True)
        v = v[v["key"].notna()]
        observed = {str(c) for c in v["val"].dropna().unique()}
        if not observed & set(yes_s):
            res.update(supported=False, reason=f"none of the yes-codes {yes_s} occur in {var!r} "
                                               f"(codes present: {sorted(observed)[:15]})")
            out["definitions"][dname] = res
            continue
        valid = v[v["val"].notna()].copy()
        valid["yes"] = valid["val"].astype(str).isin(yes_s)
        g = valid.groupby("key")["yes"].agg(n_valid="size", n_yes="sum")
        flagged = g.index[g["n_yes"] >= 1]
        pts = per_key.reindex(flagged).fillna(0)
        amb = tv[(tv["variable"] == var) & tv["refers_to_ambiguous"].fillna(True).astype(bool)]
        res.update(
            supported=True,
            n_person_keys_total=int(len(per_key)),
            n_records_flagged=int(valid["yes"].sum()),
            n_keys_flagged=int(len(flagged)),
            share_of_keys=float(len(flagged) / len(per_key)) if len(per_key) else None,
            n_keys_yes_in_all_valid_records=int((g.loc[flagged, "n_yes"] == g.loc[flagged, "n_valid"]).sum()),
            n_keys_yes_in_some_but_not_all=int((g.loc[flagged, "n_yes"] < g.loc[flagged, "n_valid"]).sum()),
            n_keys_flagged_linked_2plus=int((pts >= 2).sum()),
            n_keys_flagged_at_min_time_points=int((pts >= min_pts).sum()),
            n_keys_flagged_full_window=int((pts >= n_points).sum()),
            ambiguity=("UNCONFIRMED: " + "; ".join(sorted(set(amb["ambiguity_reason"].astype(str)))))
            if len(amb) else "label references a single item (still confirm in the questionnaire)",
        )
        if dname == "recent_completion" and len(amb):
            res["note"] = "unconfirmed: may include exam or entrance-course completion, not only vocational training"
        out["definitions"][dname] = res
    out["issues"] = issues
    out["min_time_points"], out["expected_time_points"] = min_pts, n_points
    return out


def trainee_report(tables: dict[str, pd.DataFrame], cfg: Config) -> dict[str, Any]:
    """Trainee counts under each supported definition, and how many survive linkage.

    Never pooled across designs: with more than one primary design_id the counts are reported per
    design under "by_design" and "definitions" is left empty.
    """
    designs = _primary_designs(tables, cfg)
    if len(designs) <= 1:
        out = _trainee_one(tables, cfg, None)
        out["design_id"] = designs[0] if designs else None
        return out
    subs = {d: _trainee_one(tables, cfg, d) for d in designs}
    first = next(iter(subs.values()))
    out = {k: first[k] for k in ("declared_definition", "timing_support", "post_training_wording_allowed",
                                 "wording", "min_time_points", "expected_time_points")}
    out["definitions"] = {}
    out["by_design"] = {d: s["definitions"] for d, s in subs.items()}
    out["issues"] = [f"primary person files span {len(designs)} designs {designs}: trainee counts are NOT "
                     "pooled across designs"]
    return out


# ---------------------------------------------------------------------------------------------
# Missingness and non-response
# ---------------------------------------------------------------------------------------------
def missingness_report(tables: dict[str, pd.DataFrame], cfg: Config) -> pd.DataFrame:
    """Blank counts per declared column, plus the status column's blank/unknown-code share by time point."""
    data = cfg.to_dict()
    schema = data["data"]["schema"]
    status = (_as_list(schema.get("status_col")) or [None])[0]
    tcol = _time_col(schema)
    unknown = {str(c) for c in data["unknown_codes"]}
    cols = ["file_id", "scope", "column", "time_label", "n_records", "n_blank", "pct_blank",
            "n_unknown_code", "pct_unknown_code"]
    rows = []
    for e in _entries(cfg):
        df = tables.get(e["id"])
        if df is None:
            continue
        for c in df.columns:
            n, nb = len(df), int(df[c].isna().sum())
            nu = int(df[c].astype(str).isin(unknown).sum()) if c == status else None
            rows.append([e["id"], "column", c, "ALL", n, nb, nb / n if n else None, nu,
                         (nu / n if n and nu is not None else None)])
        if status and status in df.columns:
            if tcol and tcol in df.columns:
                groups = {str(k): g for k, g in df.groupby(df[tcol].astype(str))}
            else:
                groups = {str(e.get("period") or "ALL"): df}
            for lab in _sorted_labels(groups):
                g = groups[lab]
                n, nb = len(g), int(g[status].isna().sum())
                nu = int(g[status].astype(str).isin(unknown).sum())
                rows.append([e["id"], "status_by_time", status, lab, n, nb, nb / n if n else None, nu,
                             nu / n if n else None])
    return pd.DataFrame(rows, columns=cols, dtype=object)


def nonresponse_report(tables: dict[str, pd.DataFrame], cfg: Config) -> pd.DataFrame:
    """Non-response / casualty codes per file, and how config classifies each (lost, unknown, unclassified)."""
    data = cfg.to_dict()
    nr_cols = _as_list(data["data"]["schema"].get("nonresponse_col"))
    lost = {str(c) for c in data["lost_codes"]}
    unknown = {str(c) for c in data["unknown_codes"]}
    cols = ["file_id", "column", "code", "n_records", "pct_records", "config_class"]
    rows = []
    if not nr_cols:
        return pd.DataFrame(rows, columns=cols)
    for e in _entries(cfg):
        df = tables.get(e["id"])
        if df is None:
            continue
        for c in nr_cols:
            if c not in df.columns:
                continue
            for code, n in _counts(df[c]).items():
                cls = ("blank" if code == BLANK else "lost_to_follow_up" if code in lost
                       else "unknown" if code in unknown else "not classified in config")
                rows.append([e["id"], c, code, n, n / len(df) if len(df) else None, cls])
    return pd.DataFrame(rows, columns=cols, dtype=object)


# ---------------------------------------------------------------------------------------------
# Orchestration and output
# ---------------------------------------------------------------------------------------------
def _jsonable(obj: Any) -> Any:
    if isinstance(obj, pd.DataFrame):
        return _jsonable(obj.to_dict(orient="records"))
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_jsonable(v) for v in (sorted(obj) if isinstance(obj, set) else obj)]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        return None if math.isnan(float(obj)) else float(obj)
    if isinstance(obj, Path):
        return str(obj)
    if obj is pd.NA or obj is None:
        return None
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


def run_audit(cfg: Config) -> dict[str, Any]:
    """Read every configured file and run every report. Returns a JSON-ready dict of counts only."""
    data = cfg.to_dict()
    layouts = data["data"]["layouts"] or {}
    tables: dict[str, pd.DataFrame] = {}
    read_errors: dict[str, str] = {}
    for e in data["data"]["files"]:
        try:
            if e["id"] not in layouts:
                raise ValueError(f"no layout under data.layouts.{e['id']}")
            tables[e["id"]] = read_table(cfg.root / e["path"], layouts[e["id"]])
        except (FileNotFoundError, ValueError, KeyError, OSError, pd.errors.ParserError) as exc:
            read_errors[e["id"]] = f"{type(exc).__name__}: {exc}"
    report: dict[str, Any] = {
        "is_synthetic": False,
        "config": {"plan": data["data"]["plan"], "verified": data["data"]["verified"],
                   "trainee_definition": data["trainee"]["definition"],
                   "timing_support": data["trainee"]["timing_support"], "n_points": data["time"]["n_points"],
                   "reference_period": data["time"]["reference_period"], "min_time_points": data["trainee"]["min_time_points"]},
        "environment": {"python": sys.version.split()[0], "pandas": pd.__version__, "numpy": np.__version__},
        "files": [{"id": e["id"], "path": e["path"], "n_rows": int(len(tables[e["id"]])) if e["id"] in tables else None}
                  for e in data["data"]["files"]],
        "sha256": file_hashes(cfg),
        "read_errors": read_errors,
        "design": design_report(cfg),
        "schema_issues": check_schema(tables, cfg),
        "linkage": linkage_report(tables, cfg),
        "coverage": coverage_report(tables, cfg),
        "training_variables": training_variable_report(tables, cfg),
        "trainee": trainee_report(tables, cfg),
        "missingness": missingness_report(tables, cfg),
        "nonresponse": nonresponse_report(tables, cfg),
    }
    return _jsonable(report)


def _pct(x: Any) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def _fmt_linkage(add: Any, lk: dict[str, Any], pad: str = "") -> None:
    add(f"{pad}LINKAGE: status={lk.get('status')}" + (f"  design={lk['design_id']}" if lk.get("design_id") else ""))
    for i in lk.get("issues", []):
        add(f"{pad}  ISSUE: {i}")
    if lk.get("status") != "ok":
        return
    add(f"{pad}  records={lk['n_records']}  person keys={lk['n_person_keys']}  "
        f"records without a full key={lk['n_records_missing_key']}")
    add(f"{pad}  linked at 2+ time points: {lk['n_linked_2plus']} ({_pct(lk['linkage_rate_2plus'])})  "
        f"at >= min_time_points: {_pct(lk['share_at_min_time_points'])}  full window ({lk['expected_time_points']}): "
        f"{_pct(lk['share_full_window'])}  mean points: {lk['mean_time_points']:.2f}")
    add(f"{pad}  time points per person (points: persons): {lk['time_points_per_person']}")
    add(f"{pad}  legacy key/time collision groups/excess rows: "
        f"{lk.get('legacy_key_visit_collision_groups', 0)}/{lk.get('legacy_key_visit_collision_excess_rows', 0)}")
    if lk.get("quarter_aware_linking"):
        add(f"{pad}  quarter/visit key collision groups/excess rows: "
            f"{lk.get('quarter_visit_collision_groups', 0)}/{lk.get('quarter_visit_collision_excess_rows', 0)}")
    add(f"{pad}  time labels in order ({lk['time_label_order_rule']}): {lk['time_labels_sorted']}")
    add(f"{pad}  retention from first label: "
        + ", ".join(f"{k}={_pct(v)}" for k, v in lk["retention_from_first_label"].items()))
    add(f"{pad}  link validity: {lk['link_validity']}")
    for sec, v in (lk.get("linkage_by_first_sector") or {}).items():
        add(f"{pad}  sector {sec}: keys={v['n_keys']}  linked 2+={_pct(v['share_linked_2plus'])}")


def _fmt_definitions(add: Any, defs: dict[str, Any], pad: str = "  ") -> None:
    for name, res in defs.items():
        mark = " (DECLARED)" if res.get("declared") else ""
        if not res.get("supported"):
            add(f"{pad}{name}{mark}: NOT SUPPORTED - {res.get('reason')}")
            continue
        add(f"{pad}{name}{mark}: variable={res['variable']} yes={res['codes_yes']}")
        add(f"{pad}  keys flagged={res['n_keys_flagged']} ({_pct(res['share_of_keys'])} of {res['n_person_keys_total']})  "
            f"yes in all valid records={res['n_keys_yes_in_all_valid_records']}  "
            f"some-but-not-all={res['n_keys_yes_in_some_but_not_all']}")
        add(f"{pad}  SURVIVE LINKAGE: 2+ points={res['n_keys_flagged_linked_2plus']}  "
            f">= min_time_points={res['n_keys_flagged_at_min_time_points']}  full window={res['n_keys_flagged_full_window']}")
        add(f"{pad}  {res['ambiguity']}")
        if res.get("note"):
            add(f"{pad}  NOTE: {res['note']}")


def format_audit(report: dict[str, Any]) -> str:
    """A compact plain-text summary of the audit, meant to be pasted back at CHECKPOINT 1."""
    L: list[str] = []
    add = L.append
    c = report["config"]
    add("=== DATA AUDIT (CHECKPOINT 1) ===" + ("   [SYNTHETIC DEMO DATA - not a result]" if report.get("is_synthetic") else ""))
    add(f"plan={c['plan']}  verified={c['verified']}  trainee.definition={c['trainee_definition']}  "
        f"timing_support={c['timing_support']}  n_points={c['n_points']}  reference_period={c['reference_period']}  "
        f"min_time_points={c['min_time_points']}")
    env = report["environment"]
    add(f"python {env['python']}, pandas {env['pandas']}, numpy {env['numpy']}")
    add("")
    add("FILES (id | rows | sha256[:12])")
    for f in report["files"]:
        add(f"  {f['id']} | {f['n_rows']} | {str(report['sha256'].get(f['id']))[:12]}")
    for fid, err in report["read_errors"].items():
        add(f"  READ ERROR {fid}: {err}")
    d = report["design"]
    add(f"DESIGN (declared, not verified): designs={d['primary_designs']}  mixed={d['mixed_designs']}  "
        f"mix_justification={d['mix_justification_present']}")
    for n in d["notes"]:
        add(f"  note: {n}")
    add("")
    add(f"SCHEMA ISSUES ({len(report['schema_issues'])})")
    for m in report["schema_issues"]:
        add(f"  - {m}")
    add("")
    lk = report["linkage"]
    if lk.get("status") == "multiple_designs":
        add("LINKAGE: status=multiple_designs")
        for i in lk.get("issues", []):
            add(f"  ISSUE: {i}")
        for sub in lk["by_design"].values():
            _fmt_linkage(add, sub, "  ")
    else:
        _fmt_linkage(add, lk)
    add("")
    cov = report["coverage"]
    add(f"COVERAGE: time labels={cov['time_labels_overall']}  sector codes={cov['sector_codes_overall']}  "
        f"declared period={cov['declared_period']}  declared sector coverage={cov['declared_sector_coverage']}")
    for f in cov["files"]:
        if f.get("status") == "not_read":
            add(f"  {f['file_id']}: not read")
        else:
            add(f"  {f['file_id']} ({f['kind']}, {f['role']}): rows={f['n_records']}  time={f.get('time_labels')} "
                f"(source {f['time_source']})  sectors={f.get('sector_codes')}")
    for n in cov["notes"]:
        add(f"  note: {n}")
    add("")
    add("TRAINING VARIABLES (per file; exact codes listed up to 25)")
    for r in report["training_variables"]:
        add(f"  {r['file_id']} / {r['variable']}: present={r['present']}  ambiguous={r['refers_to_ambiguous']}")
        add(f"    label: {r['label_text']!r}  refers_to(label)={r['refers_to_from_label']}  refers_to(config)={r['refers_to_from_config']}")
        add(f"    reason: {r['ambiguity_reason']}")
        if r["present"]:
            codes = dict(list((r["code_counts"] or {}).items())[:25])
            add(f"    records={r['n_total']}  blank={r['n_blank']}  declared n/a={r['n_declared_na']}  "
                f"valid={r['n_valid']} ({_pct(r['share_valid'])})  distinct codes={r['n_distinct_codes']}")
            add(f"    codes: {codes}")
            add(f"    valid by age band: {r['valid_by_age_band']}")
            add(f"    n/a coding: {r['not_applicable_note']}")
    add("")
    tr = report["trainee"]
    add(f"TRAINEES: declared definition={tr['declared_definition']}  timing_support={tr['timing_support']}  "
        f"post-training wording allowed={tr['post_training_wording_allowed']}")
    add(f"  wording: {tr['wording']}")
    if tr.get("by_design"):
        for i in tr.get("issues", []):
            add(f"  ISSUE: {i}")
        for dsg, defs in tr["by_design"].items():
            add(f"  design {dsg}:")
            _fmt_definitions(add, defs, "    ")
    else:
        _fmt_definitions(add, tr["definitions"], "  ")
    add("")
    add("MISSINGNESS (columns with blanks; status by time)")
    cols = [m for m in report["missingness"] if m["scope"] == "column" and (m["n_blank"] or m["n_unknown_code"])]
    for m in sorted(cols, key=lambda m: -(m["pct_blank"] or 0))[:15]:
        add(f"  {m['file_id']} / {m['column']}: blank {m['n_blank']}/{m['n_records']} ({_pct(m['pct_blank'])})"
            + (f"  unknown-code {m['n_unknown_code']}" if m["n_unknown_code"] is not None else ""))
    for m in report["missingness"]:
        if m["scope"] == "status_by_time":
            add(f"  status at {m['time_label']} [{m['file_id']}]: records={m['n_records']}  blank={_pct(m['pct_blank'])}  "
                f"unknown-code={_pct(m['pct_unknown_code'])}")
    add("")
    add("NON-RESPONSE / CASUALTY CODES (file | code | records | config class)")
    if not report["nonresponse"]:
        add("  none reported (data.schema.nonresponse_col not set, or no such column read)")
    for r in report["nonresponse"]:
        add(f"  {r['file_id']} | {r['code']} | {r['n_records']} ({_pct(r['pct_records'])}) | {r['config_class']}")
    return "\n".join(L)


def _write_result(cfg: Config, report: dict[str, Any]) -> Path:
    out_dir = resolve_path(cfg, "results_dir")
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"audit__{result_tag(bool(report.get('is_synthetic')))}.json"
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=False)
    return target


# ---------------------------------------------------------------------------------------------
# Smoke demo on a tiny SYNTHETIC dataset (built in a temporary folder; touches nothing in the project)
# ---------------------------------------------------------------------------------------------
def _demo() -> int:
    import tempfile

    import yaml

    rng = make_rng(load_config(), "data_audit/demo")
    n = 300
    ids = np.arange(n)
    n_obs = rng.choice([4, 3, 2, 1], size=n, p=[0.5, 0.2, 0.15, 0.15])
    age0 = rng.integers(16, 60, n)
    age0[:20] = rng.integers(8, 15, 20)                    # children: the training question does not apply
    sex = rng.choice(["M", "F"], n)
    sector = rng.choice(["U", "R"], n)
    trained = np.where(age0 < 15, "", np.where(rng.random(n) < 0.3, "Y", "N"))
    when = np.where(trained == "Y", np.where(rng.random(n) < 0.4, "R", "O"), "")
    flip, jump = np.arange(100, 103), np.arange(110, 112)  # planted link errors: sex changes, age jumps
    n_obs[np.r_[flip, jump]] = 3
    rows_by_month: list[list[dict[str, str]]] = [[] for _ in range(4)]
    n_unmapped = 0
    for i in ids:
        for m in range(n_obs[i]):
            r = rng.random()
            status, nonresp = str(rng.choice(list("ABCDEF"))), "R"
            if r < 0.03:
                status, nonresp = "", "L"
            elif r < 0.05:
                status, nonresp = "", "S"
            elif r < 0.07:
                status = "X"
            elif r < 0.09:
                status, n_unmapped = "Q", n_unmapped + 1
            rows_by_month[m].append({
                "hh_key": f"H{i // 3:04d}", "person_no": str(i % 3 + 1),
                "age": str(age0[i] + (5 if (i in jump and m >= 1) else 0)),
                "sex_code": ("F" if sex[i] == "M" else "M") if (i in flip and m >= 1) else sex[i],
                "sector_code": sector[i], "activity_code": status, "nonresp": nonresp,
                "trained": trained[i], "trained_when": when[i]})
    layout_cols = {
        "hh_key": {}, "person_no": {}, "age": {"dtype": "int"}, "sex_code": {}, "sector_code": {},
        "activity_code": {}, "nonresp": {},
        "trained": {"label": "received training of the demo kind"},
        "trained_when": {"label": "completion period of the course named in item 5 or item 6"},
    }
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "data" / "raw").mkdir(parents=True)
        files, layouts = [], {}
        for m in range(4):
            fid = f"demo_m{m + 1}"
            pd.DataFrame(rows_by_month[m]).to_csv(root / "data" / "raw" / f"{fid}.csv", index=False)
            files.append({"id": fid, "path": f"data/raw/{fid}.csv", "release_id": "demo_release",
                          "design_id": "demo_design", "period": f"M{m + 1}", "sector": "both",
                          "kind": "person", "role": "primary"})
            layouts[fid] = {"format": "csv", "encoding": "utf-8", "sep": ",", "columns": layout_cols}
        d = load_config().to_dict()
        d["data"].update(files=files, layouts=layouts, period="demo", sector_coverage="both")
        d["data"]["schema"].update(person_id="person_no", household_id="hh_key", sector="sector_code",
                                   age="age", sex="sex_code", status_col="activity_code",
                                   nonresponse_col="nonresp", training_cols=["trained", "trained_when"], quarter=None)
        for st, code in zip(d["states"], "ABCDEF"):
            st["raw_codes"] = [code]
        d["unknown_codes"], d["lost_codes"] = ["X"], ["L"]
        d["trainee"]["rules"] = {"ever_trained": {"variable": "trained", "codes_yes": ["Y"]},
                                 "recent_completion": {"variable": "trained_when", "codes_yes": ["R"]}}
        with open(root / "config.yaml", "w", encoding="utf-8") as fh:
            yaml.safe_dump(d, fh, sort_keys=False)
        cfg = load_config(root / "config.yaml")
        report = run_audit(cfg)
        report["is_synthetic"] = True
        print(format_audit(report))

    # The audit must reproduce the facts planted in the generator.
    lk, tr = report["linkage"], report["trainee"]["definitions"]
    truth_hist = {str(k): int((n_obs == k).sum()) for k in (1, 2, 3, 4)}
    ever = (trained == "Y")
    recent = (when == "R")
    checks = {
        "person keys": lk["n_person_keys"] == n,
        "records": lk["n_records"] == int(n_obs.sum()),
        "time points per person": lk["time_points_per_person"] == truth_hist,
        "no legacy key/time collision excess rows": lk["legacy_key_visit_collision_excess_rows"] == 0,
        "planted sex changes found": lk["link_validity"]["keys_with_changing_sex"] == len(flip),
        "planted age changes found": lk["link_validity"]["keys_with_any_age_change"] == len(jump),
        "ever_trained keys": tr["ever_trained"]["n_keys_flagged"] == int(ever.sum()),
        "ever_trained survive 3+ points": tr["ever_trained"]["n_keys_flagged_at_min_time_points"] == int((ever & (n_obs >= 3)).sum()),
        "recent_completion keys": tr["recent_completion"]["n_keys_flagged"] == int(recent.sum()),
        "recent_completion flagged ambiguous": "UNCONFIRMED" in tr["recent_completion"]["ambiguity"],
        "unmapped status code found": any("'Q'" in m for m in report["schema_issues"]),
        "post-training wording blocked": report["trainee"]["post_training_wording_allowed"] is False,
    }
    for name, ok in checks.items():
        print(f"  demo check [{'ok' if ok else 'FAILED'}]: {name}")
    if not all(checks.values()):
        return 1
    print(f"Demo checks passed ({len(checks)}). Demo data is SYNTHETIC; nothing was written to the project.")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI. Returns 0 when the audit ran, 1 when a file could not be read, 2 for a config or usage error."""
    ap = argparse.ArgumentParser(prog="python -m src.data_audit", description=__doc__.split("\n")[0])
    ap.add_argument("--config", default=None, help="path to config.yaml (default: the project's)")
    ap.add_argument("--demo", action="store_true", help="run the smoke demo on a tiny SYNTHETIC dataset")
    ap.add_argument("--no-write", action="store_true", help="do not write reports/results/audit__real.json")
    args = ap.parse_args(argv)
    if args.demo:
        return _demo()
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        return 2
    if not cfg.data.files:
        print("Nothing to audit: data.files is empty. Fill data.files and data.layouts in config.yaml "
              "from the official data dictionary, or run with --demo to see the audit on synthetic data.")
        return 0
    report = run_audit(cfg)
    print(format_audit(report))
    if not args.no_write:
        print(f"\nFull JSON written to {_write_result(cfg, report)}")
    return 1 if report["read_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
