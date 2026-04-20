# Repository Notes

## 1) Architecture direction: object-oriented when it helps

- Prefer object-oriented design for new stateful features.
- Keep small pure utilities as functions when that is simpler and clearer.
- Encapsulate mutable state in classes instead of growing global state.
- Favor dataclasses for structured domain/config objects.
- For larger features, separate concerns:
  - route/controller layer (Flask endpoint)
  - service layer (business logic)
  - data model layer (typed objects)

Practical rule:
- If a feature has lifecycle/state/coordination across multiple functions, implement a class.
- If logic is a single pure transformation, keep it functional.

## 2) Testing policy for new features

- Keep tests under tests/.
- Every new feature should include tests in the same change.
- Add at least:
  - one success-path test
  - one failure/edge-path test
- For API features, use Flask test client tests.
- Keep tests fast and deterministic (no network and no external services).

Definition of done for feature work:
- behavior implemented
- tests added/updated
- docs/notes updated when behavior changes

## 3) Near-term refactor targets (OO migration candidates)

- Move endpoint-specific parsing/normalization code into dedicated service classes.
- Isolate model editor state/update logic behind an explicit model service.
- Reduce module-level mutable globals where possible.
