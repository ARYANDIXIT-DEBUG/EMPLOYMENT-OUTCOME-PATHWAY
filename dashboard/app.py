"""Read-only dashboard for the Turkey CA and preserved PLFS/synthetic routes.

The primary panel reads saved Turkey aggregate outputs only and validates the
source hash recorded by `src.turkey_pipeline`. The separate PLFS views remain
behind their existing data gates. The legacy six-tab pathway explorer reads
saved `run_pipeline.py` results; it does not compute statistics or fit models.

Run from the project root:
    streamlit run dashboard/app.py
    python dashboard/app.py --self-test

The dashboard shows saved runs, not live analysis. Rerun the appropriate
pipeline to refresh results. Missing or stale inputs are reported explicitly.
"""
from __future__ import annotations

import os
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import Config, load_config, resolve_path                     # noqa: E402
from src.report_builder import load_results                                  # noqa: E402
from run_pipeline import GateError, check_data_gate                           # noqa: E402
from src.cross_sectional import CrossSectionError, check_cross_sectional_gate # noqa: E402
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
    """Saved-result tags available under the current gate; real is hidden unless the gate passes."""
    out = []
    if real_gate_status(cfg)[0] and load_results(cfg, False):
        out.append(REAL)
    if load_results(cfg, True):
        out.append(SYNTHETIC)
    return out


def real_gate_status(cfg: Config) -> tuple[bool, str]:
    """Return whether real results may be viewed and the gate's first blocking reason."""
    try:
        check_data_gate(cfg)
    except GateError as exc:
        return False, str(exc)
    return True, "All configured real-data gate checks pass."


def load_cross_sectional_saved(cfg: Config) -> tuple[dict[str, Any] | None, pd.DataFrame | None, pd.DataFrame | None, str]:
    """Load a validated saved first-visit summary and estimates; never recompute results."""
    try:
        check_cross_sectional_gate(cfg)
    except CrossSectionError as exc:
        return None, None, None, str(exc)
    root = cfg.root / "outputs" / "cross_sectional" / "real"
    summary_path, table_path = root / "cross_sectional_summary.json", root / "cws_estimates.csv"
    indicator_path = root / "employment_indicators.csv"
    figure_paths = [root / "cws_weighted_shares.png", root / "employment_indicators.png"]
    if not summary_path.is_file() or not table_path.is_file() or not indicator_path.is_file() or not all(p.is_file() for p in figure_paths):
        return None, None, None, "No saved cross-sectional real-data outputs are available."
    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        provenance = payload["provenance"]
        config_hash = hashlib.sha256((cfg.root / "config.yaml").read_bytes()).hexdigest()
        input_path = cfg.root / provenance["input_file"]
        input_hash = hashlib.sha256(input_path.read_bytes()).hexdigest()
        code_path = cfg.root / provenance["code_file"]
        code_hash = hashlib.sha256(code_path.read_bytes()).hexdigest()
        if payload.get("is_synthetic") is not False:
            raise ValueError("saved output is not marked as real data")
        if (provenance.get("config_sha256") != config_hash or provenance.get("input_sha256") != input_hash
                or provenance.get("code_sha256") != code_hash):
            raise ValueError("saved output hashes do not match the current config, input data and analysis code")
        table = pd.read_csv(table_path)
        indicators = pd.read_csv(indicator_path)
        if len(table) != 9 or set(table["sector"]) != {"all", "1", "2"}:
            raise ValueError("saved CWS estimate table has an unexpected shape")
        if len(indicators) != 3 or set(indicators["sector"]) != {"all", "1", "2"}:
            raise ValueError("saved employment-indicator table has an unexpected shape")
        return payload, table, indicators, "Saved cross-sectional output hashes match current inputs."
    except FileNotFoundError:
        return None, None, None, "Required source file is missing: data/raw/perv1.csv. The real PLFS view remains blocked until the authentic file is supplied."
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        message = str(exc).replace(str(cfg.root), "<project>").replace(str(cfg.root).replace("\\", "/"), "<project>")
        return None, None, None, f"Saved cross-sectional output is unavailable or stale: {message}"


