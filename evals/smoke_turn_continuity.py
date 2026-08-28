import asyncio
import sys
import time

from app.config import get_settings
from app.contracts import ModelTurnOutput
from app.gemini import generate_turn_response_async
from app.graph import build_gemini_contents


async def run_smoke() -> bool:
    """Run real Gemini multi-turn semantic continuity smoke test on Vertex AI."""
    settings = get_settings()
    print("=" * 60)
    print("RUNNING REAL-MODEL CONTROLLED SMOKE: Multi-Turn Continuity")
    print(f"Target Model ID : {settings.vertex_model}")
    print(f"Project ID      : {settings.gcp_project_id}")
    print(f"Vertex Location : {settings.vertex_location}")
    print("=" * 60)

    try:
        # Turn 1
        turn1_text = "Estoy en Perú y uso FortiClient."
        print(f"\n[Turn 1] User: {turn1_text}")
        contents1 = build_gemini_contents([], turn1_text)

        t1_start = time.perf_counter()
        output1, lat1 = await generate_turn_response_async(contents=contents1)
        t1_total = round((time.perf_counter() - t1_start) * 1000, 2)

        print(f"[Turn 1] Gemini Response ({lat1}ms): {output1.response_text}")
        assert isinstance(output1, ModelTurnOutput)
        assert len(output1.response_text.strip()) > 0

        # Turn 2
        history = [
            {"turn_id": "turn-1", "user_text": turn1_text, "bot_text": output1.response_text}
        ]
        turn2_text = "¿Qué cliente te dije que uso?"
        print(f"\n[Turn 2] User: {turn2_text}")
        contents2 = build_gemini_contents(history, turn2_text)

        t2_start = time.perf_counter()
        output2, lat2 = await generate_turn_response_async(contents=contents2)
        t2_total = round((time.perf_counter() - t2_start) * 1000, 2)

        print(f"[Turn 2] Gemini Response ({lat2}ms): {output2.response_text}")
        assert isinstance(output2, ModelTurnOutput)

        # Semantic continuity check
        resp2_lower = output2.response_text.lower()
        has_context = "forti" in resp2_lower or "forticlient" in resp2_lower

        print("\n" + "-" * 60)
        print(f"Semantic Context Evaluation: {'PASS' if has_context else 'FAIL'}")
        print(f"Turn 1 Latency: {lat1}ms (total {t1_total}ms)")
        print(f"Turn 2 Latency: {lat2}ms (total {t2_total}ms)")
        print("-" * 60)

        if not has_context:
            print("FAILED: Model did not reference 'FortiClient' in Turn 2 using context.")
            return False

        print("SUCCESS: Real Gemini turn continuity verified.")
        return True

    except Exception as exc:
        print(f"\nERROR running real Gemini smoke test: {exc}", file=sys.stderr)
        return False


if __name__ == "__main__":
    success = asyncio.run(run_smoke())
    sys.exit(0 if success else 1)
