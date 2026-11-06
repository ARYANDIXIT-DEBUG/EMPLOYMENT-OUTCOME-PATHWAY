# Employment Outcome Pathway Grouping After Skilling

INT396 Unsupervised Learning, CA-1 project. Problem statement SIH26135 (Government of Maharashtra). Group G24.

## What this is

A Python pipeline that groups trainees by how their employment status moved over a few survey visits, and checks whether that grouping says more than a plain "employed or not" split.

- k-medoids clustering of state sequences (a pathway is represented by a real trainee).
- A hierarchical clustering on the same distance, for comparison.
- A mandatory baseline: employed or not at one reference visit.
- A stability study under random loss, attribute-dependent loss and censoring.
- A Streamlit dashboard and a report whose numbers all come from saved result files.

## Status: read this first

**Current status (2026-11-06): real-data analysis BLOCKED.** `data.plan` is `UNSET`; official schema verification, b4q12 selection permission, casualty/lost-code mapping and training-before-observation timing are unresolved. Only the CHECKPOINT 1 descriptive audit has run on real files; no real trajectories or clusters exist. Synthetic outputs carry the label **SYNTHETIC DEMONSTRATION - NOT PLFS RESULTS** and are tests only.

Use `reports/06_checkpoint1.md` and `reports/10_readiness.md` for current real-data figures and gate status. An existing `reports/results/audit__real.json` is a stale historical artifact: its embedded config says `plan: A` and its linkage numbers use the legacy key/time rule. It was not overwritten; do not use it as current evidence or authorization.

A real run is refused unless CHECKPOINT 1 is explicitly `PASSED`, `b4q12` selection permission is explicitly `CONFIRMED`, the documented lost-code list and nonresponse column are present, training timing is dated and verified, `data.plan` is `A`, `data.verified` is true, and the design check passes. Missing statuses fail closed; `run_pipeline.py` exits with code 3. These config statuses are attestations that must be filled only after evidence is supplied and reviewed; do not set them to open the gate without that evidence. The separate `audit` stage can run while the gate is closed. Current gate status is BLOCKED; see [reports/10_readiness.md](reports/10_readiness.md).

## Where this was tested, and where it was not

Prior release verification: Python 3.13.16 on Ubuntu 24.04.5 LTS (x86_64), in a clean virtual environment built from `requirements.txt`, with versions recorded in `requirements.lock.txt`. Latest final verification in this workspace: Python 3.13.1 on Windows, pandas 3.1.1 and numpy 2.5.4; full pytest passed 153 tests with three distance warnings, and the real-data audit exited 0 using `--no-write`. The synthetic demo pipeline completed; no real modeling stage was run.

Verification in this workspace was on Windows with Python 3.13.1, pandas 3.1.1 and numpy 2.5.4: pytest and the read-only real-data audit were run. A clean Windows install and the complete quick-start sequence were not tested. macOS, Python versions other than 3.13, pandas below 3.1 and numpy below 2.5 remain untested. The code is written to the Python 3.10 grammar (checked by parsing only, not by running it on 3.10); declared support is intended, not verified. `FINAL_AUDIT_REPORT.md` lists the earlier release checks; `reports/10_readiness.md` records this final workspace verification.

## Quick start

You need Python 3.10 or newer. Run these from the project folder (the one that contains `run_pipeline.py`).

Linux and macOS (macOS commands UNVERIFIED; the Linux commands were run):

```
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python run_pipeline.py --synthetic        # writes SYNTHETIC results, figures and a report
streamlit run dashboard/app.py            # read-only view of the saved results
python -m pytest tests -q                 # 153 tests (verified 2026-11-06; 3 warnings)
```

Windows, Command Prompt or PowerShell (pytest and audit verified here; clean install/quick start not verified):

```
py -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python run_pipeline.py --synthetic
streamlit run dashboard/app.py
python -m pytest tests -q                 # 153 tests (verified 2026-11-06; 3 warnings)
```

In PowerShell the activation line is `.venv\Scripts\Activate.ps1`; if PowerShell refuses to run it, that is its script-execution policy, not this project. To install the exact versions that were verified instead of the supported ranges, use `python -m pip install -r requirements.lock.txt`.

`python run_pipeline.py --synthetic --quick` uses fewer stability repeats (synthetic testing only). The synthetic run writes `reports/results/*__SYNTHETIC.json`, `reports/figures/*` and `reports/report__SYNTHETIC.md`; human-facing synthetic reports, figures and dashboard views carry **SYNTHETIC DEMONSTRATION - NOT PLFS RESULTS**. These folders are created when needed and are not part of the release.

The dashboard shows what is saved, so run the pipeline first. If both real and SYNTHETIC results exist the sidebar lets you choose one; they are never shown together. To point it at another config, set the environment variable `PATHWAYS_CONFIG` to that file's path before starting it.

