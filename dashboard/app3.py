"""Employment Outcome Pathway Analytics: Turkey ISKUR dashboard (read-only).

Shows the saved, validated outputs of `src.turkey_pipeline` and nothing else.
Every number on the page is read from `outputs/turkey/` at run time. Before
anything is shown, the source file named in `summary.json` is hashed and compared
with the SHA-256 recorded by the pipeline; on a mismatch the results are hidden.

This file imports no PLFS, synthetic or legacy-pathway module. It computes no
statistics and fits no model: it reads, formats and draws saved values, and
derives only plain descriptive sentences (largest, highest, change) from them.

Navigation is a left sidebar (collapsible with Streamlit's own control). The
selected section is kept in the URL (?section=...), so a reload or a shared link
opens the same section.

Run from the project root:
    streamlit run dashboard/app3.py
    python dashboard/app3.py --self-test

To refresh the numbers, rerun `python -m src.turkey_pipeline`.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------------------------
# Design tokens (charcoal surfaces; cyan / pink / purple / green / amber accents)
# ---------------------------------------------------------------------------------------------
BG, CARD, LINE = "#1a1a1b", "#232324", "#333335"
TEXT, MUTED = "#f3f3f4", "#9b9ba1"
CYAN, PINK, PURPLE, GREEN, AMBER, BLUE = "#6cc5c9", "#f0698a", "#9a7bf0", "#7ac75a", "#e8a94d", "#4f94e0"
SLATE = "#6b7280"
PATHWAY_COLOURS = [CYAN, PINK, AMBER, PURPLE, GREEN, BLUE]
FONT = "Inter, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"

OUT_DIR = ("outputs", "turkey")
EXTRA_TABLES = {
    "baseline": "baseline_employed_comparison.csv",
    "admin": "cluster_admin_profile.csv",
    "state": "cluster_jan2012_state_profile.csv",
    "methods": "cluster_method_evaluation.csv",
    "gender": "cluster_gender_profile.csv",
    "baseline_by_cluster": "baseline_employment_by_cluster.csv",
    "attrition": "attrition_admin_comparison.csv",
}
REPORT_FILE = "cluster_profile_report.md"
STAGES = ["Pre-course any work", "Post-course any work", "Aug 2013 formal work"]
STAGE_COLS = {"baseline_any_work_rate": STAGES[0], "followup_any_work_rate": STAGES[1], "aug2013_formal_work_rate": STAGES[2]}

# Sidebar sections: (name, icon path data). Names are the radio options, in this order.
NAV = [
    ("Overview", "M3 10.5L12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"),
    ("Employment Pathways", "M6 8.5a2.6 2.6 0 1 0 0-.01M6 18.5a2.6 2.6 0 1 0 0-.01M18 13.5a2.6 2.6 0 1 0 0-.01M6 10.6v5.2M8.2 7.4l7.6 4.3M8.2 17.2l7.6-3.9"),
    ("Baseline Comparison", "M5 20V10M12 20V4M19 20v-7M3 20h18"),
    ("Training Outcomes", "M22 9L12 4 2 9l10 5 10-5zM6 11.2V16c0 1.5 2.7 3 6 3s6-1.5 6-3v-4.8"),
    ("Administrative Outcomes", "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"),
    ("Attrition & Stability", "M12 3l8 3v6c0 5-3.4 8-8 9-4.6-1-8-4-8-9V6zM8.6 12.2l2.4 2.4 4.4-4.8"),
    ("Scope & Provenance", "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5M9 13h6M9 17h6"),
]
SECTIONS = [n for n, _ in NAV]

ICONS = {
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
             '<path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "network": '<circle cx="6" cy="6" r="2.6"/><circle cx="6" cy="18" r="2.6"/><circle cx="18" cy="12" r="2.6"/>'
               '<path d="M6 8.6v6.8M8.3 7.2l7.4 3.6M8.3 16.8l7.4-3.6"/>',
    "target": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.2"/>',
    "trend": '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
    "shield": '<path d="M12 3l8 3v6c0 5-3.4 8-8 9-4.6-1-8-4-8-9V6z"/><path d="M8.6 12.2l2.4 2.4 4.4-4.8"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
}


class _Cfg:
    """Minimal stand-in carrying only the project root (used when no project config is needed)."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)


# ---------------------------------------------------------------------------------------------
# Pure helpers (no streamlit)
# ---------------------------------------------------------------------------------------------
def get_config() -> Any:
    """Project config, a bare root for tests (TURKEY_DASHBOARD_ROOT), or the file named by PATHWAYS_CONFIG."""
    override = os.environ.get("TURKEY_DASHBOARD_ROOT")
    if override:
        return _Cfg(Path(override))
    from src.config import load_config  # lazy: the page needs only cfg.root
    path = os.environ.get("PATHWAYS_CONFIG")
    return load_config(path) if path else load_config(str(ROOT / "config.yaml"))


def fmt(v: Any, spec: str = ".3f") -> str:
    """Number to text; None or NaN is shown as n/a, never as a number."""
    if v is None or (isinstance(v, float) and v != v):
        return "n/a"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int, float)):
        if spec == "d":
            return f"{int(v):,}"
        return format(v, spec) if isinstance(v, float) else f"{v:,}"
    return str(v)


def pct(v: Any, digits: int = 1) -> str:
    """Fraction (0..1) to a percentage string; missing values are n/a."""
    n = pd.to_numeric(v, errors="coerce")
    return "n/a" if pd.isna(n) else f"{float(n) * 100:.{digits}f}%"


def esc(v: Any) -> str:
    return html.escape(str(v), quote=True)


def clean_path(message: str, cfg: Any) -> str:
    root = str(cfg.root)
    return message.replace(root, "<project>").replace(root.replace("\\", "/"), "<project>")


def pathway_label(cluster_id: Any) -> str:
    try:
        return f"Pathway {int(float(cluster_id))}"
    except (TypeError, ValueError):
        return f"Pathway {cluster_id}"


def pathway_colours(prevalence: pd.DataFrame) -> dict[str, str]:
    labels = [pathway_label(x) for x in prevalence["cluster_id"]]
    return {lab: PATHWAY_COLOURS[i % len(PATHWAY_COLOURS)] for i, lab in enumerate(labels)}


def read_csv_safe(path: Path) -> pd.DataFrame | None:
    try:
        return pd.read_csv(path) if path.is_file() else None
    except (OSError, ValueError):
        return None


def load_turkey(cfg: Any) -> dict[str, Any]:
    """Load saved Turkey outputs after validating provenance.

    Returns {"status": "ok" | "missing" | "invalid", ...}. Nothing is computed here.
    The source file's SHA-256 must equal the value saved by the pipeline, and the source
    must live inside the project folder.
    """
    root = Path(cfg.root).joinpath(*OUT_DIR)
    summary_path, table_path = root / "summary.json", root / "cluster_prevalence.csv"
    if not summary_path.is_file() or not table_path.is_file():
        return {"status": "missing"}
    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("summary.json is not a JSON object")
        source = (Path(cfg.root) / payload["input"]).resolve()
        source.relative_to(Path(cfg.root).resolve())
        if hashlib.sha256(source.read_bytes()).hexdigest() != payload.get("input_sha256"):
            raise ValueError("Turkey source hash does not match the saved analysis")
        table = pd.read_csv(table_path)
        if "cluster_id" not in table.columns or table.empty:
            raise ValueError("cluster_prevalence.csv has no pathway rows")
    except (OSError, KeyError, TypeError, ValueError) as exc:
        return {"status": "invalid", "reason": clean_path(str(exc) or exc.__class__.__name__, cfg)}
    tables = {key: read_csv_safe(root / name) for key, name in EXTRA_TABLES.items()}
    report = root / REPORT_FILE
    inventory = [("summary.json", f"{len(payload)} saved fields"), ("cluster_prevalence.csv", f"{len(table)} rows × {table.shape[1]} columns")]
    for key, name in EXTRA_TABLES.items():
        frame = tables[key]
        inventory.append((name, f"{len(frame)} rows × {frame.shape[1]} columns" if frame is not None else "not saved"))
    inventory.append((REPORT_FILE, "saved" if report.is_file() else "not saved"))
    return {"status": "ok", "payload": payload, "prevalence": table, "tables": tables, "root": root,
            "source": str(source.relative_to(Path(cfg.root).resolve())).replace("\\", "/"),
            "report": report.read_text(encoding="utf-8") if report.is_file() else None, "inventory": inventory}


def kpi_items(payload: dict[str, Any], prevalence: pd.DataFrame) -> list[dict[str, str]]:
    """Four headline cards, every value taken from the saved summary and table."""
    stab = payload.get("cluster_stability") or {}
    share = pd.to_numeric(prevalence["share_complete_pathways"], errors="coerce") if "share_complete_pathways" in prevalence else None
    smallest = f"smallest pathway {pct(share.min())} of attendees" if share is not None and share.notna().any() else "pathway sizes not saved"
    n_rows = payload.get("n_rows")
    return [
        {"icon": "users", "colour": CYAN, "label": "Complete sequences",
         "value": fmt(payload.get("n_valid_post_training_trajectories"), "d"),
         "sub": f"from {fmt(n_rows, 'd')} original applicants" if n_rows is not None else "original applicant count not saved"},
        {"icon": "network", "colour": GREEN, "label": "Employment pathways",
         "value": fmt(payload.get("selected_k"), "d"), "sub": smallest},
        {"icon": "target", "colour": AMBER, "label": "Hamming silhouette",
         "value": fmt(payload.get("silhouette_hamming"), ".4f"), "sub": "internal separation of the pathways"},
        {"icon": "trend", "colour": PURPLE, "label": "Mean stability ARI",
         "value": fmt(stab.get("ari_mean"), ".4f"),
         "sub": f"{fmt(stab.get('replicates'), 'd')} subsample refits · SD {fmt(stab.get('ari_sd'), '.3f')}"},
    ]


def key_findings(prevalence: pd.DataFrame) -> list[dict[str, str]]:
    """Plain descriptive sentences (largest, highest, change) derived from the saved pathway table."""
    out: list[dict[str, str]] = []
    frame = prevalence.copy()
    frame["Pathway"] = frame["cluster_id"].map(pathway_label)

    def num(col: str) -> pd.Series | None:
        return pd.to_numeric(frame[col], errors="coerce") if col in frame.columns else None
    n, share = num("n"), num("share_complete_pathways")
    if n is not None and n.notna().any():
        i = n.idxmax()
        extra = f" ({pct(share[i])} of attendees)" if share is not None and pd.notna(share[i]) else ""
        out.append({"label": "Largest pathway", "colour": CYAN, "text": f"{frame.at[i, 'Pathway']}: {fmt(int(n[i]), 'd')} people{extra}."})
    aug = num("aug2013_formal_work_rate")
    if aug is not None and aug.notna().any():
        i = aug.idxmax()
        out.append({"label": "Highest formal work, Aug 2013", "colour": AMBER, "text": f"{frame.at[i, 'Pathway']}: {pct(aug[i])} in formal employment."})
    pre, post = num("baseline_any_work_rate"), num("followup_any_work_rate")
    if pre is not None and post is not None:
        delta = (post - pre) * 100
        if delta.notna().any():
            i = delta.abs().idxmax()
            out.append({"label": "Largest pre-to-post change", "colour": PINK,
                        "text": f"{frame.at[i, 'Pathway']}: any-work share moves from {pct(pre[i])} to {pct(post[i])} ({delta[i]:+.1f} percentage points)."})
    comp = num("completion_share_observed")
    if comp is not None and comp.notna().any():
        i = comp.idxmax()
        out.append({"label": "Highest course completion", "colour": GREEN, "text": f"{frame.at[i, 'Pathway']}: {pct(comp[i])} of those with a known outcome."})
    return out


