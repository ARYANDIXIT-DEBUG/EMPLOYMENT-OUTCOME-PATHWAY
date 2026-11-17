# Project readiness

## Superseding update — 2026-11-06

The original longitudinal pathway analysis remains blocked. A separate cross-sectional real-data route is now validated and completed: annual weighted CWS estimates at first visit for 13,027 respondents aged 15–59 reporting formal vocational/technical training (both sectors). Combined WPR/LFPR/UR are 62.24%/71.45%/12.90%. These are descriptive weighted point estimates; no PAM or hierarchical clustering was run, and design-based uncertainty is not implemented. The cross-sectional route does not open CHECKPOINT 1 or the longitudinal gate. The user confirmed instructor approval and required MoSPI permissions, so readiness is **READY for submission under this revised descriptive scope**; make no inferential significance claims without design-based uncertainty.

See [reports/14_final_design_and_results.md](reports/14_final_design_and_results.md) and the saved artifacts under `outputs/cross_sectional/real/`. The original longitudinal pathway analysis remains blocked.

Updated: 2026-11-06. This report supersedes the earlier verification snapshot below; earlier task reports remain preserved as historical records.

## Historical longitudinal-gate snapshot (superseded for the revised analysis)

The real-data gate remains closed. The user confirmed approval and required permissions; `config.yaml` records `b4q12_permission_status: user_confirmed` and `validation.permissions: user_confirmed`. No profiling-variable whitelist is inferred from that statement.

Other unresolved conditions include CHECKPOINT 1, `data.plan`, complete mapping validation (especially CWS code 99 and individual 91–98 labels), persistent person-link semantics, person-level lost-code handling, dated training completion, and linked-weight validity. `data.verified` is now false. Separate statuses are recorded under `validation`.

## Historical synthetic validation

The active synthetic results are in `reports/results/` with figures in `reports/figures/`. These are the configured, canonical output locations and the legacy dashboard source. The temporary `outputs/synthetic_demo/` directory is absent from the current checkout; prior notes describing it as a preserved copy are superseded. Historical analysis notes remain for context, but generated files not present in the checkout are not deliverables.

The regenerated synthetic run reports 2,000 input people and 1,912 eligible people. The eligible sample contains 7,359 source rows and 7,648 person-visit cells. Row kinds are 7,082 observed states, 156 recorded missing/unknown values, and 121 lost values, totaling 7,359. There are 289 cells with no source row. Cell kinds are 7,082 observed, 445 missing (156 recorded plus 289 no-row), and 121 lost, totaling 7,648. No row or cell discrepancy remains.

Synthetic headline results remain k=6, PAM silhouette 0.78796, baseline ARI 0.24545, hierarchical ARI 0.56137, random-40% stability ARI 0.99949, and two-visit-censoring stability ARI 0.76493. They are **SYNTHETIC DEMONSTRATION - NOT PLFS RESULTS** and are not real-data evidence.

## Mapping correction

MoSPI Instruction Manual Vol. I §3.6.14 (PDF pp. 104–106) documents the CWS broad groups: 11–72 employed, 81/82 unemployed, and 91–98 out of labour force. Vol. I §§3.6.2 and 3.6.8 (PDF pp. 100 and 102) document 61/62 as absence from self-employment work associated with codes 11/12/21, and 71/72 as absence from regular salaried/wage work associated with code 31. Config now groups 61/62 with the broad self-employment category, and 71/72 with wage employment. Codes 91–98 are all mapped only to the broad out-of-labour-force state. No individual meanings for 91–98 or meaning for 99 are invented; 99 remains MISSING/unclassified. Blank/NA observations stay MISSING, never unemployment.

The synthetic `education_training` state uses a reserved `SYNTHETIC:` code and cannot map real CWS code 91.

## Historical validation results

- Full pytest: **175 passed, 3 warnings, exit 0** (`python -B -m pytest -q -p no:cacheprovider`). Warnings are the configured maximum-distance treatment for unit pairs with fewer than two jointly observed visits.
- Read-only CHECKPOINT 1 audit: **exit 0**, `python -m src.data_audit --no-write`. It emitted two pandas `FutureWarning`s in the audit ambiguity-report formatting; no audit file was written.
- The real-data audit uses `--no-write`; real trajectories and clustering were not run.
- Safety-gate behavior remains fail-closed. CHECKPOINT 1 is unresolved and `data.plan` is `UNSET`.
- Raw data were preserved. No records were deleted or excluded by linkage flags.
- Raw data SHA-256 values remain unchanged from the baseline audit: `perv1` `b852af28508a230270b2d371e5a975230dbc363982bad97d1dc8f2601c2664f6`; `perrv` `2a20a9d4ce8276c4b713494a126d54a8521596239d63e5d4a8dd4f7c5bc00963`; `hhv1` `abf63f803b7239f8f3f316ffc28ff44587d99c94362bfad7ab0989049d7c9b2e`; `hhrv` `244bdf31d3a4ef42ea2794f4c1f93db1e2a3569b252a563f6a2028182a7ae9b2`.

## Historical next steps for reopening the longitudinal design

1. Obtain and record the CHECKPOINT 1 decision and select the approved data plan.
2. Resolve persistent person-link semantics and confirm required invariant design fields.
3. Resolve individual CWS code 91–98 labels and code 99, and determine whether a person-level lost code exists.
4. Establish training completion before the employment observations using documented timing evidence.
5. Confirm the longitudinal weight and permitted profiling variables/output restrictions.
6. Rerun CHECKPOINT 1 and tests, then consider real trajectories only after every gate condition passes.
7. Do not run real-data clustering until CHECKPOINT 1 and all gate conditions have passed.
