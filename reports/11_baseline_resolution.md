# Baseline inconsistencies resolved

**Project:** Employment Outcome Pathway Grouping After Skilling — INT396 | G24 (legacy PLFS review)  
**Dataset:** PLFS 2023–24, MoSPI Catalogue 213  
**Updated:** 2026-11-06

## Summary

The synthetic eligible-sample counts now reconcile at both source-row and person-visit-cell levels. The canonical active synthetic outputs are under `reports/results/` and figures under `reports/figures/`. The earlier notes claimed that `outputs/synthetic_demo/` was retained; that tree is absent from the current checkout. CWS mapping now follows the documented broad CWS categories without assigning meanings to 91–98 individually or to 99. The old aggregate `data.verified: true` claim is removed; separate validation states are recorded. The user-confirmed b4q12 permission is recorded as `user_confirmed`, with no profiling-variable whitelist inferred.

No raw data were modified. No real-data trajectories or clustering were run. CHECKPOINT 1 remains unresolved and the real-data gate remains closed.

## Fixes

1. **Eligible sample metadata:** `TrajectoryData` now carries an optional `recorded_mask`. Eligibility subsetting preserves it and recomputes source row counts for selected people. Pipeline summaries now report eligible row counts, eligible cell counts, no-source-row cells, and cell status counts separately. This fixes the prior mismatch where `records_by_kind` described all 2,000 synthetic people while missingness described only 1,912 eligible people.
2. **Regression coverage:** added row-count and cell-count reconciliation tests, including recorded missing values, lost records, and person-visit cells with no source row. The pipeline summary is tested against these counts.
3. **Canonical synthetic output:** `reports/results/` and `reports/figures/` are the active output source, matching config and dashboard behavior. The previous note claimed copies in `outputs/archive/2026-11-06-baseline-resolution/` and its `pre-final-canonical/` subdirectory; neither archive path exists in the current checkout. These absent directories are not included as release artifacts. The pre-audit external backup preserves the project as found for this completion pass.
4. **CWS mapping:** Instruction Manual Vol. I §3.6.14 (PDF pp. 104–106) documents 11–72 employed, 81/82 unemployed, and 91–98 out of labour force. Vol. I §§3.6.2 and 3.6.8 associate 61/62 with absence from self-employment work (11/12/21) and 71/72 with absence from regular salaried/wage work (31). Config now groups 61/62 with the broad self-employment state, 71/72 with wage employment, and all 91–98 codes only under broad out-of-labour-force. No individual meanings were invented for 91–98 or 99. Code 99 remains unclassified/MISSING. The prior `education_training` code 91 mapping was replaced with a reserved synthetic-only `SYNTHETIC:education_training` code, so 91 cannot map to that state in real data.
5. **Validation status:** `data.verified` is false. `validation` now separately records data integrity, mapping, linkage, permissions, profiling scope, and research readiness. Current values distinguish an audit with open schema items, documented broad groups with unresolved detail, an implemented candidate-link rule with identity unconfirmed, user-confirmed permission, unresolved profiling scope, and blocked readiness. Gate validation accepts only passed/validated integrity, mappings, linkage, and readiness states.
6. **Permission confirmation:** `data.b4q12_permission_status` and `validation.permissions` are `user_confirmed`. This records the user's statement in this session and does not infer profiling permissions, resolve unrelated semantics, or open CHECKPOINT 1.
7. **Dashboard and documentation:** the dashboard now displays the separate validation statuses. README, DATASET_SETUP, FINAL_AUDIT_REPORT, P4/P5 status notes, and the current readiness report identify the canonical output source, user-confirmed permission, corrected CWS handling, current synthetic figures, unresolved blockers, and gate state. Earlier reports remain preserved as historical snapshots.

## Reproduced synthetic counts

The current canonical result files are tagged `SYNTHETIC` and marked **SYNTHETIC DEMONSTRATION - NOT PLFS RESULTS**.

| Metric | Reproduced value |
|---|---:|
| Generated people in panel | 2,000 |
| Eligible synthetic people | 1,912 |
| Eligible source rows | 7,359 |
| Eligible person-visit cells | 7,648 |
| Eligible cells with no source row | 289 |
| Source rows: observed / missing-or-unknown / lost | 7,082 / 156 / 121 = 7,359 |
| Cells: observed / missing / lost | 7,082 / 445 / 121 = 7,648 |
| Missing cells | 156 recorded missing/unknown + 289 no-row = 445 |
| PAM clusters; silhouette | 6; 0.7879589 |
| Binary baseline ARI; hierarchical ARI | 0.2454451; 0.5613687 |
| Random 40% attrition ARI; censoring to 2 visits ARI | 0.9994880; 0.7649311 |

All row and cell sums reconcile. Missing stays separate from unemployment.

