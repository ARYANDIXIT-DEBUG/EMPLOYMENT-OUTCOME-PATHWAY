# Cross-sectional method

## Research question

Among PLFS 2023–24 first-visit respondents aged 15–59 who report formal vocational/technical training, what is the annual weighted distribution of Current Weekly Status (CWS), overall and separately for rural and urban respondents?

This replaces the original pathway question for real-data work. The analysis is descriptive and cross-sectional; it does not estimate a causal effect, post-training outcomes, or transitions.

## Cohort and fields

Use the Catalogue 213 `perv1` file only. Include records where `visit_perv1=V1`, age is 15–59, and `b4q12_perv1=1`. Include both sectors (`b1q3_perv1=1` rural and `2` urban), and report each separately and combined. Do not link people across visits.

The formal vocational/technical training follow-up in Block 4.1 is for ages 12–59 and those with code 1 in Block 4 column 12 (Instruction Manual Vol. II, Schedule 10.4, pp. 5–6). The analysis uses age 15–59 for a working-age CWS indicator. CWS uses only the broad documented groups from Instruction Manual Vol. I §3.6.14: codes 11–72 employed, 81/82 unemployed, 91–98 out of labour force. Do not assign individual meanings to 91–98. Code 99 and blank/NA remain missing/unresolved, never unemployment.

## Annual survey weights

The Catalogue 213 rider §B states the combined-subsample multiplier is `MULT/100` when `NSS=NSC`, otherwise `MULT/200`. For an annual estimate, `MULT` may be divided by `NO_QTR`. This implementation uses:

```text
annual_weight = MULT / (100 if NSS == NSC else 200) / NO_QTR
```

Fields are `mult_perv1`, `NSS_perv1`, `NSC_perv1`, and `no_qtr_perv1`. Missing, nonnumeric, or nonpositive components stop the analysis. The same weights are used for combined, rural, and urban point estimates. A design-based variance estimator is not currently implemented, so results have no standard errors or confidence intervals.

The published final multipliers are used as documented. There is no sample nonresponse/casualty field in `perv1`, so response rates and a separate nonresponse adjustment cannot be independently assessed from these person records. The estimation procedure defines its FSU count excluding casualty units; no additional response adjustment is inferred.

## Outcomes

- WPR = weighted employed / weighted selected population.
- LFPR = weighted (employed + unemployed) / weighted selected population.
- UR = weighted unemployed / weighted (employed + unemployed).

Also report raw counts and weighted shares for employed, unemployed and out of labour force. A CWS value outside the broad documented categories stops validation. Missing values remain records with missing outcome status, are counted explicitly, and do not enter an invented category. The actual selected cohort has no missing or unclassified CWS values.

## Features and clustering

The analysis has one categorical outcome, broad CWS. Clustering that single outcome would only reproduce the outcome classes. Occupational/industry fields apply only to people with work records and would make the cohort conditional on employment. No profiling whitelist is present. The cross-sectional route therefore performs no PAM, hierarchical clustering or profile analysis. The original methods and pipeline remain preserved for a future design if justified.

## Validation and reproduction

The route checks the first-visit record key, quarter/visit coverage, cohort fields, weight components and CWS classification. It does not call the longitudinal linker or open CHECKPOINT 1. Run:

```powershell
python -B -m src.cross_sectional
python -B -m pytest -q -p no:cacheprovider
streamlit run dashboard/app.py
```

Results are stored in `outputs/cross_sectional/real/`. The JSON includes the raw input hash, configuration hash, frozen cohort, mappings, weight rule and limitations. The dashboard reads these files and hides them if the cross-sectional gate fails or hashes no longer match.

## Official source locations

- MoSPI, PLFS 2023–24 user rider, §B: multiplier, combined subsamples and annual `NO_QTR` adjustment (`docs/mospi/PLFS_2023-24_1_README.docx`).
- MoSPI, PLFS 2023–24 Sample Design and Estimation Procedure, §§4.1–4.2, pp. 8–10: annual rural and urban estimation from four quarters and ratio estimates (`docs/mospi/PLFS_2023-24_Estimation_Procedure.pdf`).
- MoSPI, PLFS 2023–24 Instruction Manual Vol. II, Schedule 10.4, pp. 5–6 (`docs/mospi/PLFS_2023-24_Instruction_Manual_Vol_II.pdf`).
- MoSPI, PLFS 2023–24 Instruction Manual Vol. I, §3.6.14, PDF pp. 104–106 (`docs/mospi/PLFS_2023-24_Instruction_Manual_Vol_I.pdf`).
- MoSPI, PLFS 2023–24 Annual Report press note, Table 5: CWS WPR for persons age 15 years and above, with rural, urban and combined estimates ([official press note](https://www.mospi.gov.in/sites/default/files/press_release/Press_note_AR_PLFS_2023_24_22092024.pdf)).
- Catalogue 213 layout and DDI (`docs/mospi/Data_LayoutPLFS_2023-24.xlsx`, `docs/mospi/PLFS_2023-24_Catalogue213_DDI.xml`).
