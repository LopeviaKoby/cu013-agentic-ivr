# ADR-0013: Una acción mutable de AD por llamada (fail-safe temporal)

- Status: Accepted
- Fecha: 2026-09-29

## Contexto y problema

La correlación RD secuencial sigue sin resolverse: `callId` es candidato
empírico observado con semántica oficial NOT DOCUMENTED, y la E2E aislada de
un solo RESET (`NONE → NONE → SUCESSO` con mismo `callId`) no acredita
operaciones secuenciales. Sin correlación acreditada, permitir dos POST
mutables en la misma llamada arriesga doble efecto en AD sin poder
correlacionar resultados.

## Decisión

**TEMPORARY FAIL-SAFE: `ONE MUTATING AD ACTION PER CALL`.**

- Scope exclusivo: mutaciones AD (`UNLOCK_ACCOUNT`, `RESET_PASSWORD` con
  `action_effect = MUTATES_AD`). No es "una sola acción por llamada".
- Guidance conversacional (`RESET GUIDED/UNDECIDED`, futura VPN/VDI guidance,
  side questions, password repetition, voice recovery, polling, identity
  lookup) queda fuera del presupuesto y puede aparecer antes, entre o después.
- Una vez despachada una mutación (`AD mutation count = 1`), cualquier intento
  posterior de despachar `UNLOCK` o `RESET` produce 0 nuevo POST, 0 nueva
  operación mutable y `TRANSFER` con mensaje determinista seguro.
- Se preservan goal/contexto para explicar el handoff, identity state e
  historial permitido. No se afirma que la acción previa falló, no se pide
  retry ni re-ejecución.
- Diseño: clasificación explícita `action_effect = MUTATES_AD | READ_ONLY |
  GUIDANCE` más función pura cerrada; sin FSM nueva. Sólo `RESET AUTONOMOUS`
  y `UNLOCK` son despachables; `RESET GUIDED/UNDECIDED` es guidance.

## Alternativas consideradas

- Permitir secuenciales con `operation_id` local como correlación: rechazado
  hasta evidencia E2E secuencial, porque RD no acredita consumirlo.
- Bloquear toda segunda gestión (incluida guidance): rechazado por
  sobrerestrictivo; rompería side questions y guía legítima.

## Condición de retiro

Se retira cuando exista correlación de operación externa aceptada con
evidencia secuencial (concurrencia, late results y mapeo `callId`/equivalente
acreditado). Entonces esta ADR pasa a `Superseded` y la SPEC se actualiza.

## Consecuencias

- `test_ad_mutation_fail_safe.py` y `test_voice_hardening.py` pinnean el
  comportamiento; `test_reset_mode_persistence.py` se aisló sin background
  para no mezclar modo con fail-safe.
- El flujo post-UNLOCK RESET AUTONOMOUS queda temporalmente en `TRANSFER`;
  `GUIDED` sigue permitido como guidance.
