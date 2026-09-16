# ADR-0002: Usar Firestore para sesiones durables

- Status: Accepted
- Fecha: 2026-09-11

## Contexto y problema

La conversación abarca múltiples requests y debe sobrevivir a reinicios o cambios de instancia de Cloud Run. El estado de proceso no proporciona esa continuidad.

## Impulsores de la decisión

- Continuidad multi-turn durable.
- Independencia del ciclo de vida de una instancia.
- Una única autoridad durable de sesión.

## Opciones consideradas

- Firestore como único store durable.
- Estado sólo en memoria.
- Firestore más un segundo store.

## Decisión

Opción elegida: **Firestore como único store durable de sesión**. Colecciones, IDs, schema, TTL, concurrencia y el mecanismo LangGraph↔Firestore permanecen TBD.

### Consecuencias

- Positiva: el estado sobrevive entre requests e instancias.
- Positiva: evita consistencia entre múltiples stores.
- Negativa: introduce latencia remota y modos de fallo.
- Negativa: exige validar concurrencia, retención y minimización de PII.

## Confirmación

- La implementación debe demostrar continuidad entre requests.
- No debe existir otro session store de producción.
- La estrategia concreta debe adoptarse posteriormente mediante un ADR Accepted respaldado por evidencia.

## Criterios de revocación

Sólo se reconsiderará si Firestore demuestra un fallo material bajo Option A y Option B, o si una restricción corporativa impide su uso. Otra base requerirá un ADR nuevo.

## Trazabilidad

- [Especificación del sistema](../specs/system.md#alcance-y-stack)
- [Acciones de cuenta — Persistencia](../specs/account-actions.md#persistencia-y-concurrencia)
- [Experimento Firestore/LangGraph](../experiments/0001-firestore-langgraph-checkpointer.md)
- [ADR-0009 — Usar un repositorio delgado de sesiones en Firestore](0009-use-thin-firestore-session-repository.md)
