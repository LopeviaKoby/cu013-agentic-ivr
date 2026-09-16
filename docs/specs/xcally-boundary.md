# CU013 v0.2.0 — Boundary HTTP XCALLY ↔ CU013

## Estado y alcance

Status: PROVISIONAL — implemented DEV baseline

Este documento describe el contrato HTTP implementado y probado hoy sobre el Thin Firestore Session Repository. Es el baseline DEV del turno conversacional disponible, no el contrato integrado final CU013↔Cally Square; no define todavía el contrato de órdenes/resultados AD/TIVIT, SendMail, VPN ni VDI.

El boundary sólo puede evolucionar con evidencia obtenida al integrar el flujo Cally Square rediseñado y AD/TIVIT, mediante caller tests/logs PII-safe y mediciones reales de latencia. Mientras conserve el estado `PROVISIONAL`, son aceptables cambios incompatibles respaldados por esa evidencia. No se modifica por especulación.

Evidencia de origen: XML del flujo Cally Square de referencia y confirmación del propietario de que XCALLY envía DTMF crudo.

## Endpoint y autenticación

```text
POST /api/v1/conversations/{conversation_id}/turns
Content-Type: application/json
X-API-Key: <secret>
X-Request-ID: <valor opaco de correlación>
```

- `conversation_id` es la identidad durable de la sesión (`UNIQUEID` observado en XCALLY).
- `X-Request-ID` se observó igual a `UNIQUEID`; no demuestra unicidad por request y **no** se usa como idempotency key.
- Cada request recibe un `turn_id` único generado internamente y devuelto en la respuesta para trazabilidad; XCALLY no está obligado a consumirlo.
- `X-API-Key` se valida contra un secreto leído únicamente del entorno (`CU013_API_KEY`), nunca de `config.yaml`, código, logs o fixtures, y se compara con `secrets.compare_digest`.
- Sin secreto configurado el servicio falla cerrado (`internal`, 500). Ausente o incorrecta producen la misma respuesta `authorization` (401), sin distinguir el caso.

## Variantes de request

Transcript ASR; sólo `transcript` es obligatorio y las variantes anteriores sin `asr_confidence` ni `channel` siguen siendo válidas:

```json
{
  "transcript": "{GOOGLE_ASR_TRANSCRIPT}",
  "asr_confidence": 0.0,
  "channel": "voice"
}
```

Evento `IDENTITY_DATA` con DTMF crudo, según el XML observado:

```json
{
  "event": "IDENTITY_DATA",
  "slots": { "document_id": "<DTMF crudo>" },
  "channel": "voice"
}
```

Ambos modelos cierran el contrato con `extra="forbid"`: un campo desconocido no se acepta. La captura de fecha de nacimiento por un flujo análogo aún no tiene contrato evidenciado.

## Response

Éxito (200):

```json
{
  "message": "...",
  "route": "...",
  "turn_id": "..."
}
```

`message` y `route` son los campos que consume Cally Square. Las rutas admitidas son un enum cerrado: `CONTINUE`, `COLLECT_IDENTITY`, `COMPLETE`, `ESCALATE`. No se añaden rutas especulativas para side effects futuros.

## Errores

Envelope estable; nunca se serializa detalle de Pydantic/FastAPI ni se ecoan transcript o DTMF:

```json
{
  "error": { "code": "<taxonomía>", "message": "<mensaje estático>" }
}
```

| `code` | HTTP | Condición |
|---|---|---|
| `validation` | 422 | Payload inválido o JSON malformado |
| `authorization` | 401 | `X-API-Key` ausente o incorrecta |
| `dependency_unavailable` | 503 | Motor conversacional no configurado; validación de identidad no integrada |
| `internal` | 500 | Fallo no esperado o API key no configurada |
| `dependency_timeout` | — | Reservado para I/O externa con deadline; todavía sin disparador |

El shape exacto de errores que Cally Square interpreta sigue pendiente de evidencia integrada (XC-005, XC-006).

## DTMF y PII

- El DTMF crudo sólo existe en el modelo transitorio `IDENTITY_DATA` durante el request.
- No se persiste, no se registra, no se devuelve, no aparece en mensajes de excepción y no alcanza al motor conversacional ni al LLM futuro.
- Recibir DTMF no valida identidad: nunca se marca `identity_validated=True` por su llegada.
- Sin integración real de validación (AD/TIVIT), `IDENTITY_DATA` termina con `dependency_unavailable` (503) sin tocar el estado durable ni crear sesión.
- Los errores de validación no registran el payload; sólo se registra la ruta y el hecho del fallo.

## Transcript y seam conversacional

- El transcript es input efímero: se entrega al seam y no se persiste.
- No existe NLU determinista, intención hard-coded, FSM conversacional ni motor sustituto. El único punto de extensión es `ConversationEngine` (`app/conversation`), que la próxima iteración implementará con Gemini; el runtime conserva legalidad, autorización, estado y efectos externos.
- Sin motor configurado, un turno de transcript falla de forma segura con `dependency_unavailable` (503).

## Persistencia

- Reutiliza el Thin Firestore Session Repository de [ADR-0009](../decisions/0009-use-thin-firestore-session-repository.md): un load, un grafo LangGraph en RAM sin persistent checkpointer y un save antes del HTTP response.
- El motor Gemini implementará el turno completo detrás del seam; el boundary HTTP no introduce checkpointer, segunda base, schema durable nuevo ni escrituras adicionales.

## Abierto

- Resultado positivo de validación de identidad y su integración con AD/TIVIT (ID-001).
- Correlación, idempotencia, polling, reintentos y resultados tardíos de XCALLY (XC-002 a XC-004).
- Shape real de responses/errors y mapeo de estados externos (XC-005, XC-006).
- Deadline explícito de Firestore (FS-002): el mecanismo por llamada existe (`timeout` en `AsyncDocumentReference.get/set`), pero su valor requiere la medición del camino real con modelo.

## Trazabilidad

- [Especificación del sistema](system.md)
- [Especificación de acciones de cuenta](account-actions.md)
- [Gaps de implementación](../gaps.md)
- [Boundary XCALLY / Orchestrator / TIVIT](account-actions.md#boundary-xcally--orchestrator--tivit)
