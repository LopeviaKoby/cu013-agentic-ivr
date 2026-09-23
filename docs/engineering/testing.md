# Estándar de testing

Este documento define niveles y reglas de prueba subordinados a la [SPEC del sistema](../specs/system.md), la [SPEC de acciones de cuenta](../specs/account-actions.md) y los ADR con `Status: Accepted`. No crea contratos de producto.

## Tres capas separadas

Las tres capas responden preguntas distintas y ninguna sustituye a otra:

| Capa | Pregunta | Herramienta | CI determinista |
|---|---|---|---|
| 1. Tests deterministas de código e invariantes | ¿El código obedece las reglas? | `pytest` (unit, integration, legalidad del runtime), Ruff y MyPy | Sí |
| 2. Gate pareado de evaluación conversacional | ¿Cómo se comporta el agente y mejoró frente al baseline aceptado? | `conversation-evaluation`: `evals/conversation_eval.py` + `evals/conversation_compare.py` sobre `evals/conversation/cases.yaml` | No (modelo real, ADC, manual) |
| 3. Evidencia de llamada XCALLY real | ¿Qué cambia al introducir el canal de voz real (ASR/TTS/XCALLY)? | `xcally-call-evidence-analysis` sobre una llamada ya ejecutada por el owner | No (evidencia del owner) |

- La capa 1 responde si el código obedece reglas; no dice nada sobre calidad conversacional.
- La capa 2 responde cómo se comporta el agente y si mejoró; no sustituye ASR/TTS ni una llamada real y no acepta wording exacto como oráculo.
- La capa 3 responde qué cambia con el canal de voz real; requiere que el owner ya haya ejecutado la llamada y aportado su evidencia. No coloca llamadas, no escucha en segundo plano ni captura logs automáticamente.

## Escalera basada en riesgo

La validación escala con el riesgo del cambio, no con la ceremonia:

1. **Determinista (siempre).** Tests unitarios, de contrato y de máquina de estados, modelo/stub, evaluadores de código deterministas y replay/regresión offline con artefactos sanitizados existentes. Cero llamadas al modelo. Un gate determinista rojo detiene la iteración.
2. **Smoke real focalizado (cuando el cambio toca lenguaje o una llamada de modelo concreta y el nivel 1 está verde).** Un conjunto pequeño de casos core, una repetición por caso, sin LLM judge, con revisión manual y evaluador de código. Presupuesto explícito y acotado; un fallo semántico detiene y se reporta.
3. **Evaluación pareada completa (sólo cuando cambia la semántica de decisión).** Obligatoria si el cambio altera modelo, decision schema, tool choice, routing semántico, autorización, memory semantics o system policy amplia, y para el gate pre-voz de un candidato conversacional.

Un cambio verificable por assertions deterministas y corpus offline (por ejemplo el wording aceptado de fecha de ingreso) no requiere por sí solo la escalera completa. Un cambio de semántica de decisión no se acepta con smoke.

## Metodología eval-driven

Todo cambio conversacional sigue este ciclo:

1. **real failure**: un fallo observado (voice DEV, eval o evidencia de caller);
2. **sanitize evidence**: eliminar PII/DTMF y registrar el caso sin datos personales;
3. **reproduce**: reproducir el fallo contra el modelo real con el caso sanitizado;
4. **add semantic eval**: añadir el caso al corpus con paráfrasis y controles opuestos;
5. **identify general missing property**: determinar la propiedad general ausente o incorrecta (no el wording);
6. **change smallest correct layer**: corregir la capa mínima correcta (prompt, policy, schema o runtime);
7. **deterministic tests**: cubrir la propiedad con tests deterministas;
8. **real-model validation**: aplicar la escalera basada en riesgo — smoke focalizado para cambios de lenguaje acotados o evaluación pareada completa contra el baseline aceptado cuando cambia la semántica de decisión — con el procedimiento `conversation-evaluation`;
9. **DEV voice validation**: solicitar autorización explícita de deploy y, tras la llamada del owner, analizar su evidencia con `xcally-call-evidence-analysis`;
10. **accept/reject**: aceptar o rechazar con evidencia.

**Regla obligatoria:** un caso individual se añade primero al corpus. Prompt, policy, estado o schema sólo cambian si la evidencia demuestra una propiedad general ausente o incorrecta. Está prohibido el patch-driven prompting sobre utterances individuales.

No se exige wording exacto salvo que exista un contrato textual real. Las assertions semánticas evalúan rutas, estados y propiedades observables, no frases.

## Corpus, oráculos y baseline

