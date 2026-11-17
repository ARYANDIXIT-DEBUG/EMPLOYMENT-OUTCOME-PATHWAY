# Part 2 — Real PLFS data validation

**Project:** Employment Outcome Pathway Grouping After Skilling — INT396 | G24 (legacy PLFS review)  
**Dataset:** PLFS 2023–24, MoSPI Catalogue 213  
**Date:** 2026-11-06  
**Outcome:** **BLOCKED — CHECKPOINT 1 not passed; real-data analysis is not authorized by technical gates.**

## Scope and safeguards

This work continues from `reports/11_baseline_resolution.md`. Local raw data and Catalogue 213 documents were reviewed. No raw file was modified, no observation was deleted or silently excluded, no real-data clustering was run, and no gate was bypassed. Because the evidence prerequisites remain incomplete, CHECKPOINT 1 was not re-run or marked passed. The previous `python -m src.data_audit --no-write` result in the baseline report is the latest reproducible audit snapshot.

## Validation results

| Area | Checks passed / resolved | Remaining issue and status |
|---|---|---|
| Person linkage | The current loader and audit share the quarter-aware candidate-link implementation. Baseline read-only audit reproduced 922,599 person rows, 546,423 candidate keys, 211,111 keys at 2+ visits, 3,390 legacy key/time collision groups and 0 quarter/visit coordinate collision groups. No records were excluded. | The Catalogue 213 rider defines a person-record key including quarter, visit, sector, FSU, hamlet-group/sub-block, second-stage stratum, household and person serial. It does not confirm that removing time components yields a persistent longitudinal person ID. Candidate links are not confirmed matches. Cross-visit design invariance and mismatch causes remain unresolved. **Blocker.** |
| CWS mapping | Instruction Manual Vol. I §3.6.14 (PDF pp. 104–106) supports broad groups: 11–72 employed, 81/82 unemployed, 91–98 out of labour force. §§3.6.2 and 3.6.8 (PDF pp. 100 and 102) associate 61/62 with absence from self-employment work (codes 11/12/21) and 71/72 with absence from regular salaried/wage work (code 31). Config now follows those broad groups. | The manual passage does not give individual meanings for 91–98. Code 99 is outside the documented ranges and remains unclassified/MISSING. No finer meaning was inferred. **Mapping validation remains open.** |
| Training variable | Catalogue 213 DDI labels `b4q12_perv1` “Whether received any Vocational/Technical Training.” User permission to use `b4q12` for trainee selection is recorded as `user_confirmed`. | The DDI label and user permission do not establish all response-code meanings or completion dates. `b4pt1q3` is a “last 365 days” completion flag, not a date. It cannot prove for each person that completion preceded each employment observation. **Timing blocker.** |
| Missing values / lost codes | Blank and unclassified CWS values remain MISSING, never unemployment. Existing `lost_codes` states are handled fail-closed. | Reviewed Catalogue 213 documentation does not define a person-level lost code or explicitly state that none exists. `lost_codes: []`, `lost_codes_status: unresolved`. **Blocker.** |
| Survey design | Available `mult_perv1` / `mult_perrv` fields are labelled “Sub-sample wise Multiplier.” | The rider’s multiplier formulas document specified quarterly/combined/annual estimates, not person-level longitudinal pathway estimates. No linked-panel weight is validated. The rider does not identify an allowed profiling-variable whitelist; `profiling.permitted_vars` remains empty. User permission confirmation does not extend to profiling. **Blockers.** |
| Cohort and trajectories | The config describes an urban trainee cohort and four CWS visits; the current safety gate requires approval, resolved mapping/linkage, dated timing, plan, and other statuses before real trajectories. | Persistent person linkage is unconfirmed; b4q12 is present in V1 only; completion timing relative to V1–V4 cannot be established from the documented fields; linked weights/profile scope are unresolved. No real cohort or trajectories were built. **Not yet defensible for analysis.** |

## CHECKPOINT 1 and gate status

CHECKPOINT 1 is **UNRESOLVED**, and `data.plan` remains `UNSET`. The technical gate remains closed. Current independent validation statuses are recorded in `config.yaml`; `data.verified` is false. The user’s `b4q12` permission confirmation is recorded as `user_confirmed`, but it does not resolve linkage, timing, lost codes, profiling scope, or CHECKPOINT 1.

The most recent real-file audit in `reports/11_baseline_resolution.md` reported these candidate diagnostics: 238 keys with sex changes, 710 with any raw age change, and 648 with compared design-field changes. None is classified as a confirmed mismatch cause or excluded. No official cross-visit age tolerance or design-field invariance rule was found.

## Tests and reproducibility

The latest full suite remains **175 passed, 3 warnings, exit 0** (`python -B -m pytest -q -p no:cacheprovider`), as documented in the baseline report. The warnings are the configured maximum-distance warnings for pairs with fewer than two jointly observed visits. Passing tests verify software behavior; they do not prove PLFS semantic validity.

No CHECKPOINT 1 run occurred in this Part 2 update because the identifier and mapping evidence required to complete it remains unresolved. No real-data modeling was run.

## Remaining blockers and required clarification

1. Obtain authoritative confirmation of the persistent person-link key and expected quarter/visit progression, including whether sector and each sample-design field must remain invariant.
2. Resolve code 99 and whether the individual CWS 91–98 meanings are needed for the intended analysis. Preserve broad OLF coding until then.
3. Resolve whether a person-level lost/nonresponse code exists and, if present, identify its documented field and values. Do not invent a value.
4. Establish whether completion timing can be documented at person-level and precedes the employment observations. If not, any future analysis must remain explicitly timing-unverified and cannot be called post-training pathways.
5. Confirm the appropriate longitudinal weight and its target estimand, if weighted pathway prevalence is required.
6. Confirm permitted profiling variables and output/disclosure restrictions. Do not infer a whitelist.
7. After these items are addressed, rerun the existing CHECKPOINT 1 and apply its existing pass/fail rules. Only then can the project determine whether technical authorization for real-data analysis is possible.

**Decision:** No real-data analysis or clustering is authorized by the current technical gate.
