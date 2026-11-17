# Final research design and real PLFS descriptive results

**Project identity:** Employment Outcome Pathway Grouping After Skilling — INT396 | G24 | CA Project  
**Dataset:** PLFS July 2023–June 2024, MoSPI Catalogue 213  
**Analysis run:** 2026-11-06  
**Decision:** **FEASIBLE WITH REVISED CROSS-SECTIONAL DESIGN**

**Review note:** `reports/13_research_feasibility.md` is not present in the workspace. This decision uses the previously shared feasibility findings, reports 11–12 and P3–P5, current Catalogue 213 documents in `docs/mospi/`, and reproduced checks on the current raw files.

## Decision

The original longitudinal pathway design remains blocked. Catalogue 213 does not establish a persistent person key, training completion dates relative to each revisit, or weights for linked-person trajectories. The separate first-visit design is supportable for descriptive CWS estimates: perv1 contains first-visit records from all four quarters and both rural and urban sectors; the catalogue describes annual CWS estimates for both sectors; MoSPI's PLFS 2023–24 annual press note reports CWS WPR for persons aged 15 years and above; and the rider gives annual `NO_QTR` and combined-subsample multiplier instructions.

The revised research question is: **Among PLFS 2023–24 respondents aged 15–59 who reported formal vocational/technical training, what was the annual weighted distribution of Current Weekly Status (CWS) at first visit, overall and by rural/urban sector?** This is a cross-sectional descriptive association. It does not estimate a training effect, post-training employment, employment transitions, or pathways.

PAM and hierarchical clustering were not run. With only broad CWS as the outcome, clustering would merely regroup the one categorical outcome. Industry and occupation are available only for people with work records, would change the analytic cohort, are high-cardinality codes, and lack a confirmed profiling-variable whitelist. The data and permission basis therefore do not support meaningful, permitted unsupervised clustering. Clustering on CWS alone is disabled in the separate route. The existing longitudinal clustering pipeline and its gate remain unchanged and closed.

## Official definitions and crosswalk

| Analysis field | Raw field(s) | Definition and use | Official source |
|---|---|---|---|
| Training cohort | `b4q12_perv1` | Block 4 asks whether persons aged 12–59 received vocational/technical training. Block 4.1 is the formal vocational/technical training detail block for those with code 1. The analysis uses code 1 as the documented formal-training group and restricts age to 15–59 for working-age CWS indicators. | Instruction Manual Vol. II, Schedule 10.4, PDF pp. 5–6 (printed pp. 5–6); DDI label `Whether received any Vocational/Technical Training`. |
| Outcome | `b6q5_perv1` | Broad CWS groups only: 11–72 employed; 81/82 unemployed; 91–98 out of labour force. Blank remains missing. A code outside those broad groups is unclassified and halts validation rather than being recoded. No individual meanings are assigned to 91–98; 99 remains unresolved. | Instruction Manual Vol. I §3.6.14, PDF pp. 104–106. |
| Sector | `b1q3_perv1` | 1 rural, 2 urban. Both are included and separately estimated. | Catalogue 213 data layout and DDI. |
| Quarter / visit | `qtr_perv1`, `visit_perv1` | Q1–Q4 and V1. Every row in perv1 must be V1; quarter is retained for annual sample coverage, not used to link people. | Catalogue 213 data layout and rider. |
| Annual multiplier inputs | `mult_perv1`, `NSS_perv1`, `NSC_perv1`, `no_qtr_perv1` | Annual weight is `MULT / (100 if NSS == NSC else 200) / NO_QTR`. The rider gives `MULT/100` or `MULT/200` for combined subsamples, and says annual `MULT` may be divided by `NO_QTR`. | Catalogue 213 user rider, §B, “Use of Sub-sample wise weights” and “Generation of combined estimate for the entire Year”; data layout. |

MoSPI's Annual Report press note reports CWS WPR for persons age 15 years and above with rural, urban and rural+urban estimates. This supports the age floor and sector reporting convention. The analysis applies an upper bound of 59 because the vocational-training module is limited to ages 12–59.

