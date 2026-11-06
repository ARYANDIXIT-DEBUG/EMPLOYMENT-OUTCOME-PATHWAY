"""Dashboard: read-only view of the saved results and figures.

Why this file exists: the report is for reading once; the dashboard is for exploring. It shows the pathways, how they
compare with the employed-versus-not baseline, how stable they are and what the analysis cannot say, using ONLY the
files `run_pipeline.py` saved in `reports/results/` and `reports/figures/`. It computes nothing statistical and
fits nothing, so whatever it shows can be traced to a results file, and it cannot disagree with the report.

Run it from the project folder:
    python run_pipeline.py --synthetic        # once, to create results (synthetic data, pipeline test only)
    streamlit run dashboard/app.py
    python dashboard/app.py --self-test       # tests of this file (needs streamlit; takes about a minute)

Design choices worth defending in a viva:
  * One tag at a time. If both SYNTHETIC and real results exist, a sidebar choice picks one (real is the default) and
    the two are never mixed on a page. A SYNTHETIC page opens with the configured banner in red.
  * A missing result never crashes a page: that section says which pipeline stage creates it.
  * The wording of "who these people are" comes from `trainee.timing_support` (via the data summary): unless the
    questionnaire dates the training, the page says the data cannot show outcomes AFTER training, and it never uses
    causal words. The limits tab restates the main limits next to the numbers, not in a footnote.
  * Plots that can be drawn from results alone (choosing k, stability, prevalence, baseline, missingness) are drawn
    live with `visualization`; the others (sequence index, medoids, state distribution, silhouette) are the PNG files
    the pipeline saved, because they need the trajectories themselves.
  * Pure helper functions hold all the preparation (formatting, tables, wording), so they are tested without a browser.

Limits: the dashboard shows the last pipeline run, not a live analysis; rerun the pipeline to refresh it.

Dependency rule: imports `config`, `report_builder` and `visualization`. The self-test also imports `run_pipeline`.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import Config, load_config, resolve_path                     # noqa: E402
from src.report_builder import load_results                                  # noqa: E402
from src.visualization import (plot_baseline_vs_clusters, plot_k_selection, plot_missingness, plot_prevalence,   # noqa: E402
                               plot_stability_curves, stamp_synthetic)

TAB_NAMES = ["Overview", "Data quality", "Choosing k", "Pathways", "Versus the baseline", "Stability and limits"]
SYNTHETIC, REAL = "SYNTHETIC", "real"


# ---------------------------------------------------------------------------------------------
# Pure helpers (no streamlit)
# ---------------------------------------------------------------------------------------------
def get_config() -> Config:
    """The project config, or the file named by the environment variable PATHWAYS_CONFIG."""
    path = os.environ.get("PATHWAYS_CONFIG")
    return load_config(path) if path else load_config(str(ROOT / "config.yaml"))


def available_tags(cfg: Config) -> list[str]:
    """Tags that have at least one results file, real first. Empty if the pipeline has not run."""
    out = []
    if load_results(cfg, False):
        out.append(REAL)
    if load_results(cfg, True):
        out.append(SYNTHETIC)
    return out


def fmt(v: Any, spec: str = ".3f") -> str:
    """Number to text; None or NaN is shown as n/a, never as a number."""
    if v is None or (isinstance(v, float) and v != v):
        return "n/a"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int, float)):
        return format(v, spec) if isinstance(v, float) else str(v)
    return str(v)


def wording_note(summary: dict[str, Any] | None) -> str:
    """What the people in the data are, from `trainee.timing_support`. Never claims more than the questionnaire dates."""
    if not summary:
        return "No data summary yet: run the pipeline."
    ts = str(summary.get("timing_support", "none"))
    base = "These are people who reported vocational training at some point in the data (an 'ever trained' definition)."
    if ts == "dated":
        return base + " The questionnaire dates the training, so outcomes after training can be described; they are still descriptive, not causal."
    if ts == "coarse_flag":
        return base + " The questionnaire gives only a coarse indication of timing, so outcomes after training cannot be separated reliably from earlier ones."
    return base + " The data do not say when the training happened relative to the visits, so nothing here describes outcomes after training, and nothing is causal."


def headline_items(r: dict[str, Any]) -> list[tuple[str, str]]:
    """(label, text) pairs for the overview, only for results that exist."""
    h = r.get("headline")
    if not h:
        return []
    items = [("Trainees analysed", fmt(h.get("n_individuals"), "d")), ("Pathways (k)", fmt(h.get("k"), "d")),
             ("Silhouette", fmt(h.get("silhouette"), ".2f")), ("Min. cluster share", fmt(h.get("min_cluster_share"), ".1%")),
             ("Stability at 40% loss (ARI)", fmt(h.get("stability_random_40pct_ari"), ".2f")),
             ("Baseline agreement (ARI)", fmt(h.get("baseline_ari"), ".2f"))]
    return items


def pathway_table(r: dict[str, Any]) -> pd.DataFrame:
    """One row per pathway: name, size, share, medoid sequence, employed share at first and last visit, stable share."""
    prof, clus = r.get("profiles"), r.get("clustering")
    if not prof or not clus:
        return pd.DataFrame()
    med = {m["pathway"]: m for m in clus["medoids"]}
    rows = []
    for p, b in sorted(prof["by_pathway"].items(), key=lambda kv: int(kv[0])):
        rows.append({"pathway": b["name"], "individuals": b["n_individuals"], "share": b["prevalence"],
                     "medoid (a real trainee)": " > ".join(s.replace("_", " ") for s in med[int(p)]["states"]),
                     "employed at first visit": b["employed_first"], "employed at last visit": b["employed_last"],
                     "members who never change state": b["share_stable"]})
    return pd.DataFrame(rows)


def composition_pivot(r: dict[str, Any], pathway: int) -> pd.DataFrame:
    """Share of the pathway's observed members in each state at each visit (rows = visits, columns = states)."""
    comp = r.get("profiles", {}).get("composition")
    if not comp:
        return pd.DataFrame()
    df = pd.DataFrame(comp)
    df = df[df["pathway"] == int(pathway)]
    piv = df.pivot(index="time", columns="state", values="share_of_observed").fillna(0.0)
    labels = df.drop_duplicates("time").set_index("time")["time_label"]
    piv.index = [labels[t] for t in piv.index]
    return piv