def render_cross_section_saved(st: Any, cfg: Config) -> None:
    """Render saved annual CWS estimates behind the independent cross-sectional gate."""
    st.header("Cross-sectional first-visit PLFS estimates")
    payload, table, indicators, note = load_cross_sectional_saved(cfg)
    if payload is None or table is None or indicators is None:
        st.info(note)
        return
    st.success("REAL PLFS — cross-sectional descriptive analysis; no longitudinal linkage or clustering.")
    summary = payload["summary"]
    st.caption("Annual weighted estimates. Cohort: first-visit rural and urban respondents age 15–59 with b4q12=1. "
               "This is descriptive, not a post-training or causal estimate.")
    a, b, c = st.columns(3)
    a.metric("Eligible first-visit records", f"{summary['eligible_rows']:,}")
    b.metric("Rural records", f"{summary['eligible_by_sector'].get('1', 0):,}")
    c.metric("Urban records", f"{summary['eligible_by_sector'].get('2', 0):,}")
    view = table.copy().rename(columns={"sector": "Area", "cws_group": "Work status group", "n_unweighted": "People (unweighted)",
        "share_unweighted_known_cws": "Unweighted share among known CWS", "weighted_estimated_count": "Estimated people (weighted)",
        "share_weighted_known_cws": "Weighted share among known CWS"})
    view["Area"] = view["Area"].replace({"1": "Rural", "2": "Urban", "all": "Combined"})
    if "Estimated people (weighted)" in view:
        view["Estimated people (weighted)"] = view["Estimated people (weighted)"].map(lambda x: f"{x:,.0f}" if pd.notna(x) else "n/a")
    for col in ("Unweighted share among known CWS", "Weighted share among known CWS"):
        if col in view: view[col] = view[col].map(lambda x: f"{x:.1%}" if pd.notna(x) else "n/a")
    st.dataframe(view, width="stretch", hide_index=True)
    _download_table(st, table, "plfs_cross_sectional_cws_estimates.csv")
    indicator_view = indicators.copy().rename(columns={"sector": "Area", "n_unweighted": "People (unweighted)",
        "weighted_population_estimate": "Estimated population (weighted)", "wpr_weighted": "WPR", "lfpr_weighted": "LFPR", "ur_weighted": "UR"})
    indicator_view["Area"] = indicator_view["Area"].replace({"1": "Rural", "2": "Urban", "all": "Combined"})
    for col in ("WPR", "LFPR", "UR"):
        if col in indicator_view: indicator_view[col] = indicator_view[col].map(lambda x: f"{x:.1%}" if pd.notna(x) else "n/a")
    st.subheader("Employment indicators among the selected cohort")
    st.dataframe(indicator_view, width="stretch", hide_index=True)
    _download_table(st, indicators, "plfs_cross_sectional_employment_indicators.csv")
    st.image(str(cfg.root / "outputs" / "cross_sectional" / "real" / "cws_weighted_shares.png"),
             caption="Annual weighted CWS distribution; saved figure from the validated run.")
    st.image(str(cfg.root / "outputs" / "cross_sectional" / "real" / "employment_indicators.png"),
             caption="WPR, LFPR and UR; saved figure from the validated run.")
    st.caption("Weights: MULT / (100 if NSS=NSC else 200) / NO_QTR. "
               f"CWS missing/unclassified records retained: {summary['outcome_missing_rows'] + summary['outcome_unclassified_rows']}. "
               "No occupational or demographic profiles are shown. The person file has no nonresponse/casualty field, so response rates cannot be calculated here.")
    st.caption(note)


def _download_table(st: Any, frame: pd.DataFrame, filename: str, label: str = "Download complete CSV") -> None:
    st.download_button(label, frame.to_csv(index=False).encode("utf-8"), filename, "text/csv", key=f"download_{filename}")


def _nice_table(st: Any, frame: pd.DataFrame, filename: str, rename: dict[str, str] | None = None,
                percent: tuple[str, ...] = (), label: str = "Download complete CSV") -> None:
    """Show an appropriately sized table and retain access to every source column."""
    shown = frame.rename(columns=rename or {}).copy()
    for column in percent:
        if column in shown.columns:
            shown[column] = pd.to_numeric(shown[column], errors="coerce") * 100
    config = {c: st.column_config.NumberColumn(c, format="%.1f%%") for c in percent if c in shown.columns}
    st.dataframe(shown, width="stretch", hide_index=True, column_config=config)
    _download_table(st, frame, filename, label)


def _safe_csv(path: Path) -> pd.DataFrame | None:
    try:
        return pd.read_csv(path) if path.is_file() else None
    except (OSError, ValueError, pd.errors.ParserError):
        return None