The applied weight expression uses the rider's multiplier scale and combines its two instructions. The perv1 source includes 13,011 eligible records with unequal NSS/NSC (divisor 200), 16 with equal NSS/NSC (divisor 100), 13,025 with `NO_QTR=4`, and 2 with `NO_QTR=3`. The multiplier is applied to each selected record; no respondent is linked across visits.

## Reproduced data checks

| Check | Result |
|---|---:|
| perv1 source rows | 418,159 |
| V1 records in Q1 / Q2 / Q3 / Q4 | 104,537 / 104,110 / 104,806 / 104,706 |
| First-visit official record-key collisions | 0 |
| Selected records, age 15–59 and b4q12=1 | 13,027 |
| Rural / urban selected records | 5,132 / 7,895 |
| Selected records by Q1 / Q2 / Q3 / Q4 | 3,452 / 3,214 / 3,173 / 3,188 |
| Records outside the explicit cohort rule | 405,132 (retained in raw source; counted as not eligible) |
| Selected records missing CWS, weight, `NO_QTR`, NSS or NSC | 0 |
| Selected CWS values outside documented broad groups | 0 |
| CWS missing or unclassified in selected cohort | 0 |
| Rows removed from raw data | 0 |

The record key check uses quarter, visit, sector, state, FSU, Sg/Sb, second-stage stratum, household number, and person serial number. It validates uniqueness of first-visit records; it does not establish longitudinal identity.

## Original longitudinal gate and audit

The existing CHECKPOINT 1 audit was rerun read-only with `python -B -m src.data_audit --no-write` (exit 0; two existing pandas `FutureWarning`s). It reports `data.plan=UNSET`, `data.verified=false`, and four unresolved schema issues. Across both person files it reproduces 922,599 person rows, 546,423 candidate keys, and 211,111 candidate keys at two or more visits; legacy key/visit collisions are 3,390 groups/3,390 excess rows and quarter/visit collisions are 0/0. It also reports 238 candidate keys with sex changes, 710 with age changes, and 648 with at least one compared design-field change. These remain unconfirmed candidate-link diagnostics; no records were removed. CHECKPOINT 1 remains unresolved and the longitudinal route remains closed.

The legacy audit calls `b4q12` label-referent ambiguity because its configured diagnostic metadata does not identify the questionnaire universe. Instruction Manual Vol. II, Schedule 10.4, pp. 5–6 independently documents that Block 4.1 formal-training details apply to ages 12–59 with code 1 in Block 4 column 12; the cross-sectional route is explicitly limited to this documented use.

## Weighted estimates

Percentages are calculated from the annual weights above. WPR is the employed estimate divided by the selected population estimate. LFPR is employed plus unemployed divided by that population estimate. UR is unemployed divided by employed plus unemployed. These are indicators for the **selected trained cohort**, not estimates of a training effect.

| Population | n | Weighted population estimate | WPR | LFPR | UR |
|---|---:|---:|---:|---:|---:|
| Combined rural + urban | 13,027 | 31,213,646.15 | 62.24% | 71.45% | 12.90% |
| Rural | 5,132 | 15,713,816.28 | 61.17% | 70.91% | 13.73% |
| Urban | 7,895 | 15,499,829.87 | 63.32% | 72.01% | 12.06% |

Counts and shares by all three documented CWS groups are in `outputs/cross_sectional/real/cws_estimates.csv`; the population indicators are in `outputs/cross_sectional/real/employment_indicators.csv`. Figures are `cws_weighted_shares.png` and `employment_indicators.png`. The complete run summary and provenance are in `outputs/cross_sectional/real/cross_sectional_summary.json`.

No design-based standard errors or confidence intervals are produced in this run. These are weighted point estimates only; uncertainty estimation under the PLFS stratified sample design remains a requirement before inferential claims. Population estimates are rounded only in this report; CSV outputs retain full precision.

