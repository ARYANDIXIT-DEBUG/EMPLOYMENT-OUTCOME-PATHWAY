"""Real-data loader: raw files in, one verified long panel out. It builds no trajectories.

Why this file exists: the project's central risk is quietly building "trajectories" from files that
do not describe the same people over time. This module is the checkpoint between the raw files and
everything after them. It reads only the columns declared in config.yaml (which you verify against
the official dictionary), refuses to run on an unverified mapping, refuses to mix designs or
releases, and links records into persons only through the declared keys, then tests the links.
It never assumes a PLFS column name, code, visit structure or weight; if the data disagree with
config, it stops with a SchemaError that says what to fix.

Pipeline order (run_pipeline does this): load_long_panel -> identify_trainees -> preprocessing ->
trajectories. `load_long_panel` returns ALL linked persons; trainee selection is a separate,
visible step so the number of people lost at each step can be reported.

Design choices worth defending in a viva:
  * Gate before linking: the real path needs `data.plan == "A"`, `data.verified == true`, no
    "UNVERIFIED:" placeholder codes and a compatible design. Plan B and C are not trajectory
    analyses and are handled outside this module, after the scope memo is approved.
  * One status variable. Exactly one `data.schema.status_col` is allowed, because usual,
    subsidiary and current weekly status are different reference periods and must never be mixed
    as if they were successive steps.
  * Time order is explicit and loud. If the file has a visit/month column, its distinct values are
    ordered numerically when all are numbers and alphabetically otherwise (the same rule the audit
    prints), and there must be exactly `time.n_points` of them. If time comes from the files
    themselves, the order is the order of `data.files`. A mismatch is a SchemaError, never a
    guess. The mapping used is stored in `long_df.attrs["time_map"]`.
  * Rotational quarter is separate from the sample key. When `data.schema.quarter` is configured,
    the loader checks uniqueness by sample key + survey quarter + visit and links records only when
    their quarter and visit imply the same V1 cohort quarter.
  * Links are flagged, not assumed. Sex changes, raw age changes, coordinate collisions, and
    incomplete coordinates are exposed in `link_quality_flag`; no demographic threshold is treated
    as official, and no record is excluded by link validation.
  * Nothing is silently dropped. Records without a full key or without a time label are retained,
    assigned a unique unlinked row identifier, and counted in `long_df.attrs`; no missing status is
    ever recoded into an employment state.
  * Files with role `comparison_only` and files of kind `household` are not read: the first are
    never pooled, and no schema role uses the second.
  * `load_long_panel(synthetic=True)` returns the labelled synthetic panel and skips the data gate,
    because there is no real data to protect; everything it produces stays SYNTHETIC.

Run the smoke demo with:  python -m src.data_loader
"""
from __future__ import annotations

import warnings
from typing import Any

import numpy as np
import pandas as pd

from .config import Config, load_config
from .data_audit import _as_list, _key_cols, _make_key, _sorted_labels, _time_col, read_table
from .synthetic_data import generate_synthetic

__all__ = [
    "SchemaError",
    "DesignMixError",
    "load_raw_tables",
    "verify_schema",
    "verify_design_compatibility",
    "quarter_aware_link_keys",
    "classify_link_quality",
    "link_persons",
    "identify_trainees",
    "load_long_panel",
]

MAX_INVALID_LINK_SHARE = 0.02      # PROPOSED: above this share of linked persons failing the link tests, the key is rejected
ATTRIBUTE_ROLES = ("age", "sex", "sector", "social_group", "religion")   # long-panel columns carry the ROLE name
DESIGN_CHECK_FIELDS = ("sector", "stratum", "sub_stratum", "sub_sample", "fod_sub_region")
SYNTHETIC_TRAINING_RULE = ("trained", ["Y"])   # generator-owned marker; never derived from real PLFS config
UNVERIFIED_PREFIX = "UNVERIFIED:"


class SchemaError(Exception):
    """The data do not match the verified config mapping (or the mapping is unverified)."""


class DesignMixError(Exception):
    """Files that must not be pooled (different design, release or sector coverage) feed one build."""


def classify_link_quality(*, sex_change: bool = False, age_change: bool = False,
                          design_mismatch: bool | None = None,
                          design_field_mismatch: bool = False,
                          coordinate_collision: bool = False,
                          incomplete_coordinates: bool = False) -> str:
    """Return transparent evidence flags without treating unverified links as true persons.

    An age change is not called implausible because the official tolerance is unavailable.
    Design comparisons are unassessed when the documented field set is unavailable.
    """
    flags = ["unresolved_identity_semantics"]
    if design_mismatch is None:
        flags.append("design_fields_unassessed")
    elif design_mismatch:
        flags.append("design_field_mismatch")
    if design_field_mismatch and "design_field_mismatch" not in flags:
        flags.append("design_field_mismatch")
    if sex_change:
        flags.append("sex_change_unresolved")
    if age_change:
        flags.append("age_change_tolerance_unconfirmed")
    if coordinate_collision:
        flags.append("same_key_quarter_visit_collision")
    if incomplete_coordinates:
        flags.append("incomplete_link_coordinates")
    return ";".join(flags)


