# Config and pytest blocker report

> Historical blocker report. `lost_codes` remains empty because no official lost/casualty code was documented. The collection failure described below was later fixed in synthetic tests with a synthetic-only sentinel; current test and readiness status is in `reports/10_readiness.md`.

Inspection date: 2026-11-06.

## Findings

- `config.yaml` contains `lost_codes: []` and `data.schema.nonresponse_col: null`.
- `reports/02_mospi_verification.md` says the official Catalogue 213 dictionary/layout and instruction manual are missing. Its “Lost / casualty codes” row explicitly says the local assertion that no casualty field exists is not sufficient to establish official codes and says not to infer one. **No lost code is documented there.**
- The code uses `lost_codes` for the synthetic generator and for the `LOST` branch in `src/trajectories.py::map_raw_to_state`. `tests/test_trajectories.py` indexes `D["lost_codes"][0]` at import time, so the empty list prevents collection.
- Full pytest was rerun with `.venv\\Scripts\\python.exe -m pytest -q`. Result: **collection interrupted; 1 error** at `tests/test_trajectories.py:35`, `IndexError: list index out of range` from `D["lost_codes"][0]`. No test bodies ran, so additional test failures cannot yet be assessed.

## Missing CWS observations

The CWS mapping does not convert missing observations to unemployment. `map_raw_to_state` initializes output to `MISSING`, writes state indices only for configured state codes, and applies `LOST` only when a configured nonresponse code matches. Blank/NA raw status therefore remains `MISSING`; configured unemployment codes `81` and `82` map to the `unemployed_seeking` state. Existing tests `test_unknown_and_blank_are_missing_and_lost_code_is_lost` and `test_a_pair_with_no_record_is_missing_not_a_state` exercise these behaviors, but the module-level `lost_codes[0]` access currently prevents the test file from collecting.

## Blocker and disposition

The requested source-constrained fix cannot be made: `reports/02_mospi_verification.md` documents no lost code and marks the official casualty/nonresponse documentation as unavailable. No `config.yaml`, code, or test changes were made, and no code was invented. Supply the official Catalogue 213 dictionary/layout or instruction-manual section that defines a lost/casualty code before populating `lost_codes`. Then rerun full pytest to discover and fix genuine test failures.
