# PROJECT_MANIFEST.md

Employment Outcome Pathway Grouping After Skilling (INT396 CA-1, group G24, SIH26135).

This is the list of every file in the release and what it is for, followed by the SHA-256 of each file. The hash block is written by `scripts/build_release.py`, not by hand; `scripts/build_release.py` refuses to build if this table and the shipped files differ. The SHA-256 of the ZIP itself cannot be stored inside it and is given separately with the delivery.

Release status: software verified on one environment; real-data run BLOCKED (CHECKPOINT 1 open). No real data, no real results and no synthetic outputs are shipped. See `FINAL_AUDIT_REPORT.md`.

## Files

<!-- BEGIN FILES -->
| Path | Purpose |
|---|---|
| `README.md` | What this is, run / test / dashboard commands (Linux, macOS, Windows), PROPOSED defaults, limits |
| `DATASET_SETUP.md` | Where the data come from, what to verify before use, how to fill the config, the verification log |
| `PROJECT_MANIFEST.md` | This file |
| `VIVA_GUIDE.md` | Questions to expect and where the evidence for each answer lives |
| `FINAL_AUDIT_REPORT.md` | What was verified on the development copy, what is blocked, open items, acceptance table |
| `config.yaml` | Every setting and code list; the single source of truth. Real-data gate is closed (`data.plan: UNSET`) |
| `requirements.txt` | Supported version ranges of the eight direct dependencies |
| `requirements.lock.txt` | Exact versions from `pip freeze` of a clean virtual environment (Python 3.13.16, Ubuntu 24.04.5) |
| `run_pipeline.py` | Orchestrator: audit, build, benchmark, cluster, evaluate, stability, profile, report; the real-data gate; `--self-test` |
| `src/__init__.py` | Shared constants (state codes `MISSING`, `LOST`) and data types |
| `src/config.py` | Loads and validates `config.yaml`; seeds; fairness guards |
| `src/data_audit.py` | The gate: audit of the real files (counts only, no modelling) |
| `src/synthetic_data.py` | SYNTHETIC panel with planted pathways; pipeline testing only |
| `src/data_loader.py` | Real files to a long panel (reached only after the gate) |
| `src/preprocessing.py` | Observation window, eligibility, attributes |
| `src/missing_data.py` | Missingness audit, tests and policies |
| `src/trajectories.py` | Long panel to states; collapsing identical sequences |
| `src/distances.py` | Dynamic Hamming, optimal matching, memory plan |
| `src/baseline.py` | Employed-or-not baseline, its lock, and the comparison with pathways |
| `src/clustering.py` | k-medoids (PAM), average-linkage hierarchical comparison |
| `src/evaluation.py` | Silhouette and other internal measures from the distance matrix |
| `src/stability.py` | Stability under attrition and censoring; choosing k |
| `src/profiling.py` | Descriptive tables and the pathway-naming helper |
| `src/visualization.py` | Figures, stamped SYNTHETIC when applicable |
| `src/report_builder.py` | Result files and the report template engine |
| `dashboard/app.py` | Streamlit page; reads saved results only; `--self-test` |
| `reports/report_template.md` | Report words and placeholders; no typed numbers; pathway tables show ids |
| `tests/test_trajectories.py` | 33 tests |
| `tests/test_distances.py` | 31 tests |
| `tests/test_evaluation.py` | 30 tests |
| `tests/test_stability.py` | 28 tests |
| `tests/test_planted_structure.py` | 11 tests: planted-structure and pure-noise checks on SYNTHETIC data |
| `docs/INTERFACES.md` | Function-level contracts between modules (version 1.8) |
| `docs/DATA_USE_ASSESSMENT.md` | What the data-use conditions may allow, and the four questions for the instructor |
| `scripts/build_release.py` | Rebuilds this ZIP reproducibly and rewrites the hash block below |
| `data/raw/.gitkeep` | Empty placeholder so `data/raw/` exists; no raw data is shipped |
<!-- END FILES -->

## Not shipped, on purpose

- Raw PLFS data (none was used), caches and bytecode, virtual environments, drafts, temp files, credentials.
- Generated outputs: `reports/results/`, `reports/figures/`, `reports/report__*.md`. They are rebuilt by `python run_pipeline.py --synthetic` and are tagged SYNTHETIC; none is a research result.
- `docs/SCOPE_CHANGE_MEMO.md`: mentioned in two code messages and in `README.md`, `DATASET_SETUP.md` and `docs/DATA_USE_ASSESSMENT.md`; it is a memo you would write if the audit forces Plan B or C, so it does not exist here.

## Rebuilding

```
python scripts/build_release.py --out <name>.zip
```

The same files give the same ZIP bytes: sorted order, fixed timestamps and permissions, one top-level folder `Employment_Outcome_Pathway_Grouping_After_Skilling/`.

## SHA-256 of each file

