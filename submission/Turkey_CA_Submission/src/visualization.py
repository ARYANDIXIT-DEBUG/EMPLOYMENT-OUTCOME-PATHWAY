"""Figures for the report and the dashboard (matplotlib only).

Why this file exists: the report and the dashboard must show the same pictures, and every picture must carry its
own warning when it comes from synthetic data. So all plotting lives here, each function takes plain tables or
arrays (never fits anything), and returns a matplotlib `Figure` that the caller can show, save or embed.

Design choices worth defending in a viva:
  * Figures are built with `matplotlib.figure.Figure`, not `pyplot`. There is no global figure registry to leak
    memory in a long-running dashboard, no backend to configure, and the same code runs headless and on a server.
  * The pictures show what was computed and nothing more. A function never recomputes a statistic that another
    module owns (silhouette, ARI, prevalence): it draws the numbers it is given. The only derived quantities are
    display transforms (column shares of a contingency table, a deterministic row sample for the sequence plot).
  * States keep one colour in every figure (Okabe-Ito, colour-blind safe, in the order of `states` in the config).
    MISSING is light grey and LOST is dark grey, so unobserved cells are never mistaken for a state.
    Pathways are not given colours of their own, so a colour always means a state.
  * The sequence-index plot samples at most `max_rows` individuals with `make_rng(cfg, "viz/sequence_index")`, so
    the picture is reproducible, and the title says how many were drawn out of how many.
  * `stamp_synthetic` adds a red line under the figure and a faint diagonal watermark. `save_figure` always stamps
    synthetic figures and puts the tag in the file name (`<name>__SYNTHETIC.png` or `<name>__real.png`), the same
    tags as the results files, so a synthetic picture cannot be mistaken for a real one on disk.

Limits: a figure is a summary; the tables in `reports/results/` are the record. Stability and baseline plots
show what the pipeline computed on the sample it was given, synthetic or real.

Dependency rule: imports `config` and the shared types only. The smoke demo imports later-delivered helpers
(`synthetic_data`, `preprocessing`, `trajectories`, `distances`, `clustering`, `evaluation`, `baseline`,
`missing_data`, `profiling`, `stability`) inside the demo function only.

Run the smoke demo with:  python -m src.visualization
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import ListedColormap
from matplotlib.figure import Figure
from matplotlib.patches import Patch

from . import LOST, MISSING, TrajectoryData
from .config import Config, ConfigError, load_config, make_rng, resolve_path

__all__ = [
    "SYNTHETIC_STAMP",
    "plot_state_distribution",
    "plot_sequence_index",
    "plot_medoid_sequences",
    "plot_prevalence",
    "plot_k_selection",
    "plot_stability_curves",
    "plot_baseline_vs_clusters",
    "plot_missingness",
    "plot_silhouette",
    "stamp_synthetic",
    "save_figure",
]

SYNTHETIC_STAMP = "SYNTHETIC DEMONSTRATION - NOT PLFS RESULTS"
_OKABE_ITO = ["#0072B2", "#E69F00", "#009E73", "#D55E00", "#CC79A7", "#56B4E9", "#F0E442"]
_MISSING_COLOUR = "#D9D9D9"
_LOST_COLOUR = "#444444"
_INK = "#222222"
_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


# ---------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------
def _fig(width: float, height: float) -> Figure:
    fig = Figure(figsize=(width, height), layout="constrained", dpi=100)
    FigureCanvasAgg(fig)                      # a headless canvas: draws and saves without any display or pyplot
    return fig


def _pretty(name: str) -> str:
    return str(name).replace("_", " ")


def _state_colours(n_states: int) -> list[str]:
    if n_states > len(_OKABE_ITO):
        raise ConfigError(f"{n_states} states exceed the {len(_OKABE_ITO)} colour-blind-safe colours available")
    return _OKABE_ITO[:n_states]


def _state_legend(state_names: list[str], with_unobserved: bool) -> list[Patch]:
    cols = _state_colours(len(state_names))
    handles = [Patch(facecolor=c, label=_pretty(n)) for c, n in zip(cols, state_names)]
    if with_unobserved:
        handles += [Patch(facecolor=_MISSING_COLOUR, label="missing"), Patch(facecolor=_LOST_COLOUR, label="lost")]
    return handles


def _plot_codes(states: np.ndarray, K: int) -> np.ndarray:
    """States 0..K-1 keep their code, MISSING becomes K and LOST becomes K+1 (for the colour map)."""
    out = np.asarray(states).astype(np.int64).copy()
    out[out == MISSING] = K
    out[out == LOST] = K + 1
    return out


def _cmap(K: int) -> ListedColormap:
    return ListedColormap(_state_colours(K) + [_MISSING_COLOUR, _LOST_COLOUR])


def _labels_ok(labels: Any, n: int) -> np.ndarray:
    lab = np.asarray(labels)
    if lab.ndim != 1 or lab.shape[0] != n:
        raise ValueError(f"labels must have one entry per individual ({n}), got shape {lab.shape}")
    lab = lab.astype(np.int64)
    if lab.min() < 0:
        raise ValueError("every individual needs a pathway label >= 0")
    return lab


def _need(df: Any, cols: set[str], what: str) -> None:
    if not isinstance(df, pd.DataFrame) or df.empty or not cols <= set(df.columns):
        raise ValueError(f"{what} must be a non-empty DataFrame with columns {sorted(cols)}")


# ---------------------------------------------------------------------------------------------
# State distribution and sequences
# ---------------------------------------------------------------------------------------------
def plot_state_distribution(td: TrajectoryData, cfg: Config, labels: Any = None) -> Figure:
    """Stacked bars: share of the OBSERVED individuals in each state at each visit.

    With `labels` (one pathway label per individual) there is one panel per pathway; without, one panel for
    everyone. Missing and lost cells are left out of the shares (see `plot_missingness`); the number observed at
    each visit is printed under the visit label.
    """
    K = len(td.state_names)
    groups = [("all individuals", np.ones(td.n, dtype=bool))]
    if labels is not None:
        lab = _labels_ok(labels, td.n)
        groups = [(f"P{p} (n={int((lab == p).sum())})", lab == p) for p in np.unique(lab)]
    ncols = min(3, len(groups))
    nrows = int(np.ceil(len(groups) / ncols))
    fig = _fig(4.2 * ncols + 1.8, 3.4 * nrows + 0.8)
    axes = fig.subplots(nrows, ncols, squeeze=False, sharey=True)
    cols = _state_colours(K)
    for ax, (title, m) in zip(axes.ravel(), groups):
        S = td.states[m]
        bottom = np.zeros(td.T)
        n_obs = (S >= 0).sum(axis=0)
        for j in range(K):
            share = np.where(n_obs > 0, (S == j).sum(axis=0) / np.maximum(n_obs, 1), 0.0)
            ax.bar(np.arange(td.T), share, bottom=bottom, color=cols[j], width=0.8, edgecolor="white", linewidth=0.4)
            bottom += share
        ax.set_xticks(np.arange(td.T), [f"{lbl}\nn={int(n)}" for lbl, n in zip(td.time_labels, n_obs)], fontsize=8)
        ax.set_ylim(0, 1)
        ax.set_title(title, fontsize=10, color=_INK)
    for ax in axes[:, 0]:
        ax.set_ylabel("share of observed individuals")
    for ax in axes.ravel()[len(groups):]:
        ax.set_visible(False)
    fig.legend(handles=_state_legend(list(td.state_names), False), loc="outside right center", title="state", frameon=False)
    return fig


def plot_sequence_index(td: TrajectoryData, cfg: Config, labels: Any, max_rows: int = 300) -> Figure:
    """Sequence-index plot: one row per individual, one column per visit, rows grouped by pathway.

    At most `max_rows` individuals are drawn (a reproducible random sample, `make_rng(cfg, "viz/sequence_index")`);
    inside a pathway rows are sorted by their state sequence so similar rows sit together. Grey is missing, dark
    grey is lost. Raises ValueError for bad labels or `max_rows` < 1.
    """
    if isinstance(max_rows, bool) or not isinstance(max_rows, (int, np.integer)) or max_rows < 1:
        raise ValueError(f"max_rows must be an integer >= 1, got {max_rows!r}")
    lab = _labels_ok(labels, td.n)
    K = len(td.state_names)
    idx = np.arange(td.n)
    if td.n > max_rows:
        idx = np.sort(make_rng(cfg, "viz/sequence_index").choice(td.n, size=int(max_rows), replace=False))
    codes = _plot_codes(td.states[idx], K)
    keys = [codes[:, t] for t in range(td.T - 1, -1, -1)] + [lab[idx]]
    order = np.lexsort(keys)                                   # primary key: label, then visit 1, 2, ...
    idx, codes, lab_s = idx[order], codes[order], lab[idx][order]
    fig = _fig(7.6, 6.2)
    ax = fig.subplots()
    ax.imshow(codes, cmap=_cmap(K), vmin=-0.5, vmax=K + 1.5, aspect="auto", interpolation="nearest")
    edges = np.flatnonzero(np.diff(lab_s)) + 0.5
    for e in edges:
        ax.axhline(e, color="white", linewidth=2.0)
    starts = np.r_[0, np.flatnonzero(np.diff(lab_s)) + 1]
    ends = np.r_[starts[1:], len(lab_s)]
    ax.set_yticks((starts + ends - 1) / 2.0, [f"P{int(lab_s[s])}\n({e - s})" for s, e in zip(starts, ends)], fontsize=8)
    ax.set_xticks(np.arange(td.T), td.time_labels, fontsize=8)
    ax.set_title(f"Sequence index: {len(idx)} of {td.n} individuals shown, grouped by pathway", fontsize=10, color=_INK)
    ax.set_ylabel("pathway (individuals shown)")
    fig.legend(handles=_state_legend(list(td.state_names), True), loc="outside right center", title="state", frameon=False)
    return fig


def plot_medoid_sequences(medoid_states: Any, state_names: list[str], cfg: Config, prevalence: Any = None) -> Figure:
    """One row per pathway: the medoid, a real trajectory, drawn as coloured cells labelled with the state.

    `prevalence` may be an array (one share per pathway), or the table from `pathway_prevalence` (the column
    `prevalence_unweighted` is used); it is printed beside each row. Raises ValueError for the wrong shapes.
    """
    M = np.asarray(medoid_states)
    if M.ndim != 2 or M.shape[0] < 1:
        raise ValueError("medoid_states must be a 2-D array with one row per pathway")
    K = len(state_names)
    k, T = M.shape
    prev = None
    if prevalence is not None:
        if isinstance(prevalence, pd.DataFrame):
            _need(prevalence, {"pathway", "prevalence_unweighted"}, "prevalence")
            prev = prevalence.sort_values("pathway")["prevalence_unweighted"].to_numpy(dtype=float)
        else:
            prev = np.asarray(prevalence, dtype=float)
        if prev.shape != (k,):
            raise ValueError(f"prevalence must have {k} entries, got shape {prev.shape}")
    fig = _fig(1.7 * T + 2.6, 0.62 * k + 1.8)
    ax = fig.subplots()
    ax.imshow(_plot_codes(M, K), cmap=_cmap(K), vmin=-0.5, vmax=K + 1.5, aspect="auto", interpolation="nearest")
    for i in range(k):
        for t in range(T):
            v = int(M[i, t])
            txt = _pretty(state_names[v]) if v >= 0 else ("missing" if v == MISSING else "lost")
            ax.text(t, i, txt.replace(" ", "\n", 1) if len(txt) > 12 else txt, ha="center", va="center", fontsize=7,
                    color="white" if v in (0, 3, 4) or v == LOST else "black")
    ax.set_xticks(np.arange(T), cfg.time.labels[:T] if len(cfg.time.labels) >= T else [f"t{t}" for t in range(T)], fontsize=8)
    ax.set_yticks(np.arange(k), [f"P{i}" + (f"  {prev[i]:.1%}" if prev is not None else "") for i in range(k)], fontsize=8)
    ax.set_title("Medoid trajectory of each pathway (a real trainee, not an average)", fontsize=10, color=_INK)
    return fig


def plot_prevalence(prev_df: pd.DataFrame, cfg: Config) -> Figure:
    """Bar chart of pathway prevalence (share of individuals), with weighted prevalence as diamonds when it exists."""
    _need(prev_df, {"pathway", "n_individuals", "prevalence_unweighted"}, "prev_df")
    df = prev_df.sort_values("pathway")
    fig = _fig(6.4, 3.8)
    ax = fig.subplots()
    x = np.arange(len(df))
    ax.bar(x, df["prevalence_unweighted"], color=_OKABE_ITO[0], width=0.65, label="share of individuals")
    for xi, (p, n) in enumerate(zip(df["prevalence_unweighted"], df["n_individuals"])):
        ax.text(xi, p, f"{p:.1%}\nn={int(n)}", ha="center", va="bottom", fontsize=8)
    if "prevalence_weighted" in df.columns and df["prevalence_weighted"].notna().any():
        ax.plot(x, df["prevalence_weighted"], linestyle="none", marker="D", color=_OKABE_ITO[3], label="share of survey weight")
    ax.set_xticks(x, [f"P{int(p)}" for p in df["pathway"]])
    ax.set_ylim(0, float(max(df["prevalence_unweighted"].max(), df.get("prevalence_weighted", pd.Series([0.0])).max(skipna=True) or 0.0)) * 1.3 + 0.02)
    ax.set_ylabel("prevalence")
    ax.set_title("How common is each pathway?", fontsize=10, color=_INK)
    ax.legend(frameon=False, fontsize=8)
    return fig


# ---------------------------------------------------------------------------------------------
# Model selection, stability, baseline, missingness, silhouette
# ---------------------------------------------------------------------------------------------
def plot_k_selection(table: pd.DataFrame, cfg: Config, chosen_k: int | None = None) -> Figure:
    """Three panels against k: silhouette, stability ARI (with its threshold) and the smallest cluster's share (with its floor).

    The silhouette is never the only criterion (see `select_k`); `chosen_k` is marked with a dashed line.
    NaN rows (k not fitted) leave gaps. Raises ValueError for a table without the needed columns.
    """
    _need(table, {"k", "silhouette", "stability_ari_mean", "min_cluster_share"}, "table")
    t = table.sort_values("k")
    k = t["k"].to_numpy()
    fig = _fig(11.0, 3.6)
    axes = fig.subplots(1, 3)
    panels = [("silhouette", "silhouette (higher is better)", None, None),
              ("stability_ari_mean", "stability: ARI on subsamples", float(cfg.clustering.k_rule.min_stability_ari), "minimum accepted"),
              ("min_cluster_share", "share of individuals in the smallest cluster", float(cfg.clustering.min_cluster_frac), "floor")]
    for ax, (col, ylabel, ref, ref_label) in zip(axes, panels):
        ax.plot(k, t[col], marker="o", color=_OKABE_ITO[0])
        if col == "stability_ari_mean" and "stability_ari_sd" in t.columns:
            sd = t["stability_ari_sd"].fillna(0.0).to_numpy()
            ax.fill_between(k, t[col] - sd, t[col] + sd, color=_OKABE_ITO[0], alpha=0.15, linewidth=0)
        if ref is not None:
            ax.axhline(ref, color=_OKABE_ITO[3], linestyle=":", label=ref_label)
            ax.legend(frameon=False, fontsize=8)
        if chosen_k is not None:
            ax.axvline(chosen_k, color=_INK, linestyle="--", linewidth=1)
        ax.set_xticks(k)
        ax.set_xlabel("number of pathways, k")
        ax.set_ylabel(ylabel, fontsize=9)
    fig.suptitle("Choosing k" + (f" (chosen: k={chosen_k})" if chosen_k is not None else ""), fontsize=10, color=_INK)
    return fig


def plot_stability_curves(curves: pd.DataFrame, cfg: Config) -> Figure:
    """Agreement with the reference clustering when trainees are lost or follow-up is cut short.

    Top row: ARI (mean, 5th percentile and minimum over repeats). Bottom row: share of repeats in which each
    pathway survives (mean over pathways and the weakest pathway). Left: random and informative loss against the
    share lost; right: censoring against the visits kept. Raises ValueError for a table without the needed columns.
    """
    _need(curves, {"scheme", "level", "ari_mean", "ari_p05", "ari_min", "mean_pathway_survival", "min_pathway_survival"}, "curves")
    fig = _fig(10.5, 7.0)
    axes = fig.subplots(2, 2)
    styles = {"random": (_OKABE_ITO[0], "o"), "informative": (_OKABE_ITO[3], "s"), "censoring": (_OKABE_ITO[2], "^")}
    for col_i, schemes in enumerate((("random", "informative"), ("censoring",))):
        for s in schemes:
            d = curves[curves["scheme"] == s].sort_values("level")
            if d.empty:
                continue
            colour, marker = styles[s]
            x = d["level"].to_numpy()
            top, bot = axes[0, col_i], axes[1, col_i]
            top.plot(x, d["ari_mean"], marker=marker, color=colour, label=f"{s}: mean")
            top.plot(x, d["ari_p05"], linestyle=":", color=colour, label=f"{s}: 5th percentile")
            top.plot(x, d["ari_min"], linestyle="none", marker="x", color=colour, label=f"{s}: worst repeat")
            bot.plot(x, d["mean_pathway_survival"], marker=marker, color=colour, label=f"{s}: mean over pathways")
            bot.plot(x, d["min_pathway_survival"], linestyle="--", color=colour, label=f"{s}: weakest pathway")
        top, bot = axes[0, col_i], axes[1, col_i]
        top.set_ylim(min(0.0, float(np.nanmin(curves[["ari_min"]].to_numpy())) - 0.05) if np.isfinite(np.nanmin(curves[["ari_min"]].to_numpy())) else 0.0, 1.03)
        bot.set_ylim(-0.03, 1.03)
        top.set_ylabel("ARI with the reference clustering")
        bot.set_ylabel("share of repeats pathway survives")
        xlabel = "share of trainees lost" if col_i == 0 else f"visits kept (of {int(cfg.time.n_points)})"
        bot.set_xlabel(xlabel)
        top.set_xlabel(xlabel)
        if col_i == 1:
            ks = sorted(curves.loc[curves["scheme"] == "censoring", "level"].unique())
            for a in (top, bot):
                a.set_xticks(ks)
        top.legend(frameon=False, fontsize=7)
        bot.legend(frameon=False, fontsize=7)
    fig.suptitle("Stability under attrition and censoring", fontsize=10, color=_INK)
    return fig


def plot_baseline_vs_clusters(cmp: dict, cfg: Config) -> Figure:
    """Left: how each baseline class (employed or not at the reference visit) splits across the pathways (cell = share
    of the pathway, number = individuals). Right: purity of each pathway, the share of its members in its largest baseline class.

    A low purity means the pathway holds people the employed/not-employed split cannot tell apart: what the
    clustering adds. ARI and NMI from `compare_to_clustering` are printed in the title. Raises ValueError for a dict
    without a contingency table.
    """
    if not isinstance(cmp, dict) or "contingency" not in cmp or "by_pathway" not in cmp:
        raise ValueError("cmp must be the dict from compare_to_clustering (with 'contingency' and 'by_pathway')")
    c = cmp["contingency"]
    counts = np.asarray(c["counts"], dtype=float)
    rows, cols = [str(r) for r in c["rows"]], [int(x) for x in c["cols"]]
    colsum = counts.sum(axis=0)
    share = np.divide(counts, colsum[None, :], out=np.zeros_like(counts), where=colsum[None, :] > 0)
    fig = _fig(10.5, 3.9)
    ax1, ax2 = fig.subplots(1, 2, gridspec_kw={"width_ratios": [1.5, 1]})
    im = ax1.imshow(share, cmap="Blues", vmin=0, vmax=1, aspect="auto")
    for i in range(counts.shape[0]):
        for j in range(counts.shape[1]):
            ax1.text(j, i, f"{int(counts[i, j])}", ha="center", va="center", fontsize=8, color="white" if share[i, j] > 0.6 else _INK)
    ax1.set_xticks(np.arange(len(cols)), [f"P{p}" for p in cols])
    ax1.set_yticks(np.arange(len(rows)), [_pretty(r) for r in rows])
    ax1.set_title("baseline class (rows) by pathway (columns)", fontsize=9)
    fig.colorbar(im, ax=ax1, label="share of the pathway", shrink=0.8)
    bp = cmp["by_pathway"]
    ids = sorted(int(k) for k in bp)
    pur = [float(bp[str(i)]["purity"]) if str(i) in bp else float(bp[i]["purity"]) for i in ids]
    ax2.bar(np.arange(len(ids)), pur, color=_OKABE_ITO[0], width=0.65)
    ax2.axhline(1.0, color=_INK, linewidth=0.6)
    ax2.set_xticks(np.arange(len(ids)), [f"P{i}" for i in ids])
    ax2.set_ylim(0, 1.05)
    ax2.set_ylabel("purity (largest baseline class)")
    ax2.set_title("is the pathway just one baseline class?", fontsize=9)
    ari, nmi = cmp.get("ari"), cmp.get("nmi")
    fmt = lambda v: "n/a" if v is None or not np.isfinite(v) else f"{v:.2f}"   # noqa: E731
    fig.suptitle(f"Employed-vs-not baseline against the pathways (ARI {fmt(ari)}, NMI {fmt(nmi)}; {int(cmp.get('n_compared', 0))} compared)",
                 fontsize=10, color=_INK)
    return fig


def plot_missingness(report: dict, cfg: Config) -> Figure:
    """Left: share of cells observed, missing and lost at each visit. Right: how many trainees have 0..T observed visits,
    with the minimum needed to enter the analysis marked. Takes the dict from `audit_missingness`."""
    if not isinstance(report, dict) or "by_time" not in report or "observed_points_histogram" not in report:
        raise ValueError("report must be the dict from audit_missingness (with 'by_time' and 'observed_points_histogram')")
    bt = report["by_time"]
    mis = np.array([float(r["share_missing"]) for r in bt])
    lost = np.array([float(r["share_lost"]) for r in bt])
    x = np.arange(len(bt))
    fig = _fig(10.0, 3.8)
    ax1, ax2 = fig.subplots(1, 2)
    ax1.bar(x, 1 - mis - lost, color=_OKABE_ITO[0], width=0.65, label="observed")
    ax1.bar(x, mis, bottom=1 - mis - lost, color=_MISSING_COLOUR, width=0.65, label="missing")
    ax1.bar(x, lost, bottom=1 - lost, color=_LOST_COLOUR, width=0.65, label="lost")
    ax1.set_xticks(x, [r["time_label"] for r in bt], fontsize=8)
    ax1.set_ylim(0, 1)
    ax1.set_ylabel("share of trainees")
    ax1.set_title("status of each visit", fontsize=9)
    ax1.legend(frameon=False, fontsize=8, loc="lower left")
    hist = {int(k): int(v) for k, v in report["observed_points_histogram"].items()}
    ks = sorted(hist)
    ax2.bar(ks, [hist[k] for k in ks], color=_OKABE_ITO[0], width=0.65)
    ax2.axvline(float(cfg.trainee.min_time_points) - 0.5, color=_OKABE_ITO[3], linestyle="--", label=f"minimum to enter: {int(cfg.trainee.min_time_points)}")
    ax2.set_xticks(ks)
    ax2.set_xlabel("observed visits per trainee")
    ax2.set_ylabel("trainees")
    ax2.set_title("how many visits does each trainee have?", fontsize=9)
    ax2.legend(frameon=False, fontsize=8)
    return fig


def plot_silhouette(per_unit: Any, labels: Any, sample_weight: Any, cfg: Config) -> Figure:
    """Silhouette plot: each pathway is a block of bars, one per unit, sorted within the pathway; a bar's thickness is
    the number of individuals it stands for (`sample_weight`, 1 each if None). The dashed line is the weighted mean.
    Raises ValueError for arrays of different lengths or negative labels."""
    s = np.asarray(per_unit, dtype=np.float64)
    lab = np.asarray(labels).astype(np.int64)
    if s.ndim != 1 or lab.shape != s.shape or s.size == 0:
        raise ValueError("per_unit and labels must be one-dimensional arrays of the same length")
    if lab.min() < 0:
        raise ValueError("labels must be >= 0")
    w = np.ones_like(s) if sample_weight is None else np.asarray(sample_weight, dtype=np.float64)
    if w.shape != s.shape or np.any(w < 0) or w.sum() <= 0:
        raise ValueError("sample_weight must be non-negative, positive in total, and the same length as per_unit")
    fig = _fig(6.4, 5.4)
    ax = fig.subplots()
    gap = 0.02 * w.sum()
    y0, mids, names = 0.0, [], []
    for c in np.unique(lab):
        m = np.flatnonzero(lab == c)
        o = m[np.argsort(s[m], kind="stable")]
        ax.barh(y0 + np.cumsum(w[o]) - w[o], s[o], height=w[o], align="edge", color=_OKABE_ITO[0], linewidth=0)
        mids.append(y0 + w[o].sum() / 2.0)
        names.append(f"P{int(c)}")
        y0 += w[o].sum() + gap
    mean = float((w * s).sum() / w.sum())
    ax.axvline(mean, color=_OKABE_ITO[3], linestyle="--", label=f"weighted mean {mean:.2f}")
    ax.axvline(0.0, color=_INK, linewidth=0.6)
    ax.set_yticks(mids, names)
    ax.set_xlim(-1.0, 1.0)
    ax.set_xlabel("silhouette")
    ax.set_title("Silhouette by pathway", fontsize=10, color=_INK)
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    return fig


# ---------------------------------------------------------------------------------------------
# Stamp and save
# ---------------------------------------------------------------------------------------------
def stamp_synthetic(fig: Figure, is_synthetic: bool) -> Figure:
    """Mark a figure as synthetic: a red line under it and a faint diagonal watermark. Does nothing if `is_synthetic`
    is False, and stamping twice adds nothing the second time. Returns the same figure."""
    if not is_synthetic or getattr(fig, "_synthetic_stamped", False):
        return fig
    fig.supxlabel(SYNTHETIC_STAMP, color="#B00020", fontsize=9, fontweight="bold")
    fig.text(0.5, 0.5, "SYNTHETIC", ha="center", va="center", rotation=30, fontsize=64, color="#B00020", alpha=0.10, fontweight="bold")
    fig._synthetic_stamped = True
    return fig


def save_figure(fig: Figure, name: str, cfg: Config, is_synthetic: bool = False) -> Path:
    """Save `fig` as `<paths.figures_dir>/<name>__<tag>.png` (150 dpi) and return the path.

    The tag is SYNTHETIC or real (as for the results files). Synthetic figures are stamped first. `name` may contain
    only letters, digits, underscore and hyphen, so it cannot point outside the figures folder. Raises ValueError otherwise.
    """
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise ValueError(f"figure name {name!r} may contain only letters, digits, '_' and '-'")
    stamp_synthetic(fig, is_synthetic)
    out_dir = resolve_path(cfg, "figures_dir")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}__{'SYNTHETIC' if is_synthetic else 'real'}.png"
    fig.savefig(path, dpi=150, format="png")
    return path


# ---------------------------------------------------------------------------------------------
# Smoke demo
# ---------------------------------------------------------------------------------------------
def _cfg_with(cfg: Config, section: str, **values: Any) -> Config:
    d = cfg.to_dict()
    return Config({**d, section: {**d[section], **values}}, cfg.root)


def _demo() -> int:
    import json
    import tempfile
    import warnings

    from .baseline import baseline_partition, compare_to_clustering
    from .clustering import cluster_full
    from .distances import build_distance, plan_reduction, substitution_cost_matrix
    from .evaluation import silhouette_precomputed
    from .missing_data import audit_missingness
    from .preprocessing import apply_eligibility
    from .profiling import pathway_prevalence
    from .stability import k_selection_table, select_k, stability_tables
    from .synthetic_data import generate_synthetic
    from .trajectories import build_trajectories

    cfg = load_config()
    print("SYNTHETIC DEMONSTRATION - NOT PLFS RESULTS")
    warnings.simplefilter("ignore", UserWarning)

    def raises(exc: type, fn: Any) -> bool:
        try:
            fn()
        except exc:
            return True
        except Exception:
            return False
        return False

    df, truth = generate_synthetic(cfg, n=900, seed_offset=81)
    td = apply_eligibility(build_trajectories(df, cfg), cfg)
    K = len(td.state_names)
    plan = plan_reduction(td, cfg, make_rng(cfg, "viz-plan"))
    sub = substitution_cost_matrix(td, cfg)
    D = build_distance(plan.col_fit, cfg, sub)
    ref = cluster_full(plan, D, cfg, 6, make_rng(cfg, "viz-ref"), sub)
    cfg_fast = _cfg_with(_cfg_with(cfg, "clustering", k_stability_repeats=2, k_candidates=[2, 3, 4]), "stability", n_repeats=2, random_loss=[0.1, 0.3], censor_points=[3, 2])
    tab = k_selection_table(plan, D, cfg_fast, make_rng(cfg, "viz-k"))
    k_chosen, _ = select_k(tab, cfg_fast)
    curves, _ = stability_tables(td, cfg_fast, ref)
    base = baseline_partition(td, cfg)
    cmp = compare_to_clustering(base, ref.full_labels, td, cfg)
    rep = audit_missingness(td, cfg)
    prev = pathway_prevalence(td, ref.full_labels)
    sil_mean, sil_units = silhouette_precomputed(D, ref.fit_result.labels, plan.col_fit.freq.astype(float))

    figs = {
        "state_all": plot_state_distribution(td, cfg),
        "state_by_pathway": plot_state_distribution(td, cfg, ref.full_labels),
        "sequence": plot_sequence_index(td, cfg, ref.full_labels, max_rows=200),
        "medoids": plot_medoid_sequences(ref.medoid_states, td.state_names, cfg, prev),
        "prevalence": plot_prevalence(prev, cfg),
        "k_selection": plot_k_selection(tab, cfg_fast, k_chosen),
        "stability": plot_stability_curves(curves, cfg_fast),
        "baseline": plot_baseline_vs_clusters(cmp, cfg),
        "missingness": plot_missingness(rep, cfg),
        "silhouette": plot_silhouette(sil_units, ref.fit_result.labels, plan.col_fit.freq, cfg),
    }
    for f in figs.values():
        f.canvas.draw()

    def px(fig: Figure) -> np.ndarray:
        fig.canvas.draw()
        return np.asarray(fig.canvas.buffer_rgba()).copy()

    # data behind the pictures
    ax_seq = figs["sequence"].axes[0]
    seq_img = ax_seq.images[0].get_array()
    seq_again = plot_sequence_index(td, cfg, ref.full_labels, max_rows=200)
    med_img = figs["medoids"].axes[0].images[0].get_array()
    ax_all = figs["state_all"].axes[0]
    share_cols = np.array([[p.get_height() for p in ax_all.patches if abs(p.get_x() + p.get_width() / 2 - t) < 1e-9] for t in range(td.T)])
    ax_k = figs["k_selection"].axes[0]
    ax_sil = figs["silhouette"].axes[0]
    mean_line = [l for l in ax_sil.lines if len(l.get_xdata()) == 2 and l.get_xdata()[0] == l.get_xdata()[1] and l.get_xdata()[0] != 0.0][0].get_xdata()[0]
    base_img = figs["baseline"].axes[0].images[0].get_array()
    cnt = np.asarray(cmp["contingency"]["counts"], dtype=float)

    tmp = Path(tempfile.mkdtemp(prefix="viz_demo_"))
    cfg_tmp = _cfg_with(cfg, "paths", figures_dir=str(tmp))
    fig_syn = plot_prevalence(prev, cfg)
    p_syn = save_figure(fig_syn, "prevalence", cfg_tmp, is_synthetic=True)
    fig_real = plot_prevalence(prev, cfg)
    p_real = save_figure(fig_real, "prevalence", cfg_tmp, is_synthetic=False)
    before = px(plot_prevalence(prev, cfg))
    f_twice = stamp_synthetic(stamp_synthetic(plot_prevalence(prev, cfg), True), True)
    n_texts_twice = len(f_twice.texts)
    f_once = stamp_synthetic(plot_prevalence(prev, cfg), True)
    one_cluster = plot_state_distribution(td, cfg, np.zeros(td.n, dtype=int))
    tab_nan = tab.copy()
    tab_nan.loc[tab_nan.index[0], ["silhouette", "stability_ari_mean", "min_cluster_share"]] = np.nan
    prev_nan = prev.copy()
    prev_nan["prevalence_weighted"] = np.nan
    cmp_none = {**cmp, "ari": None, "nmi": None}
    png = p_syn.read_bytes()[:8]

    checks = {
        "every plot returns a Figure and draws without error": all(isinstance(f, Figure) for f in figs.values()) and len(figs) == 10,
        "state distribution: bar heights equal the shares of observed individuals and sum to 1": bool(np.allclose(share_cols.sum(axis=1), 1.0))
            and bool(np.allclose(share_cols[0], [(td.states[:, 0] == j).sum() / (td.states[:, 0] >= 0).sum() for j in range(K)])),
        "state distribution: one panel per pathway with labels, one panel without": len([a for a in figs["state_by_pathway"].axes if a.get_visible() and a.patches]) == 6
            and len([a for a in figs["state_all"].axes if a.patches]) == 1,
        "sequence index: draws exactly max_rows individuals, grouped by pathway, with MISSING and LOST colour codes": seq_img.shape == (200, td.T)
            and int(seq_img.max()) <= K + 1 and np.all(np.diff(sorted(set(np.asarray(ax_seq.get_yticks()))) ) > 0),
        "sequence index is reproducible (same sample, same picture)": np.array_equal(seq_img, seq_again.axes[0].images[0].get_array())
            and np.array_equal(px(figs["sequence"]), px(seq_again)),
        "sequence index shows everyone when n <= max_rows": plot_sequence_index(td, cfg, ref.full_labels, max_rows=5000).axes[0].images[0].get_array().shape[0] == td.n,
        "medoid plot: cells equal the medoid states (every medoid fully observed)": np.array_equal(med_img, np.asarray(ref.medoid_states)) and int(med_img.max()) < K,
        "k selection plot: silhouette line equals the table and the chosen k is marked": np.allclose(ax_k.lines[0].get_ydata(), tab["silhouette"], equal_nan=True)
            and any(len(l.get_xdata()) == 2 and np.allclose(l.get_xdata(), [k_chosen, k_chosen]) for l in ax_k.lines),
        "silhouette plot: the dashed mean equals the frequency-weighted mean silhouette": abs(mean_line - sil_mean) < 1e-9,
        "baseline plot: heatmap equals the contingency table shares by pathway": np.allclose(base_img, cnt / cnt.sum(axis=0, keepdims=True)),
        "stability plot: curves in two columns, ARI and survival rows": len(figs["stability"].axes) == 4,
        "gaps and missing values still draw (NaN table row, no weighted prevalence, ARI None, one pathway)": all(isinstance(f, Figure) for f in (
            plot_k_selection(tab_nan, cfg_fast), plot_prevalence(prev_nan, cfg), plot_baseline_vs_clusters(cmp_none, cfg), one_cluster))
            and not figs["k_selection"].axes[0].lines[0].get_ydata().tolist() == [],
        "stamp: synthetic figures get the banner and the watermark, real figures are untouched": any("SYNTHETIC" in t for t in [x.get_text() for x in f_once.texts])
            and "SYNTHETIC DEMONSTRATION - NOT PLFS RESULTS" in f_once._supxlabel.get_text() and not np.array_equal(before, px(f_once)) and np.array_equal(before, px(stamp_synthetic(plot_prevalence(prev, cfg), False))),
        "stamp twice adds nothing the second time": len(f_twice.texts) == len(f_once.texts) == n_texts_twice,
        "save_figure: tagged file names, valid PNG, the synthetic file differs from the real one": p_syn.name == "prevalence__SYNTHETIC.png" and p_real.name == "prevalence__real.png"
            and png == b"\x89PNG\r\n\x1a\n" and p_syn.stat().st_size > 0 and p_syn.read_bytes() != p_real.read_bytes() and p_syn.parent == tmp.resolve(),
        "save_figure refuses names that could leave the figures folder": all(raises(ValueError, lambda n=n: save_figure(plot_prevalence(prev, cfg), n, cfg_tmp)) for n in ("../x", "a/b", "", "a.png", "a b")),
        "bad input raises": raises(ValueError, lambda: plot_sequence_index(td, cfg, ref.full_labels[:-1])) and raises(ValueError, lambda: plot_sequence_index(td, cfg, ref.full_labels, max_rows=0))
            and raises(ValueError, lambda: plot_medoid_sequences(np.array([1, 2, 3]), td.state_names, cfg)) and raises(ValueError, lambda: plot_medoid_sequences(ref.medoid_states, td.state_names, cfg, prevalence=[0.5]))
            and raises(ValueError, lambda: plot_prevalence(pd.DataFrame({"x": [1]}), cfg)) and raises(ValueError, lambda: plot_baseline_vs_clusters({}, cfg))
            and raises(ValueError, lambda: plot_missingness({}, cfg)) and raises(ValueError, lambda: plot_silhouette([0.1, 0.2], [0, 1, 1], None, cfg))
            and raises(ValueError, lambda: plot_stability_curves(pd.DataFrame({"scheme": ["random"]}), cfg)),
        "state colours are fixed: one colour per state, MISSING and LOST are greys": len(set(_state_colours(K))) == K and _MISSING_COLOUR != _LOST_COLOUR
            and raises(ConfigError, lambda: _state_colours(8)),
        "the stamp text is JSON-safe plain text": bool(json.dumps(SYNTHETIC_STAMP)),
    }
    for name, ok in checks.items():
        print(f"  demo check [{'ok' if ok else 'FAILED'}]: {name}")
    print(f"  figures written to {tmp}: {sorted(p.name for p in tmp.iterdir())}")
    if not all(checks.values()):
        return 1
    print(f"Demo checks passed ({len(checks)}). All data above is SYNTHETIC or hand-built.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_demo())
