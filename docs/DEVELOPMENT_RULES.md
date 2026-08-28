# Development Rules & Workflow

## The Core Acceptance Loop

```
Small Focused Change
  ──> Unit & Contract Tests (`pytest tests/`)
  ──> Static Analysis (`ruff check`, `mypy app`)
  ──> Container Build (`docker build`)
  ──> Deploy to DEV Environment (when conversational behavior changes)
  ──> Live Phone Call Verification
  ──> Inspect Telephony Logs
  ──> PASS
  ──> Git Commit on `dev`
```

## Quality Standards

1. **Hermetic Unit Tests**: All unit tests must execute and pass locally without requiring external cloud credentials or live network calls.
2. **Strict Typing**: MyPy must pass across the entire `app/` codebase with no global error suppression.
3. **Structured Logging**: Every turn must emit a JSON log record with `conversation_id`, `turn_id`, `route`, and latency measurements.
4. **No Premature Architecture**: Add nodes, state fields, or abstractions only when a demonstrated failure necessitates them.
