"""Employment Outcome Pathway Analytics: Turkey ISKUR dashboard (read-only).

Shows the saved, validated outputs of `src.turkey_pipeline` and nothing else.
Every number on the page is read from `outputs/turkey/` at run time. Before
anything is shown, the source file named in `summary.json` is hashed and compared
with the SHA-256 recorded by the pipeline; on a mismatch the results are hidden.

This file imports no PLFS, synthetic or legacy-pathway module. It computes no
statistics and fits no model; it only reads, formats and draws saved values.

Run from the project root:
    streamlit run dashboard/app.py
    python dashboard/app.py --self-test

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
# Design tokens (taken from the reference dashboard: charcoal surfaces, cyan / pink / purple /
# green / amber accents)
# ---------------------------------------------------------------------------------------------
BG, CARD, LINE = "#1b1b1c", "#242425", "#343436"
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

ICONS = {
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
             '<path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "network": '<circle cx="6" cy="6" r="2.6"/><circle cx="6" cy="18" r="2.6"/><circle cx="18" cy="12" r="2.6"/>'
               '<path d="M6 8.6v6.8M8.3 7.2l7.4 3.6M8.3 16.8l7.4-3.6"/>',
    "target": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.2"/>',
    "trend": '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
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
    return {"status": "ok", "payload": payload, "prevalence": table, "tables": tables, "root": root,
            "report": report.read_text(encoding="utf-8") if report.is_file() else None}


def kpi_items(payload: dict[str, Any], prevalence: pd.DataFrame) -> list[dict[str, str]]:
    """Four headline cards, every value taken from the saved summary and table."""
    stab = payload.get("cluster_stability") or {}
    share = pd.to_numeric(prevalence.get("share_complete_pathways"), errors="coerce") if "share_complete_pathways" in prevalence else None
    smallest = f"smallest pathway {pct(share.min())} of attendees" if share is not None and share.notna().any() else "pathway sizes not saved"
    n_rows = payload.get("n_rows")
    return [
        {"icon": "users", "colour": CYAN, "label": "Complete attendee sequences",
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


def humanise(column: str) -> str:
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
CSS = f"""
<style>
:root {{ --bg:{BG}; --card:{CARD}; --line:{LINE}; --text:{TEXT}; --muted:{MUTED}; }}
.stApp {{ background:var(--bg); color:var(--text); font-family:{FONT}; color-scheme:dark; }}
header[data-testid="stHeader"] {{ background:transparent; }}
#MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"] {{ display:none !important; visibility:hidden; }}
.block-container {{ max-width:1560px; padding:1.8rem clamp(1rem,3vw,3rem) 3.5rem; }}
[data-testid="stMarkdownContainer"] {{ color:var(--text); }}
[data-testid="stHorizontalBlock"] {{ align-items:stretch; }}
[data-testid="stColumn"] > [data-testid="stVerticalBlock"] {{ height:100%; }}
[data-testid="stColumn"] > [data-testid="stVerticalBlock"] > [data-testid="stLayoutWrapper"]:has([class*="st-key-card_"]) {{ flex:1 1 auto; display:flex; flex-direction:column; }}
[data-testid="stLayoutWrapper"] > [class*="st-key-card_"] {{ flex:1 1 auto; }}
.hero {{ display:flex; justify-content:space-between; align-items:flex-start; gap:1.5rem; flex-wrap:wrap;
        padding:0 0 1.35rem; margin-bottom:1.6rem; border-bottom:1px solid var(--line); }}
