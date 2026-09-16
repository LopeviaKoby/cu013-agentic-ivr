"""Focused real-model probe for the prior-request conversational policy.

Manual DEV probe, not CI: it calls Vertex AI with ADC through the same
`GeminiTurnModel` the service uses and reports only route, action_requested
and latency per call. Messages are printed locally for inspection; every
text is synthetic and PII-free. No assertions, no caching, no retries.

Usage:
    python evals/conversation_policy_eval.py
"""

import asyncio
import sys
import time

from google.genai import Client
from google.genai.types import HttpOptions

from app.conversation.gemini import GeminiBaseline, GeminiTurnModel

PRIOR_REQUEST_TRANSCRIPT = "quiero desbloquear mi cuenta pero antes explícame qué puedes hacer"
DIRECT_ACTION_TRANSCRIPT = "quiero desbloquear mi cuenta"
PRIOR_QUESTION_TRANSCRIPT = "antes de continuar, explícame qué haces"

PRIOR_REQUEST_REPETITIONS = 5
CONTROL_REPETITIONS = 1


async def probe(model: GeminiTurnModel, label: str, transcript: str, repetitions: int) -> None:
    for index in range(repetitions):
        start = time.monotonic()
        decision = await model.decide(
            transcript=transcript,
            identity_validated=False,
            requested_action=None,
            pending_operation=None,
        )
        latency_ms = (time.monotonic() - start) * 1000.0
        print(
            f"{label}[{index}] route={decision.route.value} "
            f"action_requested={decision.action_requested} "
            f"latency_ms={latency_ms:.0f}"
        )
        print(f"{label}[{index}] message={decision.message}")


async def run() -> int:
    baseline = GeminiBaseline.from_env()
    client = Client(
        vertexai=True,
        project=baseline.project,
        location=baseline.location,
        http_options=HttpOptions(api_version=baseline.api_version),
    )
    model = GeminiTurnModel(client, baseline)
    try:
        await probe(model, "PRIOR_REQUEST", PRIOR_REQUEST_TRANSCRIPT, PRIOR_REQUEST_REPETITIONS)
        await probe(model, "DIRECT_ACTION", DIRECT_ACTION_TRANSCRIPT, CONTROL_REPETITIONS)
        await probe(model, "PRIOR_QUESTION", PRIOR_QUESTION_TRANSCRIPT, CONTROL_REPETITIONS)
    finally:
        await client.aio.aclose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
