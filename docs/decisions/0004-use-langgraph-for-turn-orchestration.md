# ADR-0004: Usar LangGraph para orquestar turnos

- Status: Accepted
- Fecha: 2026-09-11

## Contexto y problema

CU013 necesita orquestar conversación, estado y capacidades externas sin construir un motor propio ni una FSM conversacional grande.

## Impulsores de la decisión

- Framework de orquestación probado.
- Grafo pequeño y proporcional al slice.
- Persistencia e interrupción evaluables mediante contratos publicados.
- Evitar un orquestador custom.

## Opciones consideradas

- LangGraph.
- Orquestador custom.
- FSM conversacional propia.

## Decisión

Opción elegida: **LangGraph**. Se usarán sólo las primitivas requeridas. Este ADR no define nodos, GraphState keys, topología ni mecanismo de persistencia.

### Consecuencias

- Positiva: evita crear primitivas propias de orquestación.
- Positiva: ofrece un contrato de checkpointing evaluable.
- Negativa: crea dependencia de su API y modelo de ejecución.
- Negativa: debe evitarse que el grafo se convierta en una FSM grande.

## Confirmación

- El grafo futuro contendrá sólo estado y pasos exigidos por propiedades observables.
- No habrá routing semántico por keywords/regex ni multi-agent.
- La persistencia se decidirá por evidencia separada.

## Criterios de revocación

Se reconsiderará si LangGraph impide una propiedad requerida aun manteniendo un grafo pequeño y usando su contrato público.

## Trazabilidad

- [Especificación del sistema](../specs/system.md#alcance-y-stack)
- [Experimento Firestore/LangGraph](../experiments/0001-firestore-langgraph-checkpointer.md)
