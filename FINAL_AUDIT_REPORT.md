# FINAL_AUDIT_REPORT.md

Employment Outcome Pathway Grouping After Skilling (INT396 CA-1, group G24, SIH26135). Audit date: 2026-10-31.

**Readiness at the time of writing: software verified on one environment; real-data run BLOCKED (CHECKPOINT 1 open).** Nothing in this release is a result about real trainees.

## 0. What this report covers

This report records the checks run on the **development copy**, before the release ZIP was built. A ZIP cannot record the verification of itself, so the **ZIP-level checks** (integrity, file listing, extraction into a new folder, all self-tests and pytest from there, synthetic run, path search, run from another working directory, real-data refusal) are in `VERIFICATION_RESULT.md`, delivered next to the ZIP and not inside it. Nothing in this file claims those results.

## 1. Environment of every result below

| Item | Value |
|---|---|
| Python | 3.13.16 |
| OS | Ubuntu 24.04.5 LTS, Linux 6.18.44, x86_64 (cloud sandbox) |
| Environment | clean virtual environment (`include-system-site-packages = false`), created with `python -m venv`, then `pip install -r requirements.txt` (exit 0); pip 26.2.1 |
| Packages (exact) | pandas 3.1.0, numpy 2.5.4, scipy 1.18.1, scikit-learn 1.9.1, matplotlib 3.11.2, PyYAML 6.0.3, streamlit 1.66.1, pytest 9.2.0; the full list is `requirements.lock.txt` (51 packages) |
| pyflakes | 4.1.0, run from the sandbox's global interpreter (not a project dependency) |

Not tested: Windows, macOS, Python 3.10, 3.11 and 3.12, pandas below 3.1, numpy below 2.5, scikit-learn below 1.9. The declared ranges in `requirements.txt` are intended support, not tested support.

## 2. Verified (commands run in this session, results seen)

Run from the project folder with the clean environment's `python`. Each row is one command and its real exit code.

| # | Command | Result |
|---|---|---|
| 1 | `python -m src.config` | rc 0: "Runtime guard rejected as expected: protected attribute(s) ['religion']..." |
| 2 | `python -m src.data_audit` | rc 0: "Nothing to audit: data.files is empty" (expected: no real files) |
| 3 | `python -m src.synthetic_data` | rc 0: Demo checks passed (12) |
| 4 | `python -m src.data_loader` | rc 0: Demo checks passed (8) |
| 5 | `python -m src.preprocessing` | rc 0: Demo checks passed (13) |
| 6 | `python -m src.missing_data` | rc 0: Demo checks passed (19) |
| 7 | `python -m src.trajectories` | rc 0: Demo checks passed (35) |
| 8 | `python -m src.distances` | rc 0: Demo checks passed (42) |
| 9 | `python -m src.baseline` | rc 0: Demo checks passed (34) |
| 10 | `python -m src.clustering` | rc 0: Demo checks passed (39) |
| 11 | `python -m src.evaluation` | rc 0: Demo checks passed (26) |
| 12 | `python -m src.stability` | rc 0: Demo checks passed (38) |
| 13 | `python -m src.profiling` | rc 0: Demo checks passed (25) |
| 14 | `python -m src.visualization` | rc 0: Demo checks passed (19) |
| 15 | `python -m src.report_builder` | rc 0: Demo checks passed (15) |
| 16 | `python run_pipeline.py --self-test` | rc 0: Self-test passed (20) (19 before the fix in section 2a) |
| 17 | `python dashboard/app.py --self-test` | rc 0: Self-test passed (15) |
| 18 | `python -m pytest tests -q` | rc 0: 133 passed (run three times: 12.81 s, 20.78 s and, after the fix in section 2a, 13.69 s; no failures) |
| 19 | `python -m pyflakes src run_pipeline.py dashboard tests` | rc 0, no output |
| 20 | `python -m compileall -q src tests dashboard run_pipeline.py` | rc 0 |
| 21 | static: every source file parses with the Python 3.10 grammar (`ast.parse(feature_version=(3, 10))`, 23 files) | OK. This checks syntax only; it is not a run on Python 3.10 |
| 22 | static: no use of 3.11+ features found by text search | OK |
| 23 | static: no module imports a later module in the documented order | OK |
| 24 | static: typed numbers in the report template (`claims_audit`) | 0 typed numbers in 95 audited rows |
| 25 | `python run_pipeline.py` (real-data run, gate closed; re-run after the fix) | exit 3: "data.plan is UNSET: run `python run_pipeline.py --stage audit` ... (CHECKPOINT 1)". Refused, as designed |
| 26 | `pip install -r requirements.txt` in a fresh venv; `pip check` | exit 0; "No broken requirements found" |
| 27 | `pip install -r requirements.lock.txt` in a second fresh venv; `pip freeze` compared with the lock | exit 0; freeze identical to the lock content; `pip check` clean |
| 28 | AST scan of every import in `src`, `run_pipeline.py`, `dashboard`, `tests` | third-party imports: numpy, pandas, scipy, scikit-learn (sklearn), matplotlib, PyYAML (yaml), streamlit, pytest. All eight are declared in `requirements.txt`; none declared and unused |