def render_turkey_saved(st: Any, cfg: Config) -> None:
    """Show the primary, provenance-checked Turkey CA analysis and no other dataset."""
    root = cfg.root / "outputs" / "turkey"
    summary_path, table_path = root / "summary.json", root / "cluster_prevalence.csv"
    st.title("Employment Outcome Pathway Grouping After Skilling")
    st.subheader("INT396 | G24 | CA Project")
    st.caption("Historical Turkey ISKUR Vocational Training Evaluation (2010–2013)")
    if not summary_path.is_file() or not table_path.is_file():
        st.info("Validated Turkey results are not available. Run `python -m src.turkey_pipeline` from the project root.")
        return
    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        source = cfg.root / payload["input"]
        if hashlib.sha256(source.read_bytes()).hexdigest() != payload.get("input_sha256"):
            raise ValueError("Turkey source hash does not match the saved analysis")
        table = pd.read_csv(table_path)
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        st.warning(f"Turkey evaluation outputs are hidden because provenance validation failed: {str(exc).replace(str(cfg.root), '<project>')}")
        return
    st.divider()
    st.info("Descriptive analysis of a historical Turkish evaluation. These results do not represent India or Maharashtra and do not estimate a causal training effect.")
    cols = st.columns(5)
    cols[0].metric("Original applicants", f"{payload.get('n_rows', 0):,}")
    cols[1].metric("Valid pre-course interviews", f"{payload.get('baseline_comparison', {}).get('valid_pretraining_baseline_n', 0):,}")
    cols[2].metric("Complete attendee sequences", f"{payload.get('n_valid_post_training_trajectories', 0):,}")
    cols[3].metric("Selected pathways", payload.get("selected_k") or "n/a")
    cols[4].metric("Hamming silhouette", fmt(payload.get("silhouette_hamming"), ".3f"))
    st.markdown("**Sequence points:** pre-course any work → post-course any work → August 2013 formal Social Security employment. The final measure is narrower than the survey measures. Not working is not the same as unemployed.")
    st.subheader("Pathway prevalence and outcome profile")
    prevalence = table.copy()
    prevalence.insert(0, "Pathway", [f"Pathway {int(x)}" for x in prevalence["cluster_id"]])
    rate_cols = ["baseline_any_work_rate", "followup_any_work_rate", "aug2013_formal_work_rate"]
    if all(c in prevalence for c in rate_cols):
        chart = prevalence.set_index("Pathway")[rate_cols].rename(columns={
            "baseline_any_work_rate": "Pre-course any work", "followup_any_work_rate": "Post-course any work",
            "aug2013_formal_work_rate": "Aug 2013 formal work"}) * 100
        chart_cols = st.columns(3)
        for col, series in zip(chart_cols, chart.columns):
            col.caption(series)
            col.bar_chart(chart[[series]], height=250, x_label="Pathway", y_label="Percent (%)")
    short = prevalence[[c for c in ("Pathway", "n", "share_complete_pathways", "baseline_any_work_rate", "followup_any_work_rate", "aug2013_formal_work_rate", "trajectory_patterns") if c in prevalence]]
    _nice_table(st, short, "turkey_pathway_prevalence.csv", {
        "n": "People", "share_complete_pathways": "Cohort share", "baseline_any_work_rate": "Pre-course any work",
        "followup_any_work_rate": "Post-course any work", "aug2013_formal_work_rate": "Aug 2013 formal work",
        "trajectory_patterns": "Observed sequence patterns"}, ("Cohort share", "Pre-course any work", "Post-course any work", "Aug 2013 formal work"))
    st.caption("The four groups summarize the eight possible three-point binary sequences; the membership counts total 1,546.")
    st.subheader("Baseline comparison")
    baseline = _safe_csv(root / "baseline_employed_comparison.csv")
    if baseline is not None:
        base_view = baseline[[c for c in ("employment_baseline", "n", "postfollowup_any_work_share", "aug2013_formal_work_share") if c in baseline]].rename(columns={
            "employment_baseline": "Baseline status", "n": "People", "postfollowup_any_work_share": "Post-course any work", "aug2013_formal_work_share": "Aug 2013 formal work"})
        base_view["Baseline status"] = base_view["Baseline status"].map({0: "Not working", 1: "Worked at all"}).fillna(base_view["Baseline status"])
        _nice_table(st, base_view, "turkey_baseline_comparison.csv", percent=("Post-course any work", "Aug 2013 formal work"))
        _download_table(st, baseline, "turkey_baseline_comparison_complete.csv", "Download complete baseline table")
    st.caption(f"Comparison cohort: {payload.get('baseline_comparison', {}).get('valid_pretraining_baseline_n', 0):,} interviews dated before course start. 'Not working' includes people outside the labour force; it does not mean unemployed.")
    st.subheader("Attendance and course outcomes by pathway")
    operational = prevalence[[c for c in ("Pathway", "treatment_assigned_n", "attendance_evidence_n", "selection_reported_share", "completion_n", "completion_share_observed", "certificate_received_n", "certificate_share_observed") if c in prevalence]]
    operational = operational.rename(columns={"treatment_assigned_n": "Assigned to treatment", "attendance_evidence_n": "Attendance documented", "selection_reported_share": "Self-reported selection", "completion_n": "Completion known yes", "completion_share_observed": "Completed among known", "certificate_received_n": "Certificate known yes", "certificate_share_observed": "Certificate among known"})
    _nice_table(st, operational, "turkey_course_outcomes_by_pathway.csv", percent=tuple(c for c in ("Self-reported selection", "Completed among known", "Certificate among known") if c in operational))
    st.caption("Assignment, reported selection, documented attendance, completion and certificate receipt are distinct. Rates use their stated known/observed denominators.")
    st.subheader("Administrative employment indicators")
    admin = _safe_csv(root / "cluster_admin_profile.csv")
    if admin is not None:
        admin.insert(0, "Pathway", [f"Pathway {int(x)}" for x in admin["cluster_id"]])
        milestones = admin[[c for c in ("Pathway", "formal_entry_by_jan2012_share", "ever_formally_employed_postcourse_share", "first_job_left_by_nov2013_share", "formal_anytime_first8months2013_share") if c in admin]].rename(columns={
            "formal_entry_by_jan2012_share": "Formal job by Jan 2012", "ever_formally_employed_postcourse_share": "Ever formal job after course", "first_job_left_by_nov2013_share": "First job left by Nov 2013", "formal_anytime_first8months2013_share": "Formal job in Jan–Aug 2013 (cumulative)"})
        _nice_table(st, milestones, "turkey_admin_employment_milestones.csv", percent=tuple(c for c in milestones.columns if c != "Pathway"))
        income = admin[[c for c in ("Pathway", "aug2013_formal_income_median") if c in admin]].rename(columns={"aug2013_formal_income_median": "Median formal income, Aug 2013 (source currency)"})
        st.dataframe(income, width="stretch", hide_index=True, column_config={income.columns[-1]: st.column_config.NumberColumn(income.columns[-1], format="%.2f")})
        _download_table(st, income, "turkey_admin_income_median.csv")
    st.caption("The January–August 2013 indicator is cumulative; it is not an August point-in-time measure. No monthly job spells are present in this public-use file.")
    state = _safe_csv(root / "cluster_jan2012_state_profile.csv")
    if state is not None:
        st.subheader("January 2012 first formal-job state")
        state["Pathway"] = state["cluster_id"].map(lambda x: f"Pathway {int(x)}")
        state["State"] = state["admin_jan12_first_job_state"].map({"first_job_active_jan2012": "First formal job active", "first_job_left_by_jan2012": "First formal job already left", "no_formal_job_by_jan2012": "No formal job by Jan 2012"}).fillna(state["admin_jan12_first_job_state"])
        pivot = state.pivot(index="Pathway", columns="State", values="share_cluster").reset_index()
        _nice_table(st, pivot, "turkey_jan2012_state_profile.csv", percent=tuple(c for c in pivot.columns if c != "Pathway"))
        _download_table(st, state, "turkey_jan2012_state_profile_complete.csv", "Download complete January 2012 state table")
    st.subheader("Attrition and stability")
    st.write(f"Among {payload.get('attendee_baseline_cohort_n', 0):,} documented attendees with a valid pre-course baseline, {payload.get('attendee_with_verified_followup_n', 0):,} had verified post-course survey follow-up and {payload.get('attendee_followup_unknown_n', 0):,} had unknown follow-up.")
    bounds = payload.get("followup_work_extreme_bounds", {})
    if bounds:
        st.write(f"Extreme follow-up work-rate bounds: {bounds.get('lower', float('nan')):.1%}–{bounds.get('upper', float('nan')):.1%} (no outcomes imputed).")
    stability = payload.get("cluster_stability", {})
    st.caption(f"Mean ARI across {stability.get('replicates', 0)} deterministic 80% subsample refits: {fmt(stability.get('ari_mean'), '.3f')} (SD {fmt(stability.get('ari_sd'), '.3f')}). This is moderate resampling stability, not external validity.")
    method_path = root / "cluster_method_evaluation.csv"
    if method_path.is_file():
        methods = _safe_csv(method_path)
        with st.expander("Clustering candidate evaluation"):
            if methods is not None:
                methods = methods.rename(columns={"k": "Clusters (k)", "silhouette_hamming": "Hamming silhouette", "min_cluster_n": "Smallest pathway (people)", "min_cluster_share": "Smallest pathway (%)", "eligible_min_5pct": "Meets 5% minimum"})
                _nice_table(st, methods, "turkey_cluster_candidates.csv", percent=("Smallest pathway (%)",))
            st.caption("k=5 has a higher silhouette but its smallest cluster is below the predeclared 5% cohort-size floor, so k=4 is selected.")
    with st.expander("Full pathway profile and technical diagnostics"):
        _download_table(st, table, "turkey_cluster_prevalence_full.csv", "Download complete pathway table")
        for fname, label in (("cluster_admin_profile.csv", "Complete administrative profile by pathway"), ("cluster_gender_profile.csv", "Gender profile by pathway (descriptive)"), ("baseline_employment_by_cluster.csv", "Baseline work by pathway"), ("attrition_admin_comparison.csv", "Administrative outcomes by follow-up status")):
            data = _safe_csv(root / fname)
            if data is not None:
                st.markdown(f"**{label}**")
                _nice_table(st, data, f"turkey_{fname}")
    report = root / "cluster_profile_report.md"
    if report.is_file():
        with st.expander("Turkey methodology and limitations"):
            st.markdown(report.read_text(encoding="utf-8"))


