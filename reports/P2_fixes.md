# P2 — Lost-code states and CWS mapping fixes

**Date:** 2026-11-06  
**Evidence used:** [P1 workspace state](P1_state.md) and [P4 MoSPI permissions verification](P4_permissions.md), especially Catalogue 213 Instruction Manual Vol. I §3.6.14.  
**Real-data permission:** unchanged; no permission flag was set.

## Findings and fixes

### Lost-code handling

P4 found that the reviewed release materials do not define a person-level lost/nonresponse code and also do not explicitly state that none exists. The correct current state is therefore **UNRESOLVED**, not “unavailable.” `config.yaml` now records:

```yaml
lost_codes: []
lost_codes_status: unresolved
```

No code or nonresponse column was inferred. Config validation now accepts only `documented`, `documented_unavailable`, or `unresolved`, and enforces a consistent code-list state. Runtime behavior is:

| Status | Required configuration | Behavior |
|---|---|---|
| `documented` | Nonempty documented `lost_codes` and a nonresponse column | Matching nonresponse values map to `LOST`; inconsistent config is rejected. |
| `documented_unavailable` | Empty `lost_codes`; explicit source evidence that no mapping exists | No record is labelled `LOST`; absent/blank observations remain `MISSING`. The real-data gate can proceed past this criterion. |
| `unresolved` | Empty `lost_codes` | The real-data gate blocks. The audit reports this as unresolved. |

Trajectory metadata records `lost_codes_status`. Synthetic smoke data use the existing test-only sentinel when no real mapping exists. The unsafe `lost_codes[0]` access in the missing-data demo now uses that sentinel only for its synthetic fixture. Tests no longer index the project’s empty list.

### CWS mapping

Instruction Manual Vol. I §3.6.14 states: “employed (any of codes 11-72), unemployed (any of codes 81 or 82) and out of labour force (any of codes 91-98).” The prior config treated code 98 as unknown/MISSING and omitted 96 from the out-of-labour-force group. The config now maps 92–98, including 96 and 98, to `out_of_labour_force`; code 91 remains the project’s separately named education subgroup within the documented 91–98 range. A regression test checks codes 96 and 98.

Blank and NA CWS values still map to `MISSING`. Code 99 remains in the project’s `unknown_codes` and therefore maps to `MISSING`; the P4 materials do not supply its detailed label, so the config comment marks its interpretation as pending official confirmation. No unknown value maps to unemployment.

## Tests

- Baseline before edits: **153 passed, 3 warnings**.
- Focused trajectory and safety-gate tests after edits: **46 passed**.
- Full suite after edits: **158 passed, 3 warnings, exit 0** in 22.50 seconds.
- The three warnings are existing distance warnings for pairs with fewer than two jointly observed time points; they receive the configured maximum distance.

The tests cover a defined test-only lost mapping, an explicitly unavailable mapping that records its status and preserves `MISSING`, and an unresolved mapping that blocks real-data execution. Blank and NA CWS values remain missing. The real project config remains `lost_codes_status: unresolved`, and the real-data gate remains closed by the unresolved CHECKPOINT 1 / permission conditions.

## Files changed for P2

- `config.yaml`
- `run_pipeline.py`
- `src/config.py`
- `src/data_audit.py`
- `src/data_loader.py` (synthetic fixture status only)
- `src/missing_data.py`
- `src/trajectories.py`
- `tests/test_real_safety_gate.py`
- `tests/test_trajectories.py`
- `reports/P2_fixes.md`

## Remaining blockers

- Written clarification is still needed on person-level lost-code availability; until then the real config remains `unresolved` and the real-data gate blocks.
- `b4q12` trainee-selection permission remains unresolved.
- Code 99’s detailed CWS label is not supplied by the reviewed P4 sources; it remains an unknown/MISSING code, not an employment classification.
- CHECKPOINT 1 and other unresolved official semantics in P1/P4 remain blockers. No clustering or real-data pipeline was run.
# Historical snapshot note (2026-11-06)

The current config status, CWS grouping, synthetic eligibility metadata, canonical output source, and readiness state have been superseded by [11_baseline_resolution.md](11_baseline_resolution.md). This earlier report is retained as a historical record; its older permission and CWS-status wording is not current.

