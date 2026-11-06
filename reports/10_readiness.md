# Final project readiness

Verification date: 2026-11-06. No ZIP was created. No real-data modeling or pipeline result was run.

## Overall readiness grade: **F — not ready for real-data analysis**

The software test suite passes, and the real-data audit is reproducible. Scientific use is still blocked by missing official documentation, unconfirmed `b4q12` permission, absent casualty mapping, unverified training timing, and unsettled person-link semantics. Passing software tests do not establish that the source data support valid trainee pathways.

## Exact verification results

| Check | Result |
|---|---|
| Full pytest | **153 passed, 3 warnings, exit 0** (`python -m pytest -q -p no:cacheprovider`; `PYTHONDONTWRITEBYTECODE=1`). The warnings are distance pairs with fewer than two jointly observed time points, assigned the configured maximum cost. |
| Final real-data audit | **Exit 0**, `python -m src.data_audit --config config.yaml --no-write`; no audit output was written. |
| Real build attempt | **Refused, exit 3** before build: `CHECKPOINT 1 is not recorded as PASSED (data.checkpoint1_status)`. |
| Temporary-config safety simulations | **Passed.** `tests/test_real_safety_gate.py` simulates CHECKPOINT 1 FAILED, unresolved b4q12 permission, empty `lost_codes`, missing `nonresponse_col`, and coarse/unverified training timing. Each attempted real `build` returns gate exit 3. A separate test-only fully-cleared fixture verifies later gate checks; it uses test-only placeholder statuses/codes and is not a project permission decision. |
| Approved working config hash | SHA-256 before simulations: `48B2CA2FE9BF1149AFFAFACE30AB0BB1B299C4B01491439750ABF4430A92E933`; after: the same. `config.yaml` is byte-identical. |
| Existing saved real-audit output hash | Read-only final hash: `CA51DE0B759F66379AD4983CCBA4D6B1C79D104CDD65C046FBE6305D10471775` for `reports/results/audit__real.json`. No command in this verification wrote to it or to any other result output. |

### Reproduced CHECKPOINT 1 figures

- Person records: **922,599** (`perv1` 418,159; `perrv` 504,440); no incomplete candidate keys in these rows.
- Shared quarter-aware rule: **546,423** candidate key/cohort groups; **211,111** with 2+ visits (38.6%); 335,312 single-visit groups; 0 quarter/visit coordinate collision groups or excess rows.
- Visit count histogram: 1 point 335,312; 2 points 87,350; 3 points 82,457; 4 points 41,304. At least 3 points: 22.6%; all 4: 7.6%; mean points: 1.69.
- Legacy key/time diagnostic: **3,390 groups / 3,390 excess rows**. These are legacy coordinate collisions, not confirmed duplicate rows. The current quarter-aware result is 0/0.
- Cross-visit flags: **238** candidate keys with changing sex; **710** with any raw age change; sector changes 0. No official age tolerance is available, so no age changes are called implausible. Link causes remain unresolved.
- Configured training count (audit diagnostic, not authorization): 13,031 `b4q12 == 1` candidates; 5,860 survive at least two visits, 3,867 at least three, 1,940 all four. Permission to use the field is unresolved; no trainee trajectories were built.
- Real CWS columns have no blank records in either person file. The audit reports configured unknown codes at 30,219 in perv1 and 32,123 in perrv. Code-level documentation remains unconfirmed. `map_raw_to_state` initializes to `MISSING`; blanks/unknowns stay missing, and only configured raw codes map to employment states. Tests cover blank/unknown missing and a missing visit remaining missing, never unemployment.

### Saved-output comparison

`reports/06_checkpoint1.md` matches the final no-write audit figures above. `reports/results/audit__real.json` is a **stale historical artifact** and must not be treated as current: it embeds `plan: A`, 542,755 legacy keys, 209,902 linked keys, and the old one-year age threshold. Current config is `plan: UNSET`; current shared quarter-aware counts are 546,423 candidates and 211,111 linked 2+ candidates, with the age threshold unassessed. The stale JSON was not overwritten, as requested.

The saved SYNTHETIC report’s headline values agree with its matching synthetic JSON files (2,000 input people, 1,912 eligible, k=6, silhouette 0.788, baseline ARI 0.245, hierarchical ARI 0.561, random 40% attrition ARI 1.000, two-visit censoring ARI 0.765). These are synthetic test results, not PLFS findings. Their saved config snapshot contains an old `UNVERIFIED:lost_to_follow_up` placeholder and was not regenerated in this verification; do not interpret it as the current real-data config.

## Records and missing values

