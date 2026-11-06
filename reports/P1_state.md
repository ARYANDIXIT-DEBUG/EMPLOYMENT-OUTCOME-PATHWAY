# P1 workspace state

Inspection date: 2026-11-06. Scope: reports/01–06, current `config.yaml`, `src/data_loader.py`, `src/data_audit.py`, `tests/`, and full pytest. No project code, configuration, source data, or analysis outputs were modified for this P1 inspection. This report is the requested new artifact.

## Done

- Read reports 01–06 and reconciled their status against the current code and tests. Reports 01, 03, 04, and 05 contain historical implementation or failure snapshots; their results are not current. Report 02 remains the official-document availability assessment. Report 06 records the later quarter-aware CHECKPOINT 1 run and still marks real analysis BLOCKED. The current overall readiness and gate status are in `reports/10_readiness.md`.
- Confirmed `src/data_loader.py` implements `quarter_aware_link_keys`, and `src/data_audit.py::_linkage` imports and calls that helper. The audit also reports the legacy key/visit collision count for comparison; its compatibility field `duplicate_key_time_pairs` is null because collisions do not prove identical rows.
- Confirmed the loader retains records and sets `n_records_excluded` to zero; inconsistent and incomplete links are represented by `link_quality_flag`. Missing/unknown CWS and missing visit observations remain MISSING, not unemployment; tests cover this behavior.
- Inventoried local data without altering it: 4 PLFS CSV files in `data/raw/` (a total of 1,157,363 rows, per report 01) and `outputs/link_quality_flags.csv` (aggregate table, no person keys). The raw CSVs total about 269 MB and are excluded from the baseline Git commit.
- Ran full pytest: **153 passed, 3 warnings, exit 0** in 18.64 seconds. The warnings are distance-pair cases with fewer than two jointly observed points assigned the configured maximum cost.
- The workspace initially had no Git repository. Initialized Git and created one baseline commit after excluding `data/raw/*.csv`, `.venv/`, `__pycache__/`, and `.pytest_cache/`. No real microdata was staged.

## Current state and report reconciliation

| Topic | Current verified state | Historical report reconciliation |
|---|---|---|
| Configuration and gate | `data.plan: UNSET`; `data.verified: true`; `lost_codes: []`; `data.schema.nonresponse_col: null`; weight unset; `profiling.permitted_vars: []`; timing support is `coarse_flag`. The gate requires an explicit passed CHECKPOINT 1, confirmed b4q12 permission, documented lost codes and nonresponse field, dated verified timing, Plan A, schema verification, and design compatibility. The current configuration does not meet these conditions. | Report 01 describes the earlier legacy-only audit/test state. Report 05 correctly records that no official lost code can be inferred; its pytest failure is historical because synthetic tests now use a generator-only sentinel. |
| Linkage | Loader and audit share quarter-aware candidate-link logic. The last reproduced real-data audit in report 06 found 546,423 candidate groups, 211,111 with 2+ visits, 0 quarter/visit collision groups, and 3,390 legacy key/visit collision groups. These are candidate-key diagnostics, not confirmed person matches or identical-row duplicates. | Report 01’s 542,755 legacy keys and 209,902 linked keys are pre-synchronization figures. Report 03’s 3,390 legacy collision count is retained as a diagnostic; its older test outcome is superseded by the current suite. |
| Cross-visit quality | Report 04 records 238 candidate keys with sex changes and 710 with any raw age change. Official design-field comparison and age tolerance remain unassessed; every case is unresolved. The aggregate flag table reports zero exclusions. | Report 04 is a historical flag audit, but its counts remain the latest reported reproduced flag counts. Its initial pytest failure note is superseded. |
| Tests | Current full suite: 153 passed, 3 warnings. Gate tests use temporary configs. | Reports 01, 03, 04, and 05 document the old collection/runtime failures; retain them as history, not current test status. |
| Official semantics and permission | Report 02 finds the Catalogue 213 data dictionary/layout, instruction manual, release notes, and release-specific data-use rider absent from the workspace. Identifier completeness, quarter/visit semantics, CWS and lost codes, timing, weights, profiling permissions, and b4q12 selection permission remain unconfirmed. | No later code or tests can substitute for those official sources or written authorization. Report 06 therefore correctly remains BLOCKED. |

The earlier configuration comment says some fields were verified against Catalogue 213 materials. That claim is not supported by the current workspace document set described in report 02 and must not be treated as clearing the real-data gate. The config’s `verified: true` does not override the missing evidence or other explicit gate conditions.

## Unfinished

1. Obtain official Catalogue 213 person/household dictionaries and layouts, the instruction manual, release notes, and the actual 2023–24 rider/terms.
2. Verify the complete linking key, visit/quarter relationship, sample-design fields, CWS and casualty codes, training timing, and any linked-analysis weight from those sources.
3. Obtain written authority on whether `b4q12` may select the analysis sample; leave the permission unresolved until then.
4. Resolve the sex/age link flags with documented identifiers and an official age tolerance; do not delete or exclude records based on current flags.
5. Only after evidence is reviewed, resolve the CHECKPOINT 1 decision and any authorized Plan A configuration. Do not start real trajectories or clustering before then.

## Blocked

- **Real-data analysis:** blocked by CHECKPOINT 1 and unresolved official identifiers/code mappings.
- **Use of b4q12 for selection:** permission is unresolved; do not set the permission flag to confirmed without written evidence.
- **Lost/attrition classification and post-training interpretation:** lost codes/nonresponse field are unconfirmed, and the current coarse training flag does not establish training before observations.
- **Weighted estimates and permitted profiling:** longitudinal weight validity and rider permissions are unconfirmed; current real weighting is unset and profiling variables are empty.

## Independent work completed

- Full pytest was run as requested; no code or test changes were needed.
- Git was initialized and one baseline commit was made. Raw PLFS CSVs and local environment/cache directories were excluded. The commit contains project source, tests, configuration, reports, documentation, and the aggregate flag table; it does not contain raw microdata.
- No real-data audit or pipeline was rerun because the current report already records the latest no-write audit and the instruction was not to redo completed work.
