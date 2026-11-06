# Workspace inspection — SIH26135 / PLFS 2023–24

> Historical baseline snapshot before Prompts 3–10. Its legacy-linking, permission, and pytest statements reflect the code/configuration at that inspection point. For current quarter-aware audit status, gate conditions, full-suite result, and readiness, see `reports/06_checkpoint1.md` and `reports/10_readiness.md`.

Inspection date: 2026-11-06 (Asia/Kolkata)

## Scope and read-only checks

Inspected the workspace tree, current config, loader, audit/linkage logic, permission notes, test modules, and raw-data metadata. Ran the Checkpoint 1 audit with `--no-write`, inventoried CSVs by streaming them, and ran pytest with Python bytecode and pytest cache writes disabled. No source code, configuration, data, or pipeline outputs were changed for this inspection. This Markdown report is the requested output artifact.

## Workspace tree

The workspace has no `.git` directory. It is not a Git checkout from this path.

```text
.
├── config.yaml
├── DATASET_SETUP.md
├── FINAL_AUDIT_REPORT.md
├── PROJECT_MANIFEST.md
├── README.md
├── VIVA_GUIDE.md
├── requirements.txt
├── requirements.lock.txt
├── run_pipeline.py
├── dashboard/
│   └── app.py
├── data/
│   └── raw/
│       ├── .gitkeep
│       ├── hhrv.csv
│       ├── hhv1.csv
│       ├── perrv.csv
│       └── perv1.csv
├── docs/
│   ├── DATA_USE_ASSESSMENT.md
│   └── INTERFACES.md
├── reports/
│   ├── figures/
│   │   ├── baseline_vs_clusters__SYNTHETIC.png
│   │   ├── k_selection__SYNTHETIC.png
│   │   ├── medoid_sequences__SYNTHETIC.png
│   │   ├── missingness__SYNTHETIC.png
│   │   ├── prevalence__SYNTHETIC.png
│   │   ├── sequence_index__SYNTHETIC.png
│   │   ├── silhouette__SYNTHETIC.png
│   │   ├── stability_curves__SYNTHETIC.png
│   │   ├── state_distribution__SYNTHETIC.png
│   │   └── state_distribution_by_pathway__SYNTHETIC.png
│   ├── results/
│   │   ├── audit__real.json
│   │   ├── baseline__SYNTHETIC.json
│   │   ├── benchmark__SYNTHETIC.json
│   │   ├── clustering__SYNTHETIC.json
│   │   ├── config_snapshot.yaml
│   │   ├── data_summary__SYNTHETIC.json
│   │   ├── evaluation__SYNTHETIC.json
│   │   ├── figures__SYNTHETIC.json
│   │   ├── headline__SYNTHETIC.json
│   │   ├── hierarchical_comparison__SYNTHETIC.json
│   │   ├── k_selection__SYNTHETIC.json
│   │   ├── missing_sensitivity__SYNTHETIC.json
│   │   ├── missingness__SYNTHETIC.json
│   │   ├── planted_recovery__SYNTHETIC.json
│   │   ├── profiles__SYNTHETIC.json
│   │   ├── run_meta__SYNTHETIC.json
│   │   └── stability__SYNTHETIC.json
│   ├── 01_workspace_inspection.md  # this report
│   ├── report__SYNTHETIC.md
│   └── report_template.md
├── scripts/
│   └── build_release.py
├── src/
│   ├── __init__.py
│   ├── baseline.py
│   ├── clustering.py
│   ├── config.py
│   ├── data_audit.py
│   ├── data_loader.py
│   ├── distances.py
│   ├── evaluation.py
│   ├── missing_data.py
│   ├── preprocessing.py
│   ├── profiling.py
│   ├── report_builder.py
│   ├── stability.py
│   ├── synthetic_data.py
│   ├── trajectories.py
│   └── visualization.py
└── tests/
    ├── test_data_loader_linkage.py
    ├── test_distances.py
    ├── test_evaluation.py
    ├── test_planted_structure.py
    ├── test_stability.py
    └── test_trajectories.py
```

`.venv`, `__pycache__`, and `.pytest_cache` are local environment/cache directories and are omitted from the project tree above.

### Git status, diff, and working changes

`git rev-parse --show-toplevel`, `git status`, and `git diff` fail with “not a git repository”; consequently there is no reproducible Git status or baseline diff, and tracked/uncommitted status cannot be established. The current files include changes made in this conversation before this inspection: `src/data_loader.py`, `config.yaml`, and `tests/test_data_loader_linkage.py`. This is conversation history, not a Git-derived diff.

## Config and architecture reviewed

- `config.yaml` declares PLFS 2023–24, MoSPI catalogue 213; files `perv1`, `perrv`, `hhv1`, `hhrv`; primary person layouts are the first two. Its current `data.plan` is `UNSET`, `data.verified` is `true`, `lost_codes` is `[]`, and `profiling.permitted_vars` is `[]`.
- The schema declares six stable key fields (state, FSU, sample Sg/Sb, second-stage stratum, sample household, person serial), `visit`, and `quarter: qtr`. Weight and person-file nonresponse/casualty columns remain null.
- `src/data_loader.py` has quarter-aware logic. It requires Q1–Q4 and V1–V4, rejects duplicate sample-key/quarter/visit rows, derives a cohort quarter as `(survey quarter - visit number) modulo 4`, and retains the existing sex/age link checks. This behavior is in the loader, not the audit linkage calculation.
- `src/data_audit.py` builds a person frame from the configured static key and visit only. `_linkage` counts duplicate pairs with `f.duplicated(["key", "t"])`; it does not include `data.schema.quarter` or derive a cohort quarter. The audit therefore still uses the legacy duplicate rule.
- `run_pipeline.check_data_gate` refuses a real run while `data.plan == "UNSET"`. No clustering, dashboard pipeline, or real trajectory pipeline was run in this inspection.