The audit saw all 922,599 source person rows, zero missing full candidate keys, and zero malformed quarter/visit coordinates. The synchronized loader has no link-quality exclusion path: it keeps inconsistent, collision, and incomplete-coordinate records, assigns a flag (or a unique unlinked row key for incomplete coordinates), and records zero exclusions. Unit tests verify that collision, sex/age-change, and incomplete-coordinate examples remain present. No real trajectory dataset was built, so this confirms the loader/audit behavior and input counts, not downstream eligibility selections.

Missing CWS observations are not coded as unemployment. Blank/NA and configured unknown raw statuses map to `MISSING`; an absent person-visit row initializes to `MISSING`. Unemployment is assigned only from the configured unemployment codes. The real files currently have zero blank CWS values; configured unknown-code records remain reported separately. Official CWS code definitions still need verification.

## Gate fixes made and why

1. **Real-data gate omitted required evidence checks.** `run_pipeline.check_data_gate` previously checked plan, `data.verified`, and design compatibility only. It now also fails closed unless CHECKPOINT 1 is explicitly `PASSED`, b4q12 selection permission explicitly `CONFIRMED`, `lost_codes` is non-empty, a nonresponse column is mapped, and training timing is `dated` with timing evidence status `VERIFIED`. No status was added or confirmed in the working config. Temporary-config tests verify each blocker independently, and the real build attempt refuses before writing outputs.
2. **Synthetic tests depended on a real PLFS lost code.** The approved config correctly keeps `lost_codes: []` because no official code is documented, but synthetic generation and a test import assumed a real code existed. Synthetic-only code now uses the reserved `SYNTHETIC_LOST` sentinel when needed; the real mapper accepts it only for explicitly synthetic input. The test fixture uses its own sentinel. No real code was invented and the working config was not changed.

## Open blockers and user actions

1. Obtain the Catalogue 213 official data dictionary/layout, instruction manual and release notes; verify identifiers, quarter/visit logic, CWS codes, sample-design fields, weights, casualty/nonresponse fields, and training questions. Reconcile those materials with `data.verified: true`.
2. Obtain the actual 2023–24 rider and written clarification from the responsible authority/instructor about using `b4q12` solely for trainee selection. Current status is **UNRESOLVED**. Do not set a permission status from the variable label or the prior-year rider alone.
3. Document valid casualty/lost codes and a nonresponse column. Until then `lost_codes` remains empty and real analysis is blocked.
4. Establish training completion timing before the employment observations with official variables and person-level proof. Current `coarse_flag` (`b4pt1q3`) does not establish that order. Post-training wording and analysis remain blocked.
5. Review the 238 sex-change and 710 raw-age-change candidate links after identifier definitions and a documented age tolerance are available. Do not delete records based on the current flags.
6. Document whether longitudinal weights are valid for linked analysis and which weight to use. Until then real estimates must remain unweighted/sample-only; the current schema keeps the real weight unset.
7. Only after the evidence resolves these blockers, record CHECKPOINT 1 as PASSED, make a documented Plan A decision, lock the baseline, and rerun the audit and full tests. The current saved `audit__real.json` must remain treated as stale; do not rely on it for current results.

## Documentation / release caveats

README, setup instructions, data-use assessment, and interface/methodology notes were updated to reflect current gate and permission limits. The historical reports are labeled as snapshots where their earlier test/linkage state differs. `PROJECT_MANIFEST.md` contains a previous release's generated file/hash table and has not been regenerated; no ZIP was requested or created. It must be rebuilt and its hash block refreshed before any future release.

Git status/diff could not be collected: this workspace directory has no `.git` repository (`git rev-parse --show-toplevel` failed). The verification therefore reports observed file hashes and command results, not a Git-based changed-file inventory.

After this readiness run, synthetic human-facing artifacts were relabeled **SYNTHETIC DEMONSTRATION - NOT PLFS RESULTS** and regenerated from the existing synthetic pipeline. The real-data audit artifact hash remained `CA51DE0B759F66379AD4983CCBA4D6B1C79D104CDD65C046FBE6305D10471775`. The only `config.yaml` change was the dashboard's synthetic warning text; current SHA-256 is `A36E41077410C81A45C569064FB706A43F72D2FED26127617E24F67671509F90`. Gate, permission, linking, code mapping, and timing fields were not changed.

The synthetic regeneration exposed a genuine defect: `identify_trainees` applied configured real `b4q12` selection to a synthetic panel, which has only the generator-owned `trained` marker. Synthetic panels now always use that marker; real panels still use their configured rule. A regression test covers this separation. The full synthetic pipeline then completed with 1,912 synthetic trainees, k=6, ten regenerated figures, and a generated report; these are **SYNTHETIC DEMONSTRATION - NOT PLFS RESULTS**. Pipeline self-test passed 20 checks, dashboard self-test passed 15 checks, and the full suite passed 153 tests with 3 distance warnings. The real-data gate and all real-data configuration statuses remain unchanged.
