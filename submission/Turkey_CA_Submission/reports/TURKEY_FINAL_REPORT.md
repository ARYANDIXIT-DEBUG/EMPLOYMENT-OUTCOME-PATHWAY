# Employment outcome pathways: Turkey ISKUR evaluation

**Project:** Employment Outcome Pathway Grouping After Skilling — INT396 | G24 | CA Project.

**Historical Turkish vocational-training evaluation (2010–2013). This is not Indian or Maharashtra evidence.**

Public-use file: `data\raw\TurkeyPublicUseData.dta` (5,902 rows; SHA-256 `1bb32513435d605f48c90dca4264b678b082814dc7ad2106ecb4a144b84e96fc`).

## Observation and cohort rules

There are 3,385 baseline interviews with actual dates before administrative course commencement. The primary three-point pathway sample contains 1,546 people with documented actual course attendance and all three outcomes observed: baseline any work before course start; follow-up any work after actual course end; and administrative formal employment in August 2013. The final point measures formal work, unlike the two survey any-work measures. Assignment, course selection, attendance, completion, and certificate receipt are distinct; unknown attendance does not qualify someone as a trainee.

## Pathway clusters

| cluster_id | n | treatment_assigned_n | attendance_evidence_n | attendance_known_n | completion_n | completion_known_n | certificate_received_n | certificate_known_n | baseline_any_work_rate | followup_any_work_rate | aug2013_formal_work_rate | age_median | assignment_share | attendance_evidence_share_all | selection_reported_share | completion_share_observed | certificate_share_observed | share_complete_pathways | completion_share_all | certificate_share_all | trajectory_patterns | pathway_label |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 623 | 616 | 623 | 623 | 514 | 623 | 488 | 623 | 0.07062600321027288 | 0.0 | 0.0 | 26.0 | 0.9887640449438202 | 1.0 | 0.9402261712439418 | 0.8250401284109149 | 0.78330658105939 | 0.40297542043984474 | 0.8250401284109149 | 0.78330658105939 | 0->0->0, 1->0->0 | No follow-up work; no August formal job |
| 2 | 245 | 243 | 245 | 245 | 194 | 245 | 182 | 245 | 0.16326530612244897 | 0.0 | 1.0 | 24.0 | 0.9918367346938776 | 1.0 | 0.9465020576131687 | 0.7918367346938775 | 0.7428571428571429 | 0.15847347994825356 | 0.7918367346938775 | 0.7428571428571429 | 0->0->1, 1->0->1 | No follow-up work; formal job by August 2013 |
| 3 | 590 | 582 | 590 | 590 | 462 | 590 | 434 | 590 | 0.0 | 1.0 | 0.635593220338983 | 25.0 | 0.9864406779661017 | 1.0 | 0.9338983050847458 | 0.7830508474576271 | 0.735593220338983 | 0.3816300129366106 | 0.7830508474576271 | 0.735593220338983 | 0->1->0, 0->1->1 | Not working at baseline; working at follow-up |
| 4 | 88 | 85 | 88 | 88 | 61 | 88 | 58 | 88 | 1.0 | 1.0 | 0.6477272727272727 | 26.5 | 0.9659090909090909 | 1.0 | 0.9318181818181818 | 0.6931818181818182 | 0.6590909090909091 | 0.056921086675291076 | 0.6931818181818182 | 0.6590909090909091 | 1->1->0, 1->1->1 | Working at baseline and follow-up |

Selected k=4; individual Hamming silhouette=0.7482926611747323. Candidate results are in `cluster_method_evaluation.csv`. Clusters group similar measured sequences; no sequence is duplicated to inflate silhouette. The selected solution maximizes silhouette among k=2–5 with no cluster below 5%.

## Baseline employed versus not employed

{
  "valid_pretraining_baseline_n": 3385,
  "employed_n": 393,
  "not_employed_n": 2992,
  "employed_share": 0.11610044313146234,
  "definition": "worked at all in baseline reference period, among interviewed respondents with actual interview date strictly before administrative course start",
  "interpretation": "not working is not equivalent to unemployed; it includes people outside the labor force"
}

