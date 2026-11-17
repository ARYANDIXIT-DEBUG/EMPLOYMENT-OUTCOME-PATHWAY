# Employment Outcome Pathway Grouping After Skilling

## Current CA analysis

The primary completed CA analysis uses the World Bank Turkey Vocational Training Program (ISKUR) public-use dataset. It is a **historical Turkish evaluation from 2010–2013**, not Indian or Maharashtra evidence. The submission and presentation must retain this geographical, population, and historical scope.

The reproducible Turkey pipeline validates exact course start/end and interview dates, gates missing baseline/follow-up outcomes, preserves assignment/selection/attendance/completion/certificate as separate constructs, uses observed administrative employment outcomes, builds three-point employment sequences, evaluates Hamming silhouette and 80% subsample stability, and calculates attrition bounds without imputing unknown states. See the [Turkey methodology and data dictionary](docs/TURKEY_DATA_DICTIONARY.md), [results](outputs/turkey/cluster_profile_report.md), and [final requirement audit](reports/TURKEY_REQUIREMENT_AUDIT.md).

### Reproduce

```powershell
python -B -m src.turkey_pipeline
python -B -m pytest -q -p no:cacheprovider
streamlit run dashboard/app.py
```

The dashboard displays saved Turkey results after validating the source hash. Core results: 5,902 applicants; 3,385 valid pre-course baseline interviews; 1,546 complete three-point sequences among people with documented course attendance; selected k=4; individual Hamming silhouette 0.7483; 100-refit subsample stability mean ARI 0.620 (SD 0.080). These are descriptive results, not training effects. The sequence combines survey “worked at all” at baseline/follow-up with August 2013 formal Social Security employment, a narrower final measure.

Presentation: [Turkey ISKUR CA presentation](submission/Turkey_ISKUR_CA_presentation_v4.pptx). The updated PLFS presentation is preserved separately and must not be used to describe these Turkey findings. The release builder stages the source, tests, documentation, aggregate outputs, and presentation in `submission/Turkey_CA_Submission/` and builds `submission/Turkey_CA_Submission.zip` without raw or respondent-level data.

Responsive screenshots of the primary dashboard are saved at [1366×768](reports/dashboard_screenshots/primary_turkey_1366x768.jpg) and [1920×1080](reports/dashboard_screenshots/primary_turkey_1920x1080.jpg).

## Preserved PLFS 2023–24 project route

The original PLFS dataset and pipeline remain separate and intact. PLFS real-data work is a cross-sectional descriptive analysis, not a linked longitudinal outcome pathway study. Its inputs, gates, and existing analysis outputs are documented in [dataset setup](DATASET_SETUP.md), [cross-sectional methodology](docs/METHODOLOGY_CROSS_SECTIONAL.md), and [original audit](FINAL_AUDIT_REPORT.md). The raw `perv1.csv` file is absent from the current checkout; a hash-bound existing dashboard safety test consequently fails. The test, input hash guard, and PLFS pipeline have not been weakened, and no fabricated source file was added.

## Project limitations and submission language

- Turkey results may be submitted for the CA only when clearly titled and described as a historical Turkish ISKUR evaluation.
- Do not present any Turkey estimate as a Maharashtra, Indian, or current-program employment outcome.
- Clusters summarize observed sequence similarity and do not establish causal program impact or latent natural classes.
- Baseline “not employed” means not working in the source reference period, not necessarily unemployed.
- Missing survey outcomes remain unknown; extreme sensitivity bounds are not recovered outcomes.
- The public-use file does not include the month-by-month job registration/spell dates described in related research.
- Full project pytest currently needs the authenticated original `perv1.csv` at `data/raw/perv1.csv` to satisfy an existing PLFS hash/input test.

## Project identity and preserved submission materials

Project identity: Employment Outcome Pathway Grouping After Skilling — INT396 | G24 | CA Project. The primary analysis is the historical Turkey ISKUR Vocational Training Evaluation (2010–2013). Existing PLFS artifacts and the PLFS viva Q&A are preserved separately and are not evidence for the Turkey analysis. Use [the Turkey viva guide](VIVA_GUIDE.md) for the primary CA.