def attribute_columns(row: dict[str, Any]) -> dict[str, Any]:
    """The attribute statistics of one profile row (columns holding `__` or `=`); empty if no attributes are permitted."""
    return {k: v for k, v in row.items() if ("__" in k or "=" in k)}


def like_for_like_table(r: dict[str, Any]) -> pd.DataFrame:
    """Silhouette and smallest cluster share of the baseline, k-medoids at the baseline's k, and the pathways, on the same units."""
    b = r.get("baseline")
    if not b or "like_for_like" not in b:
        return pd.DataFrame()
    ll = b["like_for_like"]
    names = {"baseline": "employed vs not (baseline)", "clustering_same_k_as_baseline": "k-medoids, same number of groups",
             "pathways_same_units": "pathways (chosen k)"}
    rows = []
    for key, label in names.items():
        e = ll.get(key)
        if e:
            rows.append({"partition": label, "groups": e["n_clusters"], "silhouette": e["silhouette"]["overall"], "smallest group share": e["min_cluster_share"]})
    return pd.DataFrame(rows)


def hidden_pathways_table(r: dict[str, Any]) -> pd.DataFrame:
    """For each baseline class: how many individuals, how many pathways it holds in meaningful share, and which."""
    b = r.get("baseline")
    if not b:
        return pd.DataFrame()
    rows = []
    for cls, v in b["comparison"]["by_class"].items():
        rows.append({"baseline class": cls.replace("_", " "), "individuals": v["n"], "pathways it contains (effective number)": v["effective_n_pathways"],
                     "pathways with a meaningful share": ", ".join(f"P{p}" for p in v["hidden_pathways"]) if v["hidden_pathways"] else "none"})
    return pd.DataFrame(rows)


def stability_table(r: dict[str, Any]) -> pd.DataFrame:
    s = r.get("stability")
    if not s:
        return pd.DataFrame()
    df = pd.DataFrame([{"setting": k, **v} for k, v in s["by_setting"].items()])
    return df[["setting", "n_retained_mean", "ari_mean", "ari_p05", "ari_min", "mean_pathway_survival", "min_pathway_survival"]]


