# Cross-sectional field dictionary

Canonical fields loaded by `src/cross_sectional.py` from Catalogue 213 `perv1`.

| Canonical field | Raw CSV column | Meaning and valid use |
|---|---|---|
| `state` | `state_perv1` | State/UT record-key component. |
| `fsu` | `b1q1_perv1` | First-stage unit serial; record-key component. |
| `sg_sb` | `b1q13_perv1` | Sample hamlet-group/sub-block; record-key component. |
| `stratum2` | `b1q14_perv1` | Second-stage stratum; record-key component. |
| `hh_no` | `b1q15_perv1` | Sample household number; record-key component. |
| `person_no` | `b4q1_perv1` | Person serial; record-key component. |
| `qtr` | `qtr_perv1` | Quarter Q1–Q4. Used to verify annual sample coverage. |
| `visit` | `visit_perv1` | First visit, V1. |
| `sector` | `b1q3_perv1` | 1 rural; 2 urban. |
| `age` | `b4q6_perv1` | Age in years; cohort uses 15–59. |
| `b4q12` | `b4q12_perv1` | Whether vocational/technical training received; code 1 identifies the formal training follow-up group in Schedule 10.4. |
| `cws` | `b6q5_perv1` | Current Weekly Status. Broad groups only: 11–72 employed; 81/82 unemployed; 91–98 out of labour force. Other values unresolved; blanks stay missing. |
| `wt` | `mult_perv1` | Multiplier stored with two decimal places, requiring division by 100 or 200 per combined-subsample procedure. |
| `nss` | `NSS_perv1` | NSS first-stage-unit count within second-stage stratum; compared with NSC for combined subsample scaling. |
| `nsc` | `NSC_perv1` | NSC first-stage-unit count within second-stage stratum; compared with NSS. |
| `no_qtr` | `no_qtr_perv1` | Number of contributing quarters for the sector/state/stratum/sub-stratum unit; annual adjustment divisor. |
| `annual_weight` | Derived | `MULT / (100 if NSS == NSC else 200) / NO_QTR`. |
| `cws_group` | Derived | `employed`, `unemployed`, or `out_of_labour_force` from the documented broad code ranges. |

The first-visit record key is quarter, visit, sector, state, FSU, Sg/Sb, second-stage stratum, household number and person serial. It is checked for uniqueness only; it is not a persistent cross-visit person key.
