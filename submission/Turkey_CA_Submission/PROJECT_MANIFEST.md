# PROJECT_MANIFEST.md

Employment Outcome Pathway Grouping After Skilling — INT396, Group G24.

## Package scope

The release builder stages a complete reproducible project snapshot in `submission/Turkey_CA_Submission/` and writes `submission/Turkey_CA_Submission.zip`. The ZIP uses sorted file order, fixed timestamps, and fixed permissions. Rebuilding from identical files produces identical ZIP bytes. The archive digest is printed after each build and is intentionally not embedded in the archive.

The package contains the Turkey CA analysis, preserved PLFS and synthetic code routes, project tests, source documentation, the Turkey presentation, viva materials, and aggregate Turkey outputs. It excludes raw respondent microdata and the respondent-level derived files `trainee_analysis.csv` and `valid_post_training_trajectories.csv`, consistent with the World Bank study conditions. A user must obtain the Turkey dataset independently and verify its SHA-256 before reproducing results. The original authenticated PLFS `perv1.csv` is also absent; its dashboard view and one PLFS integrity test remain unavailable until it is restored.

The required Turkey dataset has SHA-256 `1bb32513435d605f48c90dca4264b678b082814dc7ad2106ecb4a144b84e96fc`. Current validation: Turkey pipeline completed; legacy pipeline self-test passed (20 checks); dashboard self-test passed (19 checks); browser checks at 1366×768 and 1920×1080 show no document-level horizontal overflow. Full suite is 188 passed, 1 failed, 3 warnings because authenticated `data/raw/perv1.csv` is missing.

## Files

