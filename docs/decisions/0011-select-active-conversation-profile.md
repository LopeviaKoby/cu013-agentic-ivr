# ADR-0011: Selección del perfil conversacional activo

- Status: Accepted
- Fecha: 2026-09-19

## Contexto y problema

CU013 necesita un único perfil conversacional reproducible para el
laboratorio sintético antes de cualquier validación de voz. La evaluación
comparativa exigida por ADR-0007 ya se ejecutó en el carril sintético.

## Impulsores de la decisión

- Referencia explícita y repetible sin etiquetas experimentales.
- Separar la ubicación del modelo (`global`) de la región de
  infraestructura (`us-east1`).
- Clasificación procedimental obligatoria y memoria reciente acotada.
- Cero violaciones críticas ejecutadas y guards del runtime intactos.

## Opciones consideradas

- Gemini 3.5 Flash-Lite en Vertex AI `global`, nivel de razonamiento
  `MINIMAL`, salida estructurada, clasificación procedimental
  estructurada obligatoria y memoria reciente de tres pares.
- Mantener el baseline histórico Gemini 2.5 como referencia activa.
- Reabrir otro modelo, región, prompt o estrategia experimental.

No se documentan proveedores descartados como decisiones productivas;
su evidencia queda archivada en el experimento.

## Decisión

Opción elegida: **Gemini 3.5 Flash-Lite sobre Vertex AI, ubicación de
modelo `global`, `thinking_level=MINIMAL` (sin `thinking_budget`),
esquema de respuesta estructurado con observación procedimental
requerida, memoria conversacional reciente de tres pares de turnos
completados y progreso procedimental guiado**. Alcance sintético de
laboratorio; no validado en voz, no aceptado en producción y sin
retención de texto real de callers.

### Consecuencias

- Positiva: perfil único, reproducible y fácil de entender sin
  cronología experimental.
- Negativa aceptada: avance procedimental prematuro raro, bloqueado por
  guards; variación semántica segura ocasional; latencias backend
  observadas p50 ≈987 ms / p95 ≈1258 ms como medidas, sin SLO.

## Confirmación

- El runtime envía sólo `thinking_level` en Gemini 3 y la identidad
  registra `thinking_budget=null`.
- El esquema enviado exige la clasificación procedimental sin default;
  el parser sigue tolerante.
- Una llamada al modelo por transcript; polling sin habla nueva hace
  cero llamadas.
- Los guards de autorización y despacho quedan intactos; la memoria
  textual real sigue desactivada sin política de retención.

## Criterios de revocación

Se reconsiderará ante regresión material no delimitable, necesidad de
debilitar guards, retención real sin política, o nueva evidencia de voz
del owner. La selección no se reabre por latencia ideal ni por
variación semántica segura.

## Trazabilidad

- [Especificación del sistema](../specs/system.md#modelo)
- [Boundary](../specs/xcally-boundary.md#transcript-y-seam-conversacional)
- [Experimento 0009](../experiments/0009-conversational-memory-and-eight-callers.md)