def status_items(cfg: Config) -> list[tuple[str, str]]:
    """Readable legacy checkpoint/status explanations; raw machine codes stay internal."""
    raw = cfg.to_dict()
    data = raw.get("data", {})
    validation = raw.get("validation", {})
    trainee = raw.get("trainee", {})
    lost_status = str(raw.get("lost_codes_status", "unresolved")).lower()
    lost_count = len(raw.get("lost_codes") or [])
    permission = str(data.get("b4q12_permission_status", "unresolved")).lower()
    timing = str(trainee.get("timing_support", "none")).lower()
    evidence = str((trainee.get("timing_evidence") or {}).get("status", "unverified")).lower()
    requested_weighted = bool(raw.get("profiling", {}).get("weighted", False))
    weight_text = ("weighted requested; longitudinal validity unresolved" if requested_weighted
                   else "unweighted; longitudinal validity unresolved")
    checkpoint = str(data.get("checkpoint1_status", "unresolved")).lower()
    integrity = str(validation.get("data_integrity", "unresolved")).lower()
    mappings = str(validation.get("mappings", "unresolved")).lower()
    linkage = str(validation.get("linkage", "unresolved")).lower()
    scope = str(validation.get("profiling_scope", "unresolved")).lower()
    readiness = str(validation.get("research_readiness", "blocked")).lower()
    cross = str(validation.get("cross_sectional_readiness", "unresolved")).lower()
    def format_status(value: str, descriptions: dict[str, str]) -> str:
        return descriptions.get(value, value.replace("_", " ").capitalize())
    return [
        ("Checkpoint 1 — input verification", "Passed; required source, schema and provenance checks recorded." if checkpoint == "passed" else "Not passed; required source and schema verification is not recorded as complete."),
        ("Training-selection permission", "Confirmed by the user." if permission in {"confirmed", "user_confirmed"} else "Unconfirmed; selecting records by the training-response field is not enabled."),
        ("Data integrity", format_status(integrity, {"audit_passed_schema_open": "Preliminary audit passed; the detailed schema review is still open."})),
        ("CWS outcome mapping", format_status(mappings, {"broad_groups_documented_detail_unresolved": "Broad work-status groups are documented; detailed occupation codes are unresolved."})),
        ("Person linkage", format_status(linkage, {"candidate_rule_implemented_identity_unconfirmed": "A respondent-linking rule exists, but respondent identities are not confirmed."})),
        ("Profiling scope", format_status(scope, {"unresolved": "Not reviewed; profile-variable scope is not confirmed."})),
        ("Research readiness", format_status(readiness, {"blocked": "Blocked until the outstanding source and validation requirements are met."})),
        ("Follow-up loss codes", (f"{lost_count} code(s) configured; mapping documented." if lost_status == "documented" else "No verified respondent-level loss mapping configured.")),
        ("Training timing", "Verified dated training timing." if timing == "dated" and evidence == "verified" else "Only coarse timing evidence is available; post-training timing is not established."),
        ("Longitudinal weighting", "Weighted estimates requested, but longitudinal weights are not validated." if requested_weighted else "Unweighted summaries only; longitudinal weights are not validated."),
        ("Annual cross-sectional review", "Validated for descriptive annual estimates only." if cross == "passed_descriptive_only" else format_status(cross) + "; annual estimates are unavailable."),
        ("Annual weight formula", "MULT / (100 when NSS=NSC, otherwise 200) / NO_QTR; annual cross-sectional route only."),
    ]


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
        display_pt = pt.copy()
        display_pt["share"] = pd.to_numeric(display_pt["share"], errors="coerce") * 100
        st.dataframe(display_pt, width="stretch", hide_index=True, column_config={"share": st.column_config.NumberColumn("Cohort share", format="%.1f%%")})


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
    st.dataframe(tab[cols], width="stretch", hide_index=True)
    st.caption("A k is admissible only if it is stable on subsamples, has no tiny cluster and wastes no medoid; the silhouette alone never decides.")