def humanise(column: str) -> str:
    if column.lower() == "n":
        return "People"
    text = column.replace("_", " ").strip()
    return text[:1].upper() + text[1:]


def is_share_column(name: str) -> bool:
    low = name.lower()
    return any(t in low for t in ("share", "rate", "pct", "percent"))


def tidy_table(frame: pd.DataFrame, rename: dict[str, str] | None = None, percent: tuple[str, ...] = ()) -> pd.DataFrame:
    """Display copy: pathway ids as labels, readable headers, percentages and thousands separators."""
    shown = frame.copy()
    if "cluster_id" in shown.columns:
        shown["cluster_id"] = shown["cluster_id"].map(pathway_label)
        shown = shown.rename(columns={"cluster_id": "Pathway"})
    rename = rename or {}
    out = pd.DataFrame(index=shown.index)
    for col in shown.columns:
        label = rename.get(col, humanise(col) if col != "Pathway" else col)
        series = shown[col]
        if pd.api.types.is_bool_dtype(series):
            out[label] = series.map(lambda x: "n/a" if pd.isna(x) else ("Yes" if x else "No"))
            continue
        numeric = pd.to_numeric(series, errors="coerce")
        if pd.api.types.is_numeric_dtype(series) or (numeric.notna().sum() == series.notna().sum() and series.notna().any() and col != "Pathway"):
            as_pct = (col in percent or label in percent) or (not percent and is_share_column(col) and numeric.dropna().between(0, 1).all())
            if as_pct:
                out[label] = numeric.map(lambda x: pct(x))
            elif (numeric.dropna() % 1 == 0).all():
                out[label] = numeric.map(lambda x: "n/a" if pd.isna(x) else f"{int(x):,}")
            else:
                out[label] = numeric.map(lambda x: "n/a" if pd.isna(x) else f"{x:,.3f}")
        else:
            out[label] = series.map(lambda x: "n/a" if pd.isna(x) else str(x))
    return out


def format_gender_table(gender: pd.DataFrame, colours: dict[str, str] | None = None) -> pd.DataFrame:
    """Format gender profile into a clean pathway summary with counts and shares."""
    if {"cluster_id", "MM_gender", "n"}.issubset(gender.columns):
        p = gender.copy()
        p["gender"] = p["MM_gender"].fillna("Unknown").replace({"": "Unknown"})
        pivot = p.pivot_table(index="cluster_id", columns="gender", values="n", aggfunc="sum", fill_value=0).reset_index()
        tot = pivot.drop(columns=["cluster_id"]).sum(axis=1)
        out = pd.DataFrame()
        out["Pathway"] = pivot["cluster_id"].map(pathway_label)
        if "Female" in pivot.columns:
            out["Female (people)"] = pivot["Female"].map(lambda x: f"{int(x):,}")
            out["Female share"] = (pivot["Female"] / tot).map(pct)
        if "Male" in pivot.columns:
            out["Male (people)"] = pivot["Male"].map(lambda x: f"{int(x):,}")
            out["Male share"] = (pivot["Male"] / tot).map(pct)
        out["People"] = tot.map(lambda x: f"{int(x):,}")
        return out
    return tidy_table(gender, {"female_share": "Female share", "n": "People"}, percent=("female_share", "Female share"))


def format_baseline_cluster_table(by_cluster: pd.DataFrame) -> pd.DataFrame:
    """Format baseline employment split by cluster into a clean summary table."""
    if {"path_baseline_any_work", "cluster_id", "n"}.issubset(by_cluster.columns):
        p = by_cluster.copy()
        p["status"] = p["path_baseline_any_work"].map({0: "Not working", 1: "Worked before"}).fillna(p["path_baseline_any_work"].astype(str))
        pivot = p.pivot_table(index="cluster_id", columns="status", values="n", aggfunc="sum", fill_value=0).reset_index()
        tot = pivot.drop(columns=["cluster_id"]).sum(axis=1)
        out = pd.DataFrame()
        out["Pathway"] = pivot["cluster_id"].map(pathway_label)
        if "Not working" in pivot.columns:
            out["Not working at baseline (people)"] = pivot["Not working"].map(lambda x: f"{int(x):,}")
            out["Not working share"] = (pivot["Not working"] / tot).map(pct)
        if "Worked before" in pivot.columns:
            out["Worked before baseline (people)"] = pivot["Worked before"].map(lambda x: f"{int(x):,}")
            out["Worked before share"] = (pivot["Worked before"] / tot).map(pct)
        out["People"] = tot.map(lambda x: f"{int(x):,}")
        return out
    return tidy_table(by_cluster, {"baseline_worked_share": "Pre-course work share", "n": "People"}, percent=("baseline_worked_share", "Pre-course work share"))


