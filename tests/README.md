# Tests

This folder contains automated tests for new and existing features.

## Run

From repository root:

```bash
python -m unittest discover -s tests -p "test_*.py"
python -m coverage run -m unittest discover -s tests -p "test_*.py"
python -m coverage report -m
```

## Policy

- Add tests in the same change as new features.
- Include success-path and edge/failure-path coverage.
- Keep tests fast and deterministic.