def render_pathways(st: Any, cfg: Config, r: dict[str, Any], tag: str) -> None:
    prof = r.get("profiles")
    if not prof:
        _missing(st, "The pathway profiles", "profile")
        return
    names = {int(p): n for p, n in prof["names"].items()}
    labels_to_ids = {label: pathway_id for pathway_id, label in names.items()}
    chosen_label = st.selectbox("Pathway", options=list(labels_to_ids), key="pathway_choice")
    chosen = labels_to_ids[chosen_label]
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
        st.dataframe(pd.DataFrame([attrs]).T.rename(columns={0: "Value"}), width="stretch")
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
    st.dataframe(hidden_pathways_table(r), width="stretch", hide_index=True)
    ll = like_for_like_table(r)
    if not ll.empty:
        st.subheader("Same units, same distance")
        st.dataframe(ll, width="stretch", hide_index=True)
        st.caption(b.get("like_for_like_note", ""))
    c = b["counts"]
    st.caption(f"Individuals: {c['n_eligible']} compared, {c['n_excluded']} excluded because the reference visit was unknown or lost "
               f"(missing {c['n_unknown_missing']}, lost {c['n_unknown_lost']}).")
    for note in cmp.get("notes", []):
        st.caption(note)
    sens = b.get("sensitivity") or {}
    if sens:
        st.subheader("Other baseline definitions")
        st.dataframe(pd.DataFrame([{"Variant": k, "ARI": v["ari"], "NMI": v["nmi"], "People compared": v["n_compared"]} for k, v in sens.items()]), width="stretch", hide_index=True)