def html_table(frame: pd.DataFrame, colours: dict[str, str] | None = None) -> str:
    """Escaped HTML table that wraps text instead of scrolling sideways."""
    if frame.empty:
        return ""

    def _is_num(text: Any) -> bool:
        t = str(text).replace(",", "").replace("%", "").replace("-", "", 1)
        return t.replace(".", "", 1).isdigit()
    numeric_cols = {c for c in frame.columns if c != "Pathway" and frame[c].map(lambda v: _is_num(v) or str(v) == "n/a").all()}
    head = "".join(f'<th class="{"num" if c in numeric_cols else ""}">{esc(c)}</th>' for c in frame.columns)
    rows = []
    for _, row in frame.iterrows():
        cells = []
        for col, val in row.items():
            if col == "Pathway":
                dot = (colours or {}).get(str(val), SLATE)
                cells.append(f'<td class="path"><span class="dot" style="background:{dot}"></span>{esc(val)}</td>')
            else:
                cells.append(f'<td class="{"num" if col in numeric_cols else ""}">{esc(val)}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return f'<div class="tbl"><table><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def melt_percent(frame: pd.DataFrame, id_col: str, columns: dict[str, str]) -> pd.DataFrame:
    """Long format of fraction columns as percentages; only columns that exist are used."""
    present = {c: label for c, label in columns.items() if c in frame.columns}
    if not present or id_col not in frame.columns:
        return pd.DataFrame(columns=[id_col, "Series", "Percent"])
    long = frame[[id_col, *present]].rename(columns=present).melt(id_vars=id_col, var_name="Series", value_name="Percent")
    long["Percent"] = pd.to_numeric(long["Percent"], errors="coerce") * 100
    return long.dropna(subset=["Percent"])


def selection_note(methods: pd.DataFrame | None, selected_k: Any) -> str:
    """Why a higher-silhouette k was not chosen, computed from the saved candidate table."""
    if methods is None or not {"k", "silhouette_hamming", "eligible_min_5pct", "min_cluster_share"} <= set(methods.columns):
        return ""
    try:
        chosen = methods[methods["k"].astype(float) == float(selected_k)]
    except (TypeError, ValueError):
        return ""
    if chosen.empty:
        return ""
    base = float(chosen["silhouette_hamming"].iloc[0])
    eligible = methods["eligible_min_5pct"].astype(str).str.lower().isin(["true", "1", "yes"])
    notes = []
    for _, r in methods[(~eligible) & (methods["silhouette_hamming"].astype(float) > base)].iterrows():
        notes.append(f"k={int(float(r['k']))} has a higher silhouette ({float(r['silhouette_hamming']):.4f}) but its smallest pathway "
                     f"({pct(r['min_cluster_share'])}) is below the predeclared 5% cohort-size floor, so k={int(float(selected_k))} is selected.")
    return " ".join(notes)


# ---------------------------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------------------------
def _nav_icon_css() -> str:
    rules = []
    for i, (_, path) in enumerate(NAV, start=1):
        uri = ("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' "
               f"stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'><path d='{path}'/></svg>")
        rules.append(f'[data-testid="stSidebar"] [data-testid="stRadioGroup"] > div:nth-of-type({i}) [data-testid="stRadioOption"]::before {{ -webkit-mask-image:url("{uri}"); mask-image:url("{uri}"); }}')
    return "\n".join(rules)


CSS = f"""
<style>
:root {{ --bg:{BG}; --card:{CARD}; --line:{LINE}; --text:{TEXT}; --muted:{MUTED}; }}
.stApp {{ background:radial-gradient(1100px 520px at 18% -8%, rgba(108,197,201,.09), transparent 60%),
          radial-gradient(900px 480px at 96% -6%, rgba(154,123,240,.09), transparent 60%), var(--bg);
          background-attachment:fixed; color:var(--text); font-family:{FONT}; color-scheme:dark; }}
header[data-testid="stHeader"] {{ background:transparent; }}
#MainMenu, footer, [data-testid="stAppDeployButton"], [data-testid="stMainMenu"], [data-testid="stToolbarActions"], [data-testid="stDecoration"] {{ display:none !important; visibility:hidden; }}
.block-container {{ max-width:1560px; padding:1.4rem clamp(1rem,2.6vw,2.8rem) 3.5rem; }}
[data-testid="stMarkdownContainer"] {{ color:var(--text); }}
[data-testid="stHorizontalBlock"] {{ align-items:stretch; }}
[data-testid="stColumn"] > [data-testid="stVerticalBlock"] {{ height:100%; }}
[data-testid="stColumn"] > [data-testid="stVerticalBlock"] > [data-testid="stLayoutWrapper"]:has([class*="st-key-card_"]) {{ flex:1 1 auto; display:flex; flex-direction:column; }}
[data-testid="stLayoutWrapper"] > [class*="st-key-card_"] {{ flex:1 1 auto; }}
/* ---------- sidebar ---------- */
[data-testid="stSidebar"] {{ background:linear-gradient(180deg,#1e1d29 0%,#18181b 46%,#17161d 100%); border-right:1px solid #2c2c31; }}
[data-testid="stSidebar"] > div:first-child {{ background:transparent; }}
[data-testid="stSidebarContent"] {{ padding-bottom:1rem; }}
[data-testid="stSidebarHeader"] {{ padding:1rem 1rem .2rem 1.2rem; }}
[data-testid="stSidebarCollapseButton"] button, [data-testid="stExpandSidebarButton"], [data-testid="stSidebarCollapsedControl"] button {{ color:#cfcfd6 !important; border-radius:10px !important; }}
[data-testid="stSidebarCollapseButton"] button:hover, [data-testid="stExpandSidebarButton"]:hover {{ background:#2b2b30 !important; color:{CYAN} !important; }}
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"], [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {{ gap:.6rem; }}
.brand {{ display:flex; align-items:center; gap:.85rem; padding:.2rem .2rem 1rem; border-bottom:1px solid #2c2c31; margin-bottom:.9rem; }}
.brand .mark {{ flex:0 0 auto; width:42px; height:42px; border-radius:12px; display:grid; place-items:center; background:linear-gradient(135deg,{CYAN},{PURPLE}); box-shadow:0 6px 18px rgba(154,123,240,.35); }}
.brand .mark svg {{ width:22px; height:22px; fill:none; stroke:#0f1316; stroke-width:2.2; stroke-linecap:round; stroke-linejoin:round; }}
.brand .t {{ font-weight:760; font-size:1.08rem; letter-spacing:-.01em; color:#fff; line-height:1.15; }}
.brand .s {{ font-size:.78rem; color:{MUTED}; margin-top:.15rem; }}
[data-testid="stSidebar"] [data-testid="stRadio"] > label {{ display:none; }}
[data-testid="stSidebar"] [data-testid="stRadioGroup"] {{ gap:.3rem; width:100%; }}
[data-testid="stSidebar"] [data-testid="stRadioGroup"] > div {{ width:100%; margin:0; }}
[data-testid="stSidebar"] [data-testid="stRadioOption"] {{ position:relative; display:flex; align-items:center; gap:.85rem; width:100%; box-sizing:border-box; padding:.72rem .9rem; margin:0; border-radius:13px;
    border:1px solid transparent; color:#b9b9c1; cursor:pointer; transition:background .18s ease, color .18s ease, border-color .18s ease, transform .18s ease; }}
[data-testid="stSidebar"] [data-testid="stRadioOption"] > div {{ display:flex; align-items:center; margin:0; min-width:0; }}
[data-testid="stSidebar"] [data-testid="stRadioOption"] > div > div:first-child {{ display:none !important; }}
[data-testid="stSidebar"] [data-testid="stRadioOption"]::before {{ content:""; flex:0 0 auto; width:21px; height:21px; background-color:currentColor;
    -webkit-mask-repeat:no-repeat; mask-repeat:no-repeat; -webkit-mask-position:center; mask-position:center; -webkit-mask-size:contain; mask-size:contain; }}
[data-testid="stSidebar"] [data-testid="stRadioOption"] p {{ font-size:.96rem; font-weight:600; color:inherit !important; margin:0; line-height:1.25; }}
[data-testid="stSidebar"] [data-testid="stRadioOption"]:hover {{ background:#26262c; color:#f0f0f4; transform:translateX(2px); }}
[data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"] {{ color:#fff; background:linear-gradient(90deg,rgba(154,123,240,.38),rgba(108,197,201,.12));
    border-color:rgba(154,123,240,.55); box-shadow:0 8px 22px rgba(120,90,220,.22); }}
[data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"]::before {{ color:{CYAN}; }}
[data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"]::after {{ content:""; position:absolute; left:-1px; top:22%; bottom:22%; width:3px; border-radius:3px; background:{CYAN}; box-shadow:0 0 10px {CYAN}; }}
[data-testid="stSidebar"] [data-testid="stRadioOption"]:focus-within {{ outline:2px solid rgba(108,197,201,.55); outline-offset:1px; }}
{_nav_icon_css()}
.dscard {{ margin-top:1.1rem; padding:1rem 1.05rem; border-radius:16px; background:rgba(255,255,255,.035); border:1px solid #2f2f36; }}
.dscard .r {{ padding:.55rem 0; border-bottom:1px solid #2c2c33; }}
.dscard .r:last-child {{ border-bottom:none; padding-bottom:0; }}
.dscard .r:first-child {{ padding-top:0; }}
.dscard .l {{ font-size:.72rem; letter-spacing:.06em; text-transform:uppercase; color:{MUTED}; font-weight:650; }}
.dscard .v {{ font-size:.88rem; color:#e8e8ec; margin-top:.15rem; line-height:1.35; overflow-wrap:anywhere; }}
.dscard .ok {{ color:{GREEN}; }}
.sidefoot {{ margin-top:1rem; text-align:center; color:{MUTED}; font-size:.8rem; }}
/* ---------- main header ---------- */
.hero {{ display:flex; justify-content:space-between; align-items:flex-start; gap:1.5rem; flex-wrap:wrap; padding:.2rem 0 1.3rem; }}
.hero h1 {{ padding:0; font-size:clamp(1.7rem,2.6vw,2.45rem); font-weight:780; letter-spacing:-.025em; line-height:1.12; margin:0 0 .5rem; color:var(--text);
           background:linear-gradient(92deg,#fff 30%,{CYAN} 120%); -webkit-background-clip:text; background-clip:text; -webkit-text-fill-color:transparent; }}
.hero .sub {{ font-size:1.04rem; color:var(--muted); margin:0; }}
.chips {{ display:flex; gap:.6rem; flex-wrap:wrap; align-items:center; }}
.chip {{ display:inline-flex; align-items:center; gap:.5rem; padding:.45rem .95rem; border-radius:999px; font-size:.82rem; font-weight:600;
        border:1px solid var(--line); background:#202021; color:#d9d9dd; white-space:nowrap; }}
.chip.ok {{ border-color:#3b5a33; color:{GREEN}; background:#1f2a1d; }}
.chip .dot {{ width:8px; height:8px; border-radius:50%; background:currentColor; box-shadow:0 0 8px currentColor; }}
.scope {{ display:flex; gap:.9rem; align-items:flex-start; background:#1f2226; border:1px solid #2f3540; border-radius:14px; padding:.9rem 1.15rem;
         color:#c9ced6; font-size:.92rem; line-height:1.55; margin:.2rem 0 1.4rem; }}
.scope b {{ color:#eaf7f8; }}
.scope svg {{ flex:0 0 auto; width:22px; height:22px; margin-top:2px; fill:none; stroke:{CYAN}; stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round; }}
.alert {{ border-radius:12px; padding:1rem 1.2rem; font-size:.95rem; line-height:1.5; border:1px solid var(--line); background:var(--card); }}
.alert.warn {{ border-color:#6b5224; background:#2a2418; color:#f1d9a6; }}
.alert.info {{ border-color:#2f4d57; background:#1d2629; color:#bfe3e6; }}
/* ---------- KPI ---------- */
.kpi-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,225px),1fr)); gap:1rem; margin-bottom:1.5rem; }}
.kpi {{ position:relative; overflow:hidden; display:flex; gap:.9rem; align-items:flex-start; background:var(--card); border:1px solid var(--line); border-radius:18px;
       padding:1.2rem 1.1rem; box-shadow:0 10px 28px rgba(0,0,0,.34); transition:transform .15s ease, border-color .15s ease; }}
.kpi:before {{ content:""; position:absolute; left:0; right:0; top:0; height:3px; background:linear-gradient(90deg,var(--c),transparent 80%); opacity:.9; }}
.kpi:after {{ content:""; position:absolute; right:-40px; top:-40px; width:140px; height:140px; border-radius:50%; background:radial-gradient(circle,var(--c),transparent 68%); opacity:.10; }}
.kpi:hover {{ transform:translateY(-2px); border-color:#46464a; }}
.kpi-icon {{ flex:0 0 auto; width:46px; height:46px; border-radius:15px; display:grid; place-items:center; background:color-mix(in srgb, var(--c) 16%, {CARD}); color:var(--c); }}
.kpi-icon svg {{ width:25px; height:25px; fill:none; stroke:currentColor; stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round; }}
.kpi-body {{ min-width:0; position:relative; z-index:1; }}
.kpi-label {{ font-size:.9rem; color:var(--muted); margin-bottom:.2rem; }}
.kpi-value {{ font-size:clamp(1.7rem,2.2vw,2.15rem); font-weight:760; letter-spacing:-.02em; line-height:1.15; color:var(--text); font-variant-numeric:tabular-nums; }}
.kpi-sub {{ font-size:.82rem; color:var(--c); margin-top:.5rem; line-height:1.35; }}
/* ---------- cards ---------- */
[class*="st-key-card_"] {{ background:var(--card); border:1px solid var(--line); border-radius:18px; padding:1.4rem 1.5rem 1.2rem;
                         box-shadow:0 10px 28px rgba(0,0,0,.34); margin-bottom:.5rem; }}
.card-title {{ font-size:1.2rem; font-weight:690; letter-spacing:-.01em; color:var(--text); margin:0 0 .25rem; }}
.card-sub {{ font-size:.86rem; color:var(--muted); margin:0 0 .9rem; line-height:1.45; }}
.section {{ margin:1.7rem 0 1rem; }}
.section.first {{ margin-top:.2rem; }}
.section h2 {{ padding:0; font-size:1.38rem; font-weight:730; letter-spacing:-.015em; margin:0; color:var(--text); display:flex; align-items:center; gap:.7rem; }}
.section h2:before {{ content:""; width:4px; height:1.2em; border-radius:3px; background:var(--accent,{CYAN}); }}
.section p {{ margin:.35rem 0 0 1.05rem; color:var(--muted); font-size:.92rem; }}
.note {{ color:var(--muted); font-size:.82rem; line-height:1.5; margin:.7rem 0 .9rem; }}
.foot code, .note code {{ background:#2b2b2d; color:#9fd8dc; padding:.1rem .45rem; border-radius:6px; font-size:.78rem; }}
/* pathway storyboard */
.pgrid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,205px),1fr)); gap:1.25rem; margin-bottom:1.5rem; }}
.pcard {{ position:relative; background:var(--card); border:1px solid var(--line); border-radius:18px; padding:1.25rem 1.3rem 1.15rem; box-shadow:0 10px 28px rgba(0,0,0,.34); }}
.pcard:before {{ content:""; position:absolute; left:1.3rem; right:1.3rem; top:0; height:3px; border-radius:0 0 4px 4px; background:var(--c); }}
.ptop {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:.5rem; }}
.pname {{ display:flex; align-items:center; gap:.55rem; font-weight:700; font-size:1.02rem; }}
.pname i {{ width:11px; height:11px; border-radius:4px; background:var(--c); display:inline-block; }}
.pshare {{ font-size:.8rem; font-weight:700; color:var(--c); background:color-mix(in srgb, var(--c) 14%, {CARD}); padding:.2rem .6rem; border-radius:999px; }}
.pn {{ font-size:2rem; font-weight:760; letter-spacing:-.02em; font-variant-numeric:tabular-nums; line-height:1.1; }}
.pn small {{ font-size:.85rem; font-weight:500; color:var(--muted); margin-left:.35rem; }}
.track {{ height:7px; background:#1b1b1c; border-radius:999px; overflow:hidden; margin:.45rem 0 .9rem; }}
.track span {{ display:block; height:100%; border-radius:999px; background:var(--c); }}
.prow {{ display:flex; justify-content:space-between; font-size:.82rem; color:#cfcfd4; margin-top:.55rem; }}
.prow b {{ color:var(--text); font-variant-numeric:tabular-nums; }}
.track.thin {{ height:5px; margin:.25rem 0 0; }}
.find {{ display:flex; gap:.9rem; align-items:flex-start; padding:.85rem 0; border-bottom:1px solid #2d2d2f; }}
.find:last-child {{ border-bottom:none; }}
.find i {{ flex:0 0 auto; width:10px; height:10px; border-radius:50%; margin-top:.45rem; background:var(--c); box-shadow:0 0 10px var(--c); }}
.find .l {{ font-size:.74rem; letter-spacing:.07em; text-transform:uppercase; color:var(--muted); font-weight:650; }}
.find .t {{ font-size:.97rem; color:#ececef; line-height:1.45; margin-top:.15rem; }}
.about {{ display:flex; gap:1rem; align-items:flex-start; color:#d6d6db; font-size:.95rem; line-height:1.6; }}
.about svg {{ flex:0 0 auto; width:26px; height:26px; margin-top:2px; fill:none; stroke:{PURPLE}; stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round; }}
/* ---------- tables ---------- */
.tbl {{ width:100%; overflow-x:auto; }}
.tbl table {{ width:100%; border-collapse:collapse; table-layout:auto; }}
.tbl th {{ text-align:left; font-size:.72rem; letter-spacing:.06em; text-transform:uppercase; color:var(--muted); font-weight:650; padding:.55rem .65rem; border-bottom:1px solid var(--line); vertical-align:bottom; }}
.tbl th.num {{ text-align:right; }}
.tbl td {{ padding:.65rem .65rem; border-bottom:1px solid #2d2d2f; font-size:.9rem; color:#e6e6e9; overflow-wrap:anywhere; vertical-align:top; }}
.tbl td.num {{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }}
.tbl td.path {{ white-space:nowrap; }}
.tbl tr:last-child td {{ border-bottom:none; }}
.tbl tbody tr:hover td {{ background:#2b2b2d; }}
.tbl .dot {{ display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:.55rem; }}
/* ---------- reliability widgets ---------- */
.stack {{ display:flex; height:16px; border-radius:999px; overflow:hidden; background:#1c1c1d; margin:.6rem 0 .7rem; }}
.stack span {{ display:block; height:100%; }}
.legend-row {{ display:flex; gap:1.4rem; flex-wrap:wrap; font-size:.86rem; color:#d6d6da; }}
.legend-row i {{ display:inline-block; width:10px; height:10px; border-radius:3px; margin-right:.45rem; }}
.big {{ font-size:1.9rem; font-weight:740; letter-spacing:-.02em; font-variant-numeric:tabular-nums; }}
.gauge {{ position:relative; height:14px; background:#1c1c1d; border-radius:999px; margin:.7rem 0 .35rem; }}
.gauge .fill {{ position:absolute; left:0; top:0; bottom:0; border-radius:999px; background:linear-gradient(90deg,{PURPLE},{CYAN}); }}
.gauge .band {{ position:absolute; top:-3px; bottom:-3px; border-radius:6px; background:rgba(255,255,255,.28); border:1px solid rgba(255,255,255,.55); }}
.scale {{ display:flex; justify-content:space-between; font-size:.75rem; color:var(--muted); }}
.stack-3 {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:1rem; margin-top:.5rem; }}
.stack-3 .mini {{ background:#1e1e1f; border:1px solid #2c2c2e; border-radius:12px; padding:.8rem .95rem; }}
.mini .l {{ font-size:.78rem; color:var(--muted); }}
.mini .v {{ font-size:1.35rem; font-weight:720; font-variant-numeric:tabular-nums; margin-top:.15rem; }}
.facts {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:1rem; margin-bottom:.4rem; }}
.facts .mini {{ background:#1e1e1f; border:1px solid #2c2c2e; border-radius:12px; padding:.8rem .95rem; }}
.facts .mini .v {{ font-size:1.02rem; font-weight:680; line-height:1.35; }}
.hash {{ font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; font-size:.84rem; color:{GREEN}; background:#1d261b; border:1px solid #33502d; border-radius:10px; padding:.7rem .9rem; overflow-wrap:anywhere; }}
.bul {{ margin:.2rem 0 0; padding:0; list-style:none; }}
.bul li {{ position:relative; padding:.55rem 0 .55rem 1.4rem; border-bottom:1px solid #2d2d2f; color:#d9d9de; font-size:.93rem; line-height:1.5; }}
.bul li:last-child {{ border-bottom:none; }}
.bul li:before {{ content:""; position:absolute; left:.1rem; top:1.05rem; width:7px; height:7px; border-radius:50%; background:{CYAN}; }}
.stDownloadButton button, .stButton button {{ background:#2b2b2d !important; color:#e8e8ec !important; border:1px solid #3d3d40 !important; border-radius:10px !important; font-size:.82rem !important; padding:.35rem .85rem !important; }}
.stDownloadButton button:hover {{ border-color:{CYAN} !important; color:{CYAN} !important; }}
[data-testid="stExpander"] {{ margin-top:.6rem; background:var(--card); border:1px solid var(--line) !important; border-radius:14px; }}
.foot {{ color:var(--muted); font-size:.8rem; text-align:center; margin-top:2.2rem; }}
@media (max-width:960px) {{ .stack-3 {{ grid-template-columns:1fr; }} .hero {{ padding-bottom:1rem; }}
  [data-testid="stHorizontalBlock"] {{ flex-wrap:wrap; }} [data-testid="stColumn"] {{ min-width:100% !important; flex:1 1 100% !important; }} }}
@media (max-width:640px) {{ .block-container {{ padding-top:3.2rem; }} .chip {{ white-space:normal; }} }}
</style>
"""


def inline_html(markup: str) -> str:
    """Collapse to one line: Streamlit's markdown parser ends an HTML block at a blank line."""
    return " ".join(line.strip() for line in markup.splitlines() if line.strip())


def put(st: Any, markup: str) -> None:
    st.markdown(inline_html(markup), unsafe_allow_html=True)


def section(st: Any, title: str, sub: str = "", accent: str = CYAN, first: bool = False) -> None:
    put(st, f'<div class="section{" first" if first else ""}" style="--accent:{accent}"><h2>{esc(title)}</h2>' + (f"<p>{esc(sub)}</p>" if sub else "") + "</div>")


def card_head(st: Any, title: str, sub: str = "") -> None:
    put(st, f'<div class="card-title">{esc(title)}</div>' + (f'<div class="card-sub">{esc(sub)}</div>' if sub else ""))


def note(st: Any, text: str) -> None:
    if text:
        put(st, f'<div class="note">{esc(text)}</div>')


def alert(st: Any, kind: str, text: str) -> None:
    put(st, f'<div class="alert {kind}">{esc(text)}</div>')


def download(st: Any, frame: pd.DataFrame, filename: str, label: str = "Download CSV") -> None:
    st.download_button(label, frame.to_csv(index=False).encode("utf-8"), filename, "text/csv", key=f"dl_{filename}")


# ---------------------------------------------------------------------------------------------
# Charts (Altair ships with Streamlit; nothing extra to install)
# ---------------------------------------------------------------------------------------------
def style_chart(chart: Any, height: int = 300) -> Any:
    return (chart.properties(height=height, background="transparent")
            .configure_view(stroke=None)
            .configure_axis(labelColor=MUTED, titleColor=MUTED, gridColor="#343436", gridOpacity=1, domainColor="#4a4a4e",
                            tickColor="#4a4a4e", labelFontSize=12, titleFontSize=12, labelFont=FONT, titleFont=FONT, titlePadding=10)
            .configure_legend(labelColor="#dcdce0", titleColor=MUTED, labelFontSize=12.5, labelFont=FONT, symbolType="square",
                              symbolSize=150, orient="top", padding=6, labelLimit=260)
            .configure_title(color=TEXT, font=FONT))


def draw(st: Any, chart: Any, height: int = 300) -> None:
    st.altair_chart(style_chart(chart, height), theme=None, width="stretch")


def grouped_bars(st: Any, long: pd.DataFrame, x: str, series_colours: dict[str, str], height: int = 300, x_title: str | None = None,
                 value_title: str = "Percent (%)", percent: bool = True) -> None:
    import altair as alt
    if long.empty:
        alert(st, "info", "This chart is not available: the saved output does not contain the needed columns.")
        return
    data = long.copy()
    data["Label"] = data["Percent"].map(lambda v: f"{v:.0f}%" if percent else f"{v:,.0f}")
    legend = alt.Legend(orient="top", columns=len(series_colours) if sum(len(k) for k in series_colours) <= 62 else 2, labelLimit=320, columnPadding=14)
    xenc = alt.X(f"{x}:N", title=x_title, axis=alt.Axis(labelAngle=0, labelPadding=8, grid=False, ticks=False))
    yenc = alt.Y("Percent:Q", title=value_title, scale=alt.Scale(domain=[0, 100], nice=False) if percent else alt.Scale(zero=True),
                 axis=alt.Axis(tickCount=5, format=".0f" if percent else ",.0f"))
    colour = alt.Color("Series:N", title=None, scale=alt.Scale(domain=list(series_colours), range=list(series_colours.values())), legend=legend)
    bars = alt.Chart(data).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
        x=xenc, xOffset=alt.XOffset("Series:N"), y=yenc, color=colour,
        tooltip=[alt.Tooltip(f"{x}:N"), alt.Tooltip("Series:N", title="Measure"), alt.Tooltip("Percent:Q", title=value_title, format=".1f" if percent else ",.0f")])
    labels = alt.Chart(data).mark_text(dy=-7, fontSize=10.5, color="#dcdce0", font=FONT).encode(
        x=alt.X(f"{x}:N"), xOffset=alt.XOffset("Series:N"), y=alt.Y("Percent:Q"), text="Label:N")
    draw(st, bars + labels, height)


