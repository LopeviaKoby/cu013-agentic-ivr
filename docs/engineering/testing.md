# Estándar de testing

Este documento define niveles y reglas de prueba subordinados a la [SPEC del sistema](../specs/system.md), la [SPEC de acciones de cuenta](../specs/account-actions.md) y los ADR con `Status: Accepted`. No crea contratos de producto.

## Niveles

| Nivel | Propósito | CI determinista |
|---|---|---|
| Unit | Lógica, validación, reducers/state y contratos | Sí |
| Integration | FastAPI, LangGraph, persistencia y adapters simulados o emulador | Sí |
| Real-model semantic evals | Comprensión, routing conversacional, política, tool choice y contexto, contra el corpus de [evals/conversation](../../evals/conversation/) | No |
| Voice DEV | ASR → backend → persistencia/modelo → TTS y latencia E2E | No |

## Metodología eval-driven

Todo cambio conversacional sigue este ciclo:

1. **real failure**: un fallo observado (voice DEV, eval o evidencia de caller);
2. **sanitize evidence**: eliminar PII/DTMF y registrar el caso sin datos personales;
3. **reproduce**: reproducir el fallo contra el modelo real con el caso sanitizado;
4. **add semantic eval**: añadir el caso al corpus con paráfrasis y controles opuestos;
5. **identify general missing property**: determinar la propiedad general ausente o incorrecta (no el wording);
6. **change smallest correct layer**: corregir la capa mínima correcta (prompt, policy, schema o runtime);
7. **deterministic tests**: cubrir la propiedad con tests deterministas;
8. **real-model eval**: validar contra el modelo real, por familia y con controles;
9. **DEV voice validation**: validar en voz DEV cuando el cambio afecte comportamiento hablado;
10. **accept/reject**: aceptar o rechazar con evidencia.

**Regla obligatoria:** un caso individual se añade primero al corpus. Prompt, policy, estado o schema sólo cambian si la evidencia demuestra una propiedad general ausente o incorrecta. Está prohibido el patch-driven prompting sobre utterances individuales.

No se exige wording exacto salvo que exista un contrato textual real. Las assertions semánticas evalúan rutas, estados y propiedades observables, no frases.

## Reglas

- Usar fixtures sintéticos y PII-safe. El corpus de evaluación no contiene PII, DTMF crudo ni transcripciones reales identificables.
- Los tests deterministas no dependen de Gemini, XCALLY ni AD/TIVIT reales.
- No usar assertions de strings literales para lenguaje natural salvo que exista un contrato textual exacto.
- Los real-model evals usan assertions semánticas y métricas, se ejecutan fuera del CI determinista y evalúan varias paráfrasis por propiedad con controles positivos y negativos; una única utterance repetida no es evidencia de generalización.
- Voice DEV es un gate integrado de producto; no sustituye unit ni integration tests.
- No fijar todavía un coverage threshold.
- El build del `Dockerfile` es un gate determinista cuando una iteración modifica el contenedor, las dependencias o el runtime empaquetado, o prepara una release/deploy; no se exige en cambios puramente documentales.

CU013 prevé `asyncio` como único modelo asíncrono. Por ello pytest-asyncio usa `asyncio_mode = "auto"` en [`pyproject.toml`](../../pyproject.toml). Antes de cambiar esa configuración se debe verificar compatibilidad con la versión efectiva instalada.

No se crean directorios `app/` o `tests/` vacíos para satisfacer herramientas o gates.

## Referencias oficiales

- [pytest configuration](https://docs.pytest.org/en/stable/reference/customize.html)
- [pytest-asyncio configuration](https://pytest-asyncio.readthedocs.io/en/stable/reference/configuration.html)