## Read-only CHECKPOINT 1 audit

Command: `python -m src.data_audit --no-write` (exit 0). The command did not write the real audit output. It emitted two pandas `FutureWarning`s at `src/data_audit.py:813` in ambiguity-report formatting.

- Person records: 922,599; candidate keys: 546,423; candidate keys at 2+ visits: 211,111.
- Legacy key/time collisions: 3,390 groups and 3,390 excess rows. Quarter/visit coordinate collisions: 0 groups and 0 excess rows. These are key collisions, not confirmed duplicate records.
- Candidate mismatch diagnostics: 238 keys with sex changes, 710 with any raw age change, 648 with any compared design-field change. Persistent person-link validity is unconfirmed; none of these candidates were excluded.
- Audit schema issues: `data.verified` false, longitudinal weight unset, `lost_codes_status` unresolved, and configured code 96 absent from the inspected status values.
- CHECKPOINT 1 is not passed. `data.plan` remains `UNSET`.

## Tests

`python -B -m pytest -q -p no:cacheprovider`: **175 passed, 3 warnings, exit 0**. Warnings are existing maximum-distance warnings for pairs with fewer than two jointly observed visits. Tests cover documented broad CWS grouping, no invented CWS labels, synthetic-only education code isolation, row/cell reconciliation, real-gate validation states, and dashboard permission/status behavior.

The full synthetic pipeline was also run using the existing methodology and model-selection settings. It wrote only tagged synthetic results to the canonical output folders. It did not run a real-data trajectory or clustering stage.

## Important hashes and workspace state

Raw CSV SHA-256 hashes (unchanged):

- `data/raw/perv1.csv`: `b852af28508a230270b2d371e5a975230dbc363982bad97d1dc8f2601c2664f6`
- `data/raw/perrv.csv`: `2a20a9d4ce8276c4b713494a126d54a8521596239d63e5d4a8dd4f7c5bc00963`
- `data/raw/hhv1.csv`: `abf63f803b7239f8f3f316ffc28ff44587d99c94362bfad7ab0989049d7c9b2e`
- `data/raw/hhrv.csv`: `244bdf31d3a4ef42ea2794f4c1f93db1e2a3569b252a563f6a2028182a7ae9b2`
- `config.yaml` after this work: `844caa9f47602632b42b8978c7c8bb027d526c8055a4ae06d074a25297aa6c7d`

Git branch is `master`. The worktree was already dirty at the start of this task; existing code, reports, config, tests, audit output, and link-quality flag changes were preserved. Current `git status --short` also includes this task's edits, regenerated canonical synthetic results/figures, and new preserved output archives. No Git reset, commit, or deletion was performed.

Files changed in this task include:

- Code/config: `src/__init__.py`, `src/trajectories.py`, `src/synthetic_data.py`, `src/missing_data.py`, `src/config.py`, `run_pipeline.py`, `config.yaml`, `dashboard/app.py`.
- Regression tests: `tests/test_trajectories.py`, `tests/test_real_safety_gate.py`, `tests/test_dashboard_safety.py`, `tests/test_stability.py`, `tests/test_planted_structure.py`, `tests/test_distances.py`.
- Documentation: `docs/INTERFACES.md`, `README.md`, `DATASET_SETUP.md`, `reports/report_template.md`, historical status notes in `reports/02_mospi_verification.md`, `reports/06_checkpoint1.md`, `reports/P2_fixes.md`, `reports/P3_linkage.md`, `reports/P4_permissions.md`, and `reports/P5_analysis.md`, plus `reports/10_readiness.md`, `FINAL_AUDIT_REPORT.md`, and this report.
- Generated synthetic output updates: `reports/results/`, `reports/figures/`, `reports/report__SYNTHETIC.md`. Earlier notes mentioned snapshots under `outputs/archive/2026-11-06-baseline-resolution/`; that path is absent from the current checkout (see the correction in section 3 above).

These are the files changed during this task; they coexist with pre-existing modifications visible in the working tree. No raw data files were changed.

## Remaining blockers and next actions

1. Record a valid CHECKPOINT 1 decision and user-approved `data.plan`.
2. Obtain authoritative confirmation of the persistent person-link rule and design-field invariants.
3. Resolve the meaning of code 99 and individual CWS codes 91–98 if finer classification is needed; do not infer.
4. Resolve whether person-level lost codes exist and how to handle them.
5. Prove that training completion precedes each trajectory observation. `b4pt1q3` is only a last-365-days flag and does not establish order.
6. Obtain the allowed profiling-variable/output scope; no whitelist is currently configured.
7. Confirm whether a documented multiplier is valid for linked longitudinal pathway estimates.
8. Rerun CHECKPOINT 1 and the complete test suite after those items are resolved. Real clustering must remain unrun until all gate conditions pass.
