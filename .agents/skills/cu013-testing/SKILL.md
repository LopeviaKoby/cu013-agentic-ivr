---
name: cu013-testing
description: Operates and maintains test suites, test doubles, linting, and typecheck gates.
---

# cu013-testing

## Responsibility
Ensure fast, hermetic, and high-coverage automated unit and contract tests across all system boundaries.

## Allowed Changes
- Adding focused unit tests for new contracts or bug fixes.
- Enhancing test doubles for Firestore or Vertex AI.
- Refining Ruff and MyPy configurations.

## Forbidden Changes
- Requiring live cloud credentials or network connections to pass `pytest`.
- Using `ignore_errors = true` globally in MyPy.
- Disabling Ruff lint rules globally to silence simple errors.
- Committing tests that depend on execution order or shared state.

## Inputs / Contracts
- `tests/` directory, `pyproject.toml` test configuration.

## Outputs / Contracts
- Clean green test suites and type/lint reports.

## Trusted References
- [tests/conftest.py](../../tests/conftest.py)
- [pyproject.toml](../../pyproject.toml)

## Quality Checks
- `pytest tests/ -v`
- `ruff check app tests`
- `mypy app`

## STOP Conditions
- Test suite fails or exhibits non-deterministic flakiness.
