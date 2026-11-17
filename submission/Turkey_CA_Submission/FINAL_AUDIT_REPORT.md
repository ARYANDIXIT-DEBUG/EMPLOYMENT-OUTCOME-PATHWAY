# Project data and submission audit

**Updated:** 2026-11-07. The completed CA analysis is the Turkey ISKUR evaluation. The previously developed PLFS route is preserved and remains separate from the primary dashboard view.

## Primary CA analysis: historical Turkey ISKUR

The DTA contains 5,902 Turkish vocational-training applicants and 1,535 variables. Processing is isolated in `src/turkey_pipeline.py`; the raw data and PLFS sources are not altered. Exact course dates gate employment timing. The analysis has 3,385 valid pre-course baseline respondents and 1,546 complete three-observation sequences among documented course attendees (pre-course survey any-work; post-course survey any-work; August 2013 formal Social Security employment).

Average-linkage agglomerative clustering on individual Hamming distances selects k=4 under a minimum 5% cluster constraint: cluster sizes 623, 245, 590 and 88. Silhouette is 0.7483; 100 deterministic 80% subsamples produce mean ARI 0.620 (SD 0.080). These describe the geometry and sample stability of the observed low-dimensional sequences, not natural latent classes or causal effects. The valid baseline comparison is n=3,385 (393 employed at all, 2,992 not employed). The complement is not synonymous with unemployed.

Among 1,623 documented attendees with pre-course baseline, 75 lack a verified follow-up survey outcome. Follow-up work-rate extreme bounds are 41.8%–46.5%; admin comparisons and fixed-medoid missing-state cluster scenarios are reported. No missing outcomes are imputed. Source certification semantics are verified from the official World Bank variable-construction do-file: `MIS_EC23` asks certificate receipt; blanks remain unknown in the treatment group. Survey reporting, assignment, attendance, completion, and certification are separate.

The public DTA supports first-formal-job milestones, August 2013 point/cumulative outcomes and August earnings, but not the month-by-month job-spell records discussed in related papers. Do not recreate those observations. Turkey is not Maharashtra and cannot support Maharashtra employment conclusions. Complete audit: [Turkey requirement audit](reports/TURKEY_REQUIREMENT_AUDIT.md); detailed definitions and source links: [Turkey data dictionary](docs/TURKEY_DATA_DICTIONARY.md).

## Preserved PLFS 2023–24 work

Prior PLFS analysis remains an independently gated cross-sectional descriptive study of first-visit people aged 15–59 reporting formal vocational/technical training (`b4q12=1`). It does not measure post-training pathways or causal effects. Saved weighted point estimates: combined n=13,027, WPR 62.24%, LFPR 71.45%, UR 12.90%; rural n=5,132, WPR 61.17%, LFPR 70.91%, UR 13.73%; urban n=7,895, WPR 63.32%, LFPR 72.01%, UR 12.06%. Design-based uncertainty was not calculated. Original PLFS methods and outputs are retained.

The raw authenticated `data/raw/perv1.csv` is absent from this checkout. A prior real-data dashboard test binds to expected SHA-256 `b852af28508a230270b2d371e5a975230dbc363982bad97d1dc8f2601c2664f6`. The pipeline/gate and test were not weakened and no substitute file was created. Restoring the authentic source is required to make that pre-existing test pass.

## Readiness decision

**CA submission:** Turkey analysis deliverables are complete, with required geographic/historical disclosure. Claims must be limited to historical Turkish ISKUR applicants.

**Maharashtra/SIH evidence:** FAIL. Turkish data cannot establish Maharashtra outcomes. PLFS path remains cross-sectional and does not fulfill linked post-training trajectory requirements.

**Full test suite:** PARTIAL pending restoration of authentic PLFS input. Turkey-specific tests pass (6/6); full suite is **188 passed, 1 failed, 3 warnings**. The failing test requires missing `data/raw/perv1.csv`, which MoSPI provides behind account login. Restore the official file matching the saved SHA-256 to complete validation. Do not weaken input integrity checks to claim PASS.

**Dashboard checks:** the legacy `run_pipeline.py --self-test` passes 20 checks, and `dashboard/app.py --self-test` passes 19 checks. Turkey is the default dashboard page; it shows only hash-verified Turkey outputs. The gated PLFS and synthetic explorer is a separate navigation page. Browser viewport validation at 1366×768 and 1920×1080 found no document-level horizontal overflow; the legacy page displays all 12 checkpoints without internal table scrolling. The PLFS gate fixtures are synthetic; the gate-passing fixture supplies all required test-only readiness fields, and production gates were not changed. Screenshots are in `reports/dashboard_screenshots/`.

**Distance warnings:** the three full-suite warnings are emitted by legacy missing-trajectory distance tests. When two records share fewer than the configured two observed time points, their empirical distance is undefined; the legacy pairwise distance rule assigns the maximum substitution cost and reports the count. This conservative rule avoids inferring similarity from insufficient overlap, but can overstate dissimilarity under extensive missingness, so warning counts and missing-data sensitivities matter. The primary Turkey analysis requires complete three-point sequences and is unaffected by this legacy warning behavior.

**Release:** `submission/Turkey_CA_Submission/` and `submission/Turkey_CA_Submission.zip` contain 70 allowlisted files: source, tests, essential documentation, Turkey aggregate outputs, dashboard screenshots and both presentations. They exclude the World Bank raw file and respondent-level Turkey derived tables. The World Bank catalog requires research use and non-identification and does not permit redistribution of the microdata; the actual dataset download date is not recorded in this checkout and must be added to the final data citation.

**Overall project readiness: PARTIAL.** The Turkey CA materials are ready for professor evaluation within the historical Turkish scope. Full-project test completion is blocked by the absent authentic PLFS input; a reproducible extraction requires obtaining the Turkey dataset separately. The project is not submission-ready for Maharashtra/SIH employment claims.