def limits(cfg: Config, r: dict[str, Any]) -> list[str]:
    """The limits that always sit beside the numbers (text only; numbers come from the results)."""
    s = r.get("data_summary") or {}
    nt = s.get("n_time_points")
    out = [wording_note(s),
           (f"There are only {nt} visits per person, so a 'pathway' here is a short-run pattern over a short window, not a career." if nt else
            "The number of visits per person is small, so a 'pathway' is a short-run pattern, not a career."),
           "Pathways are descriptive. Sex, social group and religion are never used to form them; they are shown, where permitted, only to see who is in each pathway.",
           f"Missing visits are handled by '{s.get('missing_policy', 'pairwise_available')}' (a pair of people is compared on the visits both have). "
           "The missing-data table below repeats the analysis under other policies.",
           "The employed-versus-not baseline is built from the same trajectories that are clustered, so agreement with it is not independent validation."]
    if s.get("is_synthetic"):
        out.append("This page shows SYNTHETIC data made to test the pipeline. Recovering the planted structure shows the code works; it says nothing about real trainees.")
    return out


# ---------------------------------------------------------------------------------------------
# Streamlit page
# ---------------------------------------------------------------------------------------------
def _png(cfg: Config, name: str, tag: str) -> Path | None:
    p = resolve_path(cfg, "figures_dir") / f"{name}__{tag}.png"
    return p if p.is_file() else None


def _missing(st: Any, what: str, stage: str) -> None:
    st.info(f"{what} is not available yet. It is created by the `{stage}` stage: run `python run_pipeline.py --stage {stage}` (or the whole pipeline).")


def _live(st: Any, fig: Any, tag: str) -> None:
    stamp_synthetic(fig, tag == SYNTHETIC)
    st.pyplot(fig)


def _image(st: Any, cfg: Config, name: str, tag: str, caption: str) -> None:
    p = _png(cfg, name, tag)
    if p is None:
        _missing(st, f"The figure '{name}'", "report")
    else:
        st.image(str(p), caption=caption)


def render_overview(st: Any, cfg: Config, r: dict[str, Any], tag: str) -> None:
    st.write(wording_note(r.get("data_summary")))
    items = headline_items(r)
    if items:
        cols = st.columns(len(items))
        for c, (lab, val) in zip(cols, items):
            c.metric(lab, val)
    else:
        _missing(st, "The headline numbers", "report")
    k = r.get("k_selection")
    if k:
        st.caption(f"How k was chosen: {k['reason']}")
    pt = pathway_table(r)
    if pt.empty:
        _missing(st, "The pathway table", "profile")
    else:
        st.subheader("The pathways")
        st.dataframe(pt, hide_index=True, column_config={"share": st.column_config.NumberColumn(format="%.3f")})


def render_quality(st: Any, cfg: Config, r: dict[str, Any], tag: str) -> None:
    m = r.get("missingness")
    if not m:
        _missing(st, "The missing-data audit", "audit")
        return
    _live(st, plot_missingness(m, cfg), tag)
    c = m["cells"]
    st.write(f"Of {m['n_cells']} person-visit cells, {fmt(c['share_observed'], '.1%')} are observed, {fmt(c['share_missing'], '.1%')} missing and "
             f"{fmt(c['share_lost'], '.1%')} lost to follow-up. {fmt(m['share_complete_cases'], '.1%')} of trainees are observed at every visit.")
    d = m["dropout"]
    st.write(f"Dropout pattern: {d['n_monotone_dropout']} trainees drop out for good, {d['n_intermittent']} have gaps and later return, "
             f"{d['n_unobserved_at_first_point']} are unobserved at the first visit.")
    st.write(f"Tests of whether missingness depends on observed information: {m['verdict']}")
    st.caption(m["limits"])


def render_k(st: Any, cfg: Config, r: dict[str, Any], tag: str) -> None:
    k = r.get("k_selection")
    if not k:
        _missing(st, "The k-selection table", "cluster")
        return
    tab = pd.DataFrame(k["table"])
    _live(st, plot_k_selection(tab, cfg, k["chosen_k"]), tag)
    st.write(k["reason"])
    cols = [c for c in ("k", "silhouette", "stability_ari_mean", "min_cluster_share", "n_small_clusters", "n_zero_distance_medoid_pairs", "n_candidate_units", "note") if c in tab.columns]
    st.dataframe(tab[cols], hide_index=True)
    st.caption("A k is admissible only if it is stable on subsamples, has no tiny cluster and wastes no medoid; the silhouette alone never decides.")


