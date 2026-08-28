---
name: cu013-gemini-vertex
description: Operates and maintains the async Vertex AI / Gemini 3.5 Flash-Lite client boundary.
---

# cu013-gemini-vertex

## Responsibility
Manage async model invocations, prompt dispatch, client reuse, and latency constraints using Google GenAI SDK and Vertex AI.

## Allowed Changes
- Tuning generation config (temperature, max tokens, system instruction).
- Modifying prompt formatting for conversational clarity.
- Adjusting timeout or retry policies.

## Forbidden Changes
- Creating new `genai.Client` instances on every turn.
- Using API keys for production authentication (must use ADC / Vertex AI).
- Allowing SDK automatic tool execution loops.
- Adding secondary model providers or unverified model IDs.

## Inputs / Contracts
- `prompt: str`, optional `system_instruction: str`.

## Outputs / Contracts
- `str` generated text response from Gemini.

## Trusted References
- [app/gemini.py](../../app/gemini.py)
- [AGENTS.md](../../AGENTS.md)

## Quality Checks
- `pytest tests/test_gemini.py`
- Async contract verification.

## STOP Conditions
- Model call count exceeds 2 in a single turn.
- Model latency consistently exceeds 1500ms on DEV.
