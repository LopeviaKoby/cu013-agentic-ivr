---
name: cu013-observability
description: Operates structured logging, latency profiling, and PII-safe tracing for Cloud Logging.
---

# cu013-observability

## Responsibility
Ensure high-fidelity, structured, and PII-safe operational logs are emitted per turn for performance analysis in Google Cloud Logging.

## Allowed Changes
- Adding performance metrics or latency tracking for sub-operations.
- Enhancing PII redaction rules for newly encountered sensitive formats.

## Forbidden Changes
- Logging raw caller transcripts, passwords, tokens, or personal identifiers.
- Introducing complex APM agents (OpenTelemetry, DataDog, etc.) without prior approval.
- Emitting unstructured plain text logs from production endpoints.

## Inputs / Contracts
- Log records generated during request lifecycle.

## Outputs / Contracts
- Formatted JSON log strings containing `conversation_id`, `turn_id`, `route`, `latency_ms`, `model_call_count`.

## Trusted References
- [app/logging.py](../../app/logging.py)
- [AGENTS.md](../../AGENTS.md)

## Quality Checks
- Verify JSON log formatting and PII redaction in tests.

## STOP Conditions
- Unredacted credentials or sensitive identity data detected in log output.
