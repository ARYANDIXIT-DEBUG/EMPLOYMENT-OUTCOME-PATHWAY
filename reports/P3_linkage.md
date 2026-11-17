# P3 — Quarter-aware linking and cross-visit inconsistency audit

**Date:** 2026-11-06  
**Scope:** Reconcile historical reports 03–04 with current code and rerun CHECKPOINT 1 against configured PLFS files. No person was deleted or excluded.

## Shared linker and CHECKPOINT 1 path

The loader and audit use one quarter-aware implementation:

1. `src.data_loader.quarter_aware_link_keys` composes the configured candidate key with the quarter/visit rule and computes both legacy and quarter/visit key-collision counts.
2. `src.data_loader.link_persons` calls this function to form candidate cohort links and retains `link_quality_flag` on output.
3. `src.data_audit._linkage` imports and calls the same function. `linkage_report` feeds that result into `run_audit`, which is the CHECKPOINT 1 audit/report path. `run_pipeline`'s audit stage also calls `run_audit`; its real-data gate checks the recorded checkpoint status rather than reimplementing linking.

The synthetic loader/audit agreement test verifies their collision counts agree. The shared function's counts refer to key-coordinate collisions, not confirmed duplicate rows. No full-row identity check is performed.

## Documentation and interpretation boundary

P4's official-source review confirms the Catalogue 213 README lists a person-record primary key containing quarter, visit, sector, FSU, hamlet-group/sub-block, second-stage stratum, household, and person serial. The current configured candidate key does not include sector, and P4 does not establish that dropping time fields from the row key yields a valid persistent person key. The key's longitudinal meaning therefore remains **unresolved**. The local quarter/visit computation is reproducible, but a candidate link is not a confirmed person match.

P4 found no official age-change tolerance and no rule saying which sample-design fields must remain invariant between revisits. The layout documents labels for stratum, sub-stratum, sub-sample, FSU, FOD sub-region, sample Sg/Sb, second-stage stratum, and household. Labels alone do not establish a longitudinal mismatch rule. All observed sex, age, and design-field differences remain **unresolved**. Age thresholds below are sensitivity summaries only; none is an official tolerance or exclusion rule. See [reports/P4_permissions.md](P4_permissions.md) for source locators and written clarifications still needed.

## Reproduced CHECKPOINT 1 counts

Real audit command: `python -m src.data_audit --no-write`.

| Measure | Reproduced count |
|---|---:|
| Person records read (`perv1` + `perrv`) | 922,599 |
| Candidate cohort keys | 546,423 |
| Legacy key + visit collision groups / excess rows | 3,390 / 3,390 |
| Quarter + visit collision groups / excess rows | 0 / 0 |
| Candidate keys observed at 2+ visits | 211,111 (38.6% of candidate keys) |
| Candidate keys with changing sex | 238 |
| Candidate keys with any raw age change | 710 |
| Candidate keys with any compared design-field change | 648 |
| Records excluded or deleted | **0** |

The 3,390 legacy results are **key collisions**, not duplicates: full-row identity was not checked. Under the quarter/visit rule there are no repeated key-coordinate groups. The 211,111 links are candidate links under the configured key, whose longitudinal validity remains unresolved.

Compared cross-visit fields: sector, stratum, sub-stratum, sub-sample, and FOD sub-region. Across linked candidate keys, mismatches were sector **0**, stratum **429**, sub-stratum **429**, sub-sample **425**, and FOD sub-region **561**; **648** unique keys differ in at least one of these fields. The sector comparison is zero for linked keys, but sector's omission from the configured candidate key remains a documented-key discrepancy. Candidate-key components FSU, sample Sg/Sb, second-stage stratum, household, state, and person serial are not independent stability checks because the current candidate key already fixes those values.

Sex and age aggregate counts use nonmissing comparisons across the linked candidate's visits. Whole-window age-span sensitivity counts are: absolute span >0 years **710**, >1 **674**, >2 **649**, >5 **565**, and >10 **423**. They are sensitivity counts only; none is labelled implausible.

## Quarter/cohort and visit-pair diagnostics

Each row counts candidate keys present at both visits within the derived cohort. `Design` lists unique candidate keys with at least one mismatch, followed by field counts in this order: stratum / sub-stratum / sub-sample / FOD sub-region. Sector mismatches were zero in every pair. `Age >n` counts pairs whose absolute age difference exceeds n years. These are labelled sensitivity thresholds; no threshold is selected as valid.

