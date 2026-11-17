# Data-use and release assessment

Updated 2026-11-06 for the primary Turkey ISKUR CA analysis. This is an operational summary of the source conditions, not legal advice. The originating catalog terms control.

## Primary dataset: Turkey ISKUR public-use microdata

The World Bank catalog entry for the *Vocational Training Program for the Unemployed Impact Evaluation 2010–2012* (reference `TUR_2010_VTPUIE_v01_M`) says that access to anonymized data is permitted for research, with the standard condition that users do not attempt to identify respondents. The World Bank Microdata Library terms also state that datasets and related materials may not be redistributed or sold without prior written agreement and that they are for statistical/scientific research producing aggregate information, not investigation of specific individuals or organizations.

Project consequences:

- Keep the raw `.dta` file out of public releases and submission ZIPs.
- Keep respondent-level derived files (`trainee_analysis.csv` and `valid_post_training_trajectories.csv`) out of release packages. The package includes only aggregate tables, summary metrics, and documentation.
- Do not attempt to identify applicants or link records to outside information.
- Cite the source, study title, reference number, principal investigator names, and actual download source/date. The current project records the source and dataset hash but not the download date; record it from the acquisition record before final publication.
- Treat aggregate outputs as research summaries and retain their study geography and period: selected Turkish ISKUR applicants, 2010–2013. Do not state that the results represent Maharashtra or India.

Sources: [World Bank Turkey study catalog](https://microdata.worldbank.org/catalog/1973), [World Bank Microdata Library terms of use](https://microdata.worldbank.org/terms-of-use), [World Bank dataset terms](https://www.worldbank.org/en/about/legal/permissions).

## Preserved PLFS 2023–24 route

PLFS is a separate historical project route. The current project records the user's attestation that instructor approval and the required MoSPI permissions were obtained for the defined cross-sectional training-cohort analysis (`reports/P4_permissions.md` and `config.yaml`). This does not resolve the separate technical blockers on longitudinal linkage, dated training, linked weights, and lost-code semantics. The original real longitudinal gate remains closed. The current checkout lacks authenticated `data/raw/perv1.csv`, so source-bound PLFS outputs cannot presently be revalidated.

Historical PLFS data-use analysis, including the scope question around using `b4q12` for cohort selection and the unresolved profiling/output questions, remains preserved in `reports/P4_permissions.md`. This legacy PLFS assessment must not be read as a condition on the Turkey dataset or as evidence about Turkish outcomes.

## Academic and geographic scope

The Turkey analysis is descriptive. It does not use randomized assignment as a treatment-effect estimator, does not infer causal impact, and does not establish four natural latent classes. Its four clusters summarize similarities among three observed binary outcomes. The underlying survey's “not working” state is not automatically unemployment. Missing outcomes remain unknown, and the extreme bounds are sensitivity calculations only.

The PLFS cross-sectional estimates and older PLFS presentation are separate work. Do not combine the Turkish and Indian datasets or use either to claim the other country's findings.
