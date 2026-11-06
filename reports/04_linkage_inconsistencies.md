# Cross-visit linkage inconsistencies

> Historical linkage-flag audit. Its initial full-pytest collection note predates the synthetic-only LOST sentinel fix; current final test results and gate status are in `reports/10_readiness.md`.

Inspection date: 2026-11-06. The analysis rebuilt candidate links from `data/raw/perv1.csv` and `data/raw/perrv.csv`; no saved cross-visit match output existed in `outputs/` before this run. It read the configured six candidate-key fields, quarter, visit, sex, and age only. No training variables were read. Counts describe candidate links under the local quarter-aware rule, not verified person identities.

## Documentation limits and classification

`reports/02_mospi_verification.md` records that the official Catalogue 213 data dictionary/layout, instruction manual, release notes, and data-use rider were not available in the workspace. Therefore the official completeness/stability of the candidate key and quarter/visit semantics are unconfirmed. The documentation also provides no official age-change tolerance, and the configured/previously coded one-year threshold is not an official tolerance. The local person layouts do not include a verified complete set of sample-design fields for cross-visit comparison.

Every pair is consequently classified **unresolved**. The observed changes cannot reliably separate a probable key collision from data-entry error or legitimate change. In particular, no raw age change is called implausible. `design_mismatch_count` and `implausible_age_change_pairs` are unassessed (blank/NA in the CSV), not zero. Zero design fields were assessable under the official-documentation criterion.

## Reproduced scope

| Measure | Count |
|---|---:|
| Source person records read | 922,599 |
| Candidate key/cohort groups | 546,423 |
| Candidate groups with 2+ visits | 211,111 |
| Records in 2+ visit candidate groups | 587,287 |
| Single-visit candidate groups | 335,312 |
| Linked candidates with any observed sex change | 238 people / 929 records |
| Linked candidates with any raw age difference | 710 people / 2,793 records |
| Both sex and age flags | 232 people / 905 records |
| Either sex or raw age flag (union) | 716 people / 2,817 records |
| Records excluded in this run | **0** |

## Quarter and visit-pair results

“Pairs” counts candidate identities present at both listed visits. Age changes count unequal nonmissing ages; the delta is visit B minus visit A. Pair rows overlap across visit pairs. Design mismatches and implausible age changes are unassessed for every row, not zero. Every row's classification is unresolved.

| Cohort | Visits | Candidate pairs | Design mismatches | Sex changes | Raw age changes | Age delta min / median / max | Implausible age changes |
|---|---|---:|---|---:|---:|---|---|
| Q1 | V1–V2 | 42,347 | Unassessed | 0 | 0 | 0 / 0 / 0 | Unassessed |
| Q1 | V1–V3 | 41,679 | Unassessed | 0 | 0 | 0 / 0 / 0 | Unassessed |
| Q1 | V1–V4 | 41,331 | Unassessed | 0 | 0 | 0 / 0 / 0 | Unassessed |
| Q1 | V2–V3 | 41,482 | Unassessed | 0 | 0 | 0 / 0 / 0 | Unassessed |
| Q1 | V2–V4 | 41,071 | Unassessed | 0 | 0 | 0 / 0 / 0 | Unassessed |
| Q1 | V3–V4 | 41,317 | Unassessed | 0 | 0 | 0 / 0 / 0 | Unassessed |
| Q2 | V1–V2 | 42,483 | Unassessed | 0 | 0 | 0 / 0 / 0 | Unassessed |
| Q2 | V1–V3 | 42,035 | Unassessed | 0 | 0 | 0 / 0 / 0 | Unassessed |
| Q2 | V1–V4 | 209 | Unassessed | 65 | 207 | -57 / -1 / 69 | Unassessed |
| Q2 | V2–V3 | 41,863 | Unassessed | 0 | 0 | 0 / 0 / 0 | Unassessed |
| Q2 | V2–V4 | 206 | Unassessed | 62 | 204 | -57 / -1 / 69 | Unassessed |
| Q2 | V3–V4 | 205 | Unassessed | 63 | 203 | -57 / -1 / 69 | Unassessed |
| Q3 | V1–V2 | 42,931 | Unassessed | 0 | 0 | 0 / 0 / 0 | Unassessed |
| Q3 | V1–V3 | 263 | Unassessed | 101 | 255 | -88 / -5 / 55 | Unassessed |
| Q3 | V1–V4 | 254 | Unassessed | 95 | 246 | -88 / -4 / 55 | Unassessed |
| Q3 | V2–V3 | 258 | Unassessed | 99 | 250 | -88 / -4.5 / 55 | Unassessed |
| Q3 | V2–V4 | 249 | Unassessed | 93 | 241 | -88 / -4 / 55 | Unassessed |
| Q3 | V3–V4 | 40,750 | Unassessed | 0 | 0 | 0 / 0 / 0 | Unassessed |
| Q4 | V1–V2 | 253 | Unassessed | 70 | 245 | -53 / 0 / 68 | Unassessed |
| Q4 | V1–V3 | 244 | Unassessed | 68 | 236 | -53 / 0 / 68 | Unassessed |
| Q4 | V1–V4 | 243 | Unassessed | 67 | 235 | -53 / 0 / 68 | Unassessed |
| Q4 | V2–V3 | 40,496 | Unassessed | 0 | 0 | 0 / 0 / 0 | Unassessed |
| Q4 | V2–V4 | 40,003 | Unassessed | 0 | 0 | 0 / 0 / 0 | Unassessed |
| Q4 | V3–V4 | 40,373 | Unassessed | 0 | 0 | 0 / 0 / 0 | Unassessed |