| employment_baseline | n | assigned_treatment_share | attendance_evidence_n | attendance_evidence_known_n | completion_share_among_known | completion_known_n | certificate_share_among_known | certificate_known_n | postfollowup_any_work_share | aug2013_formal_work_share | attendance_evidence_share_all |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 2992 | 0.48663101604278075 | 1443 | 1443 | 0.797683923705722 | 1468 | 0.752724795640327 | 1468 | 0.4211640211640212 | 0.4135162261625962 | 0.4822860962566845 |
| 1 | 393 | 0.44274809160305345 | 180 | 180 | 0.7333333333333333 | 180 | 0.6944444444444444 | 180 | 0.5305039787798409 | 0.5521628498727735 | 0.4580152671755725 |

Employment means worked at all during the source reference period. The complement is not synonymous with unemployment and includes people outside the labor force. Only respondents interviewed before course start enter this comparison.

## Exposure and certification

Random assignment (`MM_Group`) is separate from self-reported selection (`FF_C60`), administrative attendance evidence (`MIS_course_attend_days` or documented early dropout), course completion (`MIS_EC22`), and certificate receipt (`MIS_EC23`). The official World Bank variable-construction do-file maps the certificate question response Yes to 1 and gives control-arm blanks 0 in its derived field; raw treatment-arm blanks remain unknown. Course status self-report (`FF_C62`) is preserved separately.

## Admin employment history, attrition, and robustness

The public DTA supports first formal-job milestones by Jan-2012 and Nov-2013, and Aug-2013 point/cumulative outcomes. The study paper describes monthly first-job spell data, but those granular dates are not present in the supplied public-use file. The analysis does not invent those time points.
Cluster-level administrative employment milestones (rates use nonmissing source denominators):

| cluster_id | n | formal_entry_by_jan2012_share | ever_formally_employed_postcourse_share | first_job_left_by_nov2013_share | formal_anytime_first8months2013_share | aug2013_formal_income_median | jan2012_first_job_state_known_n |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 623 | 0.21829855537720708 | 0.41252006420545745 | 0.31942215088282505 | 0.18138041733547353 | 0.0 | 623 |
| 2 | 245 | 0.3877551020408163 | 0.8775510204081632 | 0.6 | 1.0 | 1021.510009765625 | 245 |
| 3 | 590 | 0.688135593220339 | 0.811864406779661 | 0.6457627118644068 | 0.7627118644067796 | 1021.5 | 590 |
| 4 | 88 | 0.7159090909090909 | 0.9204545454545454 | 0.7159090909090909 | 0.7272727272727273 | 1021.5 | 88 |

January 2012 first-job state counts and within-cluster shares, including explicit unknowns:

| cluster_id | admin_jan12_first_job_state | n | share_cluster |
| --- | --- | --- | --- |
| 1 | first_job_active_jan2012 | 33 | 0.052969502407704656 |
| 1 | first_job_left_by_jan2012 | 103 | 0.1653290529695024 |
| 1 | no_formal_job_by_jan2012 | 487 | 0.7817014446227929 |
| 2 | first_job_active_jan2012 | 24 | 0.09795918367346938 |
| 2 | first_job_left_by_jan2012 | 71 | 0.2897959183673469 |
| 2 | no_formal_job_by_jan2012 | 150 | 0.6122448979591837 |
| 3 | first_job_active_jan2012 | 197 | 0.3338983050847458 |
| 3 | first_job_left_by_jan2012 | 209 | 0.35423728813559324 |
| 3 | no_formal_job_by_jan2012 | 184 | 0.31186440677966104 |
| 4 | first_job_active_jan2012 | 30 | 0.3409090909090909 |
| 4 | first_job_left_by_jan2012 | 33 | 0.375 |
| 4 | no_formal_job_by_jan2012 | 25 | 0.2840909090909091 |

Among 1,623 pre-course baseline attendees, 1,548 have verified post-course survey follow-up and 75 do not. Worst/best-case bounds for follow-up any-work prevalence are 41.8%–46.5%; unknown survey outcomes remain missing. Administrative August formal-work rates by follow-up response status and frozen-medoid cluster scenarios are in `attrition_admin_comparison.csv` and `summary.json`.
Subsample stability: 100 deterministic 80% refits; ARI mean 0.620, SD 0.080, minimum 0.533, 10th percentile 0.533. This assesses sample stability, not causal validity.

## Geography and use

This is appropriate as a CA analysis of a historical Turkish program when its geography, population, and period are stated. It cannot substantiate Indian or Maharashtra employment outcomes.
