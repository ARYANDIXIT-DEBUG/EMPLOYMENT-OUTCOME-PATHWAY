"""Run the whole analysis, stage by stage, from the command line.

Why this file exists: the project is a chain of modules that each do one job (load, build trajectories, build a
distance, cluster, evaluate, stress-test, describe, report). This script is the only place that wires them together,
so it is also the only place that can enforce the rules that cross modules: the real-data gate, one set of
substitution costs for every distance, the baseline defined before any clustering, and every number written to a
tagged results file before the report reads it.

Usage (from the project folder):
    python run_pipeline.py --synthetic                   # every stage on SYNTHETIC data (pipeline test only)
    python run_pipeline.py --synthetic --quick           # fewer stability repeats, for a fast test
    python run_pipeline.py --synthetic --stage cluster   # one stage (earlier steps it needs are recomputed in memory)
    python run_pipeline.py --stage audit                 # real data: the Phase 0 audit (CHECKPOINT 1)
    python run_pipeline.py                               # real data: refused unless the gate below is passed
    python run_pipeline.py --self-test                   # tests of this file itself (gate refusals, a quick synthetic run)

Stages, in order: audit, build, benchmark, cluster, evaluate, stability, profile, report.

Design choices worth defending in a viva:
  * The gate. A real run is refused (exit code 3) unless `data.plan` is set, `data.verified` is true, the design
    check passes, and the plan is A (the only plan that builds trajectories; B and C need the scope memo and your
    instructor's approval, and are not trajectory analyses). `--synthetic` skips the gate but tags every result and
    figure SYNTHETIC. The `audit` stage is how a real dataset reaches the gate, so it does not need it.
  * One set of substitution costs. They are estimated once from all trainees and passed to the distance matrix, to the
    clustering and to the stability repeats (which re-estimate their own from the degraded sample).
  * The baseline is checked with `check_baseline_lock` before any clustering; for real data an unlocked baseline stops
    the run. The baseline is evaluated on the SAME distance matrix as the pathways, on the same units, and the
    clustering is re-scored on exactly those units, so the two are compared like for like. A silhouette at k = 2 is
    shown beside the baseline because silhouettes at different k are not comparable.
  * Results are files. Each stage saves tagged JSON through `report_builder.save_result` and the report is filled only
    from those files. `run_meta` holds what ran, the settings overrides, library versions and every warning raised;
    it has no timestamps or timings, so two identical runs give identical files.
  * Warnings are collected, not hidden: the pairwise-overlap and small-cluster warnings are saved with the stage that
    raised them.
  * Stages are separable but not cached on disk: a stage run alone recomputes what it needs, deterministically (all
    randomness comes from `make_rng(cfg, salt)`), and k is re-chosen from the data each time, never read from an old file.
  * `--quick` (synthetic only) lowers `stability.n_repeats` and `clustering.k_stability_repeats` to 3 and records the
    override. It is for testing; its stability numbers are rougher.

Exit codes: 0 done, 1 a stage failed, 2 bad usage or config, 3 data gate refused.

Limits: this file computes nothing statistical itself except the like-for-like re-scoring of the baseline; if a
number looks wrong, the module that owns it is the place to look. If the report template is missing,
the report stage still writes the figures and says the render was skipped.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import platform
import sys
import tempfile
import time
import warnings
from pathlib import Path
from typing import Any, Callable, Iterator

import numpy as np
import pandas as pd

from src import MISSING
from src.baseline import (BaselineError, baseline_partition, baseline_unit_labels, check_baseline_lock, compare_to_clustering,
                          sensitivity_variants)
from src.clustering import cluster_full, benchmark_clustering, hierarchical, kmedoids, medoid_candidates, medoids_from_labels
from src.config import Config, ConfigError, load_config, make_rng, resolve_path, snapshot_config
from src.data_audit import format_audit, run_audit
from src.data_loader import DesignMixError, SchemaError, identify_trainees, load_long_panel, verify_design_compatibility
from src.distances import benchmark_distance, build_distance, plan_reduction, substitution_cost_matrix
from src.evaluation import evaluate_partition, silhouette_precomputed
from src.missing_data import audit_missingness, sensitivity_analysis
from src.preprocessing import apply_eligibility, select_observation_window
from src.profiling import name_pathways, pathway_prevalence, pathway_profiles, state_composition_by_time
from src.report_builder import ReportError, render_report, save_result
from src.stability import adjusted_rand_index, k_selection_table, select_k, stability_tables
from src.synthetic_data import generate_synthetic
from src.trajectories import build_trajectories, expand_labels
from src.visualization import (plot_baseline_vs_clusters, plot_k_selection, plot_medoid_sequences, plot_missingness, plot_prevalence,
                               plot_sequence_index, plot_silhouette, plot_stability_curves, plot_state_distribution, save_figure)

__all__ = ["STAGES", "GateError", "check_data_gate", "run", "main"]

STAGES = ("audit", "build", "benchmark", "cluster", "evaluate", "stability", "profile", "report")
QUICK_REPEATS = 3
EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_GATE = 0, 1, 2, 3


class GateError(Exception):
    """A real-data run was refused: the data have not passed the checks that must come first."""


class PipelineError(Exception):
    """A stage cannot run because something it needs is missing."""


# ---------------------------------------------------------------------------------------------
# Gate and settings
# ---------------------------------------------------------------------------------------------
def check_data_gate(cfg: Config) -> None:
    """Refuse a real run unless the data have passed the gate. Raises GateError naming the first unmet condition.

    Conditions include explicit CHECKPOINT 1 completion, documented b4q12 selection permission,
    a non-empty documented lost-code mapping, and dated/verified trainee timing before the existing
    plan, schema verification, and design checks. Missing statuses fail closed; synthetic runs bypass
    this real-data gate in `run()`.
    """
    d = cfg.to_dict()["data"]
    if str(d.get("checkpoint1_status", "UNRESOLVED")).upper() != "PASSED":
        raise GateError("CHECKPOINT 1 is not recorded as PASSED (data.checkpoint1_status)")
    if str(d.get("b4q12_permission_status", "UNRESOLVED")).upper() != "CONFIRMED":
        raise GateError("permission to select the sample using b4q12 is not confirmed (data.b4q12_permission_status)")
    if not cfg.to_dict().get("lost_codes"):
        raise GateError("lost_codes is empty: verify and document the release's casualty/nonresponse mapping before real analysis")
    if not cfg.to_dict().get("data", {}).get("schema", {}).get("nonresponse_col"):
        raise GateError("data.schema.nonresponse_col is unset: loss-to-follow-up records cannot be classified")
    trainee = cfg.to_dict().get("trainee", {})
    timing_evidence = trainee.get("timing_evidence") or {}
    if str(trainee.get("timing_support", "none")).lower() != "dated" or \
            str(timing_evidence.get("status", "UNVERIFIED")).upper() != "VERIFIED":
        raise GateError("training timing is not documented and verified as dated (trainee.timing_support/timing_evidence.status)")
    plan = str(d["plan"])
    if plan == "UNSET":
        raise GateError("data.plan is UNSET: run `python run_pipeline.py --stage audit` on the real files, paste the output "
                        "(CHECKPOINT 1), and choose Plan A, B or C before any modelling")
    if not bool(d["verified"]):
        raise GateError("data.verified is false: verify every mapping in data.schema, data.layouts and states against the official "
                        "data dictionary, then set data.verified: true and describe who checked what in data.verified_note")
    if plan in ("B", "C"):
        if not bool(d.get("scope_approved", False)):
            raise GateError(f"Plan {plan} needs docs/SCOPE_CHANGE_MEMO.md approved by your instructor (data.scope_approved: true)")
        raise GateError(f"Plan {plan} is not a trajectory analysis: this pipeline builds trajectories for Plan A only")
    if plan != "A":
        raise GateError(f"data.plan must be one of UNSET, A, B, C, got {plan!r}")
    try:
        verify_design_compatibility(cfg)
    except DesignMixError as exc:
        raise GateError(f"design check failed: {exc}") from exc


def _override(cfg: Config, **sections: dict[str, Any]) -> Config:
    d = cfg.to_dict()
    for name, values in sections.items():
        d[name] = {**d[name], **values}
    return Config(d, cfg.root)


def _run_settings(cfg: Config, synthetic: bool, quick: bool) -> tuple[Config, dict[str, Any]]:
    """The settings actually used: the results tag is fixed to the data tag, and --quick lowers the repeat counts."""
    over: dict[str, Any] = {"report.results_tag": "SYNTHETIC" if synthetic else "real"}
    secs: dict[str, dict[str, Any]] = {"report": {"results_tag": over["report.results_tag"]}}
    if quick:
        secs["stability"] = {"n_repeats": QUICK_REPEATS}
        secs["clustering"] = {"k_stability_repeats": QUICK_REPEATS}
        over.update({"stability.n_repeats": QUICK_REPEATS, "clustering.k_stability_repeats": QUICK_REPEATS})
    return _override(cfg, **secs), over


# ---------------------------------------------------------------------------------------------
# The pipeline object: lazily built, cached pieces shared by the stages
# ---------------------------------------------------------------------------------------------
class Pipeline:
    def __init__(self, cfg: Config, synthetic: bool, quick: bool = False, log: Callable[[str], None] = print) -> None:
        self.cfg, self.overrides = _run_settings(cfg, synthetic, quick)
        self.synthetic, self.quick, self.log = bool(synthetic), bool(quick), log
        self.warns: dict[str, list[str]] = {}
        self.saved: dict[str, Any] = {}          # name -> data exactly as stored on disk
        self.written: list[str] = []
        self.skipped: list[str] = []
        self._cache: dict[str, Any] = {}
        self._lock_checked = False

    # ----- bookkeeping
    @contextlib.contextmanager
    def watch(self, stage: str) -> Iterator[None]:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            yield
        msgs = self.warns.setdefault(stage, [])
        for w in caught:
            m = f"{w.category.__name__}: {str(w.message)[:300]}"
            if m not in msgs:
                msgs.append(m)

    def save(self, name: str, obj: Any) -> None:
        path = save_result(name, obj, self.cfg, self.synthetic)
        self.saved[name] = json.loads(path.read_text(encoding="utf-8"))["data"]
        if path.name not in self.written:
            self.written.append(path.name)

    def need(self, name: str, stage: str) -> Any:
        if name not in self.saved:
            raise PipelineError(f"result {name!r} is not available: run the {stage!r} stage first (in the same run)")
        return self.saved[name]

    def cached(self, key: str, build: Callable[[], Any]) -> Any:
        if key not in self._cache:
            self._cache[key] = build()
        return self._cache[key]

    # ----- data
    @property
    def truth(self) -> Any:
        if not self.synthetic:
            raise PipelineError("planted truth exists only for synthetic data")
        return self.cached("truth", lambda: generate_synthetic(self.cfg)[1])

    @property
    def td(self) -> Any:
        def build() -> Any:
            long_df = load_long_panel(self.cfg, synthetic=self.synthetic)
            self._cache["n_persons_panel"] = int(long_df["person_id"].nunique())
            trained = identify_trainees(long_df, self.cfg)
            window = select_observation_window(trained, self.cfg)
            td = apply_eligibility(build_trajectories(window, self.cfg), self.cfg)
            if td.is_synthetic != self.synthetic:
                raise PipelineError("the trajectory data's synthetic flag disagrees with the run: refusing to continue")
            return td
        with self.watch("build"):
            return self.cached("td", build)

    @property
    def planted_by_individual(self) -> np.ndarray:
        pid = np.array([int(x[1:]) for x in self.td.ids])
        return self.truth.labels[pid]

    # ----- distance
    @property
    def sub_cost(self) -> np.ndarray:
        return self.cached("sub_cost", lambda: substitution_cost_matrix(self.td, self.cfg))

    @property
    def plan(self) -> Any:
        return self.cached("plan", lambda: plan_reduction(self.td, self.cfg, make_rng(self.cfg, "pipeline/plan")))

    @property
    def D(self) -> np.ndarray:
        def build() -> np.ndarray:
            with self.watch("distance"):
                return build_distance(self.plan.col_fit, self.cfg, self.sub_cost)
        return self.cached("D", build)

    # ----- clustering
    def lock_baseline(self) -> None:
        if not self._lock_checked:
            with self.watch("baseline_lock"):
                try:
                    check_baseline_lock(self.cfg)
                except BaselineError as exc:
                    raise GateError(f"baseline lock: {exc}") from exc
            self._lock_checked = True

    @property
    def k_info(self) -> tuple[pd.DataFrame, int, str]:
        def build() -> tuple[pd.DataFrame, int, str]:
            self.lock_baseline()
            with self.watch("cluster"):
                table = k_selection_table(self.plan, self.D, self.cfg, make_rng(self.cfg, "pipeline/k_table"))
                k, reason = select_k(table, self.cfg)
            return table, int(k), reason
        return self.cached("k_info", build)

    @property
    def ref(self) -> Any:
        def build() -> Any:
            k = self.k_info[1]
            with self.watch("cluster"):
                return cluster_full(self.plan, self.D, self.cfg, k, make_rng(self.cfg, "pipeline/cluster"), self.sub_cost)
        return self.cached("ref", build)

    # ----- stages
    def stage_audit(self) -> None:
        if self.synthetic:
            self.save("missingness", audit_missingness(self.td, self.cfg))
            self.save("data_summary", self.data_summary())
            return
        if not self.cfg.data.files:
            self.log("Nothing to audit: data.files is empty. Fill data.files and data.layouts in config.yaml from the official data dictionary.")
            return
        report = run_audit(self.cfg)
        self.log(format_audit(report))
        self.save("audit", report)
        try:
            check_data_gate(self.cfg)
        except GateError as exc:
            self.log(f"(gate not passed yet, so no trajectories were built: {exc})")
            return
        self.save("missingness", audit_missingness(self.td, self.cfg))
        self.save("data_summary", self.data_summary())

    def data_summary(self) -> dict[str, Any]:
        td, cfg = self.td, self.cfg
        return {"is_synthetic": self.synthetic, "data_plan": "synthetic" if self.synthetic else str(cfg.data.plan),
                "n_persons_in_panel": self._cache.get("n_persons_panel"), "n_trainees_analysed": int(td.n), "n_time_points": int(td.T),
                "time_labels": list(td.time_labels), "state_names": list(td.state_names), "weights_attached": td.weights is not None,
                "min_time_points": int(cfg.trainee.min_time_points), "trainee_definition": str(cfg.trainee.definition),
                "timing_support": str(cfg.trainee.timing_support), "missing_policy": str(cfg.missing.policy),
                "distance": str(cfg.distance.name), "eligibility": td.meta.get("eligibility"),
                "records_by_kind": td.meta.get("records_by_kind")}

    def stage_build(self) -> None:
        self.save("data_summary", self.data_summary())
        self.log(f"  {self.td.n} trainees x {self.td.T} visits; {len(self.td.state_names)} states")

    def stage_benchmark(self) -> None:
        td = self.td
        sizes = sorted({s for s in ((100, 200) if self.quick else (100, 200, 400, 800)) if s <= td.n}) or [int(td.n)]
        with self.watch("benchmark"):
            dist = benchmark_distance(td, self.cfg, sizes)
            clus = benchmark_clustering(self.plan, self.cfg, sizes, make_rng(self.cfg, "pipeline/benchmark"))
        self.save("benchmark", {"sizes": sizes, "distance": dist, "clustering": clus,
                                "note": "measured on this machine; use them to replace the PLACEHOLDER distance.max_n and distance.max_matrix_mb in config.yaml"})

    def stage_cluster(self) -> None:
        td, plan, cfg = self.td, self.plan, self.cfg
        table, k, reason = self.k_info
        ref = self.ref
        fit = plan.col_fit
        cand, thr = medoid_candidates(fit, cfg, k)
        names = list(td.state_names)
        label = lambda s: names[s] if s >= 0 else ("missing" if s == MISSING else "lost")   # noqa: E731
        sizes = np.bincount(ref.full_labels, minlength=k)
        self.save("k_selection", {"table": table, "chosen_k": k, "reason": reason, "k_candidates": [int(x) for x in cfg.clustering.k_candidates]})
        self.save("clustering", {
            "k": k, "n_individuals": int(td.n),
            "reduction": {"mode_requested": plan.mode_requested, "mode_used": plan.mode_used, "n_units_all": int(plan.n_units_all),
                          "n_units_fit": int(plan.n_units_fit), "est_peak_mb": float(plan.est_peak_mb), "cap_mb": float(plan.cap_mb),
                          "max_n": int(plan.max_n), "reason": plan.reason},
            "fit": {"cost": float(ref.fit_result.cost), "converged": bool(ref.fit_result.converged), "n_iter": int(ref.fit_result.n_iter)},
            "medoid_min_observed_used": int(thr), "n_candidate_units": int(cand.sum()),
            "all_medoids_fully_observed": bool((ref.medoid_states >= 0).all()),
            "medoids": [{"pathway": j, "states": [label(int(s)) for s in ref.medoid_states[j]], "n_observed": int((ref.medoid_states[j] >= 0).sum()),
                         "size": int(sizes[j]), "share": float(sizes[j] / td.n)} for j in range(k)]})
        if self.synthetic:
            planted = self.planted_by_individual
            pnames = [p["name"] for p in cfg.to_dict()["synthetic"]["planted"]]
            cont = np.zeros((len(pnames), k), dtype=np.int64)
            np.add.at(cont, (planted, ref.full_labels), 1)
            self.save("planted_recovery", {
                "warning": "SYNTHETIC ONLY: this checks that the pipeline can find structure it was given. It is not a result about trainees.",
                "ari_kmedoids_vs_planted": adjusted_rand_index(planted, ref.full_labels),
                "planted_names": pnames, "contingency_planted_by_found": cont})
        self.log(f"  k = {k}; sizes {sizes.tolist()}; all medoids fully observed: {bool((ref.medoid_states >= 0).all())}")

    def stage_evaluate(self) -> None:
        td, plan, cfg, D = self.td, self.plan, self.cfg, self.D
        k, ref, fit = self.k_info[1], self.ref, plan.col_fit
        f = fit.freq.astype(np.float64)
        cand, _ = medoid_candidates(fit, cfg, k)
        with self.watch("evaluate"):
            ev_k = evaluate_partition(D, ref.fit_result.labels, cfg, ref.fit_result.medoid_idx, None, fit.freq, "fit_sample")
            hres = hierarchical(D, k, f, "average", cand)
            ev_h = evaluate_partition(D, hres.labels, cfg, hres.medoid_idx, None, fit.freq, "fit_sample")
        hier: dict[str, Any] = {"k": k, "linkage": "average", "ari_vs_kmedoids_fit_sample": adjusted_rand_index(ref.fit_result.labels, hres.labels, f),
                                "evaluation": ev_h, "sizes_individuals": ev_h["sizes"]}
        if self.synthetic:
            hier["warning"] = "SYNTHETIC ONLY"
            if plan.fit_unit_idx is None:
                hier["ari_hierarchical_vs_planted"] = adjusted_rand_index(self.planted_by_individual, expand_labels(plan.col_fit, hres.labels))
                hier["ari_kmedoids_vs_planted"] = adjusted_rand_index(self.planted_by_individual, ref.full_labels)
            else:
                hier["planted_note"] = "the fit set is a subsample, so recovery of the planted pathways is not computed for the hierarchical method"
        self.save("evaluation", {"kmedoids": ev_k, "hierarchical": ev_h})
        self.save("hierarchical_comparison", hier)

        # ----- baseline, scored on the same matrix and the same units as the pathways
        base = baseline_partition(td, cfg)
        unit_lab = baseline_unit_labels(fit, cfg)
        keep = np.flatnonzero(unit_lab >= 0)
        cmp = compare_to_clustering(base, ref.full_labels, td, cfg)
        block: dict[str, Any] = {"definition": base.definition, "counts": base.counts, "comparison": cmp, "n_units_compared": int(len(keep))}
        if len(keep) >= 3:
            _, lab_b = np.unique(unit_lab[keep], return_inverse=True)
            lab_c = np.unique(ref.fit_result.labels[keep], return_inverse=True)[1]
            Db, fb, cb = D[np.ix_(keep, keep)], fit.freq[keep], cand[keep]
            med_b = medoids_from_labels(Db, lab_b, fb.astype(np.float64), cb)
            med_c = medoids_from_labels(Db, lab_c, fb.astype(np.float64), cb)
            k_b = int(lab_b.max()) + 1
            with self.watch("evaluate"):
                like = {"baseline": evaluate_partition(Db, lab_b, cfg, med_b, None, fb, "fit_sample"),
                        "pathways_same_units": evaluate_partition(Db, lab_c, cfg, med_c, None, fb, "fit_sample")}
                if 2 <= k_b <= len(keep) and int(cb.sum()) >= k_b:
                    r2 = kmedoids(Db, k_b, int(cfg.clustering.n_init), int(cfg.clustering.max_iter), make_rng(cfg, "pipeline/baseline_same_k"),
                                  fb.astype(np.float64), cb)
                    like["clustering_same_k_as_baseline"] = evaluate_partition(Db, r2.labels, cfg, r2.medoid_idx, None, fb, "fit_sample")
                    like["k_of_baseline"] = k_b
            block["like_for_like"] = like
            block["like_for_like_note"] = ("baseline, pathways and a k-medoids clustering with the baseline's number of classes are all scored on the "
                                           "same units and the same distance matrix; silhouettes at different k are not directly comparable")
        else:
            block["like_for_like_note"] = "fewer than 3 baseline-eligible units: no like-for-like scores"
        sens = {}
        for lab, res in sensitivity_variants(cfg, td).items():
            c = compare_to_clustering(res, ref.full_labels, td, cfg)
            sens[lab] = {"definition": res.definition, "counts": res.counts, "ari": c["ari"], "nmi": c["nmi"], "n_compared": c["n_compared"],
                         "n_pathways_spanning_classes": c["n_pathways_spanning_classes"]}
        block["sensitivity"] = sens
        self.save("baseline", block)

        # ----- missing-data policies: the whole analysis again under each policy
        index = pd.Index(td.ids)

        def run_policy(tdp: Any) -> dict[str, float]:
            sc = substitution_cost_matrix(tdp, cfg)
            pl = plan_reduction(tdp, cfg, make_rng(cfg, "pipeline/sens_plan"))
            Dp = build_distance(pl.col_fit, cfg, sc)
            fp = cluster_full(pl, Dp, cfg, k, make_rng(cfg, "pipeline/sens_cluster"), sc)
            e = evaluate_partition(Dp, fp.fit_result.labels, cfg, fp.fit_result.medoid_idx, None, pl.col_fit.freq, "fit_sample")
            pos = index.get_indexer(tdp.ids)
            if (pos < 0).any():
                raise ValueError("a policy produced individuals that are not in the primary sample")
            sil = e["silhouette"]["overall"]
            return {"silhouette": float("nan") if sil is None else float(sil), "min_cluster_share": float(e["min_cluster_share"]),
                    "ari_vs_primary_pathways": adjusted_rand_index(ref.full_labels[pos], fp.full_labels)}
        with self.watch("missing_sensitivity"):
            table = sensitivity_analysis(td, cfg, None, run_policy)
        self.save("missing_sensitivity", {"table": table, "note": "each row repeats the whole analysis with the same k; the ARI compares with the primary pathways on the individuals both contain; a policy that cannot run keeps its error text"})

    def stage_stability(self) -> None:
        td, ref = self.td, self.ref
        with self.watch("stability"):
            curves, surv = stability_tables(td, self.cfg, ref)
        by = {}
        for r in curves.itertuples(index=False):
            key = f"censoring_{int(r.level)}visits" if r.scheme == "censoring" else f"{r.scheme}_{int(round(r.level * 100))}pct"
            by[key] = {"ari_mean": float(r.ari_mean), "ari_p05": float(r.ari_p05), "ari_min": float(r.ari_min),
                       "mean_pathway_survival": float(r.mean_pathway_survival), "min_pathway_survival": float(r.min_pathway_survival),
                       "n_retained_mean": float(r.n_retained_mean)}
        self.save("stability", {"curves": curves, "survival": surv, "by_setting": by, "n_repeats": int(self.cfg.stability.n_repeats),
                                "quick": self.quick, "survival_max_dist": float(self.cfg.stability.survival_max_dist)})

    def stage_profile(self) -> None:
        td, cfg, labels = self.td, self.cfg, self.ref.full_labels
        prev = pathway_prevalence(td, labels)
        prof = pathway_profiles(td, labels, cfg)
        names = name_pathways(prof, cfg)
        comp = state_composition_by_time(td, labels)
        by = {}
        for row in prof.to_dict("records"):
            by[str(row["pathway"])] = {"name": names[int(row["pathway"])], **row}
        self.save("profiles", {"names": {str(p): n for p, n in names.items()}, "profiles": prof, "by_pathway": by, "prevalence": prev,
                               "composition": comp, "weighted": bool(prof.attrs.get("weighted", False)), "variables": list(prof.attrs.get("variables", []))})

    def stage_report(self) -> None:
        td, cfg, ref, plan = self.td, self.cfg, self.ref, self.plan
        labels = ref.full_labels
        k_tab = pd.DataFrame(self.need("k_selection", "cluster")["table"])
        stab = pd.DataFrame(self.need("stability", "stability")["curves"])
        prev = pd.DataFrame(self.need("profiles", "profile")["prevalence"])
        cmpd = self.need("baseline", "evaluate")["comparison"]
        miss = self.need("missingness", "audit")
        _, per_unit = silhouette_precomputed(self.D, ref.fit_result.labels, plan.col_fit.freq.astype(np.float64))
        figs = {
            "state_distribution": plot_state_distribution(td, cfg),
            "state_distribution_by_pathway": plot_state_distribution(td, cfg, labels),
            "sequence_index": plot_sequence_index(td, cfg, labels),
            "medoid_sequences": plot_medoid_sequences(ref.medoid_states, td.state_names, cfg, prev),
            "prevalence": plot_prevalence(prev, cfg),
            "k_selection": plot_k_selection(k_tab, cfg, self.k_info[1]),
            "stability_curves": plot_stability_curves(stab, cfg),
            "baseline_vs_clusters": plot_baseline_vs_clusters(cmpd, cfg),
            "missingness": plot_missingness(miss, cfg),
            "silhouette": plot_silhouette(per_unit, ref.fit_result.labels, plan.col_fit.freq, cfg),
        }
        paths = [save_figure(f, n, cfg, self.synthetic).name for n, f in figs.items()]
        self.save("figures", {"files": paths})
        s = self.saved
        ev, st = s["evaluation"]["kmedoids"], s["stability"]["by_setting"]
        self.save("headline", {
            "is_synthetic": self.synthetic, "n_individuals": int(td.n), "n_units_fit": int(plan.n_units_fit), "k": self.k_info[1],
            "reduction_mode": plan.mode_used, "silhouette": ev["silhouette"]["overall"], "min_cluster_share": ev["min_cluster_share"],
            "hierarchical_ari_vs_kmedoids": s["hierarchical_comparison"]["ari_vs_kmedoids_fit_sample"],
            "baseline_ari": s["baseline"]["comparison"]["ari"], "baseline_nmi": s["baseline"]["comparison"]["nmi"],
            "stability_random_40pct_ari": st.get("random_40pct", {}).get("ari_mean"),
            "stability_censoring_2visits_ari": st.get("censoring_2visits", {}).get("ari_mean")})
        tpl = cfg.report.template
        tpl_path = (cfg.root / tpl).resolve() if tpl else resolve_path(cfg, "report_template")
        if not tpl_path.is_file():
            self.log(f"  figures written ({len(paths)}). Report render SKIPPED: template not found at {tpl_path}")
            self.skipped.append("report (template missing)")
            return
        self.log(f"  figures written ({len(paths)}); report: {render_report(cfg)}")


# ---------------------------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------------------------
def _save_run_meta(pipe: "Pipeline", synthetic: bool, done: list[str]) -> None:
    """Save `run_meta` (what ran, overrides, versions, warnings) and the config snapshot. Saving twice is safe: the later save wins."""
    import matplotlib
    import scipy
    import sklearn
    pipe.save("run_meta", {
        "is_synthetic": synthetic, "stages": done, "overrides": pipe.overrides, "skipped": list(pipe.skipped),
        "seed": int(pipe.cfg.project.seed), "warnings": pipe.warns,
        "versions": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__, "scipy": scipy.__version__,
                     "scikit_learn": sklearn.__version__, "matplotlib": matplotlib.__version__}})
    snapshot_config(pipe.cfg, resolve_path(pipe.cfg, "results_dir"))


def run(cfg: Config, stages: list[str], synthetic: bool, quick: bool = False, log: Callable[[str], None] = print) -> int:
    """Run the stages in order and return an exit code (0 done, 1 stage failed, 2 usage, 3 gate refused).

    A real run (synthetic False) is gated before any stage except `audit`. `quick` is allowed for synthetic data only.
    `run_meta` (what ran, overrides, versions, warnings) is saved just before the report stage renders, because the report
    template reads it, and saved again after the last stage so it also holds the report stage's own warnings.
    A failed stage stops the run.
    """
    bad = [s for s in stages if s not in STAGES]
    if bad:
        log(f"USAGE ERROR: unknown stage(s) {bad}; choose from {list(STAGES)}")
        return EXIT_USAGE
    if quick and not synthetic:
        log("USAGE ERROR: --quick lowers repeat counts and is for synthetic testing only; it is refused for real data")
        return EXIT_USAGE
    if synthetic:
        log("SYNTHETIC DEMONSTRATION - NOT PLFS RESULTS")
    pipe = Pipeline(cfg, synthetic, quick, log)
    status: list[tuple[str, str, float]] = []
    gated = synthetic
    for st in stages:
        t0 = time.perf_counter()
        log(f"[{st}] start")
        try:
            if st != "audit" and not gated:
                check_data_gate(pipe.cfg)
                gated = True
            if st == "report" and pipe.written:
                _save_run_meta(pipe, synthetic, [s for s, _, _ in status] + ["report"])   # the report template reads run_meta
            getattr(pipe, f"stage_{st}")()
        except GateError as exc:
            log(f"[{st}] REFUSED: {exc}")
            return EXIT_GATE
        except (ConfigError, SchemaError, DesignMixError) as exc:
            log(f"[{st}] CONFIG/DATA ERROR: {type(exc).__name__}: {exc}")
            return EXIT_USAGE if isinstance(exc, ConfigError) else EXIT_FAILED
        except (PipelineError, ReportError, ValueError, KeyError, MemoryError) as exc:
            log(f"[{st}] FAILED: {type(exc).__name__}: {exc}")
            return EXIT_FAILED
        dt = time.perf_counter() - t0
        status.append((st, "done", dt))
        log(f"[{st}] done in {dt:.1f} s")
    if pipe.written:
        _save_run_meta(pipe, synthetic, [s for s, _, _ in status])
    log("Stages: " + ", ".join(f"{s} ({d:.0f}s)" for s, _, d in status) + ("; skipped: " + ", ".join(pipe.skipped) if pipe.skipped else ""))
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python run_pipeline.py", description="Employment outcome pathway grouping: run the pipeline.")
    ap.add_argument("--config", default=None, help="path to config.yaml (default: the project's)")
    ap.add_argument("--synthetic", action="store_true", help="run on SYNTHETIC data (skips the real-data gate; everything is tagged SYNTHETIC)")
    ap.add_argument("--stage", default="all", choices=list(STAGES) + ["all"], help="one stage, or all (default)")
    ap.add_argument("--quick", action="store_true", help="fewer stability repeats (synthetic testing only)")
    ap.add_argument("--self-test", action="store_true", help="run the tests of this file itself")
    args = ap.parse_args(argv)
    if args.self_test:
        return _selftest()
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        return EXIT_USAGE
    stages = list(STAGES) if args.stage == "all" else [args.stage]
    return run(cfg, stages, args.synthetic, args.quick)


# ---------------------------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------------------------
def _selftest() -> int:
    cfg0 = load_config()
    tmp = Path(tempfile.mkdtemp(prefix="pipeline_selftest_"))

    def sandbox(name: str, n: int = 500) -> Config:
        return _override(cfg0, paths={"results_dir": str(tmp / name / "results"), "figures_dir": str(tmp / name / "figures"),
                                      "report_template": str(tmp / name / "no_template.md")}, synthetic={"n": n})

    def quiet(cfg: Config, stages: list[str], synthetic: bool, quick: bool = False) -> tuple[int, list[str]]:
        lines: list[str] = []
        return run(cfg, stages, synthetic, quick, lines.append), lines

    def raises(exc: type, fn: Callable[[], Any]) -> bool:
        try:
            fn()
        except exc:
            return True
        except Exception:
            return False
        return False

    print("SYNTHETIC DEMONSTRATION - NOT PLFS RESULTS")
    gate_cfgs = {
        "default config (plan UNSET)": cfg0,
        "plan A but not verified": _override(cfg0, data={"plan": "A", "verified": False}),
        "plan B without approval": _override(cfg0, data={"plan": "B", "verified": True, "scope_approved": False}),
        "plan C even when approved": _override(cfg0, data={"plan": "C", "verified": True, "scope_approved": True}),
        "plan A verified but no files": _override(cfg0, data={"plan": "A", "verified": True}),
    }
    gate_codes = {name: quiet(c, ["build"], False)[0] for name, c in gate_cfgs.items()}
    gate_raise = all(raises(GateError, lambda c=c: check_data_gate(c)) for c in gate_cfgs.values())
    code_audit, lines_audit = quiet(_override(cfg0, data={"files": []}), ["audit"], False)
    code_quick, _ = quiet(cfg0, ["build"], False, True)
    code_bad, _ = quiet(cfg0, ["nonsense"], True)
    code_need, lines_need = quiet(sandbox("need"), ["report"], True, True)

    cfg_a = sandbox("a")
    t0 = time.perf_counter()
    code_a, lines_a = quiet(cfg_a, list(STAGES), True, True)
    t_run = time.perf_counter() - t0
    rdir = resolve_path(cfg_a, "results_dir")
    fdir = resolve_path(cfg_a, "figures_dir")
    files = sorted(p.name for p in rdir.iterdir())
    figs = sorted(p.name for p in fdir.iterdir()) if fdir.exists() else []

    def res(name: str) -> Any:
        return json.loads((rdir / f"{name}__SYNTHETIC.json").read_text())["data"]

    expected = {"data_summary", "missingness", "benchmark", "k_selection", "clustering", "planted_recovery", "evaluation", "hierarchical_comparison",
                "baseline", "missing_sensitivity", "stability", "profiles", "figures", "headline", "run_meta"}
    k_sel, clus, base, stab_r, meta, heads = res("k_selection"), res("clustering"), res("baseline"), res("stability"), res("run_meta"), res("headline")
    miss_sens = pd.DataFrame(res("missing_sensitivity")["table"])

    # regression: a full run into an EMPTY results folder with the shipped report template (run_meta must exist before the report renders)
    cfg_c = _override(cfg0, paths={"results_dir": str(tmp / "c" / "results"), "figures_dir": str(tmp / "c" / "figures")}, synthetic={"n": 500})
    code_c, lines_c = quiet(cfg_c, list(STAGES), True, True)
    rep_c = resolve_path(cfg_c, "results_dir").parent / "report__SYNTHETIC.md"

    cfg_b1, cfg_b2 = sandbox("b1"), sandbox("b2")
    quiet(cfg_b1, ["cluster", "evaluate", "profile"], True, True)
    quiet(cfg_b2, ["cluster", "evaluate", "profile"], True, True)
    same = all((resolve_path(cfg_b1, "results_dir") / f"{n}__SYNTHETIC.json").read_bytes() == (resolve_path(cfg_b2, "results_dir") / f"{n}__SYNTHETIC.json").read_bytes()
               for n in ("k_selection", "clustering", "evaluation", "baseline", "profiles", "planted_recovery"))

    checks = {
        "gate: every unmet condition is refused with exit code 3 and by check_data_gate": all(c == EXIT_GATE for c in gate_codes.values()) and gate_raise,
        "gate: the audit stage needs no gate (nothing to audit is exit 0 with a message)": code_audit == EXIT_OK and any("Nothing to audit" in l for l in lines_audit),
        "usage errors: --quick on real data and an unknown stage are exit 2": code_quick == EXIT_USAGE and code_bad == EXIT_USAGE,
        "a stage that needs earlier results says so (exit 1)": code_need == EXIT_FAILED and any("run the" in l for l in lines_need),
        "all stages run on quick synthetic data (exit 0)": code_a == EXIT_OK and meta["stages"] == list(STAGES),
        "every expected result file exists, all tagged SYNTHETIC, none tagged real": expected <= {f.split("__")[0] for f in files if f.endswith("__SYNTHETIC.json")}
            and not any(f.endswith("__real.json") for f in files),
        "ten figures written, all tagged SYNTHETIC": len(figs) == 10 and all(f.endswith("__SYNTHETIC.png") for f in figs) and len(res("figures")["files"]) == 10,
        "the chosen k is a candidate and the clustering result agrees with the table": k_sel["chosen_k"] in k_sel["k_candidates"] and clus["k"] == k_sel["chosen_k"]
            and len(clus["medoids"]) == clus["k"] and sum(m["size"] for m in clus["medoids"]) == clus["n_individuals"],
        "v1.6: every medoid is fully observed and the candidate threshold is recorded": clus["all_medoids_fully_observed"] and clus["medoid_min_observed_used"] == 4,
        "the baseline was scored like for like on the same units (and at the baseline's k)": "like_for_like" in base and {"baseline", "pathways_same_units", "clustering_same_k_as_baseline"} <= set(base["like_for_like"]),
        "stability results are keyed for the report and the quick override is recorded": {"random_40pct", "censoring_2visits", "informative_10pct"} <= set(stab_r["by_setting"])
            and stab_r["quick"] is True and stab_r["n_repeats"] == QUICK_REPEATS and meta["overrides"]["stability.n_repeats"] == QUICK_REPEATS,
        "missing-data sensitivity: the primary row plus each policy, errors kept not hidden": len(miss_sens) == 4 and bool(miss_sens.loc[0, "is_primary"]) and "error" in miss_sens.columns,
        "the planted structure is recovered by the pipeline end to end (sanity of the wiring)": res("planted_recovery")["ari_kmedoids_vs_planted"] > 0.6
            and res("planted_recovery")["warning"].startswith("SYNTHETIC ONLY"),
        "the hierarchical comparison is reported with its agreement and recovery": "ari_vs_kmedoids_fit_sample" in res("hierarchical_comparison") and "ari_hierarchical_vs_planted" in res("hierarchical_comparison"),
        "the report stage writes figures and says the render was skipped when the template is missing": any("Report render SKIPPED" in l for l in lines_a) and meta["skipped"] == ["report (template missing)"],
        "a full run into an empty results folder renders the shipped report template, filled and tagged SYNTHETIC": code_c == EXIT_OK and rep_c.is_file()
            and "{{" not in rep_c.read_text(encoding="utf-8") and "SYNTHETIC" in rep_c.read_text(encoding="utf-8")[:600],
        "the headline collects what the report will quote": heads["is_synthetic"] is True and heads["k"] == clus["k"] and heads["baseline_ari"] is not None,
        "run_meta has versions and warnings, and no timings or dates": "versions" in meta and "warnings" in meta and "seconds" not in json.dumps(meta) and "2026" not in json.dumps(meta["versions"]),
        "config snapshot saved beside the results": (rdir / "config_snapshot.yaml").exists(),
        "two identical runs give identical result files (cluster, evaluate, profile)": same,
    }
    for name, ok in checks.items():
        print(f"  self-test [{'ok' if ok else 'FAILED'}]: {name}")
    print(f"  (one full quick run: {t_run:.0f} s; files in {tmp})")
    if not all(checks.values()):
        print("--- log of the full run ---\n" + "\n".join(lines_a[-30:]))
        print("gate codes:", gate_codes)
        print("--- log of the empty-folder run ---\n" + "\n".join(lines_c[-12:]))
        return 1
    print(f"Self-test passed ({len(checks)}). All data above is SYNTHETIC.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
