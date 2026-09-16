"""DEV latency benchmark through the real FastAPI boundary.

Runs from the local DEV host with ADC against real Firestore and Vertex AI.
Methodology: 5 warmups, 30 measured sequential requests (RESET, UNLOCK and
a multi-turn sequence), per-segment monotonic timings and token counts only.

PII-safe: transcripts are synthetic and no transcript, DTMF or generated
text is ever recorded or printed.
"""

import asyncio
import math
import os
import sys
import time

from httpx import ASGITransport, AsyncClient

from app.conversation.gemini import GeminiBaseline
from app.main import DEFAULT_FIRESTORE_COLLECTION, FIRESTORE_COLLECTION_ENV, build_app
from app.session.metrics import RecordingTurnMetrics

SYNTHETIC_API_KEY_ENV = "CU013_API_KEY"
SYNTHETIC_API_KEY = "synthetic-dev-benchmark-api-key-0000"

WARMUPS = 5

RESET_TRANSCRIPT = "Buenas, olvidé mi contraseña y necesito restablecerla"
UNLOCK_TRANSCRIPT = "Mi cuenta está bloqueada, quiero desbloquearla"
MULTI_TURN_TRANSCRIPTS = [
    "Hola",
    "Necesito restablecer mi contraseña",
    "Listo, ya hice lo que me pidieron",
    "Gracias",
]

SEGMENTS = ["handler", "session_load", "model", "graph", "runtime", "session_save", "total"]
COUNTERS = ["prompt_tokens", "completion_tokens", "total_tokens"]

TURNS_URL = "/api/v1/conversations/{conversation_id}/turns"


def percentile(sorted_values: list[float], p: float) -> float | None:
    """Nearest-rank percentile (ceil(p*n)th value, 1-based)."""
    if not sorted_values:
        return None
    rank = max(1, math.ceil(p * len(sorted_values)))
    return sorted_values[rank - 1]


async def run_measurement(
    client: AsyncClient,
    conversation_id: str,
    transcript: str,
    metrics: RecordingTurnMetrics,
) -> dict[str, object]:
    """Run one boundary request and collect its PII-safe measurements."""
    metrics.drain_segments()
    metrics.drain_counters()
    start = time.monotonic()
    response = await client.post(
        TURNS_URL.format(conversation_id=conversation_id),
        json={"transcript": transcript},
    )
    total_ms = (time.monotonic() - start) * 1000.0
    segments = dict(metrics.drain_segments())
    counters: dict[str, int] = {}
    for name, value in metrics.drain_counters():
        counters[name] = value
    graph = segments.get("graph")
    model = segments.get("model")
    if graph is not None and model is not None:
        segments["runtime"] = graph - model
    segments["total"] = total_ms
    route = None
    error_code = None
    try:
        body = response.json()
        if response.status_code == 200:
            route = body.get("route")
        else:
            error_code = body.get("error", {}).get("code")
    except ValueError:
        pass
    return {
        "status": response.status_code,
        "segments": segments,
        "counters": counters,
        "route": route,
        "error_code": error_code,
        "error": response.status_code != 200,
    }


def aggregate(results: list[dict[str, object]]) -> None:
    """Print per-segment, per-counter and outcome statistics for one scenario."""
    requests = len(results)
    errors = sum(1 for r in results if r["error"])
    print(f"requests={requests} errors={errors}")
    routes: dict[str, int] = {}
    error_codes: dict[str, int] = {}
    for result in results:
        route = result.get("route")
        if route is not None:
            routes[str(route)] = routes.get(str(route), 0) + 1
        error_code = result.get("error_code")
        if error_code is not None:
            error_codes[str(error_code)] = error_codes.get(str(error_code), 0) + 1
    print(f"routes={routes if routes else '-'}")
    print(f"error_codes={error_codes if error_codes else '-'}")
    print(f"{'segment':<16}{'first':>9}{'p50':>9}{'p95':>9}{'min':>9}{'max':>9}")
    for segment in SEGMENTS:
        values = [
            r["segments"][segment]
            for r in results
            if isinstance(r["segments"], dict) and segment in r["segments"]
        ]
        if not values:
            print(f"{segment:<16}{'-':>9}{'-':>9}{'-':>9}{'-':>9}{'-':>9}")
            continue
        ordered = sorted(values)
        p50 = percentile(ordered, 0.5)
        p95 = percentile(ordered, 0.95)
        print(
            f"{segment:<16}{values[0]:>9.1f}{p50:>9.1f}{p95:>9.1f}"
            f"{ordered[0]:>9.1f}{ordered[-1]:>9.1f}"
        )
    print(f"{'counter':<16}{'first':>9}{'p50':>9}{'p95':>9}{'min':>9}{'max':>9}")
    for counter in COUNTERS:
        values = [r["counters"][counter] for r in results if counter in r["counters"]]
        if not values:
            print(f"{counter:<16}{'-':>9}{'-':>9}{'-':>9}{'-':>9}{'-':>9}")
            continue
        ordered = sorted(values)
        p50 = percentile(ordered, 0.5)
        p95 = percentile(ordered, 0.95)
        print(f"{counter:<16}{values[0]:>9}{p50:>9}{p95:>9}{ordered[0]:>9}{ordered[-1]:>9}")
    print()