Earlier in the session the same 18 commands (rows 1 to 18) also passed in the sandbox's global environment (pandas 3.0.5, numpy 2.5.3, scikit-learn 1.9.1), after the five cosmetic edits (unused names and imports in `src/profiling.py`, `src/baseline.py`, `src/report_builder.py`, `src/preprocessing.py` and `tests/test_distances.py`). The whole table above was then run again in the clean environment after the fix in section 2a, and every row passed; the dev-copy tables in this report are the post-fix runs.

### 2a. A defect found by fresh extraction, and its fix

Running `python run_pipeline.py --synthetic` from a fresh extraction of the first draft ZIP failed at the report stage: the report template reads `run_meta.seed` and `run_meta.versions.*`, but `run_pipeline.py` saved `run_meta` only after the last stage, so the report could not be built into an empty results folder. The development copy had hidden this: it held a `run_meta` file left by an earlier run, so the report built from stale metadata (the pipeline self-test never saw it because it used a nonexistent template path). Fix, in `run_pipeline.py` only: `run_meta` is saved just before the report stage renders and again after the last stage (private helper `_save_run_meta`). Regression check added to the pipeline self-test (a full quick run into an empty results folder with the shipped template must render a filled report); removing the fix in a scratch copy made that check fail, and with the fix it passes. `docs/INTERFACES.md` is v1.9 for this. That first draft ZIP is superseded.

What these results show: the code runs, its internal checks and 133 unit tests pass, and the gate refuses a real run. What they do not show: that the method works on real PLFS data. The planted-structure tests show the code can recover clear structure it was given.

## 3. BLOCKED

| Item | Why it is blocked |
|---|---|
| Real-data run | CHECKPOINT 1 is open: `data.plan` is UNSET and `data.verified` is false. No PLFS file was available or used. The gate is not loosened |
| Schema verification on a real file | There is no real file, and the PLFS column names, codes, panel key and weights are deliberately not assumed. Every `UNVERIFIED:` code in `config.yaml` is still a placeholder |
| Other operating systems | Windows and macOS were not available. The README's Windows and macOS commands are unverified |
| Other Python and library versions | Only Python 3.13.16 with the lock-file versions was run |
| Instructor / data-use decisions | The four questions in `docs/DATA_USE_ASSESSMENT.md` are unanswered, so attribute profiling stays off (`profiling.permitted_vars: []`) |

The clean-install check is not blocked: network access was available and it passed (rows 26 and 27).

## 4. Open items for you, in order