<!-- BEGIN HASHES -->
| File | SHA-256 |
|---|---|
| `DATASET_SETUP.md` | `81516fad2f9b65bd88ec376d698fb9bbbe7d2da44e6591060fbd96e11c321f6d` |
| `FINAL_AUDIT_REPORT.md` | `aafb8d66c90e4db3d38da2793cde0d57c5d6ce823e2296eb7b2d95709b6da7b2` |
| `README.md` | `486b2af47bb20f0ccb26c177f2464d4ef74005fe624ea03ce05bba3e64fd701b` |
| `VIVA_GUIDE.md` | `74b35e639df2ebd6cd4aa2a095312f9e2bfc272f2e15b4f2f4527d7727ac6347` |
| `config.yaml` | `b8266fc4b481a0dcd8241b908245c84774f515b87985826d9ed3e3ef02a41c0d` |
| `dashboard/app.py` | `3af26772d8f98f34f885de4aca07ae3ba6ff0f7fc02821425dca02eb2727b1e9` |
| `data/raw/.gitkeep` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `docs/DATA_USE_ASSESSMENT.md` | `1db211b7cc811d09cbdeef300504a4a752a04208c2a327c3c8e9f5d2cad4ca13` |
| `docs/INTERFACES.md` | `5c9a8289a63929d921bb86e1b20dc1dcf672f20f801c567107e381ff7b01ca64` |
| `reports/report_template.md` | `bd2043aee0e9a294c70b65a47bc80bf1f9d3871f96ff4fa36352a27bee718ca9` |
| `requirements.lock.txt` | `05c0c30e5eb24adef2f14d479ca90d2a7f86c7b063da6bb18a107f773b883348` |
| `requirements.txt` | `0421c0e0e55fa4541274a78206a99a835e39765a02e2e20f1376a9f05fd95590` |
| `run_pipeline.py` | `1564d97f2514759f727d1b2ae75ba047f05a620929847046ce47647b1a15937b` |
| `scripts/build_release.py` | `5c1383699e67594eca4889b9705f54527a52a63f342355088f085b546d4fcf59` |
| `src/__init__.py` | `27ff6246314925909f744fc636355687afb0d037f83a3c54d4fbc1054def1faf` |
| `src/baseline.py` | `bd16afb8a5127210e44b5f6ad73156f21fbe256d502a6a09564e9647276ee978` |
| `src/clustering.py` | `f2e5c5c398c43625d50f5204100404b5c64b113d82e212bf86858390a8dbd4cf` |
| `src/config.py` | `29ea59a0952b340fb1bdc762aeb9f5662af74b5d092e5ca466374fa6c74122bd` |
| `src/data_audit.py` | `19dc9f1ff9aabc054c073e1b089fd9c8bf0b35c4f68f2c337cc188123300f43d` |
| `src/data_loader.py` | `02472945148cd2197abdf2e6450fafabc9be51c0b6065174a52ab1bea0d30be1` |
| `src/distances.py` | `40bae5f8d9d447e1731e5e5424e4f23b0255b8e432c90a7c59b4922df52cc0da` |
| `src/evaluation.py` | `dc5775b889a3346491a9c2ec12bb853db87659fca390c9899edb0e70064e0aed` |
| `src/missing_data.py` | `6b9e39ab46bd7be8610d55542e4dc82feb42cd2dc089d0c372e6fe3443e5f1b1` |
| `src/preprocessing.py` | `bddf0ba44f91bc279f9b7edc19afea63196736239dd220efc89e15917c18feac` |
| `src/profiling.py` | `f3d681334720b4e7091878fa3969f44dd88fe300de00252a14b9cf5ecc1d75cc` |
| `src/report_builder.py` | `e41904c30d2062d31be83c6552ba98da6d893c2d417b0d05865b385e4aaf49fe` |
| `src/stability.py` | `ad9999d04556a3671611564260f59d5beb38971e0ae2b4d88a1d1dcaa305105f` |
| `src/synthetic_data.py` | `30e3dc899072b918e4886cc8bdec9d18436a8d4a3db864466454d2df7a7629d4` |
| `src/trajectories.py` | `ca0cd6525a8c9cac8646974a77bc9588d0047fb1184460ac903a972ec350a0ec` |
| `src/visualization.py` | `363fae92c197d59c805875710152148968da2df1076c7a43e949e475f8465863` |
| `tests/test_distances.py` | `6c2026d01b18d359de026c5c6108dcdee822718cd77c56c68216509a9060c059` |
| `tests/test_evaluation.py` | `9c940eff0e745e497ba88b38b08b842d2eb1fc421c8385745a30bba8915323d3` |
| `tests/test_planted_structure.py` | `fc5635486348f1c52a578bbfb3977c8cdeba25dec582406ff4ba7babacbff3c7` |
| `tests/test_stability.py` | `1841d3d25f08a21eeef6cb1bb0bf7662b670f2bb53ee8021bb26e02e7cd4cc99` |
| `tests/test_trajectories.py` | `d9f44b28ac3f703980abcd5237a729c1f66251464fc065c092f429f67447e51c` |
<!-- END HASHES -->