| Cohort | Visit pair | Candidate pairs | Sex changes | Design any (stratum / sub / sub-sample / FOD) | Raw age changes | Age >1 | Age >2 | Age >5 | Signed age delta min / median / max |
|---|---|---:|---:|---|---:|---:|---:|---:|---|
| Q1 | V1–V2 | 42,347 | 0 | 0 (0 / 0 / 0 / 0) | 0 | 0 | 0 | 0 | 0 / 0 / 0 |
| Q1 | V1–V3 | 41,679 | 0 | 0 (0 / 0 / 0 / 0) | 0 | 0 | 0 | 0 | 0 / 0 / 0 |
| Q1 | V1–V4 | 41,331 | 0 | 0 (0 / 0 / 0 / 0) | 0 | 0 | 0 | 0 | 0 / 0 / 0 |
| Q1 | V2–V3 | 41,482 | 0 | 0 (0 / 0 / 0 / 0) | 0 | 0 | 0 | 0 | 0 / 0 / 0 |
| Q1 | V2–V4 | 41,071 | 0 | 0 (0 / 0 / 0 / 0) | 0 | 0 | 0 | 0 | 0 / 0 / 0 |
| Q1 | V3–V4 | 41,317 | 0 | 0 (0 / 0 / 0 / 0) | 0 | 0 | 0 | 0 | 0 / 0 / 0 |
| Q2 | V1–V2 | 42,483 | 0 | 0 (0 / 0 / 0 / 0) | 0 | 0 | 0 | 0 | 0 / 0 / 0 |
| Q2 | V1–V3 | 42,035 | 0 | 0 (0 / 0 / 0 / 0) | 0 | 0 | 0 | 0 | 0 / 0 / 0 |
| Q2 | V1–V4 | 209 | 65 | 182 (165 / 165 / 79 / 182) | 207 | 197 | 192 | 159 | -57 / -1 / 69 |
| Q2 | V2–V3 | 41,863 | 0 | 0 (0 / 0 / 0 / 0) | 0 | 0 | 0 | 0 | 0 / 0 / 0 |
| Q2 | V2–V4 | 206 | 62 | 179 (162 / 162 / 76 / 179) | 204 | 194 | 190 | 158 | -57 / -1 / 69 |
| Q2 | V3–V4 | 205 | 63 | 178 (161 / 161 / 76 / 178) | 203 | 193 | 189 | 157 | -57 / -1 / 69 |
| Q3 | V1–V2 | 42,931 | 0 | 0 (0 / 0 / 0 / 0) | 0 | 0 | 0 | 0 | 0 / 0 / 0 |
| Q3 | V1–V3 | 263 | 101 | 236 (137 / 137 / 186 / 203) | 255 | 238 | 229 | 198 | -88 / -5 / 55 |
| Q3 | V1–V4 | 254 | 95 | 228 (129 / 129 / 179 / 195) | 246 | 230 | 221 | 192 | -88 / -4 / 55 |
| Q3 | V2–V3 | 258 | 99 | 232 (136 / 136 / 183 / 200) | 250 | 234 | 225 | 194 | -88 / -4.5 / 55 |
| Q3 | V2–V4 | 249 | 93 | 224 (128 / 128 / 176 / 192) | 241 | 226 | 217 | 188 | -88 / -4 / 55 |
| Q3 | V3–V4 | 40,750 | 0 | 0 (0 / 0 / 0 / 0) | 0 | 0 | 0 | 0 | 0 / 0 / 0 |
| Q4 | V1–V2 | 253 | 70 | 227 (125 / 125 / 159 / 173) | 245 | 236 | 225 | 206 | -53 / 0 / 68 |
| Q4 | V1–V3 | 244 | 68 | 218 (120 / 120 / 150 / 169) | 236 | 227 | 216 | 197 | -53 / 0 / 68 |
| Q4 | V1–V4 | 243 | 67 | 218 (120 / 120 / 150 / 169) | 235 | 226 | 215 | 196 | -53 / 0 / 68 |
| Q4 | V2–V3 | 40,496 | 0 | 0 (0 / 0 / 0 / 0) | 0 | 0 | 0 | 0 | 0 / 0 / 0 |
| Q4 | V2–V4 | 40,003 | 0 | 0 (0 / 0 / 0 / 0) | 0 | 0 | 0 | 0 | 0 / 0 / 0 |
| Q4 | V3–V4 | 40,373 | 0 | 0 (0 / 0 / 0 / 0) | 0 | 0 | 0 | 0 | 0 / 0 / 0 |

Differences concentrate in Q2 links involving V4, Q3 links involving V3/V4, and Q4 links involving V1. These patterns warrant clarification of the candidate key and panel schedule, but are not enough to label individual cases as confirmed collisions, data-entry errors, or legitimate changes. Classification stays **unresolved**.

## Flags, exclusions, and outputs

The loader keeps `link_quality_flag`. It flags unresolved identity semantics, unassessed design-field stability, observed design-field changes, sex changes, age changes without a documented tolerance, coordinate collisions, and incomplete coordinates. The updated aggregate [outputs/link_quality_flags.csv](../outputs/link_quality_flags.csv) contains no person keys, records **0 exclusions**, and has no official age tolerance or implausible-age count populated. No rows were deleted, filtered, or excluded for this audit.

## Test results and readiness

- Focused linkage tests: **14 passed**.
- Full `python -m pytest -q`: **160 passed, 3 warnings, exit 0** in 29.51 seconds. The warnings are existing maximum-distance warnings for pairs with fewer than two joint observations.
- CHECKPOINT 1 audit status: linkage computation completed, but the recorded gate status remains **not passed** (`data.checkpoint1_status` is absent; `data.b4q12_permission_status` is absent). Real-data approval is **BLOCKED**; `data.plan` is `UNSET`, `lost_codes_status` is unresolved, and trainee timing is coarse. No permission was set, and no trajectory construction or clustering was run.

## Remaining clarification

Obtain written confirmation of the persistent person-link key (including whether sector belongs in it), the expected revisit stability of sample-design fields, and whether any official age-difference tolerance exists. Until then, keep every `link_quality_flag`, report sensitivity counts only, and apply no exclusion policy.
# Status note (2026-11-06)

This is the earlier linkage audit snapshot. Its candidate-link counts remain consistent with the latest read-only audit, but it does not reflect the current CWS correction, user-confirmed b4q12 status, separate validation statuses, or the reconciled synthetic output metadata. See [11_baseline_resolution.md](11_baseline_resolution.md) for current state.