The supplied final multipliers are used as documented. The `perv1` file has no sample nonresponse/casualty field, so response rates and any nonresponse adjustment cannot be independently assessed from these person records. The estimation procedure's FSU count definition excludes casualty units; this report does not infer a separate nonresponse correction beyond the published multiplier.

## Training timing and recent-training subgroup

`b4pt1q3` records whether training was completed during the last 365 days (yes=1, no=2) for the formal-training detail block. That flag does not provide an exact completion date or prove completion occurred before a particular CWS reference week. A subgroup could be labelled “reported formal training completed during the last 365 days,” if that variable's selection is within the confirmed use scope. It cannot be called a post-training employment cohort or used to estimate an after-training outcome. The subgroup was not used in this analysis.

## A/B/C feasibility and changed claims

| Approach | Finding |
|---|---|
| A. Original longitudinal | Not feasible on current documented evidence. Persistent identity and timing are unverified; no linked-person annual weight is documented; profiling scope remains unspecified. The existing gate remains blocked (`data.plan: UNSET`, CHECKPOINT 1 unresolved). |
| B. First-visit cross-section | Feasible for the descriptive question above, combining rural and urban records with documented annual weights. No linkage is needed. |
| C. Other question | The same cross-sectional design can describe CWS among formal vocationally trained respondents; changing the cohort to all respondents would answer an overall labour-status question, but would no longer address trained respondents. No stronger alternative is supported by this task's permissions and feature scope. |

The words **pathway**, **transition**, **after skilling**, **post-training**, and any causal/effect wording must be removed from claims about the real-data estimates. The official project identity remains in the cover and metadata, followed by the revised scope. The historic longitudinal pipeline, its tests, model-selection rules, and closed safety gate are preserved.

## Reproducibility and validation

- Command: `python -B -m src.cross_sectional`
- Output tag: `REAL PLFS — CROSS-SECTIONAL DESCRIPTIVE`; no synthetic data were used.
- Input SHA-256 (`data/raw/perv1.csv`): `b852af28508a230270b2d371e5a975230dbc363982bad97d1dc8f2601c2664f6`
- Configuration SHA-256 at run: `c735d9f9bf0873814d1f750adac49df65dab5289b57e410435821f21b9bee54d`
- Analysis code SHA-256 (`src/cross_sectional.py`): `f9d09ec5df3871c55c172eaab2905f6d4efba3a461e6f2872f0575ba319adebb`
- Randomness: none; seed: not applicable.
- Annual weight formula and crosswalk are frozen in `config.yaml` and `src/cross_sectional.py`.
- Full tests after implementation: **183 passed, 3 warnings**. Warnings are existing longitudinal-distance maximum-cost warnings in synthetic tests.
- The dashboard reads saved output tables and checks current configuration, raw-file and analysis-code hashes. It does not recompute estimates.
- The eight-slide deck is in `submission/PLFS_2023-24_Cross_Sectional_Study_final_submission_v2.pptx`; package integrity and layout checks passed.

## Remaining limitations

1. These are weighted point estimates. Add design-based standard errors/confidence intervals only if inferential comparisons are required; do not claim statistical significance from this run.
2. Do not add occupation/industry profiles or real-data clusters until the allowed profiling scope is established and the feature space is justified.
3. Keep longitudinal linkage, post-training ordering, linked weights, lost-code semantics and individual CWS 91–98 / code 99 issues open for the original design.

**Readiness:** **READY for submission as a revised cross-sectional descriptive study**, based on the user's confirmation of instructor approval and required MoSPI permissions. The original longitudinal pathway and clustering design remains **BLOCKED**. The title/project identity is preserved, but real-data claims have been narrowed and must not imply post-skilling effects, pathways or transitions.

**Additional official source:** [MoSPI PLFS 2023–24 Annual Report press note](https://www.mospi.gov.in/sites/default/files/press_release/Press_note_AR_PLFS_2023_24_22092024.pdf), Table 5, CWS WPR for age 15 years and above, rural/urban/rural+urban.
