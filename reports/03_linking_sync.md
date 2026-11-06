# Shared quarter-aware linking synchronization

> Historical implementation/test snapshot. The 150-pass full suite and current safety-gate requirements are recorded in `reports/10_readiness.md`; the historical counts and code notes below describe this synchronization step only.

Inspection date: 2026-11-06 (Asia/Kolkata)

## Scope and identifier boundary

`reports/02_mospi_verification.md` confirms **no official identifier definition**: the Catalogue 213 dictionary/layout, instruction manual, release notes, and rider were absent. The implementation below adds no identifier fields and does not assert that the configured key is officially complete. For a reproducible mechanical comparison, it uses only the existing schema-declared candidate key and configured quarter/visit fields. Its behavior is algorithmically tested; PLFS identity semantics remain unconfirmed, so the real-data gate stays closed (`data.plan: UNSET`).

## Shared implementation

- Added `quarter_aware_link_keys` in `src/data_loader.py`. It receives the composed candidate key and configured quarter/visit columns, validates Q1–Q4 and V1–V4 coordinates, derives the cohort key, and returns collision group/excess-row counts for both coordinate rules.
- `link_persons` uses this shared function in strict mode. Invalid labels, missing coordinates, incomplete four-visit coverage, or any repeated candidate-key/quarter/visit coordinate raise `SchemaError`; no rows are silently resolved or removed by the shared function.
- `data_audit._person_frame` now carries the configured quarter. `_linkage` lazily imports and calls the loader function in non-strict audit mode, avoiding a module import cycle while ensuring the audit and loader use the same normalization, cohort rule, and collision counts.
- The audit retains the historical JSON key `duplicate_key_time_pairs` for shape compatibility, but sets it to `null`: neither collision rule proves that two full source rows are identical. User-facing audit output now says “key/time collision” and reports groups and excess rows.
- Added a synthetic integration test proving loader/audit agreement; the prior quarter-linking tests remain intact.

## Reproduced real-data counts

Counts below were recomputed from the four configured person files using a narrow projection of the configured candidate key, quarter, visit, age, sex, and sector. Training fields, including `b4q12`, were not read for this calculation. The configured key composition is not officially verified; these are candidate-key collision counts, not a finding that source records are duplicate or that people are correctly linked.

| Rule | Collision groups | Excess rows | Interpretation |
|---|---:|---:|---|
| Legacy candidate key + visit | 3,390 | 3,390 | 3,390 key/visit coordinate collisions. Full-row identity was not checked; do not call these duplicate records. |
| Candidate key + quarter + visit | 0 | 0 | No repeated coordinate groups under the configured quarter/visit rule. |

Additional linked-frame diagnostics from the same audit call: 922,599 person rows; 546,423 derived cohort keys; 211,111 candidate keys observed at 2+ visits; 22.65% at 3+ visits and 7.56% at all 4. The quarter/visit parser found 0 invalid-coordinate rows. Linkage rates are mechanical outputs using an unconfirmed candidate key, not verified PLFS person-match rates.

No data rows were deleted. The actual count run used `data_audit.linkage_report` on the narrow projection; loader/audit agreement is separately checked on a synthetic fixture. No real trainee selection or clustering was run. The Checkpoint 1 software gate remains closed.

## Test results

- Focused linkage tests, including the new audit/loader agreement test: **8 passed**. This includes all seven previously existing quarter-linking test cases.
- Synthetic audit demo: **12 checks passed**.
- Full suite, run with `--continue-on-collection-errors`: **89 passed, 4 failed, 16 errors** (exit 1).

All four failures occur because `lost_codes` is empty and `src.synthetic_data._state_setup` raises `ConfigError: unknown_codes and lost_codes must each hold at least one code for the generator`:

- `tests/test_distances.py::test_collapsed_estimate_equals_individual_estimate`
- `tests/test_distances.py::test_collapsing_does_not_change_distances_between_people`
- `tests/test_planted_structure.py::test_collapsing_does_not_change_the_answer`
- `tests/test_planted_structure.py::test_more_noise_means_worse_recovery_and_a_lower_silhouette`

Fifteen setup errors in planted-structure/stability tests have the same `ConfigError`. The remaining error is collection of `tests/test_trajectories.py`: line 35 indexes `D["lost_codes"][0]`, raising `IndexError` because `lost_codes: []`. No lost code was invented to make tests pass.

## Blockers and interpretation

1. Obtain the official Catalogue 213 person/household dictionary and layout. Until then, the candidate key and quarter/visit meaning remain unconfirmed; zero quarter/visit collisions do not establish true person identity.
2. Reconcile Checkpoint 1's legacy collision display with the new quarter-aware calculation. The computed 3,390 is now explicitly a legacy coordinate collision count; it is not an identical-row count.
3. Resolve the synthetic-test contract for an empty `lost_codes` list without inventing an official casualty code, then rerun the complete suite.
4. Keep `data.plan: UNSET`; this synchronization is not approval to run real trajectories.

## Files changed for this task

- `src/data_loader.py`
- `src/data_audit.py`
- `tests/test_data_loader_linkage.py`
- `reports/03_linking_sync.md` (this report)

No config or raw-data files were changed.