# ---------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------
def _primary_person_entries(cfg: Config) -> list[dict[str, Any]]:
    return [e for e in cfg.to_dict()["data"]["files"]
            if e.get("kind") == "person" and e.get("role", "primary") == "primary"]


def _first(value: Any) -> str | None:
    cols = _as_list(value)
    return cols[0] if cols else None


def _needed_columns(cfg: Config) -> dict[str, list[str]]:
    """Columns every primary person file must have, and columns needed in at least one file."""
    d = cfg.to_dict()
    schema = d["data"]["schema"]
    every = _key_cols(schema) + _as_list(schema.get("status_col")) + _as_list(schema.get("nonresponse_col")) \
        + _as_list(schema.get("weight"))
    tcol = _time_col(schema)
    if tcol:
        every.append(tcol)
    # When configured, the quarter is a second, distinct time coordinate. It is
    # required in every person file and is used to derive the cohort quarter;
    # it is deliberately not part of the stable sample/person key.
    every += _as_list(schema.get("quarter"))
    for role in ATTRIBUTE_ROLES:
        every += _as_list(schema.get(role))
    role_cols = {col for role in ATTRIBUTE_ROLES for col in _as_list(schema.get(role))}
    some = _as_list(schema.get("training_cols")) + [field for field in DESIGN_CHECK_FIELDS if field not in role_cols]
    for rule in (d["trainee"].get("rules") or {}).values():
        var = (rule or {}).get("variable")
        if var and var not in some:
            some.append(str(var))
    return {"every": list(dict.fromkeys(every)), "some": list(dict.fromkeys(some))}


# ---------------------------------------------------------------------------------------------
# Reading and verification
# ---------------------------------------------------------------------------------------------
def _text_layout(layout: dict[str, Any], cfg: Config) -> dict[str, Any]:
    """The layout with the weight and age columns forced to text.

    read_table turns a numeric-dtype column into NaN wherever the text is not a number, which would hide
    corrupt values. Reading them as text lets verify_schema count and report non-numeric entries;
    link_persons then converts them.
    """
    schema = cfg.to_dict()["data"]["schema"]
    forced = set(_as_list(schema.get("weight")) + _as_list(schema.get("age")))
    out = {**layout, "columns": {k: dict(v or {}) for k, v in (layout.get("columns") or {}).items()}}
    for col in forced:
        if col in out["columns"]:
            out["columns"][col]["dtype"] = "str"
    return out


def load_raw_tables(cfg: Config) -> dict[str, pd.DataFrame]:
    """Read every primary person file (declared columns only) with data_audit.read_table, keyed by file id."""
    layouts = cfg.to_dict()["data"]["layouts"] or {}
    entries = _primary_person_entries(cfg)
    if not entries:
        raise SchemaError("data.files has no primary person file: nothing to load. Fill data.files and "
                          "data.layouts in config.yaml from the official dictionary.")
    tables: dict[str, pd.DataFrame] = {}
    errors: list[str] = []
    for e in entries:
        if e["id"] not in layouts:
            errors.append(f"file {e['id']}: no layout under data.layouts.{e['id']}")
            continue
        try:
            tables[e["id"]] = read_table(cfg.root / e["path"], _text_layout(layouts[e["id"]], cfg))
        except (FileNotFoundError, ValueError, OSError, pd.errors.ParserError) as exc:
            errors.append(f"file {e['id']}: {type(exc).__name__}: {exc}")
    if errors:
        raise SchemaError("could not read the data files:\n  - " + "\n  - ".join(errors))
    return tables