def render_pathways(st: Any, cfg: Config, r: dict[str, Any], tag: str) -> None:
    prof = r.get("profiles")
    if not prof:
        _missing(st, "The pathway profiles", "profile")
        return
    names = {int(p): n for p, n in prof["names"].items()}
    chosen = st.selectbox("Pathway", options=list(names), format_func=lambda p: names[p], key="pathway_choice")
    b = prof["by_pathway"][str(chosen)]
    c1, c2, c3 = st.columns(3)
    c1.metric("Individuals", fmt(b["n_individuals"], "d"))
    c2.metric("Share of trainees", fmt(b["prevalence"], ".1%"))
    c3.metric("Never change state", fmt(b["share_stable"], ".0%"))
    st.write(f"Most common state at each visit: {b['modal_path'].replace('_', ' ')}")
    st.write(f"Employed at the first visit: {fmt(b['employed_first'], '.0%')}; at the last visit: {fmt(b['employed_last'], '.0%')}.")
    piv = composition_pivot(r, chosen)
    if not piv.empty:
        st.bar_chart(piv)
        st.caption("Share of this pathway's observed members in each state at each visit. Missing and lost cells are not counted as states.")
    attrs = attribute_columns(b)
    if attrs:
        st.write("Who is in this pathway (permitted attributes only, descriptive):")
        st.dataframe(pd.DataFrame([attrs]).T.rename(columns={0: "value"}))
    else:
        st.caption("No attribute profiling: `profiling.permitted_vars` is empty (set it from docs/DATA_USE_ASSESSMENT.md).")
    prev = r.get("profiles", {}).get("prevalence")
    if prev:
        _live(st, plot_prevalence(pd.DataFrame(prev), cfg), tag)
    with st.expander("Medoid sequences, sequence index and state distribution (saved figures)"):
        for name, cap in (("medoid_sequences", "The medoid of each pathway: a real trainee."), ("sequence_index", "One row per trainee (a sample), grouped by pathway."),
                          ("state_distribution_by_pathway", "State shares at each visit, by pathway.")):
            _image(st, cfg, name, tag, cap)


def render_baseline(st: Any, cfg: Config, r: dict[str, Any], tag: str) -> None:
    b = r.get("baseline")
    if not b:
        _missing(st, "The baseline comparison", "evaluate")
        return
    cmp = b["comparison"]
    st.write(f"Baseline rule: {b['definition']['rule']}.")
    c1, c2, c3 = st.columns(3)
    c1.metric("Agreement (ARI)", fmt(cmp["ari"], ".2f"))
    c2.metric("Shared information (NMI)", fmt(cmp["nmi"], ".2f"))
    c3.metric("Pathways spanning both classes", f"{cmp['n_pathways_spanning_classes']} of {cmp['n_pathways']}")
    _live(st, plot_baseline_vs_clusters(cmp, cfg), tag)
    st.subheader("What the baseline hides")
    st.dataframe(hidden_pathways_table(r), hide_index=True)
    ll = like_for_like_table(r)
    if not ll.empty:
        st.subheader("Same units, same distance")
        st.dataframe(ll, hide_index=True)
        st.caption(b.get("like_for_like_note", ""))
    c = b["counts"]
    st.caption(f"Individuals: {c['n_eligible']} compared, {c['n_excluded']} excluded because the reference visit was unknown or lost "
               f"(missing {c['n_unknown_missing']}, lost {c['n_unknown_lost']}).")
    for note in cmp.get("notes", []):
        st.caption(note)
    sens = b.get("sensitivity") or {}
    if sens:
        st.subheader("Other baseline definitions")
        st.dataframe(pd.DataFrame([{"variant": k, "ari": v["ari"], "nmi": v["nmi"], "compared": v["n_compared"]} for k, v in sens.items()]), hide_index=True)