<!-- BEGIN FILES -->
| Path | Purpose |
|---|---|
| `DATASET_SETUP.md` | Dataset provenance, access, input hash and run commands. |
| `FINAL_AUDIT_REPORT.md` | Project and Turkey analysis audit. |
| `PROJECT_MANIFEST.md` | This manifest and generated SHA-256 inventory. |
| `README.md` | Project overview, scope, results and reproduction. |
| `VIVA_GUIDE.md` | Turkey analysis viva questions and supported answers. |
| `config.yaml` | Legacy PLFS configuration; real longitudinal gate remains closed. |
| `dashboard/app.py` | Turkey-first dashboard with a separate gated legacy PLFS and synthetic page. |
| `data/raw/.gitkeep` | Empty raw-data directory placeholder; no microdata. |
| `docs/DATA_DICTIONARY_CROSS_SECTIONAL.md` | Methods and data-use documentation: DATA_DICTIONARY_CROSS_SECTIONAL. |
| `docs/DATA_USE_ASSESSMENT.md` | Methods and data-use documentation: DATA_USE_ASSESSMENT. |
| `docs/INTERFACES.md` | Methods and data-use documentation: INTERFACES. |
| `docs/METHODOLOGY_CROSS_SECTIONAL.md` | Methods and data-use documentation: METHODOLOGY_CROSS_SECTIONAL. |
| `docs/TURKEY_DATA_DICTIONARY.md` | Methods and data-use documentation: TURKEY_DATA_DICTIONARY. |
| `docs/mospi/Data_LayoutPLFS_2023-24.xlsx` | Official PLFS source documentation, retained for the legacy route. |
| `docs/mospi/PLFS_2023-24_1_README.docx` | Official PLFS source documentation, retained for the legacy route. |
| `docs/mospi/PLFS_2023-24_Catalogue213_DDI.xml` | Official PLFS source documentation, retained for the legacy route. |
| `docs/mospi/PLFS_2023-24_Estimation_Procedure.pdf` | Official PLFS source documentation, retained for the legacy route. |
| `docs/mospi/PLFS_2023-24_Instruction_Manual_Vol_I.pdf` | Official PLFS source documentation, retained for the legacy route. |
| `docs/mospi/PLFS_2023-24_Instruction_Manual_Vol_II.pdf` | Official PLFS source documentation, retained for the legacy route. |
| `docs/mospi/PLFS_2023-24_Updated_Instruction_Note.pdf` | Official PLFS source documentation, retained for the legacy route. |
| `outputs/turkey/attrition_admin_comparison.csv` | Aggregate Turkey analysis output: attrition_admin_comparison.csv. |
| `outputs/turkey/baseline_employed_comparison.csv` | Aggregate Turkey analysis output: baseline_employed_comparison.csv. |
| `outputs/turkey/baseline_employment_by_cluster.csv` | Aggregate Turkey analysis output: baseline_employment_by_cluster.csv. |
| `outputs/turkey/cluster_admin_profile.csv` | Aggregate Turkey analysis output: cluster_admin_profile.csv. |
| `outputs/turkey/cluster_gender_profile.csv` | Aggregate Turkey analysis output: cluster_gender_profile.csv. |
| `outputs/turkey/cluster_jan2012_state_profile.csv` | Aggregate Turkey analysis output: cluster_jan2012_state_profile.csv. |
| `outputs/turkey/cluster_method_evaluation.csv` | Aggregate Turkey analysis output: cluster_method_evaluation.csv. |
| `outputs/turkey/cluster_prevalence.csv` | Aggregate Turkey analysis output: cluster_prevalence.csv. |
| `outputs/turkey/cluster_profile_report.md` | Aggregate Turkey analysis output: cluster_profile_report.md. |
| `outputs/turkey/summary.json` | Aggregate Turkey analysis output: summary.json. |
| `pytest.ini` | Pytest discovery is limited to the authoritative tests directory. |
| `reports/TURKEY_FINAL_REPORT.md` | Turkey deliverable or preserved PLFS viva material: TURKEY_FINAL_REPORT.md. |
| `reports/dashboard_screenshots/primary_turkey_1366x768.jpg` | Primary Turkey dashboard at 1366×768. |
| `reports/dashboard_screenshots/primary_turkey_1920x1080.jpg` | Primary Turkey dashboard at 1920×1080. |
| `reports/TURKEY_REQUIREMENT_AUDIT.md` | Turkey deliverable or preserved PLFS viva material: TURKEY_REQUIREMENT_AUDIT.md. |
| `reports/viva_questions_and_answers.md` | Turkey deliverable or preserved PLFS viva material: viva_questions_and_answers.md. |
| `requirements.lock.txt` | Pinned project Python dependencies. |
| `requirements.txt` | Pinned project Python dependencies. |
| `run_pipeline.py` | Preserved original PLFS longitudinal pipeline. |
| `scripts/build_release.py` | Reproducible submission builder; excludes microdata. |
| `src/__init__.py` | Project source module: __init__. |
| `src/baseline.py` | Project source module: baseline. |
| `src/clustering.py` | Project source module: clustering. |
| `src/config.py` | Project source module: config. |
| `src/cross_sectional.py` | Project source module: cross_sectional. |
| `src/data_audit.py` | Project source module: data_audit. |
| `src/data_loader.py` | Project source module: data_loader. |
| `src/distances.py` | Project source module: distances. |
| `src/evaluation.py` | Project source module: evaluation. |
| `src/missing_data.py` | Project source module: missing_data. |
| `src/preprocessing.py` | Project source module: preprocessing. |
| `src/profiling.py` | Project source module: profiling. |
| `src/report_builder.py` | Project source module: report_builder. |
| `src/stability.py` | Project source module: stability. |
| `src/synthetic_data.py` | Project source module: synthetic_data. |
| `src/trajectories.py` | Project source module: trajectories. |
| `src/turkey_pipeline.py` | Project source module: turkey_pipeline. |
| `src/visualization.py` | Project source module: visualization. |
| `submission/PLFS_2023-24_Cross_Sectional_Study_final_submission_v3.pptx` | Updated preserved PLFS cross-sectional presentation. |
| `submission/Turkey_ISKUR_CA_presentation_v4.pptx` | Eight-slide Turkey ISKUR CA presentation with INT396 G24 project branding. |
| `tests/test_cross_sectional.py` | Regression and methodology tests: test_cross_sectional. |
| `tests/test_dashboard_safety.py` | Regression and methodology tests: test_dashboard_safety. |
| `tests/test_data_loader_linkage.py` | Regression and methodology tests: test_data_loader_linkage. |
| `tests/test_distances.py` | Regression and methodology tests: test_distances. |
| `tests/test_evaluation.py` | Regression and methodology tests: test_evaluation. |
| `tests/test_planted_structure.py` | Regression and methodology tests: test_planted_structure. |
| `tests/test_real_safety_gate.py` | Regression and methodology tests: test_real_safety_gate. |
| `tests/test_stability.py` | Regression and methodology tests: test_stability. |
| `tests/test_trajectories.py` | Regression and methodology tests: test_trajectories. |
| `tests/test_turkey_pipeline.py` | Regression and methodology tests: test_turkey_pipeline. |
<!-- END FILES -->

