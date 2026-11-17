# P5 analysis — Branch B

> **SYNTHETIC DEMONSTRATION - NOT PLFS RESULTS**

## Branch decision

**Branch B taken.** The real-data branch requires every listed precondition; several are not met. I reran CHECKPOINT 1 as requested, using `python -m src.data_audit --no-write`, then did not build or cluster real trajectories.

| Real-data precondition | Current evidence | Met? |
|---|---|---|
| CHECKPOINT 1 passes | The audit ran, but `data.checkpoint1_status` is not recorded as PASSED. It reports unresolved lost-code status and other schema issues. | **No** |
| `data.plan` set by the user | `data.plan: UNSET`. | **No** |
| Written `b4q12` selection permission | P4 marks this **UNRESOLVED**; no permission flag is set. | **No** |
| Lost codes documented or explicitly unavailable | P2/P4 establish **UNRESOLVED**, with `lost_codes: []`; the documents do not explicitly state that no person-level code exists. | **No** |
| Identifiers documented for persistent person linkage | P4 documents the person-record key, but the persistent across-visit linking rule remains **UNRESOLVED**; the configured candidate key omits sector from that documented record key. | **No** |
| Training completion proven before all employment observations | The project has only a coarse completion flag; P4 does not establish person-specific completion dates relative to all observations. No real person-level pass/fail/undeterminable timing classification was made. | **No** |

If a real trajectory analysis is later authorized without stronger timing evidence, it must be described as **“trainee employment trajectories (timing unverified)”**, not post-training pathways. The current results below are synthetic and make no statement about PLFS trainees.

## CHECKPOINT 1 rerun

The real-data audit read the configured files to reassess the gate. It reported 922,599 person records, 546,423 candidate cohort keys, 3,390 legacy key-collision groups / excess rows, zero quarter/visit key-collision groups / excess rows, and 211,111 candidate keys observed at 2+ visits. Those are candidate-key diagnostics, not verified person matches or duplicate rows. The audit found 238 candidate keys with sex changes, 710 with raw age changes, and 648 with compared design-field changes. P3 documents these diagnostics and unresolved interpretations.

The audit reported three schema issues: weight is unset, lost-code status is unresolved, and configured CWS code 96 does not occur in the files. The CLI completed the audit, but no CHECKPOINT 1 approval status is recorded, and the real-data gate remains closed. No real trajectories, real clustering, or real profiling were run.

## Synthetic pipeline run

The existing full pipeline ran with `--synthetic --stage all`, without `--quick` and without model or selection-rule changes. A temporary configuration redirected results and figures to `outputs/synthetic_demo/`; it was removed afterward. The normal `config.yaml` remains unchanged by this run, including `data.plan: UNSET`, absent checkpoint/permission statuses, and `lost_codes_status: unresolved`.

The generated report and artifacts are explicitly tagged `SYNTHETIC`:

- [Current synthetic pipeline report directory](results/)
- [Current synthetic figures directory](figures/)

### Data and prevalence

The synthetic generator produced 2,000 people. The existing eligibility rule retained 1,912 with at least 3 observed states and left 88 below that analysis threshold. The 1,912 eligible synthetic records contain 7,245 observed state cells, 211 unknown/missing cells, and 163 synthetic lost-to-follow-up cells. No missing or lost cell was coded as an employment state.

The pathway prevalence below is **unweighted synthetic-sample prevalence**. P4 does not validate PLFS weights for longitudinal estimates, and no PLFS weight was applied. The pipeline attached synthetic weights for testing, but the saved profile result records `weighted: false`. The profile result also records `variables: []`; no attribute profile was produced. P4 confirms no real-data profiling variables as rider-permitted.

| PAM pathway | Synthetic people | Unweighted prevalence |
|---:|---:|---:|
| 0 | 537 | 28.09% |
| 1 | 341 | 17.83% |
| 2 | 341 | 17.83% |
| 3 | 265 | 13.86% |
| 4 | 225 | 11.77% |
| 5 | 203 | 10.62% |

### PAM selection and silhouette

The existing k-selection rule selected **k = 6**. It excludes k=2 because its stability ARI is below 0.6, and k=7 and k=8 because each produces a cluster below the configured 2% minimum. No parameters were tuned.

| k | PAM silhouette | Stability ARI mean | Smallest cluster share | Existing-rule note |
|---:|---:|---:|---:|---|
| 2 | 0.4982 | 0.4661 | 18.62% | Fails stability minimum |
| 3 | 0.6556 | 1.0000 | 17.89% | Admissible |
| 4 | 0.5902 | 1.0000 | 13.86% | Admissible |
| 5 | 0.6990 | 0.9000 | 11.77% | Admissible |
| 6 | 0.7880 | 1.0000 | 10.62% | Selected by existing silhouette-margin rule |
| 7 | 0.7833 | 0.9927 | 0.99% | Fails minimum cluster share |
| 8 | 0.7629 | 0.9923 | 0.99% | Fails minimum cluster share |

PAM used 251 collapsed sequence units to represent the 1,912 eligible synthetic people; the exact collapse preserved the pathway counts. The overall PAM silhouette was 0.7880. This describes separation under the configured synthetic distance, not validity for PLFS.

### Hierarchical comparison and mandatory binary baseline

Average-linkage hierarchical clustering was run at the same k on the same synthetic distance. Its silhouette was **0.5869**, and its adjusted Rand index versus PAM was **0.5614**. It produced two very small clusters of 4 and 2 people (0.21% and 0.10%), below the configured 2% cluster-size threshold. This comparison is reported as produced; no tuning was applied.

The required binary baseline used employment status at synthetic visit 4. Of 1,912 eligible people, 1,792 had an observed baseline state; 120 were unknown at that visit and excluded from the baseline comparison only. Baseline/PAM agreement was **ARI 0.2454** and **NMI 0.4174**. On the like-for-like two-cluster comparison, the binary baseline silhouette was 0.410 and PAM at k=2 was 0.498. These are synthetic comparisons, not evidence about PLFS.

### Attrition stability

The configured 30-repeat stability analysis completed. Random and informative loss remained highly stable in this synthetic sample. Censoring to two visits reduced both agreement and pathway survival.

| Stability setting | Mean ARI vs. reference | Mean pathway survival | Minimum pathway survival |
|---|---:|---:|---:|
| Random 40% loss | 0.9995 | 1.0000 | 1.0000 |
| Informative 40% loss | 0.9992 | 1.0000 | 1.0000 |
| Censor to 3 visits | 0.9509 | 1.0000 | 1.0000 |
| Censor to 2 visits | 0.7649 | 0.8333 | 0.0000 |

The 2-visit result shows that at least one pathway was not recovered under the configured medoid-survival criterion; it should be treated as a limitation of the shortened observation window.

## Gate and blockers

The real-data gate remains closed. `config.yaml` was not granted a plan, checkpoint pass, `b4q12` permission, or lost-code resolution. Identifier semantics, longitudinal weight validity, timing proof, and permitted profiling variables remain unresolved under P2–P4. Synthetic results and artifacts must not be cited as PLFS estimates or trainee outcomes.
# Historical snapshot note (2026-11-06)

This run remains synthetic and is preserved as a historical report. The user has since confirmed required PLFS permissions, recorded in current `config.yaml` as `user_confirmed`; no profiling whitelist is inferred. The current synthetic results and figures are in `reports/results/` and `reports/figures/`, generated after eligible-row/cell metadata reconciliation. The temporary `outputs/synthetic_demo/` directory and the archive locations claimed in earlier notes are absent from the current checkout; those files are not current deliverables. See [11_baseline_resolution.md](11_baseline_resolution.md).

