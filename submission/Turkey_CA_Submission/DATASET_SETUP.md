# Dataset setup and reproduction

**Project:** Employment Outcome Pathway Grouping After Skilling — INT396 | G24 | CA Project.

## Primary CA analysis: Turkey ISKUR

The primary INT396 G24 analysis uses the World Bank public-use microdata for the Turkish Employment Agency (İŞKUR) Vocational Training Program for the Unemployed Impact Evaluation, 2010–2012, with administrative outcomes observed into 2013. The study covers 5,902 applicants to selected courses in Turkey. It is not a Maharashtra or India dataset.

The source file is `data/raw/TurkeyPublicUseData.dta`. It is excluded from submission packages because it is respondent-level microdata. Obtain it through the [World Bank study catalog](https://microdata.worldbank.org/catalog/1973), follow the catalog's research-use and non-identification conditions, and record the actual download date in the final dataset citation. The current verified source-file SHA-256 is `1bb32513435d605f48c90dca4264b678b082814dc7ad2106ecb4a144b84e96fc`. A different hash stops dashboard display and requires investigation.

Run from the project root:

```powershell
python -B -m src.turkey_pipeline
python -B -m pytest -q -p no:cacheprovider tests/test_turkey_pipeline.py
streamlit run dashboard/app.py
```

The Turkey pipeline is independent of PLFS. It validates assignment consistency and exact interview/course timing; preserves unknown exposure and outcomes; selects 1,546 documented attendees with three valid observations; and writes `outputs/turkey/summary.json`, cluster-level tables, and reports. The dashboard reads saved outputs and validates the dataset hash. Row-level generated files are retained only in the working research copy and are excluded from the submission package.

## Preserved PLFS 2023–24 routes

The PLFS unit-level sources are separate legacy project materials, not the primary CA dataset. The authentic `perv1.csv` is absent from this checkout. The saved cross-sectional output cannot currently pass the dashboard's source-hash check. Do not substitute a reconstructed file or change the expected hash. Restore the authenticated original from the [MoSPI Catalogue 213 access page](https://microdata.gov.in/nada/index.php/catalog/213/get-microdata) to `data/raw/perv1.csv` and verify SHA-256 `b852af28508a230270b2d371e5a975230dbc363982bad97d1dc8f2601c2664f6` before expecting that saved PLFS view or its test to pass. The portal requires login/register to access the unit-level files.

If all four PLFS source files are supplied, the original longitudinal pipeline remains separately guarded by `config.yaml`; do not change its unresolved design statuses based on the Turkey analysis. The independent cross-sectional route reads only `perv1.csv` and runs with:

```powershell
python -B -m src.cross_sectional
```

Historical PLFS methods, official documentation, and previous reports are retained in `docs/`, `docs/mospi/`, and `reports/`. They must not be cited as evidence for Turkish results.

## Sources and limitations

- [Turkey data dictionary and methods](docs/TURKEY_DATA_DICTIONARY.md)
- [Turkey data-use assessment](docs/DATA_USE_ASSESSMENT.md)
- [Turkey final report](reports/TURKEY_FINAL_REPORT.md)
- [Turkey requirement audit](reports/TURKEY_REQUIREMENT_AUDIT.md)
- [PLFS cross-sectional method (legacy route)](docs/METHODOLOGY_CROSS_SECTIONAL.md)
- [PLFS interface and data-use history](docs/INTERFACES.md)

Never interpret Turkey findings as Maharashtra, Indian, or current-program employment outcomes. The World Bank catalog requires non-identification and research use; respondent-level files and respondent-level derived outputs are not bundled in a release.