def donut(st: Any, prevalence: pd.DataFrame, colours: dict[str, str], total_label: str) -> None:
    import altair as alt
    if "n" not in prevalence.columns:
        alert(st, "info", "Pathway sizes are not available in the saved output.")
        return
    frame = pd.DataFrame({"Pathway": [pathway_label(x) for x in prevalence["cluster_id"]],
                          "People": pd.to_numeric(prevalence["n"], errors="coerce")}).dropna()
    frame["Share"] = frame["People"] / frame["People"].sum() * 100
    scale = alt.Scale(domain=list(colours), range=list(colours.values()))
    arc = alt.Chart(frame).mark_arc(innerRadius=82, outerRadius=128, stroke=CARD, strokeWidth=3, cornerRadius=3).encode(
        theta=alt.Theta("People:Q", stack=True), color=alt.Color("Pathway:N", scale=scale, title=None, legend=alt.Legend(orient="right")),
        order=alt.Order("Pathway:N"),
        tooltip=[alt.Tooltip("Pathway:N"), alt.Tooltip("People:Q", format=",.0f"), alt.Tooltip("Share:Q", title="Share (%)", format=".1f")])
    centre = alt.Chart(pd.DataFrame({"t": [f"{int(frame['People'].sum()):,}"]})).mark_text(size=30, fontWeight=700, color=TEXT, dy=-8, font=FONT).encode(text="t:N")
    caption = alt.Chart(pd.DataFrame({"t": [total_label]})).mark_text(size=12, color=MUTED, dy=16, font=FONT).encode(text="t:N")
    draw(st, arc + centre + caption, 340)


def slope_chart(st: Any, prevalence: pd.DataFrame, colours: dict[str, str]) -> None:
    """Employment share of each pathway at the three measurement points; the last leg is dashed (a narrower measure)."""
    import altair as alt
    long = melt_percent(prevalence.assign(Pathway=prevalence["cluster_id"].map(pathway_label)), "Pathway", STAGE_COLS).rename(columns={"Series": "Stage"})
    if long.empty:
        alert(st, "info", "Employment shares by pathway are not available in the saved output.")
        return
    short = {STAGES[0]: "Pre-course", STAGES[1]: "Post-course", STAGES[2]: "Aug 2013 (formal)"}
    long["Stage"] = long["Stage"].map(lambda x: short.get(x, x))
    stages = [short[s] for s in STAGES if short[s] in set(long["Stage"])]
    scale = alt.Scale(domain=list(colours), range=list(colours.values()))
    xenc = alt.X("Stage:O", sort=stages, title=None, scale=alt.Scale(domain=stages, paddingOuter=0.35), axis=alt.Axis(labelAngle=0, labelPadding=10, grid=False, labelFontSize=12.5))
    yenc = alt.Y("Percent:Q", title="Share in work (%)", scale=alt.Scale(domain=[0, 100], nice=False), axis=alt.Axis(tickCount=5, format=".0f"))
    first = long[long["Stage"].isin(stages[:2])]
    last = long[long["Stage"].isin(stages[1:])] if len(stages) > 2 else long.iloc[0:0]
    layers = [alt.Chart(first).mark_line(strokeWidth=3, interpolate="monotone").encode(
        x=xenc, y=yenc, color=alt.Color("Pathway:N", scale=scale, legend=None), detail="Pathway:N")]
    if not last.empty:
        layers.append(alt.Chart(last).mark_line(strokeWidth=3, strokeDash=[7, 6], opacity=.85).encode(
            x=xenc, y=yenc, color=alt.Color("Pathway:N", scale=scale, legend=None), detail="Pathway:N"))
    layers.append(alt.Chart(long).mark_point(filled=True, size=130, opacity=1, stroke=CARD, strokeWidth=2).encode(
        x=xenc, y=yenc, color=alt.Color("Pathway:N", scale=scale, title=None, legend=alt.Legend(orient="top", columns=len(colours))),
        tooltip=[alt.Tooltip("Pathway:N"), alt.Tooltip("Stage:O", title="Measure"), alt.Tooltip("Percent:Q", title="Share in work (%)", format=".1f")]))
    draw(st, alt.layer(*layers), 330)


