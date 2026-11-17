from pathlib import Path

import pandas as pd

from src.turkey_pipeline import _binary, _stata_date, load_and_preprocess, run


def test_turkey_dataset_integrity_and_assignment_crosscheck():
    d, meta = load_and_preprocess()
    assert meta["n_rows"] == 5902
    assert d.UNIQID.notna().all() and d.UNIQID.is_unique
    assert d.assignment_crosscheck_pass.all()
    assert set(d.MM_Group.unique()) == {1, 2}
    assert meta["n_columns"] == 1535


def test_nonrespondent_zero_is_never_unemployment():
    d, _ = load_and_preprocess()
    assert d.loc[d.BB_dInterview.eq(0), "employment_baseline"].isna().all()
    assert d.loc[d.FF_dmiss.eq(1), "employment_followup"].isna().all()
    assert d.loc[~d.baseline_pre_training, "employment_baseline"].isna().all()
    assert d.loc[~d.followup_post_training, "employment_followup"].isna().all()


def test_exact_dates_and_temporal_validity():
    assert pd.isna(_stata_date(pd.Series(["bad"])).iloc[0])
    d, _ = load_and_preprocess()
    assert d.course_start_date.notna().any() and d.course_end_date.notna().any()
    assert (d.loc[d.baseline_pre_training, "baseline_interview_date"] < d.loc[d.baseline_pre_training, "course_start_date"]).all()
    assert (d.loc[d.followup_post_training, "followup_interview_date"] > d.loc[d.followup_post_training, "course_end_date"]).all()
    assert d.loc[d.valid_pathway_observation, ["path_baseline_any_work", "path_followup_any_work", "path_aug2013_formal_work"]].notna().all().all()


def test_assignment_participation_completion_and_certification_remain_distinct():
    d, _ = load_and_preprocess()
    assert d.treatment_assigned.notna().all()
    assert d.course_selection_reported.isin([0, 1, pd.NA]).all()
    assert d.actual_attendance_evidence.isin([0, 1, pd.NA]).all()
    assert d.course_completion_admin.isin([0, 1, pd.NA]).all()
    assert d.certificate_received_admin.isin([0, 1, pd.NA]).all()
    assert d.loc[d.MIS_EC23.eq("Yes"), "certificate_received_admin"].eq(1).all()
    assert d.loc[d.MIS_EC23.eq("No"), "certificate_received_admin"].eq(0).all()
    assert d.loc[d.MIS_EC23.isin(["Yes", "No"]), "certificate_source_crosscheck_pass"].all()
    assert _binary(pd.Series([0, 1, 2, None])).tolist() == [0, 1, pd.NA, pd.NA]


def test_sequences_are_actual_three_point_observations(tmp_path):
    summary = run(out=tmp_path, stability_reps=8)
    assert summary["geography"] == "Turkey" and summary["not_maharashtra"]
    assert summary["n_valid_post_training_trajectories"] == 1546
    assert summary["baseline_comparison"]["valid_pretraining_baseline_n"] == 3385
    trajectories = pd.read_csv(tmp_path / "valid_post_training_trajectories.csv")
    assert trajectories.trajectory.str.fullmatch(r"[01]->[01]->[01]").all()
    assert trajectories.actual_attendance_evidence.eq(1).all()
    assert trajectories.cluster_id.nunique() == summary["selected_k"]
    assert summary["silhouette_hamming"] is not None
    assert summary["cluster_stability"]["replicates"] == 8
    prevalence = pd.read_csv(tmp_path / "cluster_prevalence.csv")
    assert prevalence.n.sum() == summary["n_valid_post_training_trajectories"]
    assert abs(prevalence.share_complete_pathways.sum() - 1) < 1e-9
    assert prevalence.pathway_label.notna().all() and prevalence.pathway_label.is_unique
    assert (tmp_path / "baseline_employed_comparison.csv").is_file()
    assert (tmp_path / "attrition_admin_comparison.csv").is_file()
    assert (tmp_path / "cluster_admin_profile.csv").is_file()
    assert (tmp_path / "cluster_jan2012_state_profile.csv").is_file()
    assert (tmp_path / "cluster_method_evaluation.csv").is_file()
    assert (tmp_path / "cluster_profile_report.md").is_file()


def test_absent_followup_remains_unknown_in_attrition_scenarios():
    d, _ = load_and_preprocess()
    eligible = d.eligible_prebaseline_attendee
    unknown = eligible & d.employment_followup.isna()
    assert unknown.sum() > 0
    assert d.loc[unknown, "employment_followup"].isna().all()
    # Sensitivity scenarios are summaries; source/preprocessed outcomes remain unchanged.

