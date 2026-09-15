# Estándar de testing

Este documento define niveles y reglas de prueba subordinados a la [SPEC del sistema](../specs/system.md), la [SPEC de acciones de cuenta](../specs/account-actions.md) y los ADR con `Status: Accepted`. No crea contratos de producto.

## Niveles

| Nivel | Propósito | CI determinista |
|---|---|---|
| Unit | Lógica, validación, reducers/state y contratos | Sí |
| Integration | FastAPI, LangGraph, persistencia y adapters simulados o emulador | Sí |
| Real-model evals | Comprensión, tool choice, conversación y contexto | No |
| Voice DEV | ASR → backend → persistencia/modelo → TTS y latencia E2E | No |

## Reglas

- Usar fixtures sintéticos y PII-safe.
- Los tests deterministas no dependen de Gemini, XCALLY ni AD/TIVIT reales.
- No usar assertions de strings literales para lenguaje natural salvo que exista un contrato textual exacto.
- Los real-model evals usan assertions semánticas y métricas, y se ejecutan fuera del CI determinista.
- Voice DEV es un gate integrado de producto; no sustituye unit ni integration tests.
- No fijar todavía un coverage threshold.
- Cuando exista Dockerfile, el build Docker será un gate determinista de release.

CU013 prevé `asyncio` como único modelo asíncrono. Por ello pytest-asyncio usa `asyncio_mode = "auto"` en [`pyproject.toml`](../../pyproject.toml). Antes de cambiar esa configuración se debe verificar compatibilidad con la versión efectiva instalada.

No se crean directorios `app/` o `tests/` vacíos para satisfacer herramientas o gates.

## Referencias oficiales

- [pytest configuration](https://docs.pytest.org/en/stable/reference/customize.html)
- [pytest-asyncio configuration](https://pytest-asyncio.readthedocs.io/en/stable/reference/configuration.html)
