# Final acceptance audit: INT396 G24 Turkey ISKUR CA

**Audit date:** 2026-11-07. **Primary source:** World Bank Turkey ISKUR Vocational Training Program for the Unemployed Impact Evaluation, 2010–2012, with administrative outcomes through 2013. **Decision:** the CA is framed as a descriptive study of historical Turkish applicants. It does not establish Maharashtra or India outcomes.

## Verified dataset and design

The working DTA is 41,973,573 bytes, has SHA-256 `1bb32513435d605f48c90dca4264b678b082814dc7ad2106ecb4a144b84e96fc`, contains 5,902 rows and 1,535 variables, and has Stata timestamp 2 April 2014. `UNIQID` is complete and unique. `MM_Group` assignment agrees with `Treat` for every row. Interview flags and actual interview dates are checked separately from course dates.

There are 3,385 valid baseline interviews dated strictly before actual course start, 5,499 valid follow-up interviews dated after course end, and 373 source follow-up attrition flags. Random assignment, reported course selection, administrative attendance evidence, course completion, certificate receipt, and self-reported completion remain distinct. Primary pathways include documented actual attendees with all three valid outcomes: 1,546 records.

The sequence is (1) any work at a valid pre-course survey interview, (2) any work at a valid post-course survey interview, and (3) formal Social Security employment in August 2013, only where the course ended before August. The third measure is narrower than “worked at all.” Missing or untimed outcomes remain unknown. `not working` is not relabeled as unemployed.

## Clustering and results

Average-linkage agglomerative clustering is fitted using individual pairwise Hamming distances on three binary points. Candidate k=2–5 are compared by the full precomputed Hamming silhouette; the selected solution is the highest-scoring candidate whose smallest group is at least 5% of the complete pathway cohort. k=5 scores 0.7691 but has 44 cases (2.85%), so it is ineligible. Selected k=4 scores **0.7482927**. The ordered groups are: 623 (40.3%; patterns 000+100), 245 (15.8%; 001+101), 590 (38.2%; 010+011), and 88 (5.7%; 110+111). The groups combine exact sequences; they are not a one-cluster-per-pattern artifact.

The stability diagnostic uses 100 seeded 80% subsamples, refits the same method, assigns all records to the nearest subsample medoid, and compares assignments to the full-data labels by ARI. Mean ARI is **0.6197633** (SD 0.0803727; minimum and 10th percentile 0.5326073). This is moderate resampling stability, not external validity. With three binary points there are only eight possible exact patterns; a high silhouette does not prove natural latent groups.

Baseline comparison: n=3,385; 393 worked at all (11.6%) and 2,992 did not. Follow-up any-work shares are 53.1% and 42.1%; August formal-work shares are 55.2% and 41.4%. These are descriptive, unadjusted comparisons.

Among 1,623 documented attendees with a valid pre-course baseline, 1,548 have verified post-course survey follow-up and 75 do not. Extreme bounds for follow-up any-work prevalence are 41.8%–46.5%; assignments of missing cases occur only in the bound calculation. The row-level analysis retains missing values. Frozen-medoid scenarios are sensitivity diagnostics and are not alternative observed outcomes.

## Acceptance categories