def render_stability(st: Any, cfg: Config, r: dict[str, Any], tag: str) -> None:
    s = r.get("stability")
    if not s:
        _missing(st, "The stability results", "stability")
    else:
        _live(st, plot_stability_curves(pd.DataFrame(s["curves"]), cfg), tag)
        st.dataframe(stability_table(r), width="stretch", hide_index=True)
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
        st.dataframe(df[[c for c in ("policy", "is_primary", "n_individuals", "silhouette", "ari_vs_primary_pathways", "error") if c in df.columns]], width="stretch", hide_index=True)
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
    st.set_page_config(page_title="Employment Outcome Pathways — INT396 G24", layout="wide")
    st.markdown("""
    <style>
      .block-container {max-width: 1440px; padding-top: 1.4rem; padding-left: clamp(1rem, 3vw, 3rem); padding-right: clamp(1rem, 3vw, 3rem);}
      h1, h2, h3 {line-height: 1.2; overflow-wrap: anywhere;}
      [data-testid="stDataFrame"] {width: 100%;}
      .stMetric {min-width: 0;}
      @media (max-width: 900px) { [data-testid="stHorizontalBlock"] {gap: .6rem;} }
    </style>
    """, unsafe_allow_html=True)
    page = st.sidebar.radio("Project area", ["Turkey ISKUR CA (primary)", "Legacy PLFS and pathway explorer"],
                            index=0, key="project_area")
    if page == "Turkey ISKUR CA (primary)":
        render_turkey_saved(st, cfg)
        return

    st.title("Legacy PLFS and pathway explorer")
    st.caption("Separate preserved route. PLFS real-data outputs are shown only when their independent validation gate passes.")
    gate_open, gate_reason = real_gate_status(cfg)
    st.subheader("PLFS validation checkpoints")
    statuses = status_items(cfg)
    status_frame = pd.DataFrame(statuses, columns=["Checkpoint", "Current status and meaning"])
    st.dataframe(status_frame, width="stretch", height=600, hide_index=True, column_config={
        "Checkpoint": st.column_config.TextColumn(width="medium"),
        "Current status and meaning": st.column_config.TextColumn(width="large")})
    _download_table(st, status_frame, "plfs_validation_checkpoints.csv")
    if gate_open:
        st.success("Longitudinal real-data gate passed. Only saved, validated result files can be displayed.")
    else:
        gate_reason = str(gate_reason).replace(str(cfg.root), "<project>").replace(str(cfg.root).replace("\\", "/"), "<project>")
        st.warning(f"Longitudinal real-data gate is blocked. Saved real PLFS results remain hidden. First unmet requirement: {gate_reason}")
    st.subheader("Separate annual cross-sectional PLFS route")
    st.caption("This route has its own descriptive validation gate and does not use longitudinal linkage or clustering.")
    render_cross_section_saved(st, cfg)
    st.divider()
    st.subheader("Legacy longitudinal pathway explorer")
    tags = available_tags(cfg)
    if not tags:
        st.warning("No viewable saved results are available. To view a synthetic demonstration, run `python run_pipeline.py --synthetic`. Real results remain hidden until validation passes.")
        return
    tag = tags[0]
    if len(tags) > 1:
        tag = st.radio("Saved result set", tags, index=0, help="Real and synthetic results are never shown together.")
    r = load_results(cfg, tag == SYNTHETIC)
    profile_weighted = (r.get("profiles") or {}).get("weighted")
    weight_label = ("Weighted prevalence selected; no validated PLFS longitudinal weight is available." if profile_weighted
                    else "Unweighted sample shares; no validated PLFS longitudinal weight is available." if profile_weighted is False
                    else "Weighting status was not recorded; do not interpret these as population estimates.")
    st.caption(f"Legacy saved prevalence: {weight_label}")
    if tag == SYNTHETIC:
        st.error("SYNTHETIC DEMONSTRATION - NOT PLFS RESULTS")
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

    at_default = AppTest.from_file(app, default_timeout=120).run()
    default_text = " ".join([h.value for h in at_default.header] + [s.value for s in at_default.subheader] + [m.value for m in at_default.markdown])
    default_is_turkey = (not at_default.exception and "INT396 | G24 | CA Project" in default_text
                         and "PLFS" not in default_text
                         and "Primary CA analysis" not in default_text
                         and all(m.label not in {"Trainees analysed", "Silhouette"} for m in at_default.metric))
    at = at_default.sidebar.radio(key="project_area").set_value("Legacy PLFS and pathway explorer").run()
    all_text = " ".join([m.value for m in at.markdown] + [e.value for e in at.error] + [c.value for c in at.caption] + [w.value for w in at.warning] + [i.value for i in at.info])
    pick = at.selectbox(key="pathway_choice")
    first_options = list(pick.options)
    at2 = pick.select(first_options[-1]).run()
    metrics = [m.label for m in at.metric]

    save_result("headline", {"is_synthetic": False, "n_individuals": 7, "k": 2, "silhouette": None, "min_cluster_share": 0.5}, cfg, False)
    at_both = AppTest.from_file(app, default_timeout=120).run()
    at_both = at_both.sidebar.radio(key="project_area").set_value("Legacy PLFS and pathway explorer").run()
    status_text = " ".join([m.value for m in at_both.metric] + [w.value for w in at_both.warning] + [i.value for i in at_both.info])
    only_synthetic = "SYNTHETIC DEMONSTRATION - NOT PLFS RESULTS" in " ".join(e.value for e in at_both.error)
    real_hidden = "remain hidden" in status_text

    # Exercise the real view only through a separate temporary config with test-only gate values.
    d_open = dict(d)
    d_open = base.to_dict()
    d_open["paths"] = dict(d["paths"])
    d_open["data"].update({"plan": "A", "verified": True, "checkpoint1_status": "PASSED", "b4q12_permission_status": "CONFIRMED"})
    # This is a test-only config. Satisfy every production readiness check so
    # the test exercises the allowed real-result view, not an incomplete gate.
    d_open["validation"].update({"data_integrity": "passed", "mappings": "validated", "linkage": "validated",
                                  "permissions": "user_confirmed", "research_readiness": "passed"})
    d_open["lost_codes"] = ["TEST_ONLY_LOST_CODE"]
    d_open["lost_codes_status"] = "documented"
    d_open["data"]["schema"]["nonresponse_col"] = "TEST_ONLY_NONRESPONSE"
    d_open["trainee"]["timing_support"] = "dated"
    d_open["trainee"]["timing_evidence"]["status"] = "VERIFIED"
    open_cfg_path = tmp / "config_gate_pass_test_only.yaml"
    open_cfg_path.write_text(yaml.safe_dump(d_open, sort_keys=False), encoding="utf-8")
    open_cfg = load_config(str(open_cfg_path))
    save_result("headline", {"is_synthetic": False, "n_individuals": 7, "k": 2, "silhouette": None, "min_cluster_share": 0.5}, open_cfg, False)
    os.environ["PATHWAYS_CONFIG"] = str(open_cfg_path)
    at_gate_open = AppTest.from_file(app, default_timeout=120).run()
    at_gate_open = at_gate_open.sidebar.radio(key="project_area").set_value("Legacy PLFS and pathway explorer").run()
    open_text = " ".join([m.value for m in at_gate_open.markdown] + [i.value for i in at_gate_open.info])

    os.environ["PATHWAYS_CONFIG"] = str(empty / "config.yaml")
    at_empty = AppTest.from_file(app, default_timeout=60).run()
    at_empty = at_empty.sidebar.radio(key="project_area").set_value("Legacy PLFS and pathway explorer").run()
    # Load the actual primary CA outputs as well as the synthetic fixtures.
    os.environ["PATHWAYS_CONFIG"] = str(ROOT / "config.yaml")
    at_turkey = AppTest.from_file(app, default_timeout=60).run()
    turkey_text = " ".join([m.value for m in at_turkey.markdown] + [h.value for h in at_turkey.header] + [t.value for t in at_turkey.title]
                            + [s.value for s in at_turkey.subheader]
                            + [i.value for i in at_turkey.info] + [w.value for w in at_turkey.warning])
    turkey_metrics = {m.label: m.value for m in at_turkey.metric}
    _, _, _, missing_cross_section_note = load_cross_sectional_saved(base)

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
        "default landing is Turkey CA and excludes legacy synthetic headline metrics": default_is_turkey,
        "missing PLFS dependency is named with its relative path and no local username": "data/raw/perv1.csv" in missing_cross_section_note
            and "C:\\Users\\" not in missing_cross_section_note,
        "separate legacy page keeps the required synthetic warning and six tabs": not at.exception and "SYNTHETIC DEMONSTRATION - NOT PLFS RESULTS" in all_text and len(at.tabs) == 6,
        "app shows the headline metrics and the pathway choice offers every pathway": len(metrics) >= 6 and len(first_options) == r["clustering"]["k"],
        "choosing another pathway reruns without an exception": not at2.exception,
        "real results are hidden when the configured gate is blocked, even if a real result file exists": real_hidden and only_synthetic and not at_both.exception,
        "gate-passing test-only config permits the real saved result and labels the status": any(list(x.options) == [REAL, SYNTHETIC] for x in at_gate_open.radio)
            and not at_gate_open.exception,
        "a page with missing results says which stage creates them instead of failing": "run_pipeline.py --stage" in open_text and not at_gate_open.exception,
        "with no results at all the app says how to create them": not at_empty.exception and any("No viewable saved results" in w.value for w in at_empty.warning),
        "primary dashboard loads hash-verified Turkey outputs without synthetic metrics": not at_turkey.exception
            and "Employment Outcome Pathway Grouping After Skilling" in turkey_text
            and "SYNTHETIC DEMONSTRATION - NOT PLFS RESULTS" not in turkey_text
            and turkey_metrics.get("Complete attendee sequences") == "1,546",
    }
    for name, ok in checks.items():
        print(f"  self-test [{'ok' if ok else 'FAILED'}]: {name}")
    if not all(checks.values()):
        print("exceptions:", [e.value for e in at.exception], [e.value for e in at_both.exception], [e.value for e in at_empty.exception], [e.value for e in at_turkey.exception])
        return 1
    print(f"Self-test passed ({len(checks)}). PLFS fixtures are SYNTHETIC (files in {tmp}); the Turkey check reads hash-verified saved analysis outputs.")
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