- Cada caso declara `scenario_kind`: `independent_trial` (cada paráfrasis parte del mismo estado inicial fresco, sin fugas entre paráfrasis y con repeticiones independientes) o `sequence` (el estado se arrastra turno a turno y se pueden afirmar checkpoints por turno).
- Una clave presente en `expected` afirma un valor, incluido `null` como ausencia esperada; una clave ausente se reporta `NOT ORACLED` y nunca se confunde con un acierto.
- `state_delta` es metadata descriptiva; `allowed_claims` y `forbidden_claims` son evidencia para la revisión manual de calidad hablada, no oráculos automáticos. La verdad de claims estructurados la impone el guard del runtime y se reporta como evidencia.
- El baseline conversacional activo se deriva de `config.yaml` y
  `app/conversation`: Gemini 3.5 Flash-Lite, Vertex AI `global`, `MINIMAL`,
  clasificación procedimental obligatoria y memoria reciente de tres pares.
  El harness obtiene la identidad desde esas fuentes reales y calcula su
  fingerprint en runtime sobre prompt, schemas, renderer, procedimiento,
  runtime, lock, corpus, runner, comparador y gate crítico. No existe
  manifiesto JSON canónico paralelo; la historia vive en la ADR de
  selección, el Experimento 0009 y Git.
- Las repeticiones son 3 válidas por trial o secuencia; el warmup es fijo, idéntico para ambos lados y se reporta aparte. `INFRA` se clasifica a nivel de repetición; el output estructurado inválido es fallo de modelo, nunca `INFRA`. Un rerun focalizado no borra el resultado original: el comparador registra la fusión y conserva los artefactos originales.
- Los artefactos de ejecución viven en `evals/results/` (ignorados por Git) y no contienen transcripciones, mensajes, DTMF crudo, documento, fecha de ingreso ni secretos; los tokens ausentes se registran como missing, nunca como 0. Son outputs generados de máquina, no documentación canónica.

## Gate pre-voz

Antes de solicitar autorización de deploy, el procedimiento exige todo lo siguiente:

- gates deterministas en verde;
- repeticiones pareadas real-model completas;
- cero violaciones críticas nuevas y ningún problema nuevo de PII/seguridad;
- familias objetivo y controles revisados;
- regresiones no relacionadas resueltas o aceptadas explícitamente por el owner;
- `INFRA` separado;
- revisión manual de calidad hablada completada;
- latencia y tokens comparados contra el baseline;
- identidades de baseline, candidato, corpus y evaluador registradas;
- debilidades residuales conocidas aceptadas explícitamente por el owner.

Sólo entonces: autorización explícita de deploy → deploy del candidato exacto a DEV controlado → el owner ejecuta la llamada → `xcally-call-evidence-analysis`.

## Reglas

- Usar fixtures sintéticos y PII-safe. El corpus de evaluación no contiene PII, DTMF crudo ni transcripciones reales identificables.
- Los tests deterministas no dependen de Gemini, XCALLY ni AD/TIVIT reales.
- No usar assertions de strings literales para lenguaje natural salvo que exista un contrato textual exacto.
- Los real-model evals usan assertions semánticas y métricas, se ejecutan fuera del CI determinista y evalúan varias paráfrasis por propiedad con controles positivos y negativos; una única utterance repetida no es evidencia de generalización.
- No se añade un LLM judge: la revisión de calidad hablada es manual, por caso/turno y con ratings `MEETS` / `CONCERN` / `NOT EVIDENCED`.
- Voice DEV es un gate integrado de producto; no sustituye unit ni integration tests.
- No fijar todavía un coverage threshold ni un SLO de latencia: el comparador reporta deltas y varianza del proveedor, sin umbral numérico inventado.
- El build del `Dockerfile` es un gate determinista cuando una iteración modifica el contenedor, las dependencias o el runtime empaquetado, o prepara una release/deploy; no se exige en cambios puramente documentales.

CU013 prevé `asyncio` como único modelo asíncrono. Por ello pytest-asyncio usa `asyncio_mode = "auto"` en [`pyproject.toml`](../../pyproject.toml). Antes de cambiar esa configuración se debe verificar compatibilidad con la versión efectiva instalada.

No se crean directorios `app/` o `tests/` vacíos para satisfacer herramientas o gates.

## Referencias oficiales

- [pytest configuration](https://docs.pytest.org/en/stable/reference/customize.html)
- [pytest-asyncio configuration](https://pytest-asyncio.readthedocs.io/en/stable/reference/configuration.html)