def render_stability(st: Any, cfg: Config, r: dict[str, Any], tag: str) -> None:
    s = r.get("stability")
    if not s:
        _missing(st, "The stability results", "stability")
    else:
        _live(st, plot_stability_curves(pd.DataFrame(s["curves"]), cfg), tag)
        st.dataframe(stability_table(r), hide_index=True)
        if s.get("quick"):
            st.warning(f"These stability numbers come from a --quick run ({s['n_repeats']} repeats per setting); they are rough.")
        st.caption("ARI compares each degraded run with the reference pathways on the people who remain. Censoring repeats differ only through random starts, "
                   "so their spread understates the uncertainty of a changed sample. A pathway 'survives' if some new medoid lies within "
                   f"{fmt(s['survival_max_dist'], '.2f')} of the visits of it.")
    h = r.get("hierarchical_comparison")
    if h:
        st.subheader("Comparison method (hierarchical, average linkage)")
        st.write(f"Agreement with k-medoids on the fit sample: ARI {fmt(h['ari_vs_kmedoids_fit_sample'], '.2f')}.")
        if "ari_hierarchical_vs_planted" in h:
            st.write(f"SYNTHETIC ONLY: agreement with the planted pathways, hierarchical {fmt(h['ari_hierarchical_vs_planted'], '.2f')} against "
                     f"k-medoids {fmt(h['ari_kmedoids_vs_planted'], '.2f')}.")
    ms = r.get("missing_sensitivity")
    if ms:
        st.subheader("Other ways of handling missing visits")
        df = pd.DataFrame(ms["table"])
        st.dataframe(df[[c for c in ("policy", "is_primary", "n_individuals", "silhouette", "ari_vs_primary_pathways", "error") if c in df.columns]], hide_index=True)
        st.caption(ms["note"])
    st.subheader("Limits")
    for line in limits(cfg, r):
        st.markdown(f"- {line}")
    meta = r.get("run_meta")
    if meta and any(meta["warnings"].values()):
        with st.expander("Warnings raised during the run"):
            for stage, msgs in meta["warnings"].items():
                for m in msgs:
                    st.write(f"[{stage}] {m}")


def main() -> None:
    import streamlit as st

    cfg = get_config()
    st.set_page_config(page_title="Employment pathways", layout="wide")
    st.title(str(cfg.dashboard.title))
    tags = available_tags(cfg)
    if not tags:
        st.warning("No results yet. Run `python run_pipeline.py --synthetic` (a pipeline test) or, once the data gate is passed, `python run_pipeline.py`.")
        return
    tag = tags[0]
    if len(tags) > 1:
        tag = st.sidebar.radio("Results to show", tags, index=0, help="Real and synthetic results are never shown together.")
    r = load_results(cfg, tag == SYNTHETIC)
    if tag == SYNTHETIC:
        st.error(str(cfg.dashboard.synthetic_banner))
    tabs = st.tabs(TAB_NAMES)
    for t, fn in zip(tabs, (render_overview, render_quality, render_k, render_pathways, render_baseline, render_stability)):
        with t:
            fn(st, cfg, r, tag)


