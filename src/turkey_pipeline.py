"""Reproducible descriptive analysis of the historical Turkey ISKUR evaluation.

This module is intentionally isolated from PLFS. Employment states are used only
when source response flags, dates, and value domains support the observation.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.spatial.distance import cdist
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics import adjusted_rand_score, silhouette_score

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data/raw/TurkeyPublicUseData.dta"
OUT = ROOT / "outputs/turkey"
SEED = 20261106

USED = {
    "UNIQID": "respondent key and uniqueness validation",
    "MM_Group": "original randomized assignment: 1 treatment, 2 control",
    "Treat": "assignment consistency check against MM_Group",
    "BB_dInterview": "baseline interview response validity",
    "BB_intdate": "actual baseline interview date",
    "BB_work4wks1": "worked at all in baseline reference period (employment, not unemployment)",
    "FF_FILTER": "follow-up interview result validity",
    "FF_dmiss": "follow-up attrition flag",
    "FF_intdate": "actual follow-up interview date",
    "FF_work4wks1": "worked at all in follow-up reference period",
    "MIS_EC7": "administrative exact course start date; baseline timing anchor",
    "MIS_EC8": "administrative exact course end date; follow-up timing anchor",
    "MIS_course_attend_days": "administrative days attended; actual participation evidence",
    "MIS_EC19": "administrative first-day dropout flag",
    "MIS_EC21": "administrative second-day dropout flag",
    "MIS_EC22": "administrative evaluation-course completion",
    "MIS_EC23": "administrative certificate receipt response",
    "MIS_certEC": "official derived certificate indicator; cross-check only",
    "FF_C60": "self-reported selection for ISKUR course, not assignment or attendance",
    "FF_C61": "self-reported other vocational training attendance",
    "FF_C62": "self-reported ISKUR course status; distinct from MIS attendance/completion",
    "employjan12": "ever in formal job by January 2012 administrative follow-up",
    "lostjobjan1": "left first formal job by January 2012 administrative follow-up",
    "infformaljob": "still in first formal job at January 2012 follow-up",
    "everemployed": "ever in formal job after course",
    "everlostjob": "left first formal job by November 2013 follow-up",
    "formallyemployedAug2013": "point-in-time formal employment in August 2013",
    "formallyemployedin2013": "any formal employment in first eight months of 2013; cumulative interval, not a wave",
    "incomeAug2013": "administrative formal earnings in August 2013",
    "MM_gender": "gender for descriptive participant profile",
    "BB_age": "baseline age for descriptive participant profile",
}


def _stata_date(s: pd.Series) -> pd.Series:
    """Parse source M/D/Y strings/dates; invalid and blank values remain NaT."""
    return pd.to_datetime(s, errors="coerce")


def _binary(s: pd.Series) -> pd.Series:
    """Retain only explicitly observed 0/1 values as nullable integers."""
    return s.where(s.isin([0, 1]), pd.NA).astype("Int64")


def load_and_preprocess(path: Path = INPUT) -> tuple[pd.DataFrame, dict[str, Any]]:
    reader = pd.io.stata.StataReader(path)
    labels = reader.variable_labels()
    raw = reader.read(convert_categoricals=False)
    missing = sorted(set(USED) - set(raw.columns))
    if missing:
        raise ValueError(f"Turkey dataset lacks required variables: {missing}")
    if raw.UNIQID.isna().any() or raw.UNIQID.duplicated().any():
        raise ValueError("UNIQID must be present and unique")
    d = raw[list(USED)].copy()
    d["treatment_assigned"] = d.MM_Group.map({1: 1, 2: 0}).astype("Int64")
    d["assignment_crosscheck_pass"] = d.treatment_assigned.eq(d.Treat).fillna(False)
    if not d.assignment_crosscheck_pass.all():
        raise ValueError("MM_Group and source-derived Treat assignment disagree")

    d["course_start_date"] = _stata_date(d.MIS_EC7)
    d["course_end_date"] = _stata_date(d.MIS_EC8)
    d["baseline_interview_date"] = _stata_date(d.BB_intdate)
    d["followup_interview_date"] = _stata_date(d.FF_intdate)
    d["baseline_valid"] = d.BB_dInterview.eq(1) & d.baseline_interview_date.notna()
    d["followup_valid"] = d.FF_FILTER.eq(1) & d.FF_dmiss.eq(0) & d.followup_interview_date.notna()
    d["baseline_pre_training"] = d.baseline_valid & d.course_start_date.notna() & (d.baseline_interview_date < d.course_start_date)
    d["followup_post_training"] = d.followup_valid & d.course_end_date.notna() & (d.followup_interview_date > d.course_end_date)
    d["employment_baseline"] = _binary(d.BB_work4wks1).where(d.baseline_pre_training, pd.NA).astype("Int64")
    d["employment_followup"] = _binary(d.FF_work4wks1).where(d.followup_post_training, pd.NA).astype("Int64")

    # Do not collapse randomized assignment, self-reported selection, exposure,
    # completion, and certificate receipt. Unknown exposure remains NA.
    d["course_selection_reported"] = d.FF_C60.map({1: 1, 2: 0}).astype("Int64")
    d["other_vocational_training"] = d.FF_C61.map({1: 1, 2: 0}).astype("Int64")
    d["course_completion_admin"] = d.MIS_EC22.map({"Yes": 1, "No": 0}).astype("Int64")
    d["certificate_received_admin"] = d.MIS_EC23.map({"Yes": 1, "No": 0}).astype("Int64")
    d["course_completion_self_reported"] = d.FF_C62.map({1: 0, 2: 0, 3: 1}).astype("Int64")
    dropout = d.MIS_EC19.eq("Yes") | d.MIS_EC21.eq("Yes")
    attendance_days = pd.to_numeric(d.MIS_course_attend_days, errors="coerce")
    d["actual_attendance_evidence"] = (attendance_days.gt(0) | dropout).astype("Int64")
    d.loc[attendance_days.isna() & ~dropout, "actual_attendance_evidence"] = pd.NA
    d["official_certificate_crosscheck"] = _binary(d.MIS_certEC)
    cert_answered = d.certificate_received_admin.notna()
    d["certificate_source_crosscheck_pass"] = pd.Series(pd.NA, index=d.index, dtype="boolean")
    d.loc[cert_answered, "certificate_source_crosscheck_pass"] = d.loc[cert_answered, "certificate_received_admin"].eq(d.loc[cert_answered, "official_certificate_crosscheck"]).astype("boolean")

    # Admin outcomes are retained as their genuine temporal estimands. Jan-12
    # and Nov-13 milestone indicators describe first-job history, not month waves.
    admin_binary = ["employjan12", "lostjobjan1", "infformaljob", "everemployed", "everlostjob",
                    "formallyemployedAug2013", "formallyemployedin2013"]
    for name in admin_binary:
        d[f"admin_{name}"] = _binary(d[name])
    d["admin_incomeAug2013"] = pd.to_numeric(d.incomeAug2013, errors="coerce")
    d["admin_jan12_first_job_state"] = pd.Series(pd.NA, index=d.index, dtype="string")
    jvalid = d.admin_employjan12.notna() & d.admin_lostjobjan1.notna() & d.admin_infformaljob.notna()
    d.loc[jvalid & d.admin_employjan12.eq(0), "admin_jan12_first_job_state"] = "no_formal_job_by_jan2012"
    d.loc[jvalid & d.admin_employjan12.eq(1) & d.admin_lostjobjan1.eq(0), "admin_jan12_first_job_state"] = "first_job_active_jan2012"
    d.loc[jvalid & d.admin_employjan12.eq(1) & d.admin_lostjobjan1.eq(1), "admin_jan12_first_job_state"] = "first_job_left_by_jan2012"
    d["admin_nov13_job_exit"] = d.admin_everlostjob

    # Primary pathway has three authentic observations: verified pre-course
    # any-work baseline, dated post-course any-work follow-up, Aug-2013 formal
    # employment point. The last is narrower and labeled explicitly.
    d["path_baseline_any_work"] = d.employment_baseline
    d["path_followup_any_work"] = d.employment_followup
    d["path_aug2013_formal_work"] = d.admin_formallyemployedAug2013.where(
        d.course_end_date.notna() & (d.course_end_date < pd.Timestamp("2013-08-01")), pd.NA
    ).astype("Int64")
    d["valid_pathway_observation"] = d[["path_baseline_any_work", "path_followup_any_work", "path_aug2013_formal_work"]].notna().all(axis=1)
    d["trajectory"] = pd.Series(pd.NA, index=d.index, dtype="string")
    v = d.valid_pathway_observation
    d.loc[v, "trajectory"] = d.loc[v, ["path_baseline_any_work", "path_followup_any_work", "path_aug2013_formal_work"]].astype(int).astype(str).agg("->".join, axis=1)
    d["eligible_prebaseline_attendee"] = d.baseline_pre_training & d.actual_attendance_evidence.eq(1)

    meta = {
        "input": str(path.relative_to(ROOT)), "input_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "pipeline_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "n_rows": int(len(raw)), "n_columns": int(raw.shape[1]), "data_label": reader.data_label,
        "stata_timestamp": reader.time_stamp, "variable_labels": {k: labels.get(k, "") for k in USED},
        "used_variables": USED, "baseline_valid_n": int(d.baseline_valid.sum()),
        "baseline_pre_training_n": int(d.baseline_pre_training.sum()), "followup_valid_n": int(d.followup_valid.sum()),
        "followup_post_course_n": int(d.followup_post_training.sum()),
        "assignment_crosscheck_fail_n": int((~d.assignment_crosscheck_pass).sum()),
        "certificate_raw_answered_n": int(cert_answered.sum()),
        "certificate_source_crosscheck_fail_n": int(d.loc[cert_answered, "certificate_source_crosscheck_pass"].eq(False).sum()),
    }
    return d, meta


def _cluster_sequences(x: np.ndarray, k: int) -> np.ndarray:
    return AgglomerativeClustering(n_clusters=k, metric="hamming", linkage="average").fit_predict(x)


def run(path: Path = INPUT, out: Path = OUT, stability_reps: int = 100) -> dict[str, Any]:
    d, meta = load_and_preprocess(path)
    out.mkdir(parents=True, exist_ok=True)
    # Cluster only documented actual attendees with three observed outcomes.
    # Never-started/unknown exposure records remain in the row-preserving file
    # but are not mislabeled trainees. Completion/certification do not gate entry.
    ix = d.index[d.valid_pathway_observation & d.actual_attendance_evidence.eq(1)]
    x = d.loc[ix, ["path_baseline_any_work", "path_followup_any_work", "path_aug2013_formal_work"]].astype(int).to_numpy()
    labels: np.ndarray | None = None
    candidate_rows = []
    distance = cdist(x, x, metric="hamming") if len(x) else np.empty((0, 0))
    max_k = min(5, len(np.unique(x, axis=0)) - 1, len(x) - 1)
    for k in range(2, max_k + 1):
        z = _cluster_sequences(x, k)
        sizes = np.bincount(z)
        sil = float(silhouette_score(distance, z, metric="precomputed"))
        candidate_rows.append({"k": k, "silhouette_hamming": sil, "min_cluster_n": int(sizes.min()),
                               "min_cluster_share": float(sizes.min() / len(z)), "eligible_min_5pct": bool(sizes.min() / len(z) >= .05)})
    eligible = [r for r in candidate_rows if r["eligible_min_5pct"]]
    selected = max(eligible, key=lambda r: (r["silhouette_hamming"], -r["k"])) if eligible else None
    if selected:
        labels = _cluster_sequences(x, selected["k"])
        # Deterministic 80% subsampling; refit the same method, then classify
        # held-out/full cases by nearest sampled cluster medoid.
    d["cluster_id"] = pd.Series(pd.NA, index=d.index, dtype="Int64")
    if labels is not None:
        # Stable human-readable ordering by cluster medoid sequence.
        medoid_seqs = []
        for lab in np.unique(labels):
            members = np.flatnonzero(labels == lab)
            med = members[np.argmin(distance[np.ix_(members, members)].sum(axis=1))]
            medoid_seqs.append((lab, tuple(x[med].tolist())))
        order = {lab: n + 1 for n, (lab, _) in enumerate(sorted(medoid_seqs, key=lambda p: p[1]))}
        labels = np.array([order[z] for z in labels])
        d.loc[ix, "cluster_id"] = labels
    # Valid trainee-level file includes all 5,902 applicants and explicit NAs.
    d.to_csv(out / "trainee_analysis.csv", index=False, date_format="%Y-%m-%d")
    pd.DataFrame(candidate_rows).to_csv(out / "cluster_method_evaluation.csv", index=False)
    trajectories = d.loc[ix].copy()
    trajectories.to_csv(out / "valid_post_training_trajectories.csv", index=False, date_format="%Y-%m-%d")

    if labels is not None:
        tr = trajectories.groupby("cluster_id").agg(
            n=("UNIQID", "size"), treatment_assigned_n=("treatment_assigned", "sum"),
            attendance_evidence_n=("actual_attendance_evidence", "sum"), attendance_known_n=("actual_attendance_evidence", "count"),
            completion_n=("course_completion_admin", "sum"), completion_known_n=("course_completion_admin", "count"),
            certificate_received_n=("certificate_received_admin", "sum"), certificate_known_n=("certificate_received_admin", "count"),
            baseline_any_work_rate=("path_baseline_any_work", "mean"),
            followup_any_work_rate=("path_followup_any_work", "mean"), aug2013_formal_work_rate=("path_aug2013_formal_work", "mean"),
            age_median=("BB_age", "median"), assignment_share=("treatment_assigned", "mean"),
            attendance_evidence_share_all=("actual_attendance_evidence", "sum"),
            selection_reported_share=("course_selection_reported", "mean"),
            completion_share_observed=("course_completion_admin", "mean"),
            certificate_share_observed=("certificate_received_admin", "mean")).reset_index()
        tr["share_complete_pathways"] = tr.n / len(trajectories)
        tr["attendance_evidence_share_all"] = tr.attendance_evidence_n / tr.n
        tr["completion_share_all"] = tr.completion_n / tr.n
        tr["certificate_share_all"] = tr.certificate_received_n / tr.n
        tr["trajectory_patterns"] = tr.cluster_id.map(lambda c: ", ".join(sorted(trajectories.loc[trajectories.cluster_id.eq(c), "trajectory"].unique())))
        labels_by_patterns = {
            frozenset({"0->0->0", "1->0->0"}): "No follow-up work; no August formal job",
            frozenset({"0->0->1", "1->0->1"}): "No follow-up work; formal job by August 2013",
            frozenset({"0->1->0", "0->1->1"}): "Not working at baseline; working at follow-up",
            frozenset({"1->1->0", "1->1->1"}): "Working at baseline and follow-up",
        }
        tr["pathway_label"] = tr.cluster_id.map(lambda c: labels_by_patterns.get(
            frozenset(trajectories.loc[trajectories.cluster_id.eq(c), "trajectory"].unique()),
            "Observed sequence group: " + ", ".join(sorted(trajectories.loc[trajectories.cluster_id.eq(c), "trajectory"].unique()))))
        gender = trajectories.groupby(["cluster_id", "MM_gender"], dropna=False).size().rename("n").reset_index()
    else:
        tr = pd.DataFrame(); gender = pd.DataFrame(columns=["cluster_id", "MM_gender", "n"])
    tr.to_csv(out / "cluster_prevalence.csv", index=False)
    gender.to_csv(out / "cluster_gender_profile.csv", index=False)
    admin_profile = pd.DataFrame()
    states = pd.DataFrame()
    if labels is not None:
        admin_profile = trajectories.groupby("cluster_id").agg(
            n=("UNIQID", "size"), formal_entry_by_jan2012_share=("admin_employjan12", "mean"),
            ever_formally_employed_postcourse_share=("admin_everemployed", "mean"),
            first_job_left_by_nov2013_share=("admin_everlostjob", "mean"),
            formal_anytime_first8months2013_share=("admin_formallyemployedin2013", "mean"),
            aug2013_formal_income_median=("admin_incomeAug2013", "median"),
            jan2012_first_job_state_known_n=("admin_jan12_first_job_state", "count"),
        ).reset_index()
        states = trajectories.groupby(["cluster_id", "admin_jan12_first_job_state"], dropna=False).size().rename("n").reset_index()
        states["share_cluster"] = states.n / states.cluster_id.map(admin_profile.set_index("cluster_id").n)
        admin_profile.to_csv(out / "cluster_admin_profile.csv", index=False)
        states.to_csv(out / "cluster_jan2012_state_profile.csv", index=False)
    else:
        pd.DataFrame().to_csv(out / "cluster_admin_profile.csv", index=False)
        pd.DataFrame().to_csv(out / "cluster_jan2012_state_profile.csv", index=False)
    trajectories.groupby(["path_baseline_any_work", "cluster_id"], dropna=False).size().rename("n").reset_index().to_csv(out / "baseline_employment_by_cluster.csv", index=False)

    stability_scores = []
    if labels is not None and stability_reps > 0:
        rng = np.random.default_rng(SEED)
        for rep in range(stability_reps):
            sample = np.sort(rng.choice(len(x), max(3, int(.8 * len(x))), replace=False))
            sublabels = _cluster_sequences(x[sample], selected["k"])
            centers = []
            for lab in range(selected["k"]):
                members = x[sample][sublabels == lab]
                centers.append(members[np.argmin(cdist(members, members, metric="hamming").sum(axis=1))])
            pred = np.argmin(cdist(x, np.asarray(centers), metric="hamming"), axis=1)
            stability_scores.append(float(adjusted_rand_score(labels, pred)))
    # Baseline employed/not-employed comparison only among dated pre-course respondents.
    baseline = d.loc[d.employment_baseline.notna()]
    employed = baseline.loc[baseline.employment_baseline.eq(1)]
    not_employed = baseline.loc[baseline.employment_baseline.eq(0)]
    base_comp = {"valid_pretraining_baseline_n": int(len(baseline)), "employed_n": int(len(employed)),
                 "not_employed_n": int(len(not_employed)), "employed_share": float(baseline.employment_baseline.mean()) if len(baseline) else None,
                 "definition": "worked at all in baseline reference period, among interviewed respondents with actual interview date strictly before administrative course start",
                 "interpretation": "not working is not equivalent to unemployed; it includes people outside the labor force"}
    by_baseline = baseline.groupby("employment_baseline").agg(n=("UNIQID", "size"), assigned_treatment_share=("treatment_assigned", "mean"),
        attendance_evidence_n=("actual_attendance_evidence", "sum"), attendance_evidence_known_n=("actual_attendance_evidence", "count"),
        completion_share_among_known=("course_completion_admin", "mean"), completion_known_n=("course_completion_admin", "count"),
        certificate_share_among_known=("certificate_received_admin", "mean"), certificate_known_n=("certificate_received_admin", "count"),
        postfollowup_any_work_share=("employment_followup", "mean"), aug2013_formal_work_share=("admin_formallyemployedAug2013", "mean")).reset_index()
    by_baseline["attendance_evidence_share_all"] = by_baseline.attendance_evidence_n / by_baseline.n
    by_baseline.to_csv(out / "baseline_employed_comparison.csv", index=False)

    # Follow-up missing-outcome extreme bounds, in pre-course baseline attendees;
    # no states are imputed. Also compare administrative Aug-2013 outcome by
    # follow-up response to diagnose differential loss.
    cohort = d.loc[d.eligible_prebaseline_attendee]
    known = cohort.employment_followup.notna()
    n, nk = len(cohort), int(known.sum())
    observed_work = int(cohort.loc[known, "employment_followup"].sum())
    admin_groups = cohort.assign(followup_observed=known).groupby("followup_observed").agg(n=("UNIQID", "size"), aug2013_formal_share=("admin_formallyemployedAug2013", "mean"), baseline_work_share=("employment_baseline", "mean")).reset_index()
    admin_groups.to_csv(out / "attrition_admin_comparison.csv", index=False)
    # Cluster prevalence under worst/best missing follow-up employment scenarios
    # with observed baseline + Aug admin outcome; classify via frozen nearest medoids.
    attrition_scenarios = {}
    if labels is not None:
        center_rows = []
        for cid in sorted(np.unique(labels)):
            members = x[labels == cid]
            center_rows.append(members[np.argmin(cdist(members, members, metric="hamming").sum(axis=1))])
        centers = np.asarray(center_rows)
        for scenario, value in [("missing_followup_assumed_not_working", 0), ("missing_followup_assumed_working", 1)]:
            potential = d.loc[d.eligible_prebaseline_attendee & d.path_aug2013_formal_work.notna()].copy()
            potential["scenario_followup"] = potential.employment_followup.fillna(value).astype(int)
            sx = potential[["employment_baseline", "scenario_followup", "path_aug2013_formal_work"]].astype(int).to_numpy()
            sc = np.argmin(cdist(sx, centers, metric="hamming"), axis=1) + 1
            attrition_scenarios[scenario] = {str(int(cid)): int((sc == cid).sum()) for cid in np.unique(labels)}

    silval = selected["silhouette_hamming"] if selected else None
    summary = {**meta, "geography": "Turkey", "population": "historical ISKUR vocational training evaluation applicants, 2010-2013",
        "not_maharashtra": True, "n_baseline_pre_training": int(d.baseline_pre_training.sum()),
        "n_valid_post_training_trajectories": int(len(trajectories)), "trajectory_patterns": sorted(trajectories.trajectory.unique().tolist()),
        "cluster_method": "average-linkage agglomerative clustering on individual three-observation binary sequences using Hamming distance",
        "candidate_cluster_metrics": candidate_rows, "selected_k": selected["k"] if selected else None,
        "silhouette_hamming": silval, "silhouette_interpretation": "individual-level precomputed Hamming distance silhouette; cluster labels are not exact-pattern identifiers",
        "baseline_comparison": base_comp,
        "baseline_employed_vs_not_employed": {str(int(row.employment_baseline)): {"n": int(row.n), "postfollowup_any_work_share": None if pd.isna(row.postfollowup_any_work_share) else float(row.postfollowup_any_work_share),
            "aug2013_formal_work_share": None if pd.isna(row.aug2013_formal_work_share) else float(row.aug2013_formal_work_share)} for row in by_baseline.itertuples()},
        "followup_attrition_n": int(d.FF_dmiss.eq(1).sum()), "followup_respondents_n": int(d.followup_valid.sum()),
        "attendee_baseline_cohort_n": int(n), "attendee_with_verified_followup_n": nk, "attendee_followup_unknown_n": n - nk,
        "followup_work_extreme_bounds": {"lower": observed_work / n if n else None, "upper": (observed_work + n - nk) / n if n else None},
        "attrition_admin_comparison": admin_groups.to_dict(orient="records"), "attrition_cluster_prevalence_scenarios": attrition_scenarios,
        "cluster_stability": {"method": "100 deterministic 80% subsamples; re-fit agglomerative clustering; assign all cases to nearest subsample medoid; compare to primary labels by ARI",
            "replicates": len(stability_scores), "ari_mean": float(np.mean(stability_scores)) if stability_scores else None,
            "ari_sd": float(np.std(stability_scores, ddof=1)) if len(stability_scores) > 1 else None,
            "ari_min": float(np.min(stability_scores)) if stability_scores else None,
            "ari_q10": float(np.quantile(stability_scores, .1)) if stability_scores else None},
        "certificate_semantics": "MIS_EC23 asks whether the evaluation-course certificate was received; official World Bank Create Variables do-file maps Yes=1 and control blanks=0. Raw response retained separately; derived source MIS_certEC cross-checked. Blank treatment responses remain unknown.",
        "admin_longitudinal_scope": "Released public DTA contains formal-job milestones by Jan-2012 and Nov-2013 and Aug-2013 point/cumulative indicators. Source paper describes monthly first-job spell records, but these dates/monthly records are not in the released public-use file; no such waves are fabricated.",
        "submission_suitability": "Suitable for a CA analysis of this historical Turkish evaluation with explicit scope disclosure; does not support Indian/Maharashtra outcome claims."}
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str, allow_nan=False), encoding="utf-8")
    stability = summary["cluster_stability"]
    bound = summary["followup_work_extreme_bounds"]
    report = ["# Employment outcome pathways: Turkey ISKUR evaluation", "", "**Historical Turkish vocational-training evaluation (2010–2013). This is not Indian or Maharashtra evidence.**", "",
        f"Public-use file: `{meta['input']}` ({meta['n_rows']:,} rows; SHA-256 `{meta['input_sha256']}`).", "",
        "## Observation and cohort rules", "", f"There are {base_comp['valid_pretraining_baseline_n']:,} baseline interviews with actual dates before administrative course commencement. The primary three-point pathway sample contains {len(trajectories):,} people with documented actual course attendance and all three outcomes observed: baseline any work before course start; follow-up any work after actual course end; and administrative formal employment in August 2013. The final point measures formal work, unlike the two survey any-work measures. Assignment, course selection, attendance, completion, and certificate receipt are distinct; unknown attendance does not qualify someone as a trainee.", "",
        "## Pathway clusters", "", _markdown_table(tr), "", f"Selected k={selected['k'] if selected else 'not supported'}; individual Hamming silhouette={silval if silval is not None else 'not estimable'}. Candidate results are in `cluster_method_evaluation.csv`. Clusters group similar measured sequences; no sequence is duplicated to inflate silhouette. The selected solution maximizes silhouette among k=2–5 with no cluster below 5%.", "",
        "## Baseline employed versus not employed", "", json.dumps(base_comp, indent=2), "", _markdown_table(by_baseline), "",
        "Employment means worked at all during the source reference period. The complement is not synonymous with unemployment and includes people outside the labor force. Only respondents interviewed before course start enter this comparison.", "",
        "## Exposure and certification", "", "Random assignment (`MM_Group`) is separate from self-reported selection (`FF_C60`), administrative attendance evidence (`MIS_course_attend_days` or documented early dropout), course completion (`MIS_EC22`), and certificate receipt (`MIS_EC23`). The official World Bank variable-construction do-file maps the certificate question response Yes to 1 and gives control-arm blanks 0 in its derived field; raw treatment-arm blanks remain unknown. Course status self-report (`FF_C62`) is preserved separately.", "",
        "## Admin employment history, attrition, and robustness", "", "The public DTA supports first formal-job milestones by Jan-2012 and Nov-2013, and Aug-2013 point/cumulative outcomes. The study paper describes monthly first-job spell data, but those granular dates are not present in the supplied public-use file. The analysis does not invent those time points.",
        "Cluster-level administrative employment milestones (rates use nonmissing source denominators):", "", _markdown_table(admin_profile), "", "January 2012 first-job state counts and within-cluster shares, including explicit unknowns:", "", _markdown_table(states), "",
        f"Among {n:,} pre-course baseline attendees, {nk:,} have verified post-course survey follow-up and {n-nk:,} do not. Worst/best-case bounds for follow-up any-work prevalence are {bound['lower']:.1%}–{bound['upper']:.1%}; unknown survey outcomes remain missing. Administrative August formal-work rates by follow-up response status and frozen-medoid cluster scenarios are in `attrition_admin_comparison.csv` and `summary.json`.",
        f"Subsample stability: {stability['replicates']} deterministic 80% refits; ARI mean {stability['ari_mean']:.3f}, SD {stability['ari_sd']:.3f}, minimum {stability['ari_min']:.3f}, 10th percentile {stability['ari_q10']:.3f}. This assesses sample stability, not causal validity.", "",
        "## Geography and use", "", "This is appropriate as a CA analysis of a historical Turkish program when its geography, population, and period are stated. It cannot substantiate Indian or Maharashtra employment outcomes."]
    (out / "cluster_profile_report.md").write_text("\n".join(report), encoding="utf-8")
    return summary


def _markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "No cluster solution met the prespecified minimum-size rule."
    cols = list(frame.columns)
    rows = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    rows.extend("| " + " | ".join(str(v) for v in row) + " |" for row in frame.itertuples(index=False, name=None))
    return "\n".join(rows)


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