The Q2 V4, Q3 V3, and Q4 V1 pair patterns have large age deltas and many sex changes. They are strong signals for follow-up, but without the official identifiers/design fields and age rules they remain unresolved candidate-link inconsistencies rather than confirmed key collisions.

## Flagging and proposed sensitivity policy

`src/data_loader.py` now adds `link_quality_flag` to linked output. Flags preserve records and identify unresolved identity semantics, unassessed design fields, observed sex changes, raw age changes with unconfirmed tolerance, coordinate collisions, or incomplete coordinates. Incomplete coordinates receive a unique unlinked row key so they cannot be silently attached to another person. The loader reports zero exclusions. `src/data_audit.py` reports raw age changes and explicitly marks an official age threshold unavailable rather than applying the former one-year assumption.

The aggregate flag table is [outputs/link_quality_flags.csv](../outputs/link_quality_flags.csv). It contains no person keys or row-level demographic profiles because rider permissions are unconfirmed.

| Proposed option (not applied) | Candidate people / records affected | Use |
|---|---:|---|
| Retain all records and report flags | 0 excluded / all 922,599 retained | Recommended pending documentation and manual review. |
| Sensitivity run excluding any candidate with a sex change | 238 / 929 | Diagnostic only; do not treat as validated exclusion. |
| Sensitivity run excluding any candidate with a raw age difference | 710 / 2,793 | Not recommended as a primary rule; age can change legitimately and no tolerance is documented. |
| Sensitivity run excluding either sex-change or raw-age-change candidates | 716 / 2,817 | Optional conservative sensitivity comparison only; overlapping groups counted once. |
| Exclude on design-field mismatch | Unassessed | Cannot calculate until the official comparison fields and their visit stability are documented. |
| Exclude on implausible age change | Unassessed | Cannot calculate until an official tolerance is found. |

No option above was applied. No records were deleted, dropped, or silently excluded in generating the flag output.

## Verification

`tests/test_data_loader_linkage.py`: **11 passed**. Tests cover flag contents, retention of inconsistent and incomplete records, no exclusion, and strict validation behavior of the shared quarter helper. A full `pytest -q` run did not collect: `tests/test_trajectories.py:35` raises `IndexError: list index out of range` when it reads `D["lost_codes"][0]`; `config.yaml` has `lost_codes: []`. That pre-existing configuration/test mismatch was not changed. The CSV and aggregate counts were generated from the two raw person files using the candidate-link formula; no `b4q12`/training field was read.
