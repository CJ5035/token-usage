# Task 1 report — DSH parser and rate primitives

## Outcome

Implemented the DSH parser and aggregation primitives in `app/dsh_api.py`.

- Added compact `_steps` snapshot metadata with session identity, step key, completion time, provider/model ownership, token fields, final/unkeyed flags, and valid speed contribution.
- Preserved legacy `scan()` fields while adding cache read/write split and internal TPS numerator tracking.
- Implemented valid-key deduplication, message-over-chunk precedence, later-message replacement, first-context ownership, and unique `unkeyed:<line>` fallback keys with observability counts.
- Kept invalid speed windows in token/step totals while excluding them from speed numerator and seconds; no valid windows now report `tps: null`.
- Kept zstd frame handling and single-file failure behavior unchanged.

## Tests

Added coverage for cache split, mixed valid/invalid speed aggregation, and missing-key observability. Updated the no-valid-window expectation to the required `null` TPS contract.

Focused validation: `pytest -q tests/test_dsh_api.py tests/test_dsh_background.py` — 33 passed.

## Notes

The snapshot retains legacy aggregate totals for compatibility. Future and undated completion metadata remain available in `_steps` for the range-query task; future records are excluded from the legacy `today` bucket.

## Round 1 review fix

Fixed late and partial `request/context` attribution. Existing step metadata now retains the first non-empty provider/model values while allowing later valid context fields to fill values that were empty when usage arrived. Added a regression test covering usage before context plus partial context events.

Validation command and output: `pytest -q tests/test_dsh_api.py tests/test_dsh_background.py` — 34 passed.