def verify_schema(tables: dict[str, pd.DataFrame], cfg: Config, allow_unverified: bool = False) -> None:
    """Check config against the tables read. Raises one SchemaError listing every problem found.

    `allow_unverified=True` turns "data.verified is false" and "UNVERIFIED: placeholder codes" into
    warnings and skips the unmapped-status-code check; it exists for dry runs on the structure of a
    file, never for results.
    """
    d = cfg.to_dict()
    schema = d["data"]["schema"]
    entries = _primary_person_entries(cfg)
    errs: list[str] = []
    warns: list[str] = []

    def soft(msg: str) -> None:
        (warns if allow_unverified else errs).append(msg)

    if not entries:
        errs.append("data.files has no primary person file")
    if not d["data"]["verified"]:
        soft("data.verified is false: verify every mapping against the official dictionary, then set it true")
    placeholders = [str(c) for s in d["states"] for c in s["raw_codes"] if str(c).startswith(UNVERIFIED_PREFIX)]
    placeholders += [str(c) for k in ("unknown_codes", "lost_codes") for c in d[k] if str(c).startswith(UNVERIFIED_PREFIX)]
    if placeholders:
        soft(f"{len(placeholders)} raw code(s) are still '{UNVERIFIED_PREFIX}' placeholders in states, "
             "unknown_codes or lost_codes")

    status_cols = _as_list(schema.get("status_col"))
    if len(status_cols) != 1:
        errs.append("data.schema.status_col must name exactly one column (current weekly status); usual, "
                    "subsidiary and current weekly status are never mixed")
    if not _as_list(schema.get("person_id")):
        errs.append("data.schema.person_id is not set")
    if not _key_cols(schema):
        errs.append("no linking key: set data.schema.person_id (and household_id if the person number repeats "
                    "across households)")
    tcol = _time_col(schema)
    if not tcol:
        for e in entries:
            if not e.get("period"):
                errs.append(f"file {e['id']}: no data.schema.visit/month column and no declared period, so its "
                            "time point is unknown")

    need = _needed_columns(cfg)
    some_present = {c: False for c in need["some"]}
    for e in entries:
        df = tables.get(e["id"])
        if df is None:
            errs.append(f"file {e['id']}: was not read")
            continue
        absent = [c for c in need["every"] if c not in df.columns]
        if absent:
            errs.append(f"file {e['id']}: declared column(s) {absent} are missing from the table (check the layout)")
        for c in need["some"]:
            some_present[c] = some_present[c] or c in df.columns
    for c, ok in some_present.items():
        if not ok:
            errs.append(f"training/trainee-rule column {c!r} is in none of the primary person files")

    for role in ("weight", "age"):
        ncol = _first(schema.get(role))
        if not ncol:
            continue
        for e in entries:
            df = tables.get(e["id"])
            if df is not None and ncol in df.columns:
                raw = df[ncol]
                num = pd.to_numeric(raw, errors="coerce")
                bad = int((raw.notna() & num.isna()).sum())
                if bad:
                    errs.append(f"file {e['id']}: {role} column {ncol!r} has {bad} non-numeric value(s)")
                elif role == "weight" and (num.dropna() < 0).any():
                    errs.append(f"file {e['id']}: weight column {ncol!r} has negative value(s)")

    if status_cols and not placeholders:
        known = {str(c) for s in d["states"] for c in s["raw_codes"]}
        known |= {str(c) for c in d["unknown_codes"]} | {str(c) for c in d["lost_codes"]}
        unmapped: dict[str, int] = {}
        for e in entries:
            df = tables.get(e["id"])
            if df is not None and status_cols[0] in df.columns:
                for k, v in df[status_cols[0]].dropna().astype(str).value_counts().items():
                    if k not in known:
                        unmapped[k] = unmapped.get(k, 0) + int(v)
        if unmapped:
            top = dict(sorted(unmapped.items(), key=lambda kv: -kv[1])[:20])
            errs.append(f"status codes in the data but NOT mapped in config (code: records): {top}. "
                        "Map them in states, unknown_codes or lost_codes from the dictionary")
    elif status_cols and placeholders:
        warns.append("status-code mapping not checked while placeholder codes remain")

    for w in warns:
        warnings.warn(w, stacklevel=2)
    if errs:
        raise SchemaError("config does not match the data:\n  - " + "\n  - ".join(errs))


