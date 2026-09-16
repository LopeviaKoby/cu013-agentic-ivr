# ADR-0009: Usar un repositorio delgado de sesiones en Firestore

- Status: Accepted
- Fecha: 2026-09-15
- Relación: concreta el mecanismo de persistencia pendiente en ADR-0002; no lo sustituye

## Contexto y problema

Firestore ya está aceptado como único almacén durable de sesiones y LangGraph como framework de orquestación de turnos. Quedaba pendiente decidir cómo relacionar ambos sin introducir latencia, amplificación de escrituras, persistencia opaca ni acoplamiento innecesario al runtime de LangGraph en el camino de voz.

Los Experimentos 0001 y 0002 evaluaron las dos opciones reales contra el mismo Firestore DEV, con el mismo flujo sintético y el mismo lock experimental seguro.

## Opciones evaluadas

### Opción A — Persistent LangGraph checkpointer

Un saver asíncrono de Firestore implementó el contrato público de checkpointing y resultó técnicamente viable con versiones parcheadas y serialización estricta. Por turno trivial midió aproximadamente 29 RPC, 28 escrituras, 17,6 KB comprometidos, cinco checkpoints y una duración p50 de 4,738 s / p95 de 4,805 s.

No se selecciona para el voice path productivo por la amplificación de escrituras, la latencia, la estructura Firestore profunda y poco semántica, el acoplamiento al contrato y versiones de LangGraph y la mayor complejidad de persistencia y retención.

### Opción B — Thin Firestore Session Repository

Un `SessionRecord` semántico se carga una vez por request; el turno LangGraph se ejecuta en memoria sin checkpointer persistente; el resultado se consolida y guarda antes de responder. Por turno trivial midió 2 RPC —una lectura y una escritura—, aproximadamente 630 bytes y una duración p50 de 485,5 ms / p95 de 941,6 ms; load p50 fue 231,8 ms y save p50 240,1 ms.

El experimento validó continuidad multi-turn, conservación intacta del último estado durable ante interrupción previa al save, `pending_operation` sintética, documento semántico de forma cerrada, timestamps nativos de Firestore y ausencia de `ABORTED`, `RESOURCE_EXHAUSTED`/429 o retries.

## Decisión

Opción elegida: **Thin Firestore Session Repository**.

El patrón productivo aceptado es:

```text
request
→ cargar SessionRecord desde Firestore
→ construir GraphState efímero en RAM
→ ejecutar LangGraph sin persistent checkpointer
→ consolidar SessionRecord
→ persistir antes del HTTP response
```

El `SessionRecord` debe ser pequeño, semántico y tener una lista explícita y cerrada de campos permitidos. El `GraphState` existe sólo durante el request. No se persisten tools, schemas de tools, SDK clients, objetos internos de LangGraph ni un `GraphState` arbitrario.

LangGraph orquesta el turno técnico; el LLM conserva la responsabilidad conversacional. Firestore continúa como único store durable. Una operación empresarial podrá exigir escrituras adicionales para un `pending_operation` durable alrededor del side effect; esas escrituras responderán a invariantes empresariales, no a internals o super-steps de LangGraph.

El security floor productivo es `langgraph>=1.0.10` y `langgraph-checkpoint>=4.1.1`. El lock de los spikes (`langgraph==1.2.11`, `langgraph-checkpoint==4.2.0`, `google-cloud-firestore==2.29.0`) demuestra compatibilidad experimental, pero no fija por sí mismo el lock productivo exacto. Ese lock se resolverá reproduciblemente en la primera implementación productiva mínima.

## Consecuencias

- Positiva: una lectura y una escritura consolidada constituyen el camino normal de persistencia por turno.
- Positiva: el documento durable es inspeccionable, semántico y apto para retención futura mediante timestamps nativos.
- Positiva: el estado durable no depende del schema interno ni del contrato de checkpointing de LangGraph.
- Positiva: la continuidad conversacional se reconstruye desde un contrato propio y cerrado.
- Negativa: un crash a mitad del turno no reanuda el grafo; el siguiente request parte de la última sesión durable.
- Negativa: el documento completo usa last-writer-wins mientras no exista evidencia de concurrencia real por `conversation_id`.
- Negativa: la primera implementación aún debe definir el schema productivo exacto, el lock reproducible y la política de retención sin copiar el harness experimental.

## Trade-offs aceptados

- **Crash mid-turn:** se reinicia desde la última sesión durable; no se requiere recuperación mid-graph para el voice path actual.
- **Concurrencia:** last-writer-wins por documento se acepta porque XCALLY ejecuta secuencialmente por `conversation_id` según la evidencia actual.
- **Operación pendiente:** pueden existir escrituras adicionales cuando sean necesarias para hacer durable una autorización u operación antes de un side effect empresarial.

## Confirmación

- El voice path no debe compilar LangGraph con un checkpointer persistente.
- La respuesta HTTP no debe emitirse antes de confirmar el save consolidado aplicable.
- Tests de contrato deben demostrar la whitelist durable, continuidad multi-turn, fallo antes del save y ausencia de PII/secretos o estado arbitrario.
- Esta decisión no introduce runtime productivo ni define contratos AD/TIVIT.

## Criterios de revocación

Reabrir esta decisión si evidencia productiva demuestra al menos una de estas condiciones:

- concurrencia real y material de requests para el mismo `conversation_id`, que obligue a evaluar optimistic locking o transacciones;
- necesidad empresarial de reanudar de forma durable un turno a mitad del grafo;
- imposibilidad de representar la continuidad aceptada mediante un `SessionRecord` pequeño y semántico;
- latencia, disponibilidad o coste del patrón consolidado incompatibles con el voice path.

Una revocación del mecanismo no revoca automáticamente Firestore como store durable ni LangGraph como orquestador; esas decisiones conservan sus propios criterios.

## Trazabilidad

- [ADR-0002 — Usar Firestore para sesiones durables](0002-use-firestore-for-durable-sessions.md)
- [ADR-0004 — Usar LangGraph para orquestar turnos](0004-use-langgraph-for-turn-orchestration.md)
- [Experimento 0001 — Firestore/LangGraph Checkpointer](../experiments/0001-firestore-langgraph-checkpointer.md)
- [Experimento 0002 — Firestore Thin Session Repository](../experiments/0002-firestore-thin-session-repository.md)
- [Especificación del sistema](../specs/system.md)
- [Especificación de acciones de cuenta](../specs/account-actions.md)