async def check_multi_turn_document(app, collection: str, conversation_id: str) -> dict | None:
    """Read only the semantic durable fields that prove continuity."""
    snapshot = await (
        app.state.firestore_client.collection(collection).document(conversation_id).get()
    )
    if not snapshot.exists:
        return None
    data = snapshot.to_dict()
    return {
        "turn_count": data.get("turn_count"),
        "revision": data.get("revision"),
        "identity_validated": data.get("identity_validated"),
        "requested_action": data.get("requested_action"),
    }


async def run() -> int:
    os.environ.setdefault(SYNTHETIC_API_KEY_ENV, SYNTHETIC_API_KEY)
    baseline = GeminiBaseline.from_env()
    print("=== DEV backend latency baseline ===")
    print(f"provider={baseline.provider}")
    print(f"project={baseline.project}")
    print(f"location={baseline.location}")
    print(f"model={baseline.model}")
    print(f"api_version={baseline.api_version}")
    print(f"thinking_budget={baseline.thinking_budget}")
    print(f"timeout_ms={baseline.timeout_ms} attempts={baseline.attempts}")
    print()

    metrics = RecordingTurnMetrics()
    app = build_app(metrics=metrics)
    collection = os.environ.get(FIRESTORE_COLLECTION_ENV, DEFAULT_FIRESTORE_COLLECTION)
    prefix = f"cu013bench_{int(time.time())}"
    print(f"firestore_collection={collection}")
    print(f"conversation_prefix={prefix}")
    print()

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    headers = {"X-API-Key": os.environ[SYNTHETIC_API_KEY_ENV]}
    try:
        async with AsyncClient(
            transport=transport, base_url="http://benchmark", headers=headers
        ) as client:
            warmup_failures = 0
            for i in range(WARMUPS):
                result = await run_measurement(
                    client, f"{prefix}-warmup-{i}", RESET_TRANSCRIPT, metrics
                )
                if result["error"]:
                    warmup_failures += 1
            if warmup_failures == WARMUPS:
                print(
                    "BLOCKER: all warmup requests failed; no latency results "
                    "recorded. Investigate ADC/Vertex/Firestore before rerunning."
                )
                return 2

            scenarios: dict[str, list[dict[str, object]]] = {}
            for i in range(13):
                result = await run_measurement(
                    client, f"{prefix}-reset-{i}", RESET_TRANSCRIPT, metrics
                )
                scenarios.setdefault("RESET", []).append(result)
            for i in range(13):
                result = await run_measurement(
                    client, f"{prefix}-unlock-{i}", UNLOCK_TRANSCRIPT, metrics
                )
                scenarios.setdefault("UNLOCK", []).append(result)

            multi_results: list[dict[str, object]] = []
            multi_id = f"{prefix}-multi-1"
            for transcript in MULTI_TURN_TRANSCRIPTS:
                result = await run_measurement(client, multi_id, transcript, metrics)
                multi_results.append(result)
            scenarios["MULTI_TURN"] = multi_results

            all_results = [r for results in scenarios.values() for r in results]
            print(f"warmups={WARMUPS} measured={len(all_results)} sequential")
            print()
            for name, results in scenarios.items():
                print(f"=== scenario {name} ===")
                aggregate(results)
            print("=== overall (30 measured requests) ===")
            aggregate(all_results)

            document = await check_multi_turn_document(app, collection, multi_id)
            print("=== multi-turn durable continuity (semantic fields only) ===")
            print(f"conversation_id={multi_id}")
            print(f"document={document}")
            print(f"multi_turn_route_sequence={[r.get('route') for r in multi_results]}")
            print("documents created during this run: 27 (26 fresh + 1 multi-turn); not deleted")
    finally:
        await app.state.genai_client.aio.aclose()
        app.state.firestore_client.close()  # type: ignore[attr-defined]
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