Self-tests (each prints its own summary line, and exits 0 when it passes):

```
python -m src.<module>              # one per module, for example: python -m src.distances
python run_pipeline.py --self-test
python dashboard/app.py --self-test
```

The 15 modules with a self-test are: config, data_audit, synthetic_data, data_loader, preprocessing, missing_data, trajectories, distances, baseline, clustering, evaluation, stability, profiling, visualization, report_builder.

## Running on real data

Do these in order. The order is the point. `DATASET_SETUP.md` has the long version with the verification log.

1. Obtain the PLFS release and its data dictionary. Read `DATASET_SETUP.md` and `docs/DATA_USE_ASSESSMENT.md`: the second lists the questions that must be answered (including the data-use conditions) before attributes are shown or any data are shared. Put the files in `data/raw/` and do not redistribute them.
2. In `config.yaml`, fill `data.files`, `data.layouts` and `data.schema` from the official dictionary. Nothing is assumed from memory: every column name and code comes from the config, and the states' `raw_codes` carry an `UNVERIFIED:` prefix until you replace them with codes checked against the questionnaire.
3. Run the audit and read it:
   ```
   python run_pipeline.py --stage audit
   ```
   It reports the linkage rate and visits per person, whether the linking key is valid (unique within a time point, sex and age consistent along a link), period and sector coverage, how large the trainee subgroup is under each trainee definition and how many survive linkage, the training variables with their exact code lists, missingness and non-response codes. It prints counts only, never a record or an identifier, and builds no model. When the primary files declare more than one survey design, everything is reported per design and never pooled.
4. Decide the plan from the audit (CHECKPOINT 1). Do not set `data.checkpoint1_status: PASSED` or `data.plan: A` until the official identifiers, quarter/visit fields, status mappings, missing/lost codes and design are verified. The current workspace report records CHECKPOINT 1 as BLOCKED.
   - Plan A requires evidence that the selected observations support actual person trajectories.
   - Plan B (cross-sectional outcome profiles) or Plan C (aggregate only) change the project's question. They need a scope-change memo that you write, and your instructor's approval (`data.scope_approved: true`). The code mentions the path `docs/SCOPE_CHANGE_MEMO.md` for it; no such file is shipped, and the pipeline refuses to run Plan B or C as pathways in any case.
5. Set `baseline.locked: true` once the baseline definition is final. The pipeline then records `baseline_lock.json` in the results folder so later changes are visible, and a real run refuses to start with the baseline unlocked.
6. Before a real run, obtain written authority to use `b4q12` for trainee selection and documentation that dates training before the employment observations. The current `coarse_flag` cannot establish that order. Fill permission/timing statuses only after documenting evidence; missing or unresolved status keeps the gate closed.
7. After every gate requirement is satisfied and the baseline is locked, run `python run_pipeline.py`, then open the dashboard and read the report in `reports/`.

## PROPOSED defaults to confirm

These values in `config.yaml` are my method choices, not facts. They are marked PROPOSED in the file. Confirm or change each deliberately before a real run.

| Key | Value now | What it decides |
|---|---|---|
| `time.n_points` | 4 | Visits per person; taken from your 2025 design note, not verified |
| `trainee.definition` | ever_trained | Who counts as a trainee (or `recent_completion`); choose at CHECKPOINT 1 |
| `trainee.min_time_points` | 3 | Observed visits needed to enter the analysis |
| `trainee.timing_support` | coarse_flag | Not enough to establish training before each employment observation; real run remains blocked |
| `missing.policy` | pairwise_available | Distance uses only visits observed in both sequences |
| `distance.name` / `distance.substitution` | dynamic_hamming / trate | The sequence distance and its state-dependent costs |
| `baseline.reference_visit` | 3 | Last visit (index into the visit labels) |
| `baseline.employed_states` | wage, self, unpaid family work | Which states count as employed |
| `clustering.medoid_min_observed` | all | A medoid must be observed at every visit |
| `clustering.min_cluster_frac` | 0.02 | A group below this share is flagged as small |
| `clustering.k_rule` | min_stability_ari 0.6, silhouette_margin 0.02 | The rule that picks k |
| `stability.informative.attribute` | age | Attribute that drives attribute-dependent loss; strength is 1.0 |
| `stability.survival_max_dist` | 0.25 | A pathway "survives" if a new medoid lies within this distance |

Also decide before real data: `profiling.permitted_vars` (empty means no attribute profile; fill it from `docs/DATA_USE_ASSESSMENT.md` once your instructor answers). `distance.max_n`, `distance.max_matrix_mb` and `distance.peak_factor` are PLACEHOLDERS: the benchmark stage measures your machine and says what to set.

## Layout

