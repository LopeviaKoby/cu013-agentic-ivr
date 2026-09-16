"""Cloud Run DEV E2E client (pre-XCALLY): real HTTPS from the local host.

Reads the API key exclusively from the CU013_API_KEY environment variable
and never prints it. Measures the client round-trip; the server-side
segmentation (handler/load/model/graph/save) is recovered from Cloud
Logging via the PII-safe structured lines emitted by the service.

Usage:
  $env:CU013_API_KEY = "<secret>"
  python evals/cloud_run_latency.py --url https://<service>-....run.app
"""

import argparse
import asyncio
import math
import os
import sys
import time

import httpx

WARMUPS = 5

RESET_TRANSCRIPT = "Buenas, olvidé mi contraseña y necesito restablecerla"
UNLOCK_TRANSCRIPT = "Mi cuenta está bloqueada, quiero desbloquearla"
NEUTRAL_TRANSCRIPT = "Buenas tardes"
MULTI_TURN_TRANSCRIPTS = [
    "Hola",
    "Necesito restablecer mi contraseña",
    "Listo, ya hice lo que me pidieron",
    "Gracias",
]

TURNS_PATH = "/api/v1/conversations/{conversation_id}/turns"


def percentile(sorted_values: list[float], p: float) -> float | None:
    """Nearest-rank percentile (ceil(p*n)th value, 1-based)."""
    if not sorted_values:
        return None
    rank = max(1, math.ceil(p * len(sorted_values)))
    return sorted_values[rank - 1]


async def run_request(
    client: httpx.AsyncClient,
    conversation_id: str,
    transcript: str,
    headers: dict[str, str],
) -> dict[str, object]:
    """One HTTPS request; timing only, never content."""
    start = time.monotonic()
    response = await client.post(
        TURNS_PATH.format(conversation_id=conversation_id),
        json={"transcript": transcript},
        headers=headers,
    )
    round_trip_ms = (time.monotonic() - start) * 1000.0
    return {
        "status": response.status_code,
        "round_trip_ms": round_trip_ms,
        "error": response.status_code != 200,
    }


def aggregate(name: str, results: list[dict[str, object]]) -> None:
    requests = len(results)
    errors = sum(1 for r in results if r["error"])
    statuses: dict[int, int] = {}
    for result in results:
        status = int(result["status"])
        statuses[status] = statuses.get(status, 0) + 1
    values = sorted(float(r["round_trip_ms"]) for r in results)
    print(f"=== {name} ===")
    print(f"requests={requests} errors={errors} statuses={statuses}")
    if values:
        p50 = percentile(values, 0.5)
        p95 = percentile(values, 0.95)
        print(f"{'round_trip_ms':<16}{'first':>9}{'p50':>9}{'p95':>9}{'min':>9}{'max':>9}")
        print(
            f"{'client_total':<16}{values[0]:>9.1f}{p50:>9.1f}{p95:>9.1f}"
            f"{values[0]:>9.1f}{values[-1]:>9.1f}"
        )
    print()


async def run() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Cloud Run service URL")
    parser.add_argument("--timeout", type=float, default=30.0, help="client timeout (s)")
    args = parser.parse_args()

    api_key = os.environ.get("CU013_API_KEY")
    if not api_key:
        print("CU013_API_KEY is not set in the environment", file=sys.stderr)
        return 2
    base_url = args.url.rstrip("/")
    prefix = f"cu013benchcr_{int(time.time())}"
    print(f"service_url={base_url}")
    print(f"conversation_prefix={prefix}")

    timeout = httpx.Timeout(args.timeout)
    async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as client:
        print("=== preflight (never prints the key) ===")
        missing = await client.post(
            TURNS_PATH.format(conversation_id=f"{prefix}-preflight-missing"),
            json={"transcript": NEUTRAL_TRANSCRIPT},
        )
        wrong = await client.post(
            TURNS_PATH.format(conversation_id=f"{prefix}-preflight-wrong"),
            json={"transcript": NEUTRAL_TRANSCRIPT},
            headers={"X-API-Key": "synthetic-wrong-key-0000"},
        )
        valid = await client.post(
            TURNS_PATH.format(conversation_id=f"{prefix}-preflight-valid"),
            json={"transcript": NEUTRAL_TRANSCRIPT},
            headers={"X-API-Key": api_key},
        )
        print(f"no_key_status={missing.status_code} (expected 401)")
        print(f"wrong_key_status={wrong.status_code} (expected 401)")
        print(f"valid_key_status={valid.status_code} (expected 200)")
        if (missing.status_code, wrong.status_code, valid.status_code) != (401, 401, 200):
            print("preflight failed; aborting benchmark")
            return 2

        headers = {"X-API-Key": api_key}
        for i in range(WARMUPS):
            await run_request(client, f"{prefix}-warmup-{i}", RESET_TRANSCRIPT, headers)

        scenarios: dict[str, list[dict[str, object]]] = {}
        for i in range(10):
            result = await run_request(client, f"{prefix}-reset-{i}", RESET_TRANSCRIPT, headers)
            scenarios.setdefault("RESET", []).append(result)
        for i in range(10):
            result = await run_request(client, f"{prefix}-unlock-{i}", UNLOCK_TRANSCRIPT, headers)
            scenarios.setdefault("UNLOCK", []).append(result)
        for i in range(6):
            result = await run_request(client, f"{prefix}-neutral-{i}", NEUTRAL_TRANSCRIPT, headers)
            scenarios.setdefault("NEUTRAL", []).append(result)

        multi_results: list[dict[str, object]] = []
        multi_id = f"{prefix}-multi-1"
        for transcript in MULTI_TURN_TRANSCRIPTS:
            result = await run_request(client, multi_id, transcript, headers)
            multi_results.append(result)
        scenarios["MULTI_TURN"] = multi_results

        all_results = [r for results in scenarios.values() for r in results]
        print(f"warmups={WARMUPS} measured={len(all_results)} sequential")
        print()
        for name, results in scenarios.items():
            aggregate(name, results)
        aggregate("overall", all_results)
        print(f"multi_turn_conversation={multi_id}")
        print(
            "server-side segments: query Cloud Logging with the PII-safe"
            " 'turn_metric' lines for this conversation prefix."
        )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