# ---------------------------------------------------------------------------------------------
# Self-test (python dashboard/app.py --self-test)
# ---------------------------------------------------------------------------------------------
def _selftest() -> int:
    import tempfile

    import yaml
    from streamlit.testing.v1 import AppTest

    from run_pipeline import STAGES, run
    from src.report_builder import save_result

    print("SYNTHETIC DEMONSTRATION - NOT PLFS RESULTS")
    base = load_config(str(ROOT / "config.yaml"))
    d = base.to_dict()
    d["synthetic"]["n"] = 500
    tmp = Path(tempfile.mkdtemp(prefix="dashboard_selftest_"))
    (tmp / "config.yaml").write_text(yaml.safe_dump(d, sort_keys=False), encoding="utf-8")
    cfg = load_config(str(tmp / "config.yaml"))
    lines: list[str] = []
    code = run(cfg, list(STAGES), True, True, lines.append)
    os.environ["PATHWAYS_CONFIG"] = str(tmp / "config.yaml")
    app = str(ROOT / "dashboard" / "app.py")
    r = load_results(cfg, True)

    empty = tmp / "empty"
    empty.mkdir()
    d2 = dict(d)
    (empty / "config.yaml").write_text(yaml.safe_dump(d2, sort_keys=False), encoding="utf-8")

    at = AppTest.from_file(app, default_timeout=120).run()
    all_text = " ".join([m.value for m in at.markdown] + [e.value for e in at.error] + [c.value for c in at.caption] + [w.value for w in at.warning] + [i.value for i in at.info])
    pick = at.selectbox(key="pathway_choice")
    first_options = list(pick.options)
    at2 = pick.select(first_options[-1]).run()
    metrics = [m.label for m in at.metric]

    save_result("headline", {"is_synthetic": False, "n_individuals": 7, "k": 2, "silhouette": None, "min_cluster_share": 0.5}, cfg, False)
    at_both = AppTest.from_file(app, default_timeout=120).run()
    radio = at_both.sidebar.radio[0]
    only_real_text = " ".join([m.value for m in at_both.markdown] + [e.value for e in at_both.error] + [i.value for i in at_both.info])
    banner_real = any("SYNTHETIC DEMONSTRATION - NOT PLFS RESULTS" in e.value for e in at_both.error)    # read BEFORE switching: AppTest updates the same tree in place
    at_syn = radio.set_value(SYNTHETIC).run()
    banner_back = any("SYNTHETIC DEMONSTRATION - NOT PLFS RESULTS" in e.value for e in at_syn.error)

    os.environ["PATHWAYS_CONFIG"] = str(empty / "config.yaml")
    at_empty = AppTest.from_file(app, default_timeout=60).run()
    os.environ["PATHWAYS_CONFIG"] = str(tmp / "config.yaml")

    pt, comp = pathway_table(r), composition_pivot(r, 0)
    ll, hid, stab = like_for_like_table(r), hidden_pathways_table(r), stability_table(r)
    lim = limits(cfg, r)
    checks = {
        "the pipeline produced results to show (quick synthetic run, exit 0)": code == 0 and bool(r),
        "fmt: None and NaN are n/a, never numbers; percent and integer formats work": fmt(None) == "n/a" and fmt(float("nan")) == "n/a" and fmt(0.256, ".1%") == "25.6%" and fmt(5, "d") == "5" and fmt(True) == "yes",
        "wording: no timing means no claim about outcomes after training, dated allows it, never causal": "nothing here describes outcomes after training" in wording_note({"timing_support": "none"})
            and "dates the training" in wording_note({"timing_support": "dated"}) and "coarse" in wording_note({"timing_support": "coarse_flag"}) and "run the pipeline" in wording_note(None),
        "pathway_table: one row per pathway, shares sum to 1, medoid shown as a sequence": len(pt) == r["clustering"]["k"] and abs(pt["share"].sum() - 1.0) < 1e-9 and pt["medoid (a real trainee)"].str.contains(">").all(),
        "composition_pivot: shares of observed members sum to 1 at every visit": bool((comp.sum(axis=1).round(9) == 1.0).all()) and list(comp.index) == r["data_summary"]["time_labels"],
        "like_for_like_table and hidden_pathways_table have the expected rows": list(ll["partition"])[0] == "employed vs not (baseline)" and len(ll) == 3 and len(hid) == 2,
        "stability_table: one row per setting": len(stab) == 10 and {"random_40pct", "censoring_2visits"} <= set(stab["setting"]),
        "limits: includes the visit count from the results, the baseline caveat and the synthetic warning": any(str(r["data_summary"]["n_time_points"]) in l for l in lim)
            and any("not independent validation" in l for l in lim) and any("SYNTHETIC" in l for l in lim),
        "attribute_columns: finds profile attribute columns only": attribute_columns({"a__mean": 1, "sex=F": 0.5, "modal_path": "x"}) == {"a__mean": 1, "sex=F": 0.5},
        "app runs without an exception, with the required SYNTHETIC warning and six tabs": not at.exception and "SYNTHETIC DEMONSTRATION - NOT PLFS RESULTS" in all_text and len(at.tabs) == 6,
        "app shows the headline metrics and the pathway choice offers every pathway": len(metrics) >= 6 and len(first_options) == r["clustering"]["k"],
        "choosing another pathway reruns without an exception": not at2.exception,
        "real and synthetic results are never mixed: with both present the real page opens with no banner, the synthetic choice shows it": len(at_both.sidebar.radio) == 1
            and list(radio.options) == [REAL, SYNTHETIC] and not at_both.exception and not banner_real and banner_back and not at_syn.exception,
        "a page with missing results says which stage creates them instead of failing": "run_pipeline.py --stage" in only_real_text and not at_both.exception,
        "with no results at all the app says how to create them": not at_empty.exception and any("No results yet" in w.value for w in at_empty.warning),
    }
    for name, ok in checks.items():
        print(f"  self-test [{'ok' if ok else 'FAILED'}]: {name}")
    if not all(checks.values()):
        print("exceptions:", [e.value for e in at.exception], [e.value for e in at_both.exception], [e.value for e in at_empty.exception])
        return 1
    print(f"Self-test passed ({len(checks)}). All data above is SYNTHETIC (files in {tmp}).")
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