def milestone_heatmap(st: Any, admin: pd.DataFrame) -> None:
    import altair as alt
    names = {"formal_entry_by_jan2012_share": "Formal job by Jan 2012", "ever_formally_employed_postcourse_share": "Ever formal job after course",
             "first_job_left_by_nov2013_share": "First job left by Nov 2013", "formal_anytime_first8months2013_share": "Formal job Jan–Aug 2013 (cumulative)"}
    long = melt_percent(admin.assign(Pathway=admin["cluster_id"].map(pathway_label)), "Pathway", names).rename(columns={"Series": "Milestone"})
    if long.empty:
        alert(st, "info", "Administrative milestones are not available in the saved output.")
        return
    long["Label"] = long["Percent"].map(lambda v: f"{v:.1f}%")
    base = alt.Chart(long).encode(
        x=alt.X("Pathway:N", title=None, axis=alt.Axis(orient="top", labelAngle=0, labelPadding=8, ticks=False, domain=False, labelFontSize=12.5)),
        y=alt.Y("Milestone:N", title=None, sort=list(names.values()), axis=alt.Axis(labelLimit=260, ticks=False, domain=False, labelFontSize=12.5, labelColor="#dcdce0")))
    rect = base.mark_rect(cornerRadius=8, stroke=CARD, strokeWidth=4).encode(
        color=alt.Color("Percent:Q", scale=alt.Scale(domain=[0, 100], range=["#2a3335", CYAN]), legend=None),
        tooltip=[alt.Tooltip("Pathway:N"), alt.Tooltip("Milestone:N"), alt.Tooltip("Percent:Q", title="Share (%)", format=".1f")])
    text = base.mark_text(fontSize=13, fontWeight=600, font=FONT).encode(
        text="Label:N", color=alt.condition(alt.datum.Percent > 55, alt.value("#10191a"), alt.value("#f0f0f2")))
    draw(st, rect + text, 280)


def silhouette_chart(st: Any, methods: pd.DataFrame, selected_k: Any) -> None:
    import altair as alt
    if not {"k", "silhouette_hamming"} <= set(methods.columns):
        alert(st, "info", "Candidate silhouettes are not available in the saved output.")
        return
    frame = methods[["k", "silhouette_hamming"]].copy()
    frame["k"] = pd.to_numeric(frame["k"], errors="coerce")
    frame["Silhouette"] = pd.to_numeric(frame["silhouette_hamming"], errors="coerce")
    frame = frame.dropna(subset=["k", "Silhouette"])
    sel = pd.to_numeric(selected_k, errors="coerce")
    frame["Status"] = frame["k"].map(lambda k: "Selected" if pd.notna(sel) and k == float(sel) else "Candidate")
    line = alt.Chart(frame).mark_line(color=CYAN, strokeWidth=2.5, interpolate="monotone").encode(
        x=alt.X("k:O", title="Number of pathways (k)", axis=alt.Axis(labelAngle=0, grid=False)),
        y=alt.Y("Silhouette:Q", title="Hamming silhouette", scale=alt.Scale(zero=False)))
    points = alt.Chart(frame).mark_point(filled=True, opacity=1, stroke=CARD, strokeWidth=2).encode(
        x="k:O", y="Silhouette:Q",
        size=alt.Size("Status:N", scale=alt.Scale(domain=["Candidate", "Selected"], range=[110, 320]), legend=None),
        color=alt.Color("Status:N", title=None, scale=alt.Scale(domain=["Candidate", "Selected"], range=[CYAN, PINK])),
        tooltip=[alt.Tooltip("k:O"), alt.Tooltip("Silhouette:Q", format=".4f"), alt.Tooltip("Status:N")])
    draw(st, line + points, 280)


def smallest_share_chart(st: Any, methods: pd.DataFrame) -> None:
    import altair as alt
    if not {"k", "min_cluster_share"} <= set(methods.columns):
        return
    frame = methods[["k", "min_cluster_share"]].copy()
    frame["k"] = pd.to_numeric(frame["k"], errors="coerce")
    frame["Smallest pathway (%)"] = pd.to_numeric(frame["min_cluster_share"], errors="coerce") * 100
    frame = frame.dropna(subset=["k", "Smallest pathway (%)"])
    if frame.empty:
        return
    bars = alt.Chart(frame).mark_bar(color=PURPLE, cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
        x=alt.X("k:O", title="Number of pathways (k)", axis=alt.Axis(labelAngle=0, grid=False)),
        y=alt.Y("Smallest pathway (%):Q", scale=alt.Scale(domain=[0, max(10.0, float(frame["Smallest pathway (%)"].max()) * 1.15)]), axis=alt.Axis(title="Smallest pathway (%)", format=".0f")),
        tooltip=[alt.Tooltip("k:O"), alt.Tooltip("Smallest pathway (%):Q", format=".1f")])
    rule = alt.Chart(pd.DataFrame({"y": [5.0]})).mark_rule(color=AMBER, strokeDash=[6, 4], strokeWidth=2).encode(y="y:Q")
    draw(st, bars + rule, 280)


def stacked_states(st: Any, state: pd.DataFrame) -> None:
    import altair as alt
    needed = {"cluster_id", "admin_jan12_first_job_state", "share_cluster"}
    if not needed <= set(state.columns):
        alert(st, "info", "The January 2012 state profile is not available in the saved output.")
        return
    names = {"first_job_active_jan2012": "First formal job active", "first_job_left_by_jan2012": "First formal job already left",
             "no_formal_job_by_jan2012": "No formal job by Jan 2012"}
    frame = pd.DataFrame({"Pathway": state["cluster_id"].map(pathway_label),
                          "State": state["admin_jan12_first_job_state"].map(lambda s: names.get(s, str(s))),
                          "Percent": pd.to_numeric(state["share_cluster"], errors="coerce") * 100}).dropna()
    colours = {"First formal job active": GREEN, "First formal job already left": AMBER, "No formal job by Jan 2012": SLATE}
    domain = [n for n in colours if n in set(frame["State"])] + [n for n in frame["State"].unique() if n not in colours]
    rng = [colours.get(n, PURPLE) for n in domain]
    chart = alt.Chart(frame).mark_bar().encode(
        x=alt.X("Pathway:N", title=None, axis=alt.Axis(labelAngle=0, grid=False, ticks=False)),
        y=alt.Y("Percent:Q", title="Share of pathway (%)", stack="zero", scale=alt.Scale(domain=[0, 100], nice=False), axis=alt.Axis(tickCount=5, format=".0f")),
        color=alt.Color("State:N", title=None, scale=alt.Scale(domain=domain, range=rng), legend=alt.Legend(orient="top", columns=2, labelLimit=320)),
        order=alt.Order("State:N"),
        tooltip=[alt.Tooltip("Pathway:N"), alt.Tooltip("State:N"), alt.Tooltip("Percent:Q", format=".1f", title="Share (%)")])
    draw(st, chart, 300)


def income_chart(st: Any, income: pd.DataFrame, colours: dict[str, str]) -> None:
    import altair as alt
    if income.empty:
        alert(st, "info", "No saved income values are available.")
        return
    chart = alt.Chart(income).mark_bar(cornerRadiusTopLeft=5, cornerRadiusTopRight=5).encode(
        x=alt.X("Pathway:N", title=None, axis=alt.Axis(labelAngle=0, grid=False, ticks=False)),
        y=alt.Y("Median:Q", title="Median formal income", scale=alt.Scale(zero=True), axis=alt.Axis(format=",.0f", tickCount=5)),
        color=alt.Color("Pathway:N", legend=None, scale=alt.Scale(domain=list(colours), range=list(colours.values()))),
        tooltip=[alt.Tooltip("Pathway:N"), alt.Tooltip("Median:Q", title="Median formal income", format=",.2f")])
    draw(st, chart, 260)


# ---------------------------------------------------------------------------------------------
# Shell: sidebar and header
# ---------------------------------------------------------------------------------------------
def render_sidebar(st: Any, result: dict[str, Any]) -> str:
    """Left navigation. Returns the selected section; the choice lives in session state and the URL."""
    wanted = st.query_params.get("section")
    last_synced = st.session_state.get("_last_synced_nav")
    if wanted in SECTIONS and wanted != last_synced and wanted != st.session_state.get("nav"):
        st.session_state["nav"] = wanted
    elif "nav" not in st.session_state:
        st.session_state["nav"] = wanted if wanted in SECTIONS else SECTIONS[0]
    with st.sidebar:
        put(st, '<div class="brand"><div class="mark"><svg viewBox="0 0 24 24"><path d="M5 20V11M12 20V4M19 20v-6"/></svg></div>'
                '<div><div class="t">Pathway Analytics</div><div class="s">Turkey ISKUR (2010–2013)</div></div></div>')
        choice = st.radio("Sections", SECTIONS, key="nav", label_visibility="collapsed")
        if result["status"] == "ok":
            p = result["payload"]
            put(st, '<div class="dscard">'
                    '<div class="r"><div class="l">Dataset</div><div class="v">Turkey ISKUR Vocational Training Evaluation (2010–2013)</div></div>'
                    f'<div class="r"><div class="l">Analytical sample</div><div class="v">{fmt(p.get("n_valid_post_training_trajectories"), "d")} attendees</div></div>'
                    f'<div class="r"><div class="l">Clustering solution</div><div class="v">k = {fmt(p.get("selected_k"), "d")} pathways</div></div>'
                    '<div class="r"><div class="l">Source file</div><div class="v ok">SHA-256 verified</div></div></div>')
        else:
            put(st, '<div class="dscard"><div class="r"><div class="l">Source file</div><div class="v">Results not shown</div></div></div>')
        put(st, '<div class="sidefoot">INT396 | G24 &nbsp;·&nbsp; CA Project</div>')
    st.session_state["_last_synced_nav"] = choice
    if st.query_params.get("section") != choice:
        st.query_params["section"] = choice
    return choice


def render_header(st: Any, verified_hash: str | None) -> None:
    chips = '<span class="chip">INT396 | G24 | CA Project</span>'
    if verified_hash:
        chips += f'<span class="chip ok"><span class="dot"></span>Validated results · SHA-256 {esc(verified_hash[:12])}…</span>'
    put(st, '<div class="hero"><div><h1>Employment Outcome Pathway Analytics</h1>'
            '<p class="sub">Historical Turkey ISKUR Vocational Training Evaluation (2010–2013)</p></div>'
            f'<div class="chips">{chips}</div></div>')


def render_scope_banner(st: Any, payload: dict[str, Any]) -> None:
    n = payload.get("n_rows")
    applicants = f" ({fmt(n, 'd')} original applicants)" if n is not None else ""
    put(st, f'<div class="scope"><svg viewBox="0 0 24 24">{ICONS["shield"]}</svg><div><b>Scope.</b> Historical Turkey, 2010–2013: applicants to ISKUR vocational '
            f'training courses{esc(applicants)}. Nothing here describes another country, period or programme. The analysis is descriptive and does not '
            'estimate a causal training effect. Pathway numbers are labels only; no pathway has been given a descriptive name.</div></div>')


def render_kpis(st: Any, payload: dict[str, Any], prevalence: pd.DataFrame) -> None:
    cards = "".join(
        f'<div class="kpi" style="--c:{k["colour"]}"><div class="kpi-icon"><svg viewBox="0 0 24 24">{ICONS[k["icon"]]}</svg></div>'
        f'<div class="kpi-body"><div class="kpi-label">{esc(k["label"])}</div><div class="kpi-value">{esc(k["value"])}</div>'
        f'<div class="kpi-sub">{esc(k["sub"])}</div></div></div>' for k in kpi_items(payload, prevalence))
    put(st, f'<div class="kpi-grid">{cards}</div>')