.hero h1 {{ padding:0; font-size:clamp(1.7rem,2.6vw,2.45rem); font-weight:750; letter-spacing:-.02em; line-height:1.15; margin:0 0 .45rem; color:var(--text); }}
.hero .sub {{ font-size:1.05rem; color:var(--muted); margin:0; }}
.chips {{ display:flex; gap:.6rem; flex-wrap:wrap; align-items:center; }}
.chip {{ display:inline-flex; align-items:center; gap:.5rem; padding:.45rem .9rem; border-radius:999px; font-size:.82rem;
        font-weight:600; border:1px solid var(--line); background:#202021; color:#d9d9dd; white-space:nowrap; }}
.chip.ok {{ border-color:#3b5a33; color:{GREEN}; background:#1f2a1d; }}
.chip .dot {{ width:8px; height:8px; border-radius:50%; background:currentColor; }}
.scope {{ background:#202226; border:1px solid #2f3540; border-left:3px solid {CYAN}; border-radius:12px; padding:.85rem 1.1rem;
         color:#c9ced6; font-size:.93rem; line-height:1.5; margin-bottom:1.6rem; }}
.alert {{ border-radius:12px; padding:1rem 1.2rem; font-size:.95rem; line-height:1.5; border:1px solid var(--line); background:var(--card); }}
.alert.warn {{ border-color:#6b5224; background:#2a2418; color:#f1d9a6; }}
.alert.info {{ border-color:#2f4d57; background:#1d2629; color:#bfe3e6; }}
.kpi-grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:1.25rem; margin-bottom:1.5rem; }}
@media (max-width:1100px) {{ .kpi-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} }}
@media (max-width:560px) {{ .kpi-grid {{ grid-template-columns:1fr; }} }}
.kpi {{ display:flex; gap:1.1rem; align-items:flex-start; background:var(--card); border:1px solid var(--line); border-radius:16px;
       padding:1.35rem 1.4rem; box-shadow:0 8px 26px rgba(0,0,0,.32); transition:transform .15s ease, border-color .15s ease; }}
.kpi:hover {{ transform:translateY(-2px); border-color:#46464a; }}
.kpi-icon {{ flex:0 0 auto; width:54px; height:54px; border-radius:14px; display:grid; place-items:center;
            background:color-mix(in srgb, var(--c) 16%, {CARD}); color:var(--c); }}
.kpi-icon svg {{ width:26px; height:26px; fill:none; stroke:currentColor; stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round; }}
.kpi-body {{ min-width:0; }}
.kpi-label {{ font-size:.92rem; color:var(--muted); margin-bottom:.2rem; }}
.kpi-value {{ font-size:clamp(1.7rem,2.2vw,2.15rem); font-weight:750; letter-spacing:-.02em; line-height:1.15; color:var(--text); font-variant-numeric:tabular-nums; }}
.kpi-sub {{ font-size:.84rem; color:var(--c); margin-top:.5rem; line-height:1.35; }}
[class*="st-key-card_"] {{ background:var(--card); border:1px solid var(--line); border-radius:16px; padding:1.4rem 1.5rem 1.2rem;
                         box-shadow:0 8px 26px rgba(0,0,0,.32); margin-bottom:.4rem; }}
.card-title {{ font-size:1.22rem; font-weight:680; letter-spacing:-.01em; color:var(--text); margin:0 0 .25rem; }}
.card-sub {{ font-size:.86rem; color:var(--muted); margin:0 0 .9rem; line-height:1.45; }}
.section {{ margin:2.1rem 0 1rem; }}
.section h2 {{ padding:0; font-size:1.4rem; font-weight:720; letter-spacing:-.015em; margin:0; color:var(--text); display:flex; align-items:center; gap:.7rem; }}
.section h2:before {{ content:""; width:4px; height:1.2em; border-radius:3px; background:var(--accent,{CYAN}); }}
.section p {{ margin:.35rem 0 0 1.05rem; color:var(--muted); font-size:.92rem; }}
.note {{ color:var(--muted); font-size:.82rem; line-height:1.5; margin:.7rem 0 .9rem; }}
.foot code {{ background:#2b2b2d; color:#9fd8dc; padding:.1rem .45rem; border-radius:6px; font-size:.78rem; }}
.tbl {{ width:100%; overflow-x:auto; }}
.tbl table {{ width:100%; border-collapse:collapse; table-layout:auto; }}
.tbl th {{ text-align:left; font-size:.72rem; letter-spacing:.06em; text-transform:uppercase; color:var(--muted); font-weight:650;
          padding:.55rem .65rem; border-bottom:1px solid var(--line); vertical-align:bottom; }}
.tbl td {{ padding:.65rem .65rem; border-bottom:1px solid #2d2d2f; font-size:.9rem; color:#e6e6e9; overflow-wrap:anywhere; vertical-align:top; }}
.tbl th.num {{ text-align:right; }}
.tbl td.num {{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }}
.tbl tr:last-child td {{ border-bottom:none; }}
.tbl tbody tr:hover td {{ background:#2b2b2d; }}
.tbl td.path {{ white-space:nowrap; }}
.tbl .dot {{ display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:.55rem; }}
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
.stDownloadButton button, .stButton button {{ background:#2b2b2d !important; color:#e8e8ec !important; border:1px solid #3d3d40 !important;
    border-radius:10px !important; font-size:.82rem !important; padding:.35rem .85rem !important; }}
.stDownloadButton button:hover {{ border-color:{CYAN} !important; color:{CYAN} !important; }}
[data-testid="stExpander"] {{ margin-top:.6rem; background:var(--card); border:1px solid var(--line) !important; border-radius:14px; }}
[data-testid="stExpander"] summary, [data-testid="stExpander"] summary * {{ color:#e8e8ec !important; }}
[data-testid="stExpander"] p, [data-testid="stExpander"] li {{ color:#d0d0d5; }}
[data-testid="stExpander"] h1, [data-testid="stExpander"] h2, [data-testid="stExpander"] h3 {{ color:var(--text); }}
[data-testid="stVegaLiteChart"], .stVegaLiteChart {{ width:100%; }}
.foot {{ color:var(--muted); font-size:.8rem; text-align:center; margin-top:2.2rem; }}
@media (max-width:900px) {{ .stack-3 {{ grid-template-columns:1fr; }} .hero {{ padding-bottom:1rem; }} }}
</style>
"""


def inline_html(markup: str) -> str:
    """Collapse to one line: Streamlit's markdown parser ends an HTML block at a blank line."""
    return " ".join(line.strip() for line in markup.splitlines() if line.strip())


def put(st: Any, markup: str) -> None:
    st.markdown(inline_html(markup), unsafe_allow_html=True)


def section(st: Any, title: str, sub: str = "", accent: str = CYAN) -> None:
    put(st, f'<div class="section" style="--accent:{accent}"><h2>{esc(title)}</h2>' + (f"<p>{esc(sub)}</p>" if sub else "") + "</div>")


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
    chart = alt.Chart(long).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
        x=alt.X(f"{x}:N", title=x_title, axis=alt.Axis(labelAngle=0, labelPadding=8, grid=False, ticks=False)),
        xOffset=alt.XOffset("Series:N"),
        y=alt.Y("Percent:Q", title=value_title, scale=alt.Scale(domain=[0, 100], nice=False) if percent else alt.Scale(zero=True),
                axis=alt.Axis(tickCount=5, format=".0f" if percent else ",.0f")),
        color=alt.Color("Series:N", title=None, scale=alt.Scale(domain=list(series_colours), range=list(series_colours.values())),
                        legend=alt.Legend(orient="top", columns=len(series_colours) if sum(len(k) for k in series_colours) <= 62 else 2, labelLimit=320, columnPadding=14)),
        tooltip=[alt.Tooltip(f"{x}:N"), alt.Tooltip("Series:N", title="Measure"), alt.Tooltip("Percent:Q", title=value_title, format=".1f" if percent else ",.0f")])
    draw(st, chart, height)


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
    draw(st, arc + centre + caption, 300)


def silhouette_chart(st: Any, methods: pd.DataFrame, selected_k: Any) -> None:
    import altair as alt
    if not {"k", "silhouette_hamming"} <= set(methods.columns):
        alert(st, "info", "Candidate silhouettes are not available in the saved output.")
        return
    frame = methods[["k", "silhouette_hamming"]].copy()
    frame["k"] = pd.to_numeric(frame["k"], errors="coerce")
    frame["Silhouette"] = pd.to_numeric(frame["silhouette_hamming"], errors="coerce")
    frame = frame.dropna(subset=["k", "Silhouette"])
    frame["Status"] = frame["k"].map(lambda k: "Selected" if pd.notna(pd.to_numeric(selected_k, errors="coerce")) and k == float(selected_k) else "Candidate")
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
    bars = alt.Chart(frame).mark_bar(color=PURPLE, cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
        x=alt.X("k:O", title="Number of pathways (k)", axis=alt.Axis(labelAngle=0, grid=False)),
        y=alt.Y("Smallest pathway (%):Q", scale=alt.Scale(domain=[0, max(10.0, float(frame["Smallest pathway (%)"].max()) * 1.15)]), axis=alt.Axis(title="Smallest pathway (%)", format=".0f")),
        tooltip=[alt.Tooltip("k:O"), alt.Tooltip("Smallest pathway (%):Q", format=".1f")])
    rule = alt.Chart(pd.DataFrame({"y": [5.0], "t": ["5% floor"]})).mark_rule(color=AMBER, strokeDash=[6, 4], strokeWidth=2).encode(y="y:Q")
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


# ---------------------------------------------------------------------------------------------
# Page sections
# ---------------------------------------------------------------------------------------------
def render_header(st: Any, verified_hash: str | None) -> None:
    chips = '<span class="chip">INT396 | G24 | CA Project</span>'
    if verified_hash:
        chips += f'<span class="chip ok"><span class="dot"></span>Provenance verified · SHA-256 {esc(verified_hash[:12])}…</span>'
    put(st, '<div class="hero"><div><h1>Employment Outcome Pathway Analytics</h1>'
            '<p class="sub">Historical Turkey ISKUR Vocational Training Evaluation (2010–2013)</p></div>'
            f'<div class="chips">{chips}</div></div>')


def render_kpis(st: Any, payload: dict[str, Any], prevalence: pd.DataFrame) -> None:
    cards = "".join(
        f'<div class="kpi" style="--c:{k["colour"]}"><div class="kpi-icon"><svg viewBox="0 0 24 24">{ICONS[k["icon"]]}</svg></div>'
        f'<div class="kpi-body"><div class="kpi-label">{esc(k["label"])}</div><div class="kpi-value">{esc(k["value"])}</div>'
        f'<div class="kpi-sub">{esc(k["sub"])}</div></div></div>' for k in kpi_items(payload, prevalence))
    put(st, f'<div class="kpi-grid">{cards}</div>')


def render_distribution(st: Any, payload: dict[str, Any], prevalence: pd.DataFrame, colours: dict[str, str]) -> None:
    section(st, "Pathway distribution and employment trajectory", "How the complete attendee sequences group, and how each pathway moves across three points in time.", CYAN)
    left, right = st.columns(2, gap="large")
    with left:
        with st.container(key="card_distribution"):
            card_head(st, "Employment pathway distribution", "People per pathway among complete attendee sequences")
            donut(st, prevalence, colours, "attendees")
            total = pd.to_numeric(prevalence.get("n"), errors="coerce").sum() if "n" in prevalence else None
            note(st, f"Pathway sizes add up to {fmt(int(total), 'd')} people." if total is not None else "")
    with right:
        with st.container(key="card_trajectory"):
            card_head(st, "Pre-course, post-course and August 2013 employment", "Share of each pathway in work at the three measurement points")
            long = melt_percent(prevalence.assign(Pathway=prevalence["cluster_id"].map(pathway_label)), "Pathway",
                                {"baseline_any_work_rate": "Pre-course any work", "followup_any_work_rate": "Post-course any work",
                                 "aug2013_formal_work_rate": "Aug 2013 formal work"})
            grouped_bars(st, long, "Pathway", {"Pre-course any work": CYAN, "Post-course any work": PINK, "Aug 2013 formal work": AMBER})
            note(st, "Sequence points: pre-course any work → post-course any work → August 2013 formal Social Security employment. "
                     "The final measure is narrower than the survey measures. Not working is not the same as unemployed.")


def render_profiles(st: Any, prevalence: pd.DataFrame, tables: dict[str, Any], colours: dict[str, str]) -> None:
    section(st, "Participant profiles", "Who is in each pathway, in numbers saved by the pipeline.", PINK)
    left, right = st.columns([1.15, 1], gap="large")
    with left:
        with st.container(key="card_profiles"):
            card_head(st, "Pathway profile", "Size, cohort share and the observed three-point work sequences")
            cols = [c for c in ("cluster_id", "n", "share_complete_pathways", "trajectory_patterns") if c in prevalence.columns]
            view = tidy_table(prevalence[cols], {"n": "People", "share_complete_pathways": "Cohort share", "trajectory_patterns": "Observed sequence patterns"})
            put(st, html_table(view, colours))
            download(st, prevalence, "turkey_pathway_prevalence_complete.csv", "Download complete pathway table")
    with right:
        with st.container(key="card_gender"):
            card_head(st, "Gender profile by pathway", "Descriptive only; gender is never used to form pathways")
            gender = tables.get("gender")
            if gender is None or gender.empty:
                alert(st, "info", "No saved gender profile is available.")
            else:
                put(st, html_table(tidy_table(gender), colours))
                download(st, gender, "turkey_cluster_gender_profile.csv")


def render_baseline(st: Any, payload: dict[str, Any], tables: dict[str, Any]) -> None:
    section(st, "Baseline employment comparison", "Does working before the course explain what happens afterwards?", GREEN)
    base = tables.get("baseline")
    left, right = st.columns(2, gap="large")
    with left:
        with st.container(key="card_baseline_chart"):
            card_head(st, "Outcomes by pre-course work status", "Post-course any work and August 2013 formal work")
            if base is None or "employment_baseline" not in base.columns:
                alert(st, "info", "No saved baseline comparison is available.")
            else:
                names = {"0": "Not working", "1": "Worked at all"}

                def status(v: Any) -> str:
                    try:
                        return names.get(str(int(float(v))), str(v))
                    except (TypeError, ValueError):
                        return str(v)
                frame = base.assign(Status=base["employment_baseline"].map(status))
                long = melt_percent(frame, "Status", {"postfollowup_any_work_share": "Post-course any work", "aug2013_formal_work_share": "Aug 2013 formal work"})
                grouped_bars(st, long, "Status", {"Post-course any work": PINK, "Aug 2013 formal work": AMBER})
    with right:
        with st.container(key="card_baseline_table"):
            card_head(st, "Baseline comparison table", "Interviews dated before the course start")
            if base is not None and "employment_baseline" in base.columns:
                cols = [c for c in ("employment_baseline", "n", "postfollowup_any_work_share", "aug2013_formal_work_share") if c in base.columns]
                view = tidy_table(base[cols], {"employment_baseline": "Baseline status", "n": "People", "postfollowup_any_work_share": "Post-course any work",
                                               "aug2013_formal_work_share": "Aug 2013 formal work"},
                                  percent=("postfollowup_any_work_share", "aug2013_formal_work_share"))
                view["Baseline status"] = base["employment_baseline"].map(lambda v: {"0": "Not working", "1": "Worked at all"}.get(str(int(float(v))) if pd.notna(v) else "", str(v)))
                put(st, html_table(view))
                download(st, base, "turkey_baseline_comparison_complete.csv")
            valid = (payload.get("baseline_comparison") or {}).get("valid_pretraining_baseline_n")
            note(st, f"Comparison cohort: {fmt(valid, 'd')} interviews dated before course start. “Not working” includes people outside the labour force; it does not mean unemployed.")
            by_cluster = tables.get("baseline_by_cluster")
            if by_cluster is not None and not by_cluster.empty:
                with st.expander("Baseline work by pathway"):
                    put(st, html_table(tidy_table(by_cluster)))


def render_training(st: Any, prevalence: pd.DataFrame, colours: dict[str, str]) -> None:
    section(st, "Training attendance, completion and certification", "Assignment, selection, documented attendance, completion and certificates are different things.", AMBER)
    left, right = st.columns(2, gap="large")
    labelled = prevalence.assign(Pathway=prevalence["cluster_id"].map(pathway_label))
    with left:
        with st.container(key="card_training_chart"):
            card_head(st, "Selection, completion and certification rates", "Each rate uses its own known or observed denominator")
            long = melt_percent(labelled, "Pathway", {"selection_reported_share": "Self-reported selection", "completion_share_observed": "Completed among known",
                                                      "certificate_share_observed": "Certificate among known"})
            grouped_bars(st, long, "Pathway", {"Self-reported selection": PURPLE, "Completed among known": GREEN, "Certificate among known": CYAN})
    with right:
        with st.container(key="card_training_counts"):
            card_head(st, "Documented attendance, completion and certificates", "Number of people with each documented outcome")
            counts = prevalence.assign(Pathway=prevalence["cluster_id"].map(pathway_label))
            present = {c: lab for c, lab in {"attendance_evidence_n": "Attendance documented", "completion_n": "Completion known yes",
                                             "certificate_received_n": "Certificate known yes"}.items() if c in counts.columns}
            if present:
                long_n = counts[["Pathway", *present]].rename(columns=present).melt(id_vars="Pathway", var_name="Series", value_name="Percent")
                long_n["Percent"] = pd.to_numeric(long_n["Percent"], errors="coerce")
                grouped_bars(st, long_n.dropna(subset=["Percent"]), "Pathway", {"Attendance documented": AMBER, "Completion known yes": GREEN, "Certificate known yes": CYAN},
                             value_title="People", percent=False)
            else:
                alert(st, "info", "Attendance counts are not available in the saved output.")
    cols = [c for c in ("cluster_id", "treatment_assigned_n", "attendance_evidence_n", "selection_reported_share", "completion_n",
                        "completion_share_observed", "certificate_received_n", "certificate_share_observed") if c in prevalence.columns]
    with st.container(key="card_training_table"):
        card_head(st, "Attendance and course outcomes by pathway", "Counts and shares as saved")
        view = tidy_table(prevalence[cols], {"treatment_assigned_n": "Assigned to treatment", "attendance_evidence_n": "Attendance documented",
                                             "selection_reported_share": "Self-reported selection", "completion_n": "Completion known yes",
                                             "completion_share_observed": "Completed among known", "certificate_received_n": "Certificate known yes",
                                             "certificate_share_observed": "Certificate among known"})
        put(st, html_table(view, colours))
        note(st, "Rates use their stated known or observed denominators; unknown outcomes are not counted as “no”.")
        download(st, prevalence[cols], "turkey_course_outcomes_by_pathway.csv")


def render_admin(st: Any, tables: dict[str, Any], colours: dict[str, str]) -> None:
    section(st, "Administrative employment milestones", "Formal (Social Security) employment records after the course.", PURPLE)
    admin, state = tables.get("admin"), tables.get("state")
    left, right = st.columns(2, gap="large")
    with left:
        with st.container(key="card_admin_chart"):
            card_head(st, "Employment milestones by pathway", "Share of each pathway reaching each milestone")
            if admin is None or "cluster_id" not in admin.columns:
                alert(st, "info", "No saved administrative profile is available.")
            else:
                long = melt_percent(admin.assign(Pathway=admin["cluster_id"].map(pathway_label)), "Pathway",
                                    {"formal_entry_by_jan2012_share": "Formal job by Jan 2012", "ever_formally_employed_postcourse_share": "Ever formal job after course",
                                     "first_job_left_by_nov2013_share": "First job left by Nov 2013", "formal_anytime_first8months2013_share": "Formal job Jan–Aug 2013 (cumulative)"})
                grouped_bars(st, long, "Pathway", {"Formal job by Jan 2012": CYAN, "Ever formal job after course": GREEN,
                                                   "First job left by Nov 2013": PINK, "Formal job Jan–Aug 2013 (cumulative)": AMBER}, height=320)
                note(st, "The January–August 2013 indicator is cumulative; it is not an August point-in-time measure. No monthly job spells are present in this public-use file.")
    with right:
        with st.container(key="card_admin_state"):
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
            with st.container(key="card_income_chart"):
                card_head(st, "Median formal income, August 2013", "In the source currency; one bar per pathway")
                income_chart(st, income.dropna(subset=["Median"]), colours)
        with c2:
            with st.container(key="card_income_table"):
                card_head(st, "Median formal income table", "Values as saved")
                view = pd.DataFrame({"Pathway": income["Pathway"], "Median formal income (source currency)": income["Median"].map(lambda x: "n/a" if pd.isna(x) else f"{x:,.2f}")})
                put(st, html_table(view, colours))
                download(st, income[["cluster_id", "aug2013_formal_income_median"]], "turkey_admin_income_median.csv")


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


def range_bar(lower: Any, upper: Any) -> str:
    lo, hi = pd.to_numeric(lower, errors="coerce"), pd.to_numeric(upper, errors="coerce")
    if pd.isna(lo) or pd.isna(hi):
        return ""
    return (f'<div class="gauge"><div class="band" style="left:{float(lo) * 100:.2f}%;width:{max(float(hi) - float(lo), 0.004) * 100:.2f}%;'
            f'background:linear-gradient(90deg,{AMBER},{PINK});border-color:transparent"></div></div>'
            '<div class="scale"><span>0%</span><span>50%</span><span>100%</span></div>')


def render_stability(st: Any, payload: dict[str, Any], tables: dict[str, Any], report: str | None) -> None:
    section(st, "Attrition and clustering stability", "How much of the cohort was followed up, and how reproducible the pathways are.", PINK)
    left, right = st.columns(2, gap="large")
    cohort = payload.get("attendee_baseline_cohort_n")
    verified = payload.get("attendee_with_verified_followup_n")
    unknown = payload.get("attendee_followup_unknown_n")
    with left:
        with st.container(key="card_attrition"):
            card_head(st, "Follow-up attrition", "Documented attendees with a valid pre-course baseline")
            numbers = [pd.to_numeric(x, errors="coerce") for x in (cohort, verified, unknown)]
            if any(pd.isna(x) for x in numbers):
                alert(st, "info", "Follow-up counts are not available in the saved output.")
            else:
                c, v, u = (float(x) for x in numbers)
                vw = v / c * 100 if c else 0
                uw = u / c * 100 if c else 0
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
            attrition = tables.get("attrition")
            if attrition is not None and not attrition.empty:
                with st.expander("Administrative outcomes by follow-up status"):
                    put(st, html_table(tidy_table(attrition)))
    with right:
        with st.container(key="card_stability"):
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
                put(st, f'<div class="big" style="color:{CYAN}">{fmt(float(ari), ".4f")}'
                        f'<span style="font-size:1rem;color:{MUTED};font-weight:500"> mean ARI · SD {fmt(None if pd.isna(sd) else float(sd), ".3f")}</span></div>'
                        f'<div class="gauge"><div class="fill" style="width:{float(ari) * 100:.2f}%"></div>{band}</div>'
                        '<div class="scale"><span>0 (no agreement)</span><span>1 (identical)</span></div>')
                put(st, f'<div class="stack-3"><div class="mini"><div class="l">Mean ARI</div><div class="v" style="color:{CYAN}">{fmt(float(ari), ".4f")}</div></div>'
                        f'<div class="mini"><div class="l">Standard deviation</div><div class="v" style="color:{PURPLE}">{fmt(None if pd.isna(sd) else float(sd), ".4f")}</div></div>'
                        f'<div class="mini"><div class="l">Subsample refits</div><div class="v" style="color:{GREEN}">{fmt(stab.get("replicates"), "d")}</div></div></div>')
                note(st, f"Mean ARI across {fmt(stab.get('replicates'), 'd')} deterministic subsample refits. This is moderate resampling stability, not external validity.")
    methods = tables.get("methods")
    if methods is not None and not methods.empty:
        with st.container(key="card_methods"):
            card_head(st, "Clustering candidate evaluation", "Silhouette and smallest-pathway size for each candidate k")
            a, b = st.columns(2, gap="large")
            with a:
                silhouette_chart(st, methods, payload.get("selected_k"))
            with b:
                smallest_share_chart(st, methods)
            note(st, "Dashed line: the predeclared 5% cohort-size floor for the smallest pathway.")
            renamed = tidy_table(methods, {"k": "Clusters (k)", "silhouette_hamming": "Hamming silhouette", "min_cluster_n": "Smallest pathway (people)",
                                           "min_cluster_share": "Smallest pathway (%)", "eligible_min_5pct": "Meets 5% minimum"},
                                 percent=("min_cluster_share", "Smallest pathway (%)"))
            for col in ("Hamming silhouette",):
                if col in renamed.columns:
                    renamed[col] = pd.to_numeric(methods["silhouette_hamming"], errors="coerce").map(lambda x: "n/a" if pd.isna(x) else f"{x:.4f}")
            put(st, html_table(renamed))
            note(st, selection_note(methods, payload.get("selected_k")))
            download(st, methods, "turkey_cluster_candidates.csv")
    if report:
        with st.expander("Turkey methodology and limitations"):
            st.markdown(report)


# ---------------------------------------------------------------------------------------------
# Streamlit page
# ---------------------------------------------------------------------------------------------
def render_turkey_saved(st: Any, cfg: Any) -> None:
    """Render the validated Turkey results, or explain why they are not shown."""
    result = load_turkey(cfg)
    if result["status"] == "missing":
        render_header(st, None)
        alert(st, "info", "Validated Turkey results are not available. Run `python -m src.turkey_pipeline` from the project root.")
        return
    if result["status"] == "invalid":
        render_header(st, None)
        alert(st, "warn", f"Turkey evaluation outputs are hidden because provenance validation failed: {result['reason']}")
        return
    payload, prevalence, tables = result["payload"], result["prevalence"], result["tables"]
    render_header(st, str(payload.get("input_sha256", "")))
    put(st, '<div class="scope">Descriptive analysis of a historical Turkish vocational-training evaluation. '
            'It does not estimate a causal training effect and does not describe any other country or programme. '
            'Pathway numbers are labels only; no pathway has been given a descriptive name.</div>')
    colours = pathway_colours(prevalence)
    render_kpis(st, payload, prevalence)
    render_distribution(st, payload, prevalence, colours)
    render_profiles(st, prevalence, tables, colours)
    render_baseline(st, payload, tables)
    render_training(st, prevalence, colours)
    render_admin(st, tables, colours)
    render_stability(st, payload, tables, result["report"])
    with st.expander("Complete pathway table and technical diagnostics"):
        put(st, html_table(tidy_table(prevalence), colours))
        download(st, prevalence, "turkey_cluster_prevalence_full.csv", "Download complete pathway table")
        if tables.get("admin") is not None:
            put(st, '<div class="note">Complete administrative profile by pathway</div>')
            put(st, html_table(tidy_table(tables["admin"]), colours))
            download(st, tables["admin"], "turkey_cluster_admin_profile.csv", "Download administrative profile")
    put(st, '<div class="foot">Saved results only: this page computes nothing. Rerun <code>python -m src.turkey_pipeline</code> to refresh the numbers.</div>')


def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="Employment Outcome Pathway Analytics", layout="wide", initial_sidebar_state="collapsed")
    st.markdown(CSS, unsafe_allow_html=True)
    render_turkey_saved(st, get_config())


# ---------------------------------------------------------------------------------------------
# Self-test (python dashboard/app.py --self-test)
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
    return payload


def _selftest() -> int:
    import shutil
    import tempfile

    from streamlit.testing.v1 import AppTest

    print("SELF-TEST FIXTURE: test-only numbers, not Turkey results")
    app = str(ROOT / "dashboard" / "app.py")
    tmp = Path(tempfile.mkdtemp(prefix="turkey_dashboard_selftest_"))

    def run_at(root: Path) -> tuple[Any, str]:
        os.environ["TURKEY_DASHBOARD_ROOT"] = str(root)
        at = AppTest.from_file(app, default_timeout=120).run()
        text = " ".join([m.value for m in at.markdown] + [m.value for m in at.title] + [m.value for m in at.header])
        return at, text

    good = tmp / "good"
    payload = _write_fixture(good)
    at_good, good_text = run_at(good)

    tampered = tmp / "tampered"
    shutil.copytree(good, tampered)
    (tampered / "data" / "fixture_source.csv").write_text("id,value\n1,3\n", encoding="utf-8")
    at_bad, bad_text = run_at(tampered)

    outside = tmp / "outside"
    shutil.copytree(good, outside)
    summary = json.loads((outside.joinpath(*OUT_DIR) / "summary.json").read_text(encoding="utf-8"))
    summary["input"] = "../good/data/fixture_source.csv"
    (outside.joinpath(*OUT_DIR) / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    at_out, out_text = run_at(outside)

    empty = tmp / "empty"
    empty.mkdir()
    at_empty, empty_text = run_at(empty)

    escaped_ok = "<b>x</b>" not in good_text and "&lt;b&gt;x&lt;/b&gt;" in good_text
    banned = ("plfs", "maharashtra", "synthetic demonstration", "six-cluster", "pathway explorer")
    real_checked, real_ok = "no saved Turkey outputs in this project: real-output comparison skipped", True
    real_cfg = _Cfg(ROOT)
    real = load_turkey(real_cfg)
    if real["status"] == "ok":
        os.environ["TURKEY_DASHBOARD_ROOT"] = str(ROOT)
        at_real = AppTest.from_file(app, default_timeout=120).run()
        real_text = " ".join(m.value for m in at_real.markdown)
        shown = [(k["label"], k["value"]) for k in kpi_items(real["payload"], real["prevalence"])]
        real_ok = (not at_real.exception) and all(esc(v) in real_text for _, v in shown) and not any(b in real_text.lower() for b in banned)
        real_checked = "real saved outputs: KPI cards equal the saved summary (" + ", ".join(f"{lab}={val}" for lab, val in shown) + ")"
    elif real["status"] == "invalid":
        real_ok = False
        real_checked = "real saved outputs failed provenance validation: " + real["reason"]

    checks = {
        "fmt: None and NaN are n/a, never numbers; 4-decimal and thousands formats work":
            fmt(None) == "n/a" and fmt(float("nan")) == "n/a" and fmt(0.74834, ".4f") == "0.7483" and fmt(1546, "d") == "1,546" and pct(0.256) == "25.6%" and pct(None) == "n/a",
        "valid fixture: page renders with no exception": not at_good.exception,
        "KPI cards show the saved values (sequences, k, silhouette, ARI)":
            all(s in good_text for s in (f">{payload['n_valid_post_training_trajectories']}<", ">3<", ">0.5123<", ">0.4321<")),
        "all four KPI cards present": good_text.count('class="kpi"') == 4,
        "no value is hardcoded: another fixture shows other numbers": "1,546" not in good_text and "0.7483" not in good_text and "0.6198" not in good_text,
        "provenance badge shows the verified hash prefix": payload["input_sha256"][:12] in good_text,
        "data-derived text is HTML-escaped": escaped_ok,
        "changed source file: results are hidden and the failure is explained":
            not at_bad.exception and "provenance validation failed" in bad_text and 'class="kpi"' not in bad_text,
        "source outside the project folder is refused": "provenance validation failed" in out_text and 'class="kpi"' not in out_text,
        "no saved outputs: page says how to create them, without failing": not at_empty.exception and "python -m src.turkey_pipeline" in empty_text,
        "Turkey-only: no PLFS, Maharashtra, synthetic-demonstration or legacy-explorer text on the page": not any(b in good_text.lower() for b in banned),
        "Turkey-only: no PLFS or pipeline module was imported by the page":
            not any(m in sys.modules for m in ("src.cross_sectional", "run_pipeline", "src.report_builder", "src.visualization")),
        real_checked: real_ok,
    }
    os.environ.pop("TURKEY_DASHBOARD_ROOT", None)
    for name, ok in checks.items():
        print(f"  self-test [{'ok' if ok else 'FAILED'}]: {name}")
    if not all(checks.values()):
        print("exceptions:", [e.value for e in at_good.exception], [e.value for e in at_bad.exception], [e.value for e in at_empty.exception])
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
        print("This is a Streamlit app. Run:  streamlit run dashboard/app.py   (tests: python dashboard/app.py --self-test)")