1. Obtain the PLFS release and its data dictionary; work through `DATASET_SETUP.md`; fill `data.files`, `data.layouts`, `data.schema`; replace the `UNVERIFIED:` codes.
2. Run `python run_pipeline.py --stage audit` and decide the plan at CHECKPOINT 1 (A, B or C). Plan B or C changes the project's question and needs your instructor's approval.
3. Put the four questions in `docs/DATA_USE_ASSESSMENT.md` section 5 to your instructor; record the answers; only then fill `profiling.permitted_vars`.
4. Confirm or change each PROPOSED default (table in `README.md`), above all `trainee.timing_support` and `time.n_points`.
5. Decide how the release records casualty cases that carry both a valid status and a lost-to-follow-up code, then set `lost_codes` and `data.schema.nonresponse_col` accordingly.
6. Set `data.verified: true` with a note of who checked what, and `baseline.locked: true`.
7. Run the benchmark stage and set `distance.max_n`, `distance.max_matrix_mb`, `distance.peak_factor` from it (the current values are placeholders).
8. Run `python -m pytest tests -q` on the machine you will present from, and tell me about any failure with the versions (`pip freeze`).
9. After a real run, read the cluster profiles. Pathway names can be considered only then; this release has none in any report table.

## 5. Unverified references and statements

- Every PLFS fact in `DATASET_SETUP.md` and `docs/DATA_USE_ASSESSMENT.md` (about four monthly observations per person, the CY2025 person dictionary and catalogue 284, the `voc` and `voc_compl` variables and what `voc_compl` refers to, differing code lists between releases, the 2025 redesign, the wording of the data-use rider) came from your notes. None was checked against an official document.
- `docs/SCOPE_CHANGE_MEMO.md` is named in two code messages (`run_pipeline.py`, `src/data_loader.py`) and in four documents (`README.md`, `DATASET_SETUP.md`, `PROJECT_MANIFEST.md`, `docs/DATA_USE_ASSESSMENT.md`). It does not exist and was not created (it is a memo you would write for Plan B or C).
- `docs/DATA_USE_ASSESSMENT.md` is written in the first person of the assistant that drafted it, and says it has not read the rider. It is not legal advice.
- The README's Windows and macOS commands, and its statement that the code is written to the Python 3.10 grammar, rest on reading and on a syntax parse, not on a run.
- The viva guide's statement about the hierarchical comparison describes the SYNTHETIC run: two groups of a few people each, far below the size rule, and weaker recovery of the planted groups than k-medoids. It is not a finding about real trainees.
- Dashboard pathway labels come from `profiling.name_pathways` and describe each run's own clusters; on SYNTHETIC results they describe synthetic clusters only.

## 6. Acceptance table

| Item | Status | Evidence / note |
|---|---|---|
| Five cosmetic fixes made, nothing else changed | PASS | pyflakes clean (row 19); tests and self-tests pass after |
| Report stage on an empty results folder (found in fresh extraction) | FIXED, PASS | section 2a; regression check in the pipeline self-test |
| 15 module self-tests | PASS | rows 1 to 15 |
| `run_pipeline.py --self-test` | PASS | row 16 |
| `dashboard/app.py --self-test` | PASS | row 17 |
| `python -m pytest tests -q` | PASS | 133 passed, row 18 |
| Static checks (pyflakes, compileall, 3.10 grammar, import order, typed numbers) | PASS | rows 19 to 24 |
| Clean isolated environment, install of `requirements.txt` | PASS | rows 26 and 27 |
| `requirements.lock.txt` from that environment | PASS | rows 27 and 28 |
| Every imported package declared | PASS | row 28 |
| Environment recorded; untested platforms named | PASS | section 1 |
| README, DATASET_SETUP, PROJECT_MANIFEST, VIVA_GUIDE, FINAL_AUDIT_REPORT present, no other new documents | PASS | file list in `PROJECT_MANIFEST.md` |
| No pathway names added to any report table | PASS | the template shows pathway ids; checked by reading the template and the rendered synthetic report |
| Real-data gate still closed and refuses with exit 3 | PASS | row 25 |
| Real-data execution | BLOCKED | section 3 |
| Schema verification on a real file | BLOCKED | section 3 |
| Windows, macOS | BLOCKED | section 3 |
| Python other than 3.13, pandas or numpy older than the lock | BLOCKED | section 3 |
| Reproducible build script, and the ZIP-level fresh-extraction verification | NOT RECORDED HERE | `VERIFICATION_RESULT.md` (section 0) |
| Synthetic outputs shipped | NOT APPLICABLE | none shipped; they regenerate with `--synthetic` |
| Tier 2 extensions | NOT APPLICABLE | switched off, not built |