```
README.md                   this file
DATASET_SETUP.md            where the data come from, what to verify, the verification log
PROJECT_MANIFEST.md         every file in the release, its purpose, and its SHA-256
VIVA_GUIDE.md               questions to expect and where the evidence lives
FINAL_AUDIT_REPORT.md       what was verified, what is blocked, open items, acceptance table
config.yaml                 every setting and code list; the single source of truth
requirements.txt            supported version ranges
requirements.lock.txt       exact versions from the clean verification environment
run_pipeline.py             orchestrator: audit, build, benchmark, cluster, evaluate, stability, profile, report
src/config.py               loads and validates config; seeds; fairness guards
src/data_audit.py           the gate: audit of the real files (no modelling)
src/data_loader.py          real files to a long panel (only after the gate)
src/preprocessing.py        observation window, eligibility, attributes
src/missing_data.py         missingness audit, tests and policies
src/synthetic_data.py       SYNTHETIC panel with planted pathways (testing only)
src/trajectories.py         long panel to states; collapsing identical rows
src/distances.py            dynamic Hamming, optimal matching, memory plan
src/clustering.py           k-medoids, hierarchical, reference clustering
src/evaluation.py           silhouette, separation, other internal measures
src/baseline.py             employed-or-not baseline and comparison
src/stability.py            attrition, censoring, choosing k
src/profiling.py            descriptive tables and the pathway-naming helper
src/visualization.py        figures (stamped SYNTHETIC when applicable)
src/report_builder.py       result files and the report template engine
dashboard/app.py            Streamlit page, reads saved results only
reports/report_template.md  words and placeholders; no typed numbers
tests/                      unit tests and planted-structure tests
docs/INTERFACES.md          function-level contracts between modules
docs/DATA_USE_ASSESSMENT.md what the data-use conditions may allow, and what to ask your instructor
scripts/build_release.py    rebuilds the release ZIP and the manifest hashes
data/raw/                   put the downloaded files here (empty in the release)
```

## How numbers reach the report

Each stage saves `reports/results/<name>__<tag>.json`, where the tag is `SYNTHETIC` or `real`. The report template contains placeholders such as a result name followed by a key, and `report_builder` fills them. A placeholder that cannot be filled stops the build with the full list of problems; it is never left blank or guessed. A report built from SYNTHETIC results opens with a banner, and every report ends with the list of result files used. Real and SYNTHETIC results are never mixed in one report or on one dashboard page.

## Exit codes of run_pipeline.py

| Code | Meaning |
|---|---|
| 0 | finished |
| 1 | a stage failed |
| 2 | usage or configuration error |
| 3 | the real-data gate refused the run |

## Method rules this project keeps

- Cross-sectional files are never combined as trajectories.
- Usual, subsidiary and current weekly status are never treated as consecutive steps in time.
- Column names, codes, panel identifiers, weights and survey design are never assumed from memory.
- Data from before and after the 2025 survey redesign are not pooled without a recorded justification.
- A missing or lost visit is never recoded into an employment state.
- Sex, social group and religion are never used to form pathways; they may be shown only to describe who is in each pathway, when the data-use assessment allows it.
- Survey weights are never mixed with the counts of identical sequences, and are used only where a table says so and only when verified.
- Synthetic data is only for testing the pipeline.

## Limits you should state when presenting

- With about four monthly visits, a "pathway" is a short-run pattern, not a career.
- Training completion before the employment observations is unverified; the current coarse flag cannot establish the order. No real-data results may be described as post-training pathways, and nothing here is causal.
- `b4q12` trainee-selection permission is unresolved. The real-data gate is closed until written permission is documented.
- `lost_codes` and the nonresponse field are unconfirmed, so loss to follow-up cannot be classified. Unknown or missing CWS values remain missing, never unemployment.
- Link-quality flags identify candidate person-key collisions and changes in sex/age. They do not prove the cause, and flagged records remain in the data; review them against confirmed identifier documentation before analysis.
- No longitudinal weight has been verified. Any current prevalence is unweighted/sample-only; do not present it as population-representative.
- The baseline is built from the same trajectories as the pathways, so agreement with it is not independent validation.
- Passing the planted-structure tests shows the code can find clear structure it was given. It says nothing about how well it will do on real data.
- Missingness tests use observed information only and cannot rule out dependence on what is unobserved.

## Troubleshooting

- Exit code 3: read the message; it names which gate condition is not met.
- "placeholder ... unresolved": a stage that creates that result has not run; the message says which names are missing.
- Dashboard says a result is missing: run the stage it names, or the whole pipeline.
- A memory-cap error: lower `distance.max_n`, or let the plan collapse or subsample (`distance.reduction`).
- Version trouble: install `requirements.lock.txt` in a fresh virtual environment, which is the combination that was verified. If your own environment differs and a test fails, report the versions with the failure.
