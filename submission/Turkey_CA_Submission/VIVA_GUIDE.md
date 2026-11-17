# INT396 G24 viva guide: Turkey ISKUR pathways

## 60-second summary

This CA describes observed employment sequences among applicants to Turkey's İŞKUR vocational training program. The World Bank public-use file contains 5,902 applicants from the 2010–2013 evaluation. I keep randomized assignment, reported selection, administrative attendance, completion, and certificate receipt separate. The primary cohort is 1,546 documented attendees with a valid pre-course interview, valid post-course interview, and August 2013 Social Security employment outcome. Average-linkage clustering on the individual Hamming distance selects four groups. The results describe this historical Turkish sample; they do not estimate a training effect or represent Maharashtra or India.

## Questions and answers

### Why use this dataset?

It provides a documented applicant population, randomized assignment, course administration records, dated baseline and follow-up interviews, and administrative formal-employment outcomes. This supports a historically scoped descriptive CA with real timing evidence. The released file does not include the month-by-month job spell dates described in related research.

### Why cluster employment sequences?

The question is whether people with different observed employment histories can be summarized into readable sequence groups. The groups are descriptive summaries. Random assignment is not used here to claim a causal program effect.

### Who enters the pathway analysis?

People with evidence of actual course attendance (positive administrative attendance days or a documented first/second-day dropout) and all three valid outcomes: any work at a baseline interview strictly before course start; any work at a follow-up interview strictly after course end; and formal Social Security employment in August 2013, conditional on course end preceding that month. This yields 1,546 complete sequences. Unknown attendance is not treated as participation.

### Why are assignment, selection, attendance, completion, and certification separate?

`MM_Group` records randomized assignment; `FF_C60` is a respondent's selection report; administrative days or early dropout flags establish attendance evidence; `MIS_EC22` records course completion; and `MIS_EC23` asks whether the evaluation-course certificate was received. These are distinct events. Neither completion nor a certificate is used as a substitute for attendance.

### Why four clusters?

The pipeline tests k=2 through 5 using individual-level Hamming silhouettes and requires each cluster to contain at least 5% of the 1,546 sequences. k=5 has the highest raw silhouette (0.7691), but its smallest cluster is 44 people (2.85%), below the predeclared 5% floor. k=4 is the highest-scoring admissible solution (0.7483); k=3 scores 0.6358. This is a transparent selection rule, not proof that four natural types exist.

### What does Hamming distance measure?

For two three-point binary sequences, it is the share of observation points where their states differ. For example, `0→1→0` and `0→1→1` differ at one of three points, so their distance is 1/3. Silhouette is calculated from the full individual pairwise Hamming-distance matrix.

### What does a silhouette of 0.7483 mean?

It indicates that, under this distance and four-cluster partition, observations tend to be closer to their assigned group than to the nearest alternative. Because sequences have only three binary points and only eight exact patterns are possible, this score measures separation in a small sequence space; it does not establish latent classes or external validity.

### What does mean ARI 0.6198 mean?

Across 100 deterministic 80% subsamples, the same clustering method is refit and all cases are assigned to the nearest subsample medoid. The mean adjusted Rand index of 0.6198 summarizes agreement with the full-data labels after accounting for chance. It is moderate sample stability, not test–retest reliability, causal evidence, or proof of population-level robustness. The standard deviation is 0.0804.

### Why include baseline employment?

It distinguishes people who were already working before training from those not working at the dated baseline. Among 3,385 valid pre-course respondents, 393 (11.6%) worked at all and 2,992 did not. “Not working” is not synonymous with unemployed; it can include people outside the labour force. Baseline comparisons are descriptive and unadjusted.

### How are attrition and missing outcomes handled?

Only interviews passing response flags, containing real interview dates, and occurring on the correct side of course dates contribute survey outcomes. Missing outcomes remain unknown. Of 1,623 documented attendees with a valid pre-course baseline, 1,548 have verified follow-up and 75 do not. Extreme bounds put follow-up any-work prevalence at 41.8%–46.5% by assigning missing outcomes to either state for the bound calculation only. Those states are never imputed into the analysis file.

### What are the four groups?

The ordered groups combine exact sequences: (1) `000` and `100`, no follow-up work and no August formal job; (2) `001` and `101`, no follow-up work but formal employment by August 2013; (3) `010` and `011`, not working at baseline but working at follow-up; and (4) `110` and `111`, working at both survey points. The final position is narrower than “worked at all” because it measures formal Social Security employment.

### Can the findings be generalized to Maharashtra or India?

No. The applicants, program, geography, and historical period are Turkish. The preserved PLFS route is a separate cross-sectional descriptive analysis and does not validate Maharashtra employment pathways.

### What are the main limitations?

The sequence has only three points and mixes two survey “any work” measures with a later formal-employment measure. There are only eight possible binary patterns, the final measure is narrower, 75 baseline attendees lack verified follow-up, and public-use data lack monthly formal-job spell dates. Clustering is descriptive, and none of the estimates is causal.

## Reproduction and evidence

```powershell
python -B -m src.turkey_pipeline
python -B -m pytest -q -p no:cacheprovider tests/test_turkey_pipeline.py
python dashboard/app.py --self-test
streamlit run dashboard/app.py
```

Use [the final Turkey report](reports/TURKEY_FINAL_REPORT.md), [the generated profile report](outputs/turkey/cluster_profile_report.md), and [the requirement audit](reports/TURKEY_REQUIREMENT_AUDIT.md) for exact tables and evidence. The raw dataset is not included in submission packages; obtain it under the World Bank catalog conditions and verify its SHA-256 against the recorded run metadata.

## Preserved PLFS viva material

The separate cross-sectional PLFS question and its limitations are documented in [the legacy viva Q&A](reports/viva_questions_and_answers.md). Do not combine its estimates with the Turkey analysis.
