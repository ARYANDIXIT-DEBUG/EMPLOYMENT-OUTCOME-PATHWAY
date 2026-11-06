# CHECKPOINT 1 — real-data rerun

> This records the audit run and gate implementation at that time. Final verification subsequently added fail-closed gate checks for explicit CHECKPOINT 1 status, b4q12 permission, non-empty lost codes plus nonresponse field, and verified dated training timing. None of those statuses was written to the working config; current gate behavior is documented in `reports/10_readiness.md`.

Run date: 2026-11-06. Command: `.venv\\Scripts\\python.exe -m src.data_audit --config config.yaml --no-write`. Exit code: **0**. The audit ran on the local real-data files and did not write the audit JSON. It did not build trajectories or start clustering.

## Overall status: **BLOCKED**

The diagnostic audit completed, but CHECKPOINT 1 is not passed. At this audit run, `data.plan` was `UNSET`; `data.verified: true` was not supported by the project’s official-document verification log, which says the official dictionary/layout, manual, release notes, and rider were absent. At that time, the gate did not separately require a b4q12 permission status; final verification subsequently hardened that check without setting permission.

## Gate/code inspection

`src/data_audit.py::_linkage` lazily imports and calls `src.data_loader.quarter_aware_link_keys(..., strict=False)`. This is the same shared implementation used by the loader after the Prompt 3 synchronization. It derives a V1-cohort candidate key from the supplied sample key, quarter, and visit; it does not certify those fields as an official person key. The actual CHECKPOINT 1 run reported quarter/visit collision groups/excess rows as **0/0**. The legacy key/time diagnostic is still printed for comparison as **3,390/3,390**; these are legacy coordinate collisions, not confirmed duplicate records and not the quarter-aware result.

## CHECKPOINT 1 checks

| Check | Result | Reproduced evidence |
|---|---|---|
| Person and household files readable | **PASS (technical)** | `perv1` 418,159 rows; `perrv` 504,440; `hhv1` 101,920; `hhrv` 132,844. Audit printed SHA-256 prefixes for all four. |
| Four visit labels present | **PASS (technical)** | `V1`, `V2`, `V3`, `V4` in that order; perrv counts V2 170,054, V3 167,594, V4 166,792. Official quarter/visit semantics remain unconfirmed in the workspace documentation. |
| Shared quarter-aware linking used | **PASS (implementation and run)** | `data_audit.py` calls loader’s helper; 922,599 person rows, 546,423 candidate keys, 0 missing full keys, 0 quarter/visit key-coordinate collision excess rows. |
| Candidate linkage volume | **PASS (reproduced, semantics unconfirmed)** | 211,111 candidates linked at 2+ points (38.6%); 22.6% at 3+ points; 7.6% at all 4; mean 1.69 points. Histogram: 1 point 335,312; 2 points 87,350; 3 points 82,457; 4 points 41,304. |
| Legacy coordinate diagnostic | **PASS (reproduced; not current linkage rule)** | 3,390 collision groups / 3,390 excess rows under legacy key/time; 0/0 under quarter-aware key/quarter/visit. Neither result establishes identical rows. |
| Declared design compatibility | **PASS (configuration check only)** | One declared design ID, `PLFS-2023-24-rotational-panel`, no declared mix. Audit explicitly labels design as declared, not verified. Official identifier/link definitions remain unconfirmed. |
| Sex/age/sector cross-visit checks | **FAIL / unresolved** | 238 candidate keys have changing sex; 710 have any raw age change; official age tolerance is unavailable; sector changes 0. Causes cannot be classified as collision, entry error, or legitimate change from current evidence. |
| Weight and nonresponse/casualty mappings | **FAIL / unresolved** | Schema issues: weight unset; `nonresponse_col` unset, so no record can be classified as lost. Audit reported no casualty codes because no nonresponse field was read. |
| Training-field meaning | **FAIL / unresolved** | `b4q12` is present in perv1 (418,159 records), marked ambiguous by the audit; 13,031 records have code `1`. The code/refers-to mapping is not established from a questionnaire in the workspace. `b4pt1q3` is also marked ambiguous. |
| Permission to select trainees using `b4q12` | **UNRESOLVED — blocker** | Actual 2023–24 rider text/permission is not in the workspace or decision log. The local assessment calls trainee selection “Unclear” and says its author has not read the rider. No permission flag was set. |
| Real-model gate | **FAIL (closed as intended)** | `data.plan: UNSET`; `run_pipeline.check_data_gate` refuses a real modeling run at this first condition. No attempt was made to open it. |

The audit’s declared trainee counts are diagnostic only, not authorization or an approved trainee analysis: `b4q12 == 1` flags 13,031 candidates; 5,860 survive 2+ visit linkage, 3,867 have at least 3 visits, and 1,940 have all four visits. No trajectories or clusters were run.

## Official documentation and rider evidence

The official [Catalogue 213 perv1 data dictionary](https://microdata.gov.in/NADA/index.php/catalog/213/data-dictionary/F4) labels `b4q12_perv1` **“Whether received any Vocational/Technical Training.”** That identifies the variable’s subject; it does not state that it may be used to select a study sample. The [Catalogue 213 related-materials page](https://microdata.gov.in/nada/index.php/catalog/213/related-materials) lists the 2023–24 layout, README, manuals, estimation procedure, and updated-instruction note, but the actual rider text and a permission decision were not available in the workspace. The local [`docs/DATA_USE_ASSESSMENT.md`](../docs/DATA_USE_ASSESSMENT.md) states that its author has not read the rider and marks trainee selection unclear; it is not an official source.

The official [PLFS July 2022–June 2023 unit-level data README/rider](https://microdata.gov.in/nada43/index.php/catalog/210/download/2445) says: **“The unit level data of PLFS should not be specifically used for studying of any variable other than the employment and unemployment indicators.”** That is an official restriction in the prior-year release, not a confirmed copy of the 2023–24 rider. The same prior-year rider does not specifically resolve whether using a training variable only to select a sample is allowed. Because the 2023–24 release-specific rider/permission is unconfirmed, permission for this use remains **UNRESOLVED**; no interpretation of silence as permission is made.

The online official [Catalogue 213 dictionary page](https://microdata.gov.in/NADA/index.php/catalog/213/data-dictionary/F4) confirms the label above. The release’s official [related materials listing](https://microdata.gov.in/nada/index.php/catalog/213/related-materials) does not list a separate rider document by title. No release-specific rider text is quoted here.

## Blocking reasons and what is needed

1. `data.plan` remains `UNSET`; do not begin Prompts 7–10 until the user makes a documented Plan A decision after addressing the findings.
2. Provide the actual 2023–24 data-use rider/terms and written authorization from the responsible MoSPI authority or instructor that explicitly answers: “May `b4q12` be used solely to select the sample of trainees for an employment-outcome analysis?” Record the decision, approver, date, and rider section in the project decision log. Until then, selection permission is **UNRESOLVED**.
3. Supply/verify official identifier, quarter/visit, CWS, weight, casualty, and training documentation. Reconcile the official sources with the local `data.verified: true` setting; this report does not change it.
4. Resolve sex-change and age-change candidate links using official definitions and review evidence; obtain the official age tolerance before calling any age change implausible.
5. Confirm the appropriate longitudinal multiplier and casualty/nonresponse mapping, or document that no such fields/codes apply to this analysis.

No gate conditions or permission flags were altered. **Stop here; Prompts 7–10 remain blocked.**