def verify_design_compatibility(cfg: Config) -> None:
    """Files that feed one trajectory build must share design and release, and cover the same sectors.

    Different designs (for example before and after the 2025 PLFS redesign) or different releases
    (code lists differ between releases) are not pooled unless `data.design_mix_justification` is
    present. Only its presence can be checked here; whether the justification is sound is for you
    and your instructor. Files with role `comparison_only` are never pooled and are ignored.
    """
    d = cfg.to_dict()["data"]
    entries = _primary_person_entries(cfg)
    problems: list[str] = []
    if not entries:
        raise DesignMixError("no primary person files declared")
    missing = [e["id"] for e in entries if not e.get("design_id")]
    if missing:
        problems.append(f"file(s) {missing} have no design_id: declare it from the official documentation")
    designs = sorted({str(e.get("design_id")) for e in entries if e.get("design_id")})
    releases = sorted({str(e.get("release_id")) for e in entries if e.get("release_id")})
    mixed_msgs = []
    if len(designs) > 1:
        mixed_msgs.append(f"files span {len(designs)} designs {designs}")
    if len(releases) > 1:
        mixed_msgs.append(f"files span {len(releases)} releases {releases} (code lists differ between releases)")
    justified = bool(d.get("design_mix_justification"))
    if mixed_msgs and not justified:
        problems.append("; ".join(mixed_msgs) + ", and data.design_mix_justification {text, approved_by, date} "
                        "is not set. Files of different designs or releases are not pooled")
    elif mixed_msgs:
        warnings.warn("design/release mix accepted because data.design_mix_justification is present: "
                      + "; ".join(mixed_msgs), stacklevel=2)
    by_period: dict[str, set[str]] = {}
    for e in entries:
        by_period.setdefault(str(e.get("period")), set()).add(str(e.get("sector")))
    if len({frozenset(s) for s in by_period.values()}) > 1:
        problems.append(f"sector coverage differs between periods {({p: sorted(s) for p, s in by_period.items()})}: "
                        "the same sectors must be present at every time point")
    if not _time_col(d["schema"]):
        pairs = [(str(e.get("period")), str(e.get("sector"))) for e in entries]
        dup = sorted({p for p in pairs if pairs.count(p) > 1})
        if dup:
            problems.append(f"more than one file for the same (period, sector) {dup} and no visit/month column")
    if problems:
        raise DesignMixError("design compatibility check failed:\n  - " + "\n  - ".join(problems))


# ---------------------------------------------------------------------------------------------
# Linking
# ---------------------------------------------------------------------------------------------
def _key_collision_counts(frame: pd.DataFrame, columns: list[str]) -> dict[str, int]:
    """Count repeated key-coordinate groups and excess rows; this does not assert row identity."""
    if frame.empty:
        return {"groups": 0, "excess_rows": 0}
    usable = frame.dropna(subset=columns)
    if usable.empty:
        return {"groups": 0, "excess_rows": 0}
    sizes = usable.groupby(columns, dropna=False).size()
    collided = sizes[sizes > 1]
    return {"groups": int(len(collided)), "excess_rows": int((collided - 1).sum())}


