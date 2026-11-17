# Turkey ISKUR evaluation: data dictionary and methods

## Source and scope

`data/raw/TurkeyPublicUseData.dta` is the World Bank public-use microdata for the Turkish Employment Agency (ISKUR) vocational-training evaluation. It contains 5,902 applicants and 1,535 variables; Stata file timestamp 2 April 2014. It is a historical Turkish program evaluation (2010–2013), not PLFS, not Maharashtra, and not Indian employment evidence. Project source metadata and materials are linked below. All results are descriptive pathways and profiles; random assignment is not used here to make causal effect claims.

The independently reproducible Turkey pipeline is `src/turkey_pipeline.py`; it neither reads nor alters PLFS. Run from repository root with `python -B -m src.turkey_pipeline`. The raw DTA is read-only; generated outputs are placed in `outputs/turkey/`. Input SHA-256 is recorded in `summary.json`.

## Analytical variables

Variable labels are read from Stata metadata and preserved in `outputs/turkey/summary.json`. Every raw variable used and its purpose is enumerated in `USED` in the pipeline and repeated here by concept.

| Raw variable | Meaning / use | Validity treatment |
|---|---|---|
| `UNIQID` | Respondent key | Required complete and unique. |
| `MM_Group` | Original randomized assignment (1 treatment, 2 control) | Retained as assignment; cross-checked against source-derived `Treat`. |
| `Treat` | Source-derived randomized treatment indicator | Consistency check only. |
| `BB_dInterview`, `BB_intdate` | Baseline completion flag and actual interview date | Valid baseline requires flag 1 and date. Pre-training only if date strictly precedes administrative course start. |
| `BB_work4wks1` | Worked at all in baseline reference period | Used only if baseline is valid and pre-training; only 0/1 retained. Complement is “not working,” not necessarily unemployed. |
| `FF_FILTER`, `FF_dmiss`, `FF_intdate` | Follow-up result, attrition flag, actual interview date | Valid follow-up requires completed interview, nonattrition and date. Post-training only if date strictly follows actual course end. |
| `FF_work4wks1` | Worked at all in follow-up reference period | Only valid, post-course 0/1 retained. |
| `MIS_EC7`, `MIS_EC8` | Administrative evaluation-course start and end dates | Parsed as exact dates; invalid/missing dates do not establish timing. |
| `MM_gender`, `BB_age` | Gender and baseline age | Descriptive profile only; missing values retained. |
| `FF_C60` | Respondent report of selection for ISKUR course | Selection report, kept separate from randomized assignment and attendance. 1/2 mapped yes/no; other codes remain missing. |
| `FF_C61` | Respondent report of other vocational training attendance | Other training, not evaluated-course participation. |
| `MIS_course_attend_days` | Administrative attendance days | Positive days are direct attendance evidence; missing is not automatically no attendance. |
| `MIS_EC19`, `MIS_EC21` | Administrative first/second-day dropout flags | Yes proves attendance, including early dropouts; distinct from the paper's no-early-dropout take-up convention. |
| `FF_C62` | Self-reported evaluated-course status | Kept separately: 1 dropout, 2 never started, 3 completed. Not used to override administrative attendance/completion. |
| `MIS_EC22` | Administrative course completion response | Yes/No mapped to completion; blank remains unknown. |
| `MIS_EC23` | “Received the certificate of evaluation course” response | Yes/No mapped to certificate receipt; blank remains unknown. Official World Bank `Create Variables File` constructs `MIS_certifiedEC` from this answer and codes blank controls as 0. |
| `MIS_certEC` | Official derived certificate indicator | Cross-check only; do not assume a control blank means a respondent reported a certificate. |
| `employjan12`, `lostjobjan1`, `infformaljob` | January 2012 administrative first-formal-job milestones | Combined as first job not yet obtained / active / left; not monthly repeated outcomes. |
| `everemployed`, `everlostjob` | Ever entered formal job after course / left first formal job by Nov 2013 | Event/history outcomes; not point-in-time employment. |
| `formallyemployedAug2013` | Formal employment in August 2013 per Social Security | Administrative point-in-time measure; third pathway point. |
| `formallyemployedin2013` | Any formal employment in first eight months of 2013 | Cumulative interval, not a separate August wave. |
| `incomeAug2013` | Administrative formal earnings in August 2013 | Numeric administrative outcome; missing preserved. |

## Outcome construction and clustering

The primary complete sequence uses: (1) any work at baseline, only for an interview dated before exact course start; (2) any work at follow-up, only for an interview dated after exact course end; and (3) formal Social Security employment in August 2013. It clusters 1,546 people with direct administrative attendance evidence (positive attendance days or a documented first/second-day dropout) and all three real outcomes. Unknown attendance and never-attenders remain in the row-preserving dataset but are not labeled trainees. The final measure is more restrictive than “worked at all” in the surveys, and this shift in definition is stated in every result view. Jan-2012/Nov-2013 administrative event milestones and August earnings remain available in the trainee-level file for supplementary profiling; they are not misrepresented as equally spaced waves.

Average-linkage agglomerative clustering uses individual-level Hamming distances on the three binary states. Candidate k=2–5 are evaluated; a solution is selected by highest silhouette among candidates with every cluster at least 5% of complete sequences. Clusters combine related patterns and are not one-cluster-per-exact-sequence. The silhouette uses the full pairwise distance matrix. The stability diagnostic refits clustering on 100 deterministic 80% subsamples and compares nearest-medoid assignments with primary labels by ARI; it is a sampling stability diagnostic, not causal validity. Candidate scores, selected cluster sizes and sequence composition are emitted by the pipeline.

Baseline employed vs. not employed is a separate mandatory descriptive comparison among 3,385 valid pre-course respondents (393 worked at all; 2,992 did not). The outcome is not labor-force status: do not call the complement “unemployed.”

## Missingness and attrition

For nonrespondents, source zeros are not interpreted as unemployment. Invalid, absent, or temporally unsupported outcomes remain nullable missing. There are 373 follow-up attritors by `FF_dmiss`; among 1,623 documented attendees with valid pre-course baseline, 75 have no verified post-course survey outcome. `summary.json` reports extreme lower/upper employment bounds without imputing or storing any missing state, compares available administrative August outcomes between survey responders and nonresponders, and reports cluster prevalence under fixed-medoid extreme follow-up state scenarios. These do not establish missing-at-random or recover attritor pathways.

## Data granularity and limits

World Bank project descriptions/publication discuss monthly Social Security registration/job-spell timing for first formal jobs, including first registration and job exit dates. The supplied public-use DTA does not contain those month-level dates or repeated person-month outcomes. It contains summarized event/state milestones listed above. No time points are fabricated. The data can support this CA's Turkish historical evaluation analysis but cannot support Indian/Maharashtra outcome claims.

## Authoritative source materials

- [World Bank microdata catalog and study metadata](https://microdata.worldbank.org/catalog/1973)
- [Catalog questionnaires and Create Variables File](https://microdata.worldbank.org/index.php/catalog/1973/related-materials)
- [World Bank evaluation report (2013)](https://documents1.worldbank.org/curated/en/954771468318313306/pdf/823060P12051400h0final0report0small.pdf)
- [World Bank dictionary: administrative employment outcomes](https://microdata.worldbank.org/catalog/1973/data-dictionary/F1/?offset=1500)
- [Related academic paper describing social-security job histories](https://escholarship.org/content/qt6rm8z78t/qt6rm8z78t.pdf)

## Reproduction

```powershell
python -B -m src.turkey_pipeline
python -B -m pytest -q -p no:cacheprovider
streamlit run dashboard/app.py
```