| Category | Status | Evidence / remaining limit |
|---|---|---|
| 1. Dataset validity | PASS | Source DTA, row/variable counts, source timestamp, unique IDs, assignment cross-check and input SHA-256 verified. The file is excluded from the release package. |
| 2. Data preprocessing | PASS | Explicit nullable mappings; assignment, selection, attendance, completion and certification remain separate; missing outcomes are not converted to unemployment. |
| 3. Temporal validity | PASS | Actual interview dates are compared strictly with exact administrative course dates; August outcome is gated by course-end timing. |
| 4. Clustering methodology | PASS | Documented actual attendees and complete outcomes; average-linkage/Hamming; deterministic labels; explicit k rule and 5% minimum. |
| 5. Cluster evaluation | PASS | Individual-level Hamming silhouette, k comparison, exact-pattern composition, and 100-replicate ARI stability are saved and reproduced. Latent-class interpretation remains limited. |
| 6. Attrition analysis | PASS | Denominators, response/admin comparisons, extreme outcome bounds and fixed-medoid cluster scenarios are reported; no missing cases are imputed in the data. Unknown attritor states cannot be recovered. |
| 7. Dashboard functionality | PASS | Turkey is the default page; PLFS and synthetic pathways are separate. Dashboard self-test passes 19/19; browser viewports at 1366×768 and 1920×1080 show no horizontal document overflow; all 12 legacy PLFS checkpoints are visible without internal scrolling. The missing PLFS source is named as `data/raw/perv1.csv`; no local path is displayed. |
| 8. Code quality | PASS | Pipeline imports and runs, outputs are written to an isolated Turkey directory, exceptions fail closed for invalid required fields, and no new dependencies were added. No separate lint suite is configured. |
| 9. Test coverage | PARTIAL | 188 passed, 1 failed, 3 warnings at last full run. The sole failure is the saved PLFS view integrity test because authentic `data/raw/perv1.csv` is absent. The warnings report the configured maximum-distance fallback for undefined low-overlap pairs in legacy synthetic tests; this conservative choice may overstate dissimilarity when missingness is extensive. Turkey uses complete three-point sequences and is unaffected. |
| 10. Documentation accuracy | PASS | README, dataset setup, data-use assessment, interface contract, Turkey methods/data dictionary, report, audit, and viva guide state the Turkish geography, 2010–2013 outcome period, descriptive scope and limitations. |
| 11. Presentation quality | PASS | Eight-slide Turkey deck checked against saved outputs and scope; cover wording was narrowed to descriptive sequence analysis and two empty shapes were removed. Separate eight-slide PLFS deck's stale test count was corrected. Both decks were text-reviewed; finalizer layout checks pass. |
| 12. Reproducibility | PARTIAL | Turkey pipeline and six focused tests pass in the current Python 3.13 Windows environment; release manifest and deterministic builder verified. A fresh isolated environment was not created, and raw DTA is intentionally not packaged. |
| 13. Data licensing and academic scope | PARTIAL | World Bank catalog research/non-identification and no-redistribution terms are documented and row-level files are excluded. Actual source download date was not recorded in this workspace and must be added to the dataset citation. Geography and causal limitations are explicit. |
| 14. Overall CA submission readiness | PARTIAL | Turkey CA deliverables and an aggregate-only reproducible package are prepared for evaluation. Full project tests retain one external PLFS data blocker; Turkey source acquisition date remains to document. The project is not evidence for Maharashtra/SIH employment outcomes. |

## Tests and operations

| Command | Result |
|---|---|
| `python -B -m src.turkey_pipeline` | Completed; 5,902 rows, 1,546 primary sequences, k=4, silhouette 0.7482927, 100 stability refits, mean ARI 0.6197633. |
| `python -B -m pytest -q -p no:cacheprovider tests/test_turkey_pipeline.py` | 6 passed. |
| `python -B -m pytest -q -p no:cacheprovider` | 188 passed, 1 failed, 3 warnings. Failure: PLFS saved-output check cannot validate without authentic `data/raw/perv1.csv`; expected SHA-256 `b852af28508a230270b2d371e5a975230dbc363982bad97d1dc8f2601c2664f6`. No replacement or weakened hash guard was used. |
| `python run_pipeline.py --self-test` | Passed 20 checks; all data in this self-test are synthetic. |
| `python dashboard/app.py --self-test` | Passed 19 checks after dashboard navigation and layout changes; PLFS gate fixtures are synthetic and the Turkey display check reads hash-verified saved analysis outputs. The “gate open” and missing-results fixtures use complete test-only readiness configuration. Production gates were not changed. |
| `python -B scripts/build_release.py` | Builds 70 explicitly listed files in `submission/Turkey_CA_Submission/` and `submission/Turkey_CA_Submission.zip`; raw and row-level files are excluded. The final archive digest is reported separately from the package contents. |

The three pytest warnings report low-overlap pairs assigned the configured maximum distance in legacy PLFS distance/stability tests. They are not suppressed. The separate PLFS dashboard test fails because the local checkout lacks its source data; the MoSPI Catalogue 213 download requires account login/register. The file was not present in the project, external backup copy, or searched user folders. Obtain it from the [official MoSPI catalog](https://microdata.gov.in/nada/index.php/catalog/213/get-microdata) and verify the expected hash before rerunning the suite.

## Deliverables and external items

- Primary report: `reports/TURKEY_FINAL_REPORT.md`.
- This audit: `reports/TURKEY_REQUIREMENT_AUDIT.md`.
- Primary presentation: `submission/Turkey_ISKUR_CA_presentation_v4.pptx`; the cover identifies INT396/G24 and the historical dataset. The separate PLFS v3 deck is retained as a legacy deliverable.
- Responsive dashboard evidence: `reports/dashboard_screenshots/primary_turkey_1366x768.jpg` and `reports/dashboard_screenshots/primary_turkey_1920x1080.jpg`.
- Primary viva material: `VIVA_GUIDE.md`.
- Aggregate analysis outputs: `outputs/turkey/` (cluster-level tables and summary only in the release).
- Complete package directory and ZIP: `submission/Turkey_CA_Submission/`, `submission/Turkey_CA_Submission.zip`.
- Dataset description and reproduction: `docs/TURKEY_DATA_DICTIONARY.md`, `DATASET_SETUP.md`.

Before an archival dataset citation, record the actual World Bank catalog download date from the acquisition record. For the preserved PLFS route, restore only the authenticated original `perv1.csv` matching the stated SHA-256; do not fabricate or weaken the test. Never claim that the Turkish findings represent Maharashtra or India.