def storyboard(prevalence: pd.DataFrame, colours: dict[str, str]) -> str:
    """One card per pathway: size, share and the three employment shares, drawn from the saved table."""
    cards = []
    n_total = pd.to_numeric(prevalence["n"], errors="coerce").sum() if "n" in prevalence else None
    for _, r in prevalence.iterrows():
        label = pathway_label(r["cluster_id"])
        colour = colours.get(label, CYAN)
        n = pd.to_numeric(r.get("n"), errors="coerce")
        share = pd.to_numeric(r.get("share_complete_pathways"), errors="coerce")
        if pd.isna(share) and n_total and pd.notna(n):
            share = n / n_total
        rows = "".join(
            f'<div class="prow"><span>{esc(lab)}</span><b>{pct(r.get(col))}</b></div>'
            f'<div class="track thin"><span style="width:{min(max(float(pd.to_numeric(r.get(col), errors="coerce") or 0), 0), 1) * 100:.1f}%"></span></div>'
            for col, lab in STAGE_COLS.items() if col in prevalence.columns and pd.notna(pd.to_numeric(r.get(col), errors="coerce")))
        cards.append(
            f'<div class="pcard" style="--c:{colour}"><div class="ptop"><span class="pname"><i></i>{esc(label)}</span>'
            f'<span class="pshare">{pct(share)}</span></div><div class="pn">{fmt(None if pd.isna(n) else int(n), "d")}<small>people</small></div>'
            f'<div class="track"><span style="width:{0 if pd.isna(share) else min(float(share), 1) * 100:.1f}%"></span></div>{rows}</div>')
    return f'<div class="pgrid">{"".join(cards)}</div>'


# ---------------------------------------------------------------------------------------------
# Sections (one per sidebar entry)
# ---------------------------------------------------------------------------------------------
def sec_overview(st: Any, ctx: dict[str, Any]) -> None:
    payload, prevalence, colours = ctx["payload"], ctx["prevalence"], ctx["colours"]
    render_kpis(st, payload, prevalence)
    left, right = st.columns([1, 1.25], gap="large")
    with left:
        with st.container(key="card_ov_donut"):
            card_head(st, "Employment pathway distribution", "People per pathway among complete attendee sequences")
            donut(st, prevalence, colours, "attendees")
    with right:
        with st.container(key="card_ov_slope"):
            card_head(st, "Employment across the three measurement points", "Share of each pathway in work: pre-course, post-course, August 2013")
            slope_chart(st, prevalence, colours)
            note(st, "The dashed leg changes the measure: August 2013 counts formal Social Security employment only. Not working is not the same as unemployed.")
    a, b = st.columns([1.25, 1], gap="large")
    with a:
        with st.container(key="card_ov_find"):
            card_head(st, "What stands out", "Read directly from the saved pathway table")
            items = key_findings(prevalence)
            if items:
                put(st, "".join(f'<div class="find" style="--c:{i["colour"]}"><i></i><div><div class="l">{esc(i["label"])}</div><div class="t">{esc(i["text"])}</div></div></div>' for i in items))
            else:
                alert(st, "info", "No pathway measures are available to summarise.")
            note(st, "These describe the saved numbers; they are not tests of difference.")
    with b:
        with st.container(key="card_ov_about"):
            card_head(st, "About the study")
            n = payload.get("n_valid_post_training_trajectories")
            put(st, f'<div class="about"><svg viewBox="0 0 24 24">{ICONS["info"]}</svg><div>A clustering analysis of {fmt(n, "d")} ISKUR vocational-training attendees in Turkey, '
                    'using employment status at three points in time (pre-course, post-course and August 2013), alongside administrative employment records '
                    'and a pre-course baseline. See Scope &amp; Provenance for what the analysis can and cannot say.</div></div>'
                    '<div class="facts" style="margin-top:1.2rem;grid-template-columns:repeat(2,minmax(0,1fr))">'
                    f'<div class="mini"><div class="l">Original applicants</div><div class="v">{fmt(payload.get("n_rows"), "d")}</div></div>'
                    f'<div class="mini"><div class="l">Complete sequences</div><div class="v">{fmt(n, "d")}</div></div>'
                    f'<div class="mini"><div class="l">Pre-course baseline cohort</div><div class="v">{fmt((payload.get("baseline_comparison") or {}).get("valid_pretraining_baseline_n"), "d")}</div></div>'
                    f'<div class="mini"><div class="l">Pathways selected (k)</div><div class="v">{fmt(payload.get("selected_k"), "d")}</div></div></div>')


def sec_pathways(st: Any, ctx: dict[str, Any]) -> None:
    prevalence, tables, colours = ctx["prevalence"], ctx["tables"], ctx["colours"]
    section(st, "The pathways at a glance", "Each card is one employment pathway found among complete attendee sequences.", CYAN, first=True)
    put(st, storyboard(prevalence, colours))
    with st.container(key="card_pw_profile"):
        card_head(st, "Pathway profile", "Size, cohort share and the observed three-point work sequences")
        cols = [c for c in ("cluster_id", "n", "share_complete_pathways", "trajectory_patterns") if c in prevalence.columns]
        view = tidy_table(prevalence[cols], {"n": "People", "share_complete_pathways": "Cohort share", "trajectory_patterns": "Observed sequence patterns"})
        put(st, html_table(view, colours))
        note(st, "Sequence points: pre-course any work → post-course any work → August 2013 formal Social Security employment.")
        download(st, prevalence, "turkey_pathway_prevalence_complete.csv", "Download complete pathway table")
    gender = tables.get("gender")
    with st.container(key="card_pw_gender"):
        card_head(st, "Participant profile: gender by pathway", "Descriptive only; gender is never used to form pathways")
        if gender is None or gender.empty:
            alert(st, "info", "No saved gender profile is available.")
        else:
            put(st, html_table(format_gender_table(gender, colours), colours))
            download(st, gender, "turkey_cluster_gender_profile.csv")


def sec_baseline(st: Any, ctx: dict[str, Any]) -> None:
    payload, tables = ctx["payload"], ctx["tables"]
    section(st, "Is a pathway more than “worked before or not”?", "The mandatory baseline splits people only by whether they worked before the course.", GREEN, first=True)
    base = tables.get("baseline")
    names = {"0": "Not working", "1": "Worked at all"}

    def status(v: Any) -> str:
        try:
            return names.get(str(int(float(v))), str(v))
        except (TypeError, ValueError):
            return str(v)
    left, right = st.columns(2, gap="large")
    with left:
        with st.container(key="card_bl_chart"):
            card_head(st, "Outcomes by pre-course work status", "Post-course any work and August 2013 formal work")
            if base is None or "employment_baseline" not in base.columns:
                alert(st, "info", "No saved baseline comparison is available.")
            else:
                long = melt_percent(base.assign(Status=base["employment_baseline"].map(status)), "Status",
                                    {"postfollowup_any_work_share": "Post-course any work", "aug2013_formal_work_share": "Aug 2013 formal work"})
                grouped_bars(st, long, "Status", {"Post-course any work": PINK, "Aug 2013 formal work": AMBER})
    with right:
        with st.container(key="card_bl_table"):
            card_head(st, "Baseline comparison table", "Interviews dated before the course start")
            if base is not None and "employment_baseline" in base.columns:
                cols = [c for c in ("employment_baseline", "n", "postfollowup_any_work_share", "aug2013_formal_work_share") if c in base.columns]
                view = tidy_table(base[cols], {"employment_baseline": "Baseline status", "n": "People", "postfollowup_any_work_share": "Post-course any work",
                                               "aug2013_formal_work_share": "Aug 2013 formal work"}, percent=("postfollowup_any_work_share", "aug2013_formal_work_share"))
                view["Baseline status"] = base["employment_baseline"].map(status)
                put(st, html_table(view))
                download(st, base, "turkey_baseline_comparison_complete.csv")
            valid = (payload.get("baseline_comparison") or {}).get("valid_pretraining_baseline_n")
            note(st, f"Comparison cohort: {fmt(valid, 'd')} interviews dated before course start. “Not working” includes people outside the labour force; it does not mean unemployed.")
    by_cluster = tables.get("baseline_by_cluster")
    if by_cluster is not None and not by_cluster.empty:
        with st.container(key="card_bl_by_pathway"):
            card_head(st, "Pre-course work by pathway", "How each pathway is made up in terms of the baseline split")
            put(st, html_table(format_baseline_cluster_table(by_cluster), colours=None))
            download(st, by_cluster, "turkey_baseline_employment_by_cluster.csv")


def sec_training(st: Any, ctx: dict[str, Any]) -> None:
    prevalence, colours = ctx["prevalence"], ctx["colours"]
    section(st, "Training participation", "Assignment, self-reported selection, documented attendance, completion and certificates are different things.", AMBER, first=True)
    labelled = prevalence.assign(Pathway=prevalence["cluster_id"].map(pathway_label))
    left, right = st.columns([1.15, 1], gap="large")
    with left:
        with st.container(key="card_tr_rates"):
            card_head(st, "Selection, completion and certification rates", "Each rate uses its own known or observed denominator")
            long = melt_percent(labelled, "Pathway", {"selection_reported_share": "Self-reported selection", "completion_share_observed": "Completed among known",
                                                      "certificate_share_observed": "Certificate among known"})
            grouped_bars(st, long, "Pathway", {"Self-reported selection": PURPLE, "Completed among known": GREEN, "Certificate among known": CYAN})
            note(st, "Unknown outcomes are not counted as “no”.")
    with right:
        with st.container(key="card_tr_counts"):
            card_head(st, "Counts behind the rates", "People per pathway, as saved: assigned to treatment, documented attendance, known completion, known certificate")
            cols = [c for c in ("cluster_id", "treatment_assigned_n", "attendance_evidence_n", "completion_n", "certificate_received_n") if c in prevalence.columns]
            view = tidy_table(prevalence[cols], {"treatment_assigned_n": "Assigned", "attendance_evidence_n": "Attended",
                                                 "completion_n": "Completed", "certificate_received_n": "Certified"})
            put(st, html_table(view, colours))
            download(st, prevalence, "turkey_course_outcomes_by_pathway.csv", "Download all pathway columns")


def sec_admin(st: Any, ctx: dict[str, Any]) -> None:
    tables, colours = ctx["tables"], ctx["colours"]
    admin, state = tables.get("admin"), tables.get("state")
    section(st, "Administrative employment after the course", "Formal (Social Security) employment records, by pathway.", PURPLE, first=True)
    a, b = st.columns([1.15, 1], gap="large")
    with a:
        with st.container(key="card_ad_heat"):
            card_head(st, "Employment milestones by pathway", "Share of each pathway reaching each milestone; darker cells are higher")
            if admin is None or "cluster_id" not in admin.columns:
                alert(st, "info", "No saved administrative profile is available.")
            else:
                milestone_heatmap(st, admin)
                note(st, "The January–August 2013 indicator is cumulative; it is not an August point-in-time measure. No monthly job spells are present in this public-use file.")
    with b:
        with st.container(key="card_ad_state"):
            card_head(st, "January 2012 first formal-job state", "Where each pathway stood in January 2012")
            if state is None:
                alert(st, "info", "No saved January 2012 state profile is available.")
            else:
                stacked_states(st, state)
    if admin is not None and "aug2013_formal_income_median" in admin.columns:
        income = admin[["cluster_id", "aug2013_formal_income_median"]].copy()
        income["Median"] = pd.to_numeric(income["aug2013_formal_income_median"], errors="coerce")
        income["Pathway"] = income["cluster_id"].map(pathway_label)
        c1, c2 = st.columns(2, gap="large")
        with c1:
            with st.container(key="card_ad_income"):
                card_head(st, "Median formal income, August 2013", "In the source currency; one bar per pathway")
                income_chart(st, income.dropna(subset=["Median"]), colours)
        with c2:
            with st.container(key="card_ad_income_table"):
                card_head(st, "Median formal income table", "Values as saved")
                view = pd.DataFrame({"Pathway": income["Pathway"], "Median formal income (source currency)": income["Median"].map(lambda x: "n/a" if pd.isna(x) else f"{x:,.2f}")})
                put(st, html_table(view, colours))
                download(st, admin, "turkey_cluster_admin_profile.csv", "Download administrative profile")