## Raw data inventory

CSV counts were obtained by parsing records and headers; the files were not rewritten.

| File | Data rows | Columns |
|---|---:|---:|
| `data/raw/perv1.csv` | 418,159 | 139 |
| `data/raw/perrv.csv` | 504,440 | 104 |
| `data/raw/hhv1.csv` | 101,920 | 37 |
| `data/raw/hhrv.csv` | 132,844 | 32 |

The two person files total 922,599 rows; the two household files total 234,764 rows; all four CSVs total 1,157,363 rows. `data/raw/.gitkeep` is empty and is not a dataset.

## CHECKPOINT 1 status

Ran `python -m src.data_audit --config config.yaml --no-write` (exit code 0; no read errors). The report says `plan=UNSET`, `verified=True`, and linkage `status=ok`, but it also emits a linkage issue: **3,390 duplicate (key, time) pairs**. “Status=ok” describes report calculation; it does not clear the issue.

Other audit findings relevant to readiness:

- 922,599 person records; 542,755 legacy person keys; no records missing a full key.
- Legacy linkage: 209,902 keys at 2+ visits (38.7%), 22.9% at the configured minimum of 3 visits, and 7.8% at all 4 visits.
- Legacy link checks report 1,448 keys with changing sex and 4,057 with age span over one year; the audit reports these, it does not remove them.
- Schema issues: no verified longitudinal weight and no person-file nonresponse/casualty field. The audit cannot produce weighted estimates or classify casualty records.
- Current software gate is closed by `data.plan: UNSET`; the audit command itself is permitted while the gate is closed.

## Quarter-linking and duplicate interpretation

At this initial inspection, quarter-aware logic was present in `src/data_loader.py` but not in `data_audit.py`. Prompt 3 later synchronized both through the loader's shared helper; Prompt 6 reproduced 3,390 legacy key/time collision groups and zero quarter/visit collision groups. These remain candidate-key diagnostics, not confirmed duplicate records.

## Tests and `lost_codes`

Confirmed `lost_codes: []` in `config.yaml` (line 364 at inspection). The normal full-suite command stops at collection:

```text
ERROR collecting tests/test_trajectories.py
tests/test_trajectories.py:35
UNK, LOSTC = str(D["unknown_codes"][0]), str(D["lost_codes"][0])
IndexError: list index out of range
```

To capture outcomes from the other modules too, ran:
`python -B -m pytest tests -q -p no:cacheprovider --continue-on-collection-errors --tb=short`

Result: **88 passed, 4 failed, 16 errors** (exit code 1; 36.77 seconds). Exact failed tests:

- `tests/test_distances.py::test_collapsed_estimate_equals_individual_estimate`
- `tests/test_distances.py::test_collapsing_does_not_change_distances_between_people`
- `tests/test_planted_structure.py::test_collapsing_does_not_change_the_answer`
- `tests/test_planted_structure.py::test_more_noise_means_worse_recovery_and_a_lower_silhouette`

All four fail because `src/synthetic_data.py::_state_setup` raises `ConfigError: unknown_codes and lost_codes must each hold at least one code for the generator`. The 15 setup errors are the other planted-structure and stability tests that hit the same `ConfigError`; the sixteenth error is the `test_trajectories.py` collection `IndexError` above. No code or config was changed to invent a lost-to-follow-up code.

## Recorded `b4q12` permission status

`docs/DATA_USE_ASSESSMENT.md` rates using the training variable to select the trainee sample **Unclear**, states the author has not read the actual rider, and has an unfilled instructor decision log. `profiling.permitted_vars` is empty. The config declares `b4q12` as the trainee variable, but that declaration is not evidence of permission. **Permission is not recorded as granted; do not treat it as granted.** The audit mechanically reports training-variable counts and explicitly marks the variable ambiguous; this inspection does not treat those counts as authorization or as a trainee analysis.

## Prioritized blockers

1. **Checkpoint 1 linkage mismatch:** update/review audit logic so it evaluates quarter-aware cohort identity; then reconcile the duplicate finding before any real-data analysis.
2. **Person-match validation:** the current audit and loader have different linkage definitions. Confirm the cohort identity against all relevant official sample-design fields and reconcile link-validity/exclusion results before treating matches as established.
3. **Broken test configuration:** `lost_codes` is empty while tests and the synthetic generator require one. Resolve the synthetic-test contract without guessing a real PLFS casualty code; then rerun the complete suite.
4. **Unresolved data-use permission:** obtain and record the actual MoSPI rider/instructor decision before selecting cases using `b4q12`; keep profiling permissions empty until cleared.
5. **Unresolved measurement fields:** verify longitudinal weight applicability and whether casualty/nonresponse can be represented; do not imply weighted or attrition-adjusted results until resolved.

## Reproducibility notes

The Git status/diff could not be reproduced because this directory has no Git metadata. CSV inventory and Checkpoint 1 were reproducible from the local files. Full pytest did not pass; the errors above are the observed results, not estimates. No clustering or real trajectory result was produced.
