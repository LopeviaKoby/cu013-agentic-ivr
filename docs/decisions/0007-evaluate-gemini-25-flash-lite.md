# ADR-0007: Evaluar Gemini 2.5 Flash-Lite

- Status: Accepted
- Fecha: 2026-09-11

## Contexto y problema

CU013 necesita un baseline reproducible antes de seleccionar un modelo de producción.

## Impulsores de la decisión

- Referencia explícita y repetible.
- Latencia comparable con thinking controlado.
- Separar evaluación de selección definitiva.

## Opciones consideradas

- `gemini-2.5-flash-lite` con `thinking_budget=0` como baseline.
- No fijar un baseline reproducible.

No se documentan modelos alternativos no evaluados como decisiones.

## Decisión

Opción elegida: **Gemini 2.5 Flash-Lite con thinking desactivado como baseline temporal**. Debe evaluarse al menos una alternativa antes del 16-10-2026.

### Consecuencias

- Positiva: permite comparaciones reproducibles.
- Negativa: puede no satisfacer los umbrales finales.
- Negativa: `thinking_budget=0` puede afectar tareas que requieran razonamiento.

## Confirmación

- La evaluación debe configurar explícitamente `ThinkingConfig(thinking_budget=0)`.
- Los benchmarks deben medir latencia, calidad conversacional, tool selection/arguments, continuidad y razonamiento necesario.
- La aceptación conversacional final requiere voz DEV.

## Criterios de revocación

Se reconsiderará según benchmarks CU013. La elección definitiva de producción requerirá evidencia comparativa y una decisión separada.

## Trazabilidad

- [Especificación del sistema](../specs/system.md#modelo)