def quarter_aware_link_keys(
    frame: pd.DataFrame,
    *,
    key_col: str,
    visit_col: str,
    quarter_col: str,
    n_points: int = 4,
    strict: bool = True,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Apply the configured Q1–Q4/V1–V4 cohort rule to an already-composed candidate key.

    This is a mechanical rule over caller-supplied schema columns; it does not establish that the
    candidate identifiers or quarter semantics are officially valid. It never drops rows or calls
    key-coordinate collisions duplicate records. In strict mode malformed coordinates, an
    incomplete four-visit window, or a repeated key/quarter/visit coordinate raises SchemaError.
    In audit mode (`strict=False`), malformed rows receive no link key and are counted in `stats`.
    """
    required = [key_col, visit_col, quarter_col]
    missing = [c for c in required if c not in frame.columns]
    if missing:
        raise SchemaError(f"quarter-aware linking column(s) missing: {missing}")

    out = frame.copy()
    key = out[key_col].astype("string")
    visit = out[visit_col].astype("string").str.strip().str.upper()
    quarter = out[quarter_col].astype("string").str.strip().str.upper()
    visit_number = pd.to_numeric(visit.str.extract(r"^V([1-4])$", expand=False), errors="coerce").astype("Int64")
    quarter_number = pd.to_numeric(quarter.str.extract(r"^Q([1-4])$", expand=False), errors="coerce").astype("Int64")
    eligible = key.notna() & visit_number.notna() & quarter_number.notna()
    invalid_rows = int((~eligible).sum())

    legacy_frame = pd.DataFrame({"_key": key, "_visit": visit})
    legacy = _key_collision_counts(legacy_frame, ["_key", "_visit"])
    quarter_frame = pd.DataFrame({"_key": key, "_quarter": quarter, "_visit": visit})
    quarter_visit = _key_collision_counts(quarter_frame[eligible], ["_key", "_quarter", "_visit"])

    visit_labels = set(visit[eligible].unique().tolist())
    problems: list[str] = []
    if n_points != 4 or visit_labels != {"V1", "V2", "V3", "V4"}:
        problems.append(f"expected exactly V1, V2, V3 and V4 across four points; found {sorted(visit_labels)}")
    if quarter_number.isna().any():
        problems.append("invalid/missing quarter label; expected Q1, Q2, Q3 or Q4")
    if visit_number.isna().any():
        problems.append("invalid/missing visit label; expected V1, V2, V3 or V4")
    if invalid_rows:
        problems.append(f"{invalid_rows} row(s) have a missing key or invalid/missing quarter/visit label")
    if quarter_visit["excess_rows"]:
        problems.append(f"{quarter_visit['excess_rows']} repeated key/quarter/visit coordinate collision(s); "
                        "this does not establish identical records")
    if strict and problems:
        raise SchemaError("quarter-aware linkage validation failed: " + "; ".join(problems))

    cohort_number = ((quarter_number - visit_number) % 4) + 1
    link_key = pd.Series(pd.NA, index=out.index, dtype="string")
    link_key.loc[eligible] = key.loc[eligible] + "|cohort=Q" + cohort_number.loc[eligible].astype("string")
    out["_quarter_link_key"] = link_key
    out["_quarter_link_time"] = (visit_number - 1).astype("Int64")
    out["_quarter_value"] = quarter.where(eligible)
    stats = {
        "legacy_key_visit_collision_groups": legacy["groups"],
        "legacy_key_visit_collision_excess_rows": legacy["excess_rows"],
        "quarter_visit_collision_groups": quarter_visit["groups"],
        "quarter_visit_collision_excess_rows": quarter_visit["excess_rows"],
        "quarter_link_invalid_rows": invalid_rows,
        "quarter_link_issues": problems,
    }
    return out, stats


def link_persons(tables: dict[str, pd.DataFrame], cfg: Config) -> pd.DataFrame:
    """Stack the primary person files into one long panel, linked by the declared person key.

    Columns: person_id, t, link_quality_flag, raw_status, nonresponse_code, weight, one column per configured attribute
    role (age, sex, sector, social_group, religion), then the training and trainee-rule variables
    under their own names. Quarter-aware configurations also expose `survey_quarter`. `df.attrs`
    records the time map and everything that was dropped.
    """
    d = cfg.to_dict()
    schema = d["data"]["schema"]
    entries = _primary_person_entries(cfg)
    n_points = int(d["time"]["n_points"])
    key_cols, tcol = _key_cols(schema), _time_col(schema)
    qcol = _first(schema.get("quarter"))
    status, nonresp, wcol = _first(schema.get("status_col")), _first(schema.get("nonresponse_col")), _first(schema.get("weight"))
    roles = {r: _first(schema.get(r)) for r in ATTRIBUTE_ROLES if _first(schema.get(r))}
    extras = _needed_columns(cfg)["some"]
    if not key_cols or not status:
        raise SchemaError("data.schema needs a person key and a status_col to link persons")
    clash = [x for x in extras if x in roles or x in ("person_id", "t", "raw_status", "nonresponse_code", "weight")]
    if clash:
        raise SchemaError(f"training/trainee-rule column name(s) {clash} clash with long-panel column names; rename them in the layout")

    parts = []
    for e in entries:
        df = tables.get(e["id"])
        if df is None:
            raise SchemaError(f"file {e['id']}: was not read")
        miss = [c for c in key_cols + [status] + ([tcol] if tcol else []) + ([qcol] if qcol else [])
                if c not in df.columns]
        if miss:
            raise SchemaError(f"file {e['id']}: column(s) {miss} missing from the table")
        if tcol:
            traw = df[tcol].astype("string")
        else:
            traw = pd.Series(str(e.get("period")), index=df.index, dtype="string")
        piece = {
            "key": _make_key(df, key_cols).astype(object),
            "traw": traw.astype(object),
            "raw_status": df[status].astype(object),
            "nonresponse_code": df[nonresp].astype(object) if nonresp and nonresp in df.columns else pd.Series(pd.NA, index=df.index, dtype=object),
            "weight": pd.to_numeric(df[wcol], errors="coerce").astype("float64") if wcol and wcol in df.columns else pd.Series(np.nan, index=df.index),
        }
        if qcol:
            piece["quarter_raw"] = df[qcol].astype("string").astype(object)
            piece["visit_label"] = traw.astype("string").astype(object)
        for role, col in roles.items():
            if col in df.columns:
                piece[role] = pd.to_numeric(df[col], errors="coerce").astype("float64") if role == "age" else df[col].astype(object)
            else:
                piece[role] = pd.Series(pd.NA, index=df.index, dtype=object)
        for x in extras:
            piece[x] = df[x].astype(object) if x in df.columns else pd.Series(pd.NA, index=df.index, dtype=object)
        parts.append(pd.DataFrame(piece))
    panel = pd.concat(parts, ignore_index=True)
    meta: dict[str, Any] = {"is_synthetic": False, "n_records_read": int(len(panel))}

    no_key = panel["key"].isna()
    no_time = panel["traw"].isna()
    meta["n_records_dropped_missing_key"] = 0
    meta["n_records_dropped_no_time"] = 0
    meta["n_records_missing_key"] = int(no_key.sum())
    meta["n_records_missing_time"] = int(no_time.sum())

    if tcol:
        labels = _sorted_labels(panel.loc[panel["traw"].notna(), "traw"].unique())
        rule = "visit/month column values ordered numerically if all numeric, otherwise alphabetically"
    else:
        labels = list(dict.fromkeys(str(e.get("period")) for e in entries))
        rule = "order of data.files (time comes from each file's declared period)"
        if _sorted_labels(labels) != labels:
            warnings.warn(f"data.files order {labels} differs from the sorted order {_sorted_labels(labels)}; "
                          "the data.files order is used. Check it is chronological", stacklevel=2)
    if len(labels) != n_points:
        raise SchemaError(f"found {len(labels)} distinct time points {labels} but time.n_points is {n_points}. "
                          "Set time.n_points to match, or restrict data.files to the intended window; the loader "
                          "will not guess which points to keep")
    tmap = {lab: i for i, lab in enumerate(labels)}
    meta["time_map"], meta["time_order_rule"] = tmap, rule
    mapped_t = panel["traw"].astype("string").map(tmap).astype("Int64")
    panel = panel.assign(t=mapped_t.fillna(-1).astype("int64")).drop(columns="traw")

    quarter_stats: dict[str, Any] = {}
    if qcol:
        panel, quarter_stats = quarter_aware_link_keys(
            panel, key_col="key", visit_col="visit_label", quarter_col="quarter_raw", n_points=n_points,
            strict=False,
        )
        panel["key"] = panel["_quarter_link_key"].astype(object)
        panel["survey_quarter"] = panel["_quarter_value"].astype(object)
        panel = panel.drop(columns=["_quarter_link_key", "_quarter_link_time", "_quarter_value"])
        meta_quarters = sorted(panel["survey_quarter"].dropna().astype(str).unique().tolist())
    else:
        meta_quarters = []

    # Keep every source row. Rows that cannot be safely assigned a candidate link get a
    # unique row key; repeated key/time coordinates are retained and explicitly flagged.
    missing_candidate = panel["key"].isna() | (panel["t"] < 0)
    panel.loc[missing_candidate, "key"] = [f"UNLINKED_ROW_{i}" for i in panel.index[missing_candidate]]
    coord_collision = panel.duplicated(["key", "t"], keep=False)
    panel["link_quality_flag"] = classify_link_quality()
    for key, idx in panel.groupby("key", sort=False).groups.items():
        sub = panel.loc[idx]
        is_sex_change = "sex" in roles and sub["sex"].dropna().nunique() > 1
        is_age_change = "age" in roles and sub["age"].dropna().nunique() > 1
        is_design_change = any(field in sub and sub[field].dropna().astype(str).nunique() > 1
                               for field in DESIGN_CHECK_FIELDS)
        is_collision = bool(coord_collision.loc[idx].any())
        incomplete = bool(sub["key"].astype(str).str.startswith("UNLINKED_ROW_").any())
        panel.loc[idx, "link_quality_flag"] = classify_link_quality(
            sex_change=bool(is_sex_change), age_change=bool(is_age_change),
            design_field_mismatch=bool(is_design_change),
            coordinate_collision=is_collision, incomplete_coordinates=incomplete,
        )
    meta["n_linked_persons"] = int((panel.groupby("key")["t"].nunique() >= 2).sum())
    meta["n_persons_excluded_invalid_link"] = 0
    meta["n_records_excluded"] = 0
    if qcol:
        meta["quarter_aware_linking"] = True
        meta["survey_quarters"] = meta_quarters
        meta["cohort_rule"] = "cohort quarter = (survey quarter - visit number) modulo 4; only equal cohort quarters link"
        meta.update(quarter_stats)

    panel = panel.rename(columns={"key": "person_id"}).sort_values(["person_id", "t"], kind="mergesort").reset_index(drop=True)
    panel["person_id"] = panel["person_id"].astype(str)
    front = ["person_id", "t", "raw_status", "nonresponse_code", "weight"]
    panel = panel[front + [c for c in panel.columns if c not in front]]
    meta["n_persons"], meta["n_records"] = int(panel["person_id"].nunique()), int(len(panel))
    panel.attrs.update(meta)
    return panel


# ---------------------------------------------------------------------------------------------
# Trainees
# ---------------------------------------------------------------------------------------------
def identify_trainees(long_df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Keep persons flagged by the declared trainee rule: at least one valid record whose code is a yes-code.

    The rule (`trainee.rules.<trainee.definition>`: variable and codes_yes) comes from config. The
    wording of what these persons are is fixed by `trainee.timing_support`: unless timing is
    `dated`, they are "ever-trained persons" and post-training wording is blocked. Whether the
    variable means what you think it means is the audit's `refers_to_ambiguous` flag and your
    verification, not something this function can know. Synthetic panels always use their generator-owned
    `trained` marker, regardless of the real-data rule in config.
    """
    d = cfg.to_dict()["trainee"]
    definition = d["definition"]
    rule = (d["rules"] or {}).get(definition) or {}
    synthetic = "is_synthetic" in long_df.columns and bool(long_df["is_synthetic"].all())
    if synthetic:
        var, yes = SYNTHETIC_TRAINING_RULE
    else:
        var, yes = rule.get("variable"), rule.get("codes_yes")
    if not var or not yes:
        raise SchemaError(f"trainee.rules.{definition} is not set (variable and codes_yes): trainees cannot be identified. "
                          "Fill it from the audit's training_variable_report")
    if var not in long_df.columns:
        raise SchemaError(f"trainee variable {var!r} is not in the long panel")
    yes_s = [str(c) for c in yes]
    valid = long_df[var].notna()
    hit = valid & long_df[var].astype(str).isin(yes_s)
    if not hit.any():
        seen = sorted(long_df.loc[valid, var].astype(str).unique())[:15]
        raise SchemaError(f"none of the yes-codes {yes_s} occur in {var!r} (codes present: {seen})")
    flagged = set(long_df.loc[hit, "person_id"])
    out = long_df[long_df["person_id"].isin(flagged)].reset_index(drop=True)
    dated = d["timing_support"] == "dated"
    out.attrs.update(long_df.attrs)
    out.attrs.update({
        "trainee_definition": definition, "trainee_variable": var, "trainee_codes_yes": yes_s,
        "n_persons_before_trainee_filter": int(long_df["person_id"].nunique()),
        "n_persons_trainees": int(len(flagged)),
        "timing_support": d["timing_support"], "post_training_wording_allowed": dated,
        "wording": ("persons whose outcomes follow a documented training date" if dated else
                    "ever-trained persons, as flagged by the declared training variable (when the training happened "
                    "relative to the observed outcomes is unknown)"),
    })
    return out


# ---------------------------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------------------------
def load_long_panel(cfg: Config, synthetic: bool = False) -> pd.DataFrame:
    """The long panel of ALL linked persons (trainee selection is identify_trainees' job).

    synthetic=True returns the labelled synthetic panel and skips the data gate. synthetic=False
    needs data.plan == "A", a verified mapping and a compatible design, then reads, verifies and links.
    """
    if synthetic:
        df, truth = generate_synthetic(cfg)
        df.attrs.update({"is_synthetic": True, "n_persons": int(df["person_id"].nunique()),
                         "n_records": int(len(df)), "planted_sizes": truth.params["sizes"]})
        return df
    d = cfg.to_dict()["data"]
    if d["plan"] != "A":
        raise SchemaError(f"data.plan is {d['plan']!r}: the loader builds trajectories only for Plan A. Plan B and C "
                          "are not trajectory analyses and need docs/SCOPE_CHANGE_MEMO.md and approval first")
    verify_design_compatibility(cfg)
    tables = load_raw_tables(cfg)
    verify_schema(tables, cfg)
    return link_persons(tables, cfg)


# ---------------------------------------------------------------------------------------------
# Smoke demo: a synthetic panel is written out as raw files, loaded through the REAL path, and must come back identical
# ---------------------------------------------------------------------------------------------
def _letter_config_dict() -> dict:
    """The project config with real-looking one-letter raw codes (no UNVERIFIED placeholders), for the demo only."""
    d = load_config().to_dict()
    for st, code in zip(d["states"], "ABCDEF"):
        st["raw_codes"] = [code]
    d["unknown_codes"], d["lost_codes"] = ["X"], ["L"]
    d["lost_codes_status"] = "documented"  # synthetic demo mapping only
    return d


def _demo_raw_table(df_syn: pd.DataFrame) -> pd.DataFrame:
    """Write-ready raw columns (household, person number, visit, ...) for a synthetic long panel."""
    i = df_syn["person_id"].str[1:].astype(int)
    raw = pd.DataFrame({"hh": [f"H{k // 3:05d}" for k in i], "pn": [str(k % 3 + 1) for k in i], "visit": df_syn["t"] + 1,
                        "age": df_syn["age"], "sex": df_syn["sex"], "sector": df_syn["sector"],
                        "act": df_syn["raw_status"], "nr": df_syn["nonresponse_code"], "wt": df_syn["weight"],
                        "trained": df_syn["trained"]})
    return raw


def _demo() -> int:
    import tempfile
    from pathlib import Path

    import yaml

    cfg0 = load_config()
    # 1) the synthetic entry point
    syn = load_long_panel(cfg0, synthetic=True)
    tr = identify_trainees(syn, cfg0)
    print("SYNTHETIC DEMONSTRATION - NOT PLFS RESULTS")
    print(f"synthetic panel: rows={len(syn)} persons={syn.attrs['n_persons']}  trainees={tr.attrs['n_persons_trainees']}")
    print(f"wording: {tr.attrs['wording']}")

    # 2) the real path, on a synthetic panel written as raw files
    d_letters = _letter_config_dict()
    df_syn, _ = generate_synthetic(Config(d_letters, cfg0.root), n=400, seed_offset=7)
    checks: dict[str, bool] = {}
    for mode in ("one_file_with_visit_column", "one_file_per_visit"):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data" / "raw").mkdir(parents=True)
            raw = _demo_raw_table(df_syn)
            # The production loader audits these design fields when they are not otherwise
            # configured roles. Give the synthetic panel stable fixture values so its schema
            # test exercises the same loader contract without depending on PLFS columns.
            for field, value in (("stratum", "S1"), ("sub_stratum", "SS1"),
                                 ("sub_sample", "SUB1"), ("fod_sub_region", "FOD1")):
                raw[field] = value
            d = load_config().to_dict()
            d.update({k: d_letters[k] for k in ("states", "unknown_codes", "lost_codes", "lost_codes_status")})
            cols = {"hh": {}, "pn": {}, "visit": {}, "age": {"dtype": "int"}, "sex": {}, "sector": {}, "act": {},
                    "nr": {}, "wt": {"dtype": "float"}, "trained": {}, "stratum": {}, "sub_stratum": {},
                    "sub_sample": {}, "fod_sub_region": {}}
            files, layouts = [], {}
            groups = [("all", raw)] if mode == "one_file_with_visit_column" else [(f"v{v}", g) for v, g in raw.groupby("visit")]
            for fid, g in groups:
                g.drop(columns="visit" if mode == "one_file_per_visit" else []).to_csv(root / "data" / "raw" / f"{fid}.csv", index=False)
                files.append({"id": fid, "path": f"data/raw/{fid}.csv", "release_id": "demo", "design_id": "demo_design",
                              "period": f"M{g['visit'].iloc[0]}" if mode == "one_file_per_visit" else "all", "sector": "both",
                              "kind": "person", "role": "primary"})
                layouts[fid] = {"format": "csv", "columns": {k: v for k, v in cols.items()
                                                             if not (mode == "one_file_per_visit" and k == "visit")}}
            d["data"].update(files=files, layouts=layouts, plan="A", verified=True, period="demo", sector_coverage="both")
            d["data"]["schema"].update(household_id="hh", person_id="pn", sector="sector", age="age", sex="sex",
                                       status_col="act", nonresponse_col="nr", weight="wt", training_cols=["trained"],
                                       visit="visit" if mode == "one_file_with_visit_column" else None,
                                       quarter=None)
            d["trainee"]["rules"] = {"ever_trained": {"variable": "trained", "codes_yes": ["Y"]}}
            with open(root / "config.yaml", "w", encoding="utf-8") as fh:
                yaml.safe_dump(d, fh, sort_keys=False)
            cfg = load_config(root / "config.yaml")
            got = load_long_panel(cfg)
            got_tr = identify_trainees(got, cfg)

        # back to the synthetic ordering: person id "H00000|1" -> index
        idx = got["person_id"].map(lambda s: (int(s.split("|")[0][1:]) * 3 + int(s.split("|")[1]) - 1))
        a = df_syn.assign(i=df_syn["person_id"].str[1:].astype(int)).sort_values(["i", "t"]).reset_index(drop=True)
        b = got.assign(i=idx).sort_values(["i", "t"]).reset_index(drop=True)
        same = len(a) == len(b) and (a["i"].to_numpy() == b["i"].to_numpy()).all() and (a["t"].to_numpy() == b["t"].to_numpy()).all()
        for c in ("raw_status", "nonresponse_code", "sex", "sector"):
            same = same and (a[c].fillna("<NA>").astype(str).to_numpy() == b[c].fillna("<NA>").astype(str).to_numpy()).all()
        for c in ("age", "weight"):
            same = same and np.allclose(a[c].to_numpy(float), b[c].to_numpy(float))
        checks[f"[{mode}] round trip equals the synthetic panel"] = bool(same)
        checks[f"[{mode}] time map is visit order"] = list(got.attrs["time_map"].values()) == [0, 1, 2, 3]
        checks[f"[{mode}] all persons are trainees"] = got_tr.attrs["n_persons_trainees"] == got.attrs["n_persons"] == 400
        checks[f"[{mode}] not flagged synthetic"] = "is_synthetic" not in got.columns and got.attrs["is_synthetic"] is False

    for name, ok in checks.items():
        print(f"  demo check [{'ok' if ok else 'FAILED'}]: {name}")
    if not all(checks.values()):
        return 1
    print(f"Demo checks passed ({len(checks)}). The panels above are SYNTHETIC; nothing was written to the project.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_demo())