## Build

```powershell
python -B scripts/build_release.py
```

The builder validates this purpose table against its explicit package allowlist, scans included text for common secret patterns, rejects raw/respondent-level datasets, writes the exact staged directory, refreshes SHA-256 values, and creates the deterministic ZIP.

## SHA-256 of packaged files

<!-- BEGIN HASHES -->
| File | SHA-256 |
|---|---|
| `DATASET_SETUP.md` | `bed05a0c00857965406b20c5f939e990a0d58279d3d136eb3fadf69ed7484fe9` |
| `FINAL_AUDIT_REPORT.md` | `e394532bb00b078b2b12c71652716bbfd86776cb4dee1992e78d3bf08697a1c5` |
| `README.md` | `b973d51139218dd8ac4a738cbbaaa8bb1989829b9422e902bfcc34b32ec2d1b7` |
| `VIVA_GUIDE.md` | `c7e417d716b4fe055bda7c97f5073ef73f3a53fdba74d4cec798a2a6c4ee05c8` |
| `config.yaml` | `5ff6020a2a579cf0d1991ca393d2cf36c653f16bd76262506c8e5587ebe02e8e` |
| `dashboard/app.py` | `32715ec99bbf89407e018dfc38a9d4fcf829c6f64da34406779842b7c3c5927e` |
| `data/raw/.gitkeep` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `docs/DATA_DICTIONARY_CROSS_SECTIONAL.md` | `320756cb34331729ac354a94ad57bd76b0d7aaa0f367fc5d081f704207448a4a` |
| `docs/DATA_USE_ASSESSMENT.md` | `c32f1716bec189ce928ac6107609ed6e4d9a157d795e82b713673a09052d4254` |
| `docs/INTERFACES.md` | `cafa1fd1fd84f088e61c13839e4604044c9443583030b7be295c3f1b9100f4d5` |
| `docs/METHODOLOGY_CROSS_SECTIONAL.md` | `faa4b6455bf2bcaa01faba5e8aa178d4b46647b9afb3b976f99c44b815a5afe4` |
| `docs/TURKEY_DATA_DICTIONARY.md` | `38ff8e2066ca38ea2e5d62936d3e3d2b69dc9a246a05154da17f8d829439f646` |
| `docs/mospi/Data_LayoutPLFS_2023-24.xlsx` | `3de65c3dcaaadfd90b78579b8eaa65557e32dc7074f178dcc1e11195e8cf3836` |
| `docs/mospi/PLFS_2023-24_1_README.docx` | `3f7448da3112fde2a29d4eaf75f32593a15a3bcaa51e39db929c908a2f4f8c5f` |
| `docs/mospi/PLFS_2023-24_Catalogue213_DDI.xml` | `cacb046915e49466e1e587af12b6370ec50e680d97620b91129a4c9cef65f0ff` |
| `docs/mospi/PLFS_2023-24_Estimation_Procedure.pdf` | `b6534db483bea876ff175feb138877445fc91f33ca183790165d6f4c5c84733d` |
| `docs/mospi/PLFS_2023-24_Instruction_Manual_Vol_I.pdf` | `038994ccb43a1d11aa5248dc463cab074984562aa131f749e49a58e06c3841ed` |
| `docs/mospi/PLFS_2023-24_Instruction_Manual_Vol_II.pdf` | `edb71767701c999d1f91b510dc6951585aec1f0eb2bc9865a36a5bea765a2e15` |
| `docs/mospi/PLFS_2023-24_Updated_Instruction_Note.pdf` | `3eb898e80c862a3d8e901655799c7d5b9972edfa9fe3caa32087ca20160a778a` |
| `outputs/turkey/attrition_admin_comparison.csv` | `6da0e63ef8251a4dcacc30a56db4ebecec1d3d41c50d2bdf3ae160e9039f89f3` |
| `outputs/turkey/baseline_employed_comparison.csv` | `b603d4b49d16d13b173e06643960f8bf496dd8f358f18208db7674872b0e27ee` |
| `outputs/turkey/baseline_employment_by_cluster.csv` | `69c73409b0caed5856503db4824e876085fcdd620479f1a4d7271042a992cefd` |
| `outputs/turkey/cluster_admin_profile.csv` | `d4037b9cbf89c307ff820863ddf52af3af6f474fb26565f68c69dcd773a16079` |
| `outputs/turkey/cluster_gender_profile.csv` | `bc98b6bbcdc0d81585607f49620eb1bfa4f90a47ceb47f721ad677a769df6713` |
| `outputs/turkey/cluster_jan2012_state_profile.csv` | `e7284f6e4390c7ec3fae9bc78bd1b8ef5078fef2dff5d9907a20434d6c568747` |
| `outputs/turkey/cluster_method_evaluation.csv` | `2dc714506a296b4544b71560da0dd8745c6242f4cbdeebe956e0064e60bd1c74` |
| `outputs/turkey/cluster_prevalence.csv` | `a3637a743baded73f1ca45f442280b38e1285f964fb61f1dd9345e597b7e4089` |
| `outputs/turkey/cluster_profile_report.md` | `090f5235315152ca7e10f76ac87df06b6bae71b853708d1c5bc08c3d4f95d46a` |
| `outputs/turkey/summary.json` | `e6e2a1d0a15908b9c61409056517e346b044c59527aaef8d1c23340aab864594` |
| `pytest.ini` | `c809c969ec7e11b9ff37784e9c6fcc0b7c5148d168e18b05aed797e03fbd6ead` |
| `reports/TURKEY_FINAL_REPORT.md` | `490b43ed4e88630268083e2bc70218b1bbcc7d7128253c49d79c9b789f43f708` |
| `reports/TURKEY_REQUIREMENT_AUDIT.md` | `222b7fc7fe0fea1d84acfa1eff63ff03b7db820638c80bf831cad6b0dcf6cc1e` |
| `reports/dashboard_screenshots/primary_turkey_1366x768.jpg` | `2a992cacefe4ee07c7d62b8d14d28a765d78227111bcbaf271d527e0d9053540` |
| `reports/dashboard_screenshots/primary_turkey_1920x1080.jpg` | `539ea3a0e911c04eebd7022636008ae5ceb750d386666b163ce3fe3d509adcac` |
| `reports/viva_questions_and_answers.md` | `0cb27e16a6500e492ff1117f8e6e13436c50ad4471ca3b29c9781943a0f7bacb` |
| `requirements.lock.txt` | `05c0c30e5eb24adef2f14d479ca90d2a7f86c7b063da6bb18a107f773b883348` |
| `requirements.txt` | `0421c0e0e55fa4541274a78206a99a835e39765a02e2e20f1376a9f05fd95590` |
| `run_pipeline.py` | `ef7edb1f4cf3a8ef79198ab0a6280a264a072c484f3eafce95fec498d794d963` |
| `scripts/build_release.py` | `ead58a2071d7d65fcbd68992df5cf046236f5ad7dcc1b23d97aff93fe1a85882` |
| `src/__init__.py` | `a6e3eee45d4f41f7b04f5926c11d3ac45fe83883abd8bbd550704c22cf60a06b` |
| `src/baseline.py` | `0362ac6b2ae65427250affdb2c8a82b0d6407a2007042d7f398776c35bc85b91` |
| `src/clustering.py` | `ac23e2a9392c9eac56d1e76b5bad865231324cfb6fdd4745663411e33ca2e681` |
| `src/config.py` | `200ffbb720df30ee903ca8b8afcced04637b845cb53e1e17165d4543d1e03b57` |
| `src/cross_sectional.py` | `80c5811eb29341728195a2e595a234997b0f1a05b97b25f2f8c51a46479e5ba2` |
| `src/data_audit.py` | `59d33cda639952f4771cf1487157fdf71774bbd3a14bc607fe01e2d9734d3be2` |
| `src/data_loader.py` | `7be810f95eb18d7e00fe0ae3523a3df108b8f9e8ec9d35bce625272f91ec5e4b` |
| `src/distances.py` | `a842cb0c6721f00d9b8c1c322cf34cff832500bb29aef5db4b0edfa72474dec7` |
| `src/evaluation.py` | `dc5a097558bd63eba4242ff043dafb5321b9cf46da6c55de3223103bfbdbe90e` |
| `src/missing_data.py` | `fbb6c4d216fb564329cf648326f7e9370218004af2582105436611cba8e75e74` |
| `src/preprocessing.py` | `be470faab2f9e7f4620b9b9198ae0e17ff25edd6db2662ef2fcc937043ba1427` |
| `src/profiling.py` | `3025cb34b42d984fc81702fa20aec47eb3a481feabd57b93e9e9eb6ac9c27152` |
| `src/report_builder.py` | `54bfae5aff54f3c8c4697dafa5290784db4f49ccd8d743d2a79701dde5a5f8f9` |
| `src/stability.py` | `a169f4fcb29d6b14151e6b28dc7bc3fb60084058b021f56b12d2bcb49c65a3ec` |
| `src/synthetic_data.py` | `db1643d44cc23b670dc63e4a5dcbcede179a7ed091c306e44ab60c47d8ebdd8d` |
| `src/trajectories.py` | `9250fb2b2921efce7e97ad7c32a6f51c7f1b8055d651073b10d91c0455889136` |
| `src/turkey_pipeline.py` | `02cedbca49e8a75ac68151d39f7ebb748880d43bcaa81a7e32544db5946a465e` |
| `src/visualization.py` | `0a952b736f0992d88bd946ef1dfb7b6ecc1589634ed4d5751559626543234fc9` |
| `submission/PLFS_2023-24_Cross_Sectional_Study_final_submission_v3.pptx` | `259680b7e557a50b9eb5dacf02b152927bb56f8aac7f9fa6e1570d1a221d8a0e` |
| `submission/Turkey_ISKUR_CA_presentation_v4.pptx` | `dacf9ab37e70e218863f803883dc1a9157074ef335adb4366ae024245a969b75` |
| `tests/test_cross_sectional.py` | `37a5a7a220a0a6188d5823a32e4127095667d1c71bff8940e96efb103c60657c` |
| `tests/test_dashboard_safety.py` | `88bd6546ec21b2528771f5e38b3c8799546cb370a106ce42ad62335f168cbb92` |
| `tests/test_data_loader_linkage.py` | `4bfd9ae9cc6bf59f39f94f860c1d822b332531f97835a786f34e033fabcf32f0` |
| `tests/test_distances.py` | `cb0291ff0040f4009ab66f926aa9d046944cde92784aa1d0ea65906e2136573f` |
| `tests/test_evaluation.py` | `9c940eff0e745e497ba88b38b08b842d2eb1fc421c8385745a30bba8915323d3` |
| `tests/test_planted_structure.py` | `d7201c0926c6318e417a91cac574f0e9ed6a55a7c1797e842531446b2b8a0f06` |
| `tests/test_real_safety_gate.py` | `29808e05741551ea357ec3248a16289ad094d618ce996322e725371408f903bf` |
| `tests/test_stability.py` | `8e3a33d8f4b2fa18bd5c7cdba0b5555921f573f90cf3b8d5e9b1eba5edddfd17` |
| `tests/test_trajectories.py` | `537d798598be86f2a90daf8b19aa8bfda12ff6070f35c50ea9a026bc5d7e27db` |
| `tests/test_turkey_pipeline.py` | `bacfd690d24865bbe15ffc911327461529ecce85002099f5603f171616228053` |
<!-- END HASHES -->