def range_bar(lower: Any, upper: Any) -> str:
    lo, hi = pd.to_numeric(lower, errors="coerce"), pd.to_numeric(upper, errors="coerce")
    if pd.isna(lo) or pd.isna(hi):
        return ""
    return (f'<div class="gauge"><div class="band" style="left:{float(lo) * 100:.2f}%;width:{max(float(hi) - float(lo), 0.004) * 100:.2f}%;'
            f'background:linear-gradient(90deg,{AMBER},{PINK});border-color:transparent"></div></div>'
            '<div class="scale"><span>0%</span><span>50%</span><span>100%</span></div>')


def sec_reliability(st: Any, ctx: dict[str, Any]) -> None:
    payload, tables = ctx["payload"], ctx["tables"]
    section(st, "How far can the pathways be trusted?", "Who was followed up, how reproducible the grouping is, and why this number of pathways was chosen.", PINK, first=True)
    left, right = st.columns(2, gap="large")
    cohort = payload.get("attendee_baseline_cohort_n")
    verified = payload.get("attendee_with_verified_followup_n")
    unknown = payload.get("attendee_followup_unknown_n")
    with left:
        with st.container(key="card_rl_attrition"):
            card_head(st, "Follow-up attrition", "Documented attendees with a valid pre-course baseline")
            numbers = [pd.to_numeric(x, errors="coerce") for x in (cohort, verified, unknown)]
            if any(pd.isna(x) for x in numbers):
                alert(st, "info", "Follow-up counts are not available in the saved output.")
            else:
                c, v, u = (float(x) for x in numbers)
                vw, uw = (v / c * 100, u / c * 100) if c else (0, 0)
                put(st, f'<div class="stack-3"><div class="mini"><div class="l">Baseline cohort</div><div class="v">{fmt(int(c), "d")}</div></div>'
                        f'<div class="mini"><div class="l">Verified follow-up</div><div class="v" style="color:{GREEN}">{fmt(int(v), "d")}</div></div>'
                        f'<div class="mini"><div class="l">Unknown follow-up</div><div class="v" style="color:{AMBER}">{fmt(int(u), "d")}</div></div></div>'
                        f'<div class="stack"><span style="width:{vw:.2f}%;background:{GREEN}"></span><span style="width:{uw:.2f}%;background:{AMBER}"></span></div>'
                        f'<div class="legend-row"><span><i style="background:{GREEN}"></i>Verified follow-up {pct(v / c if c else None)}</span>'
                        f'<span><i style="background:{AMBER}"></i>Unknown follow-up {pct(u / c if c else None)}</span></div>')
            bounds = payload.get("followup_work_extreme_bounds") or {}
            if bounds:
                lo, hi = bounds.get("lower"), bounds.get("upper")
                put(st, f'<div style="margin-top:1.3rem"><div class="card-title" style="font-size:1rem">Extreme follow-up work-rate bounds</div>'
                        f'<div class="big">{pct(lo)} – {pct(hi)}</div>{range_bar(lo, hi)}</div>')
                note(st, "Bounds assume every unknown follow-up is either not working or working; no outcomes are imputed.")
    with right:
        with st.container(key="card_rl_stability"):
            card_head(st, "Resampling stability", "Adjusted Rand Index between pathways refitted on subsamples and the selected solution")
            stab = payload.get("cluster_stability") or {}
            ari, sd = pd.to_numeric(stab.get("ari_mean"), errors="coerce"), pd.to_numeric(stab.get("ari_sd"), errors="coerce")
            if pd.isna(ari):
                alert(st, "info", "Stability results are not available in the saved output.")
            else:
                band = ""
                if not pd.isna(sd):
                    low, high = max(float(ari) - float(sd), 0.0), min(float(ari) + float(sd), 1.0)
                    band = f'<div class="band" style="left:{low * 100:.2f}%;width:{(high - low) * 100:.2f}%"></div>'
                sd_text = fmt(None if pd.isna(sd) else float(sd), ".4f")
                put(st, f'<div class="big" style="color:{CYAN}">{fmt(float(ari), ".4f")}<span style="font-size:1rem;color:{MUTED};font-weight:500"> mean ARI</span></div>'
                        f'<div class="gauge"><div class="fill" style="width:{float(ari) * 100:.2f}%"></div>{band}</div>'
                        '<div class="scale"><span>0 (no agreement)</span><span>1 (identical)</span></div>'
                        f'<div class="stack-3"><div class="mini"><div class="l">Mean ARI</div><div class="v" style="color:{CYAN}">{fmt(float(ari), ".4f")}</div></div>'
                        f'<div class="mini"><div class="l">Standard deviation</div><div class="v" style="color:{PURPLE}">{esc(sd_text)}</div></div>'
                        f'<div class="mini"><div class="l">Subsample refits</div><div class="v" style="color:{GREEN}">{fmt(stab.get("replicates"), "d")}</div></div></div>')
                note(st, f"Mean ARI across {fmt(stab.get('replicates'), 'd')} deterministic subsample refits. This is moderate resampling stability, not external validity.")
    methods = tables.get("methods")
    if methods is not None and not methods.empty:
        with st.container(key="card_rl_methods"):
            card_head(st, "Choosing the number of pathways", "Silhouette and smallest-pathway size for each candidate k")
            a, b = st.columns(2, gap="large")
            with a:
                silhouette_chart(st, methods, payload.get("selected_k"))
            with b:
                smallest_share_chart(st, methods)
            note(st, "Dashed line: the predeclared 5% cohort-size floor for the smallest pathway.")
            renamed = tidy_table(methods, {"k": "Clusters (k)", "silhouette_hamming": "Hamming silhouette", "min_cluster_n": "Smallest pathway (people)",
                                           "min_cluster_share": "Smallest pathway (%)", "eligible_min_5pct": "Meets 5% minimum"}, percent=("min_cluster_share", "Smallest pathway (%)"))
            if "Hamming silhouette" in renamed.columns:
                renamed["Hamming silhouette"] = pd.to_numeric(methods["silhouette_hamming"], errors="coerce").map(lambda x: "n/a" if pd.isna(x) else f"{x:.4f}")
            put(st, html_table(renamed))
            note(st, selection_note(methods, payload.get("selected_k")))
            download(st, methods, "turkey_cluster_candidates.csv")
    attrition = tables.get("attrition")
    if attrition is not None and not attrition.empty:
        with st.container(key="card_rl_attrition_table"):
            card_head(st, "Administrative outcomes by follow-up status", "Do people with and without verified follow-up differ in the records?")
            renamed = tidy_table(attrition, {
                "followup_observed": "Follow-up verified in survey",
                "n": "People",
                "aug2013_formal_share": "Aug 2013 formal employment",
                "baseline_work_share": "Pre-course any work",
                "ever_formal_share": "Ever formal employment",
                "followup_status": "Follow-up status"
            }, percent=("aug2013_formal_share", "baseline_work_share", "ever_formal_share",
                        "Aug 2013 formal employment", "Pre-course any work", "Ever formal employment"))
            put(st, html_table(renamed))
            download(st, attrition, "turkey_attrition_admin_comparison.csv")


def sec_scope(st: Any, ctx: dict[str, Any]) -> None:
    result = ctx["result"]
    payload = ctx["payload"]
    section(st, "Scope, limits and provenance", "What this analysis covers, what it cannot say, and proof that the numbers come from the verified source file.", CYAN, first=True)
    left, right = st.columns([1.1, 1], gap="large")
    n_rows = payload.get("n_rows")
    with left:
        with st.container(key="card_sc_scope"):
            card_head(st, "Geographic and population scope")
            put(st, '<div class="facts">'
                    '<div class="mini"><div class="l">Place</div><div class="v">Turkey</div></div>'
                    '<div class="mini"><div class="l">Period</div><div class="v">2010–2013</div></div>'
                    '<div class="mini"><div class="l">Programme</div><div class="v">ISKUR vocational training evaluation</div></div>'
                    f'<div class="mini"><div class="l">Population</div><div class="v">{fmt(n_rows, "d")} original applicants; {fmt(payload.get("n_valid_post_training_trajectories"), "d")} complete attendee sequences</div></div></div>')
            put(st, '<div style="height:1.2rem"></div>')
            card_head(st, "What this analysis can and cannot say")
            put(st, '<ul class="bul"><li>It describes patterns among Turkish ISKUR applicants in 2010–2013. It does not describe any other country, period or programme.</li>'
                    '<li>It is descriptive. It does not estimate a causal training effect.</li>'
                    '<li>The sequences have three points, so a pathway is a short pattern of work status, not a career.</li>'
                    '<li>The August 2013 point is formal Social Security employment only; informal work is not captured.</li>'
                    '<li>“Not working” includes people outside the labour force; it does not mean unemployed.</li>'
                    '<li>Pathway numbers are labels. No pathway has been given a descriptive name.</li></ul>')
    with right:
        with st.container(key="card_sc_prov"):
            card_head(st, "Source verification", "The source file's SHA-256 matched the value saved by the pipeline when this page loaded")
            put(st, f'<div class="facts"><div class="mini"><div class="l">Source file</div><div class="v" style="overflow-wrap:anywhere">{esc(result.get("source", "n/a"))}</div></div></div>'
                    f'<div class="hash">{esc(payload.get("input_sha256", ""))}</div>')
            note(st, "If the source file changes, the saved results are hidden until the pipeline is rerun. The page computes nothing.")
            card_head(st, "Saved outputs read by this page")
            put(st, html_table(pd.DataFrame(result["inventory"], columns=["File", "Status"])))
    report = result.get("report")
    if report:
        with st.container(key="card_sc_report"):
            card_head(st, "Methodology and limitations", "As written by the pipeline")
            st.markdown(report)


RENDERERS = {"Overview": sec_overview, "Employment Pathways": sec_pathways, "Baseline Comparison": sec_baseline, "Training Outcomes": sec_training,
             "Administrative Outcomes": sec_admin, "Attrition & Stability": sec_reliability, "Scope & Provenance": sec_scope}


# ---------------------------------------------------------------------------------------------
# Streamlit page
# ---------------------------------------------------------------------------------------------
def render_turkey_saved(st: Any, cfg: Any) -> None:
    """Render the sidebar and the selected section, or explain why results are not shown."""
    result = load_turkey(cfg)
    choice = render_sidebar(st, result)
    if result["status"] == "missing":
        render_header(st, None)
        alert(st, "info", "Validated Turkey results are not available. Run `python -m src.turkey_pipeline` from the project root.")
        return
    if result["status"] == "invalid":
        render_header(st, None)
        alert(st, "warn", f"Turkey evaluation outputs are hidden because provenance validation failed: {result['reason']}")
        return
    payload, prevalence = result["payload"], result["prevalence"]
    render_header(st, str(payload.get("input_sha256", "")))
    if choice == "Overview":
        render_scope_banner(st, payload)
    ctx = {"result": result, "payload": payload, "prevalence": prevalence, "tables": result["tables"], "colours": pathway_colours(prevalence)}
    RENDERERS[choice](st, ctx)
    put(st, '<div class="foot">Saved results only: this page computes nothing. Rerun <code>python -m src.turkey_pipeline</code> to refresh the numbers.</div>')


def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="Employment Outcome Pathway Analytics", layout="wide", initial_sidebar_state="auto")
    st.markdown(CSS, unsafe_allow_html=True)
    render_turkey_saved(st, get_config())


# ---------------------------------------------------------------------------------------------
# Self-test (python dashboard/app3.py --self-test)
# ---------------------------------------------------------------------------------------------
def _write_fixture(root: Path) -> dict[str, Any]:
    """Build a tiny TEST-ONLY project under `root`. These numbers are not Turkey results."""
    out = root.joinpath(*OUT_DIR)
    out.mkdir(parents=True)
    (root / "data").mkdir()
    source = root / "data" / "fixture_source.csv"
    source.write_text("id,value\n1,2\n", encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    payload = {"input": "data/fixture_source.csv", "input_sha256": digest, "n_rows": 777, "n_valid_post_training_trajectories": 321,
               "selected_k": 3, "silhouette_hamming": 0.5123, "baseline_comparison": {"valid_pretraining_baseline_n": 400},
               "cluster_stability": {"replicates": 11, "ari_mean": 0.4321, "ari_sd": 0.0456},
               "attendee_baseline_cohort_n": 200, "attendee_with_verified_followup_n": 150, "attendee_followup_unknown_n": 50,
               "followup_work_extreme_bounds": {"lower": 0.3, "upper": 0.6}}
    (out / "summary.json").write_text(json.dumps(payload), encoding="utf-8")
    pd.DataFrame({"cluster_id": [0, 1, 2], "n": [100, 120, 101], "share_complete_pathways": [100 / 321, 120 / 321, 101 / 321],
                  "baseline_any_work_rate": [0.2, 0.5, 0.8], "followup_any_work_rate": [0.3, 0.6, 0.7], "aug2013_formal_work_rate": [0.1, 0.2, 0.4],
                  "trajectory_patterns": ["a <b>x</b>", "b", "c"], "treatment_assigned_n": [50, 60, 70], "attendance_evidence_n": [40, 50, 60],
                  "selection_reported_share": [0.5, 0.6, 0.7], "completion_n": [30, 40, 50], "completion_share_observed": [0.7, 0.8, 0.9],
                  "certificate_received_n": [20, 30, 40], "certificate_share_observed": [0.4, 0.5, 0.6]}).to_csv(out / "cluster_prevalence.csv", index=False)
    # Optional tables, so that every chart and table on every section is exercised by the test.
    pd.DataFrame({"employment_baseline": [0, 1], "n": [250, 150], "postfollowup_any_work_share": [0.35, 0.65],
                  "aug2013_formal_work_share": [0.15, 0.35]}).to_csv(out / EXTRA_TABLES["baseline"], index=False)
    pd.DataFrame({"cluster_id": [0, 1, 2], "formal_entry_by_jan2012_share": [0.1, 0.3, 0.5], "ever_formally_employed_postcourse_share": [0.2, 0.4, 0.6],
                  "first_job_left_by_nov2013_share": [0.05, 0.1, 0.2], "formal_anytime_first8months2013_share": [0.15, 0.35, 0.55],
                  "aug2013_formal_income_median": [1200.5, 1500.0, 1800.25]}).to_csv(out / EXTRA_TABLES["admin"], index=False)
    pd.DataFrame({"cluster_id": [0, 0, 1, 1, 2, 2], "admin_jan12_first_job_state": ["first_job_active_jan2012", "no_formal_job_by_jan2012"] * 3,
                  "share_cluster": [0.3, 0.7, 0.5, 0.5, 0.6, 0.4]}).to_csv(out / EXTRA_TABLES["state"], index=False)
    pd.DataFrame({"k": [2, 3, 4], "silhouette_hamming": [0.40, 0.5123, 0.55], "min_cluster_n": [150, 100, 10], "min_cluster_share": [0.4, 0.3, 0.03],
                  "eligible_min_5pct": [True, True, False]}).to_csv(out / EXTRA_TABLES["methods"], index=False)
    pd.DataFrame({"cluster_id": [0, 0, 1, 1, 2, 2], "MM_gender": ["Female", "Male", "Female", "Male", "Female", "Male"],
                  "n": [50, 50, 70, 50, 60, 41]}).to_csv(out / EXTRA_TABLES["gender"], index=False)
    pd.DataFrame({"path_baseline_any_work": [0, 0, 0, 1, 1, 1], "cluster_id": [0, 1, 2, 0, 1, 2],
                  "n": [80, 60, 20, 20, 60, 81]}).to_csv(out / EXTRA_TABLES["baseline_by_cluster"], index=False)
    pd.DataFrame({"followup_observed": [False, True], "n": [50, 150], "aug2013_formal_share": [0.40, 0.55],
                  "baseline_work_share": [0.20, 0.30]}).to_csv(out / EXTRA_TABLES["attrition"], index=False)
    (out / REPORT_FILE).write_text("## Test report\n\nFixture text.", encoding="utf-8")
    return payload


def _selftest() -> int:
    import shutil
    import tempfile

    from streamlit.testing.v1 import AppTest

    print("SELF-TEST FIXTURE: test-only numbers, not Turkey results")
    app = str(Path(__file__).resolve())
    tmp = Path(tempfile.mkdtemp(prefix="turkey_dashboard_selftest_"))

    def page_text(at: Any) -> str:
        return " ".join([m.value for m in at.markdown] + [m.value for m in at.title] + [m.value for m in at.header])

    def open_at(root: Path) -> Any:
        os.environ["TURKEY_DASHBOARD_ROOT"] = str(root)
        return AppTest.from_file(app, default_timeout=120).run()

    def go(at: Any, name: str) -> Any:
        return at.sidebar.radio(key="nav").set_value(name).run()

    good = tmp / "good"
    payload = _write_fixture(good)
    at_good = open_at(good)
    overview_text = page_text(at_good)
    section_text, section_exc = {}, []
    for name in SECTIONS:
        at_s = go(at_good, name)
        section_text[name] = page_text(at_s)
        section_exc += [e.value for e in at_s.exception]
    nav = at_good.sidebar.radio(key="nav")

    tampered = tmp / "tampered"
    shutil.copytree(good, tampered)
    (tampered / "data" / "fixture_source.csv").write_text("id,value\n1,3\n", encoding="utf-8")
    at_bad = open_at(tampered)
    bad_text = page_text(at_bad)

    outside = tmp / "outside"
    shutil.copytree(good, outside)
    summary = json.loads((outside.joinpath(*OUT_DIR) / "summary.json").read_text(encoding="utf-8"))
    summary["input"] = "../good/data/fixture_source.csv"
    (outside.joinpath(*OUT_DIR) / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    out_text = page_text(open_at(outside))

    empty = tmp / "empty"
    empty.mkdir()
    at_empty = open_at(empty)
    empty_text = page_text(at_empty)

    all_text = overview_text + " " + " ".join(section_text.values())
    banned = ("plfs", "maharashtra", "synthetic demonstration", "six-cluster", "pathway explorer")
    findings = " ".join(i["text"] for i in key_findings(pd.read_csv(good.joinpath(*OUT_DIR) / "cluster_prevalence.csv")))
    real_checked, real_ok = "no saved Turkey outputs in this project: real-output comparison skipped", True
    real = load_turkey(_Cfg(ROOT))
    if real["status"] == "ok":
        at_real = open_at(ROOT)
        real_text = page_text(at_real)
        shown = [(k["label"], k["value"]) for k in kpi_items(real["payload"], real["prevalence"])]
        real_ok = (not at_real.exception) and all(esc(v) in real_text for _, v in shown) and not any(b in real_text.lower() for b in banned)
        real_checked = "real saved outputs: KPI cards equal the saved summary (" + ", ".join(f"{lab}={val}" for lab, val in shown) + ")"
    elif real["status"] == "invalid":
        real_ok = False
        real_checked = "real saved outputs failed provenance validation: " + real["reason"]

    checks = {
        "fmt: None and NaN are n/a, never numbers; 4-decimal and thousands formats work":
            fmt(None) == "n/a" and fmt(float("nan")) == "n/a" and fmt(0.74834, ".4f") == "0.7483" and fmt(1546, "d") == "1,546" and pct(0.256) == "25.6%" and pct(None) == "n/a",
        "valid fixture: Overview renders with no exception": not at_good.exception,
        "navigation: left sidebar radio lists the seven sections and no top tabs exist": list(nav.options) == SECTIONS and not at_good.tabs,
        "navigation: every section renders without an exception": not section_exc,
        "navigation: the selection is kept in the URL": at_good.query_params.get("section") in (SECTIONS[-1], [SECTIONS[-1]]),
        "KPI cards on Overview show the saved values (sequences, k, silhouette, ARI)":
            all(s in overview_text for s in (f">{payload['n_valid_post_training_trajectories']}<", ">3<", ">0.5123<", ">0.4321<")) and overview_text.count('class="kpi"') == 4,
        "storyboard on Employment Pathways has one card per pathway": section_text["Employment Pathways"].count('class="pcard"') == 3,
        "findings are derived from the table (largest, highest formal work, change, completion)":
            "Pathway 1: 120 people" in findings and "Pathway 2: 40.0% in formal employment" in findings and "10.0 percentage points" in findings and "Pathway 2: 90.0% of those" in findings,
        "no value is hardcoded: another fixture shows other numbers": "1,546" not in all_text and "0.7483" not in all_text and "0.6198" not in all_text,
        "provenance: badge, sidebar card and the Scope section show the verified hash":
            payload["input_sha256"][:12] in overview_text and "SHA-256 verified" in overview_text and payload["input_sha256"] in section_text["Scope & Provenance"],
        "scope is stated: Turkey, 2010–2013, ISKUR": "Historical Turkey, 2010–2013" in overview_text and "ISKUR" in overview_text,
        "data-derived text is HTML-escaped": "<b>x</b>" not in all_text and "&lt;b&gt;x&lt;/b&gt;" in section_text["Employment Pathways"],
        "changed source file: results are hidden and the failure is explained":
            not at_bad.exception and "provenance validation failed" in bad_text and 'class="kpi"' not in bad_text,
        "source outside the project folder is refused": "provenance validation failed" in out_text,
        "no saved outputs: page says how to create them, without failing": not at_empty.exception and "python -m src.turkey_pipeline" in empty_text,
        "Turkey-only: no PLFS, Maharashtra, synthetic-demonstration or legacy-explorer text on any section": not any(b in all_text.lower() for b in banned),
        "Turkey-only: no PLFS or pipeline module was imported by the page":
            not any(m in sys.modules for m in ("src.cross_sectional", "run_pipeline", "src.report_builder", "src.visualization")),
        real_checked: real_ok,
    }
    os.environ.pop("TURKEY_DASHBOARD_ROOT", None)
    for name, ok in checks.items():
        print(f"  self-test [{'ok' if ok else 'FAILED'}]: {name}")
    if not all(checks.values()):
        print("exceptions:", section_exc, [e.value for e in at_good.exception], [e.value for e in at_bad.exception], [e.value for e in at_empty.exception])
        return 1
    print(f"Self-test passed ({len(checks)}). Fixture files are in {tmp}.")
    return 0


def _in_streamlit() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        return get_script_run_ctx() is not None
    except Exception:
        return False


if __name__ == "__main__":
    # Streamlit check first: AppTest re-executes this file as a script with the same sys.argv, which would
    # otherwise start the self-test again inside itself.
    if _in_streamlit():
        main()
    elif "--self-test" in sys.argv:
        raise SystemExit(_selftest())
    else:
        print("This is a Streamlit app. Run:  streamlit run dashboard/app3.py   (tests: python dashboard/app3.py --self-test)")
