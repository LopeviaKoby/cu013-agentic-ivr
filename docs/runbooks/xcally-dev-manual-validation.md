# Runbook: validación manual XCALLY DEV (continuidad y presentación)

> **Estado:** instrucciones para el owner. **NOT APPLIED BY IMPLEMENTER**. **NOT E2E VALIDATED**.
> El Implementer no accede a XCALLY, no modifica Cally Square, no importa XML,
> no origina llamadas y no simula resultados. Este runbook sólo describe pasos
> manuales y valores propuestos a partir de la evidencia aportada por el owner.

## 1. Guard de contraseña presente (diagnóstico y cambio)

Baseline conocida del owner (sin causa demostrada del `false` observado):

```text
Set_TEMP_PASSWORD_LENGTH
TEMP_PASSWORD_LENGTH = ${LEN(${RD_POLL.password})}
GoToIf_PASSWORD_PRESENT
Number('{TEMP_PASSWORD_LENGTH}') > 0
```

- **Bloque:** `Set_TEMP_PASSWORD_LENGTH` / `GoToIf_PASSWORD_PRESENT`.
- **Parámetro:** `TEMP_PASSWORD_LENGTH`.
- **Valor actual:** `Number('{TEMP_PASSWORD_LENGTH}') > 0`.
- **Valor propuesto (a validar por el owner):** comparar como número sobre el
  placeholder expandido y tolerar comillas/espacios del render de Cally Square,
  por ejemplo `Number(TRIM(REPLACE('{TEMP_PASSWORD_LENGTH}','"',''))) > 0`.
  La sintaxis exacta **no está demostrada**; si no puede demostrarse,
  `OWNER MANUAL XCALLY VALIDATION REQUIRED`.
- **Por qué:** el guard debe aceptar un password sintético presente, rechazar
  vacío, rechazar un literal no expandido (`${RD_POLL.password}` sin resolver) y
  manejar caracteres especiales. No se pidió otro RESET real para diagnosticarlo.
- **Rollback:** restaurar el valor actual.

### Prueba sintética (sin llamada real)

1. Con `RD_POLL.password` sintético no vacío, el guard debe evaluar `true`.
2. Con `RD_POLL.password` vacío, `false`.
3. Con el literal sin expandir, `false`.
4. Con caracteres especiales (comillas, `$`, `%`), `true` si el valor es no vacío.

## 2. Evento de presentación fallida antes del playback

Cuando el playback de la contraseña no llegue a reproducirse, XCALLY debe
reportar el hecho por `/integration-events` (contrato `next-step-v1`) con este
body exacto, sin incluir nunca la contraseña:

```json
{
  "event": "PASSWORD_PRESENTATION_RESULT",
  "operation_id": "<operation_id>",
  "action": "RESET_PASSWORD",
  "goal_revision": <goal_revision>,
  "voice": "PRESENTATION_FAILED_BEFORE_PLAYBACK",
  "email_requested": 0,
  "email_acceptance": "UNKNOWN",
  "email_delivery": "UNKNOWN"
}
```

- `goal_revision` y `email_requested` son enteros; el adapter v1 tolera la
  representación decimal canónica entre comillas.
- Efecto en CU013: `next_step=LISTEN`, `operation_state=SUCCEEDED`; el reset
  permanece confirmado, no se re-despacha, no se crea operación nueva y no se
  promete correo.
- Para el caso de playback devuelto, usar `"voice": "PLAYBACK_RETURNED"` con el
  mismo body.

## 3. Limpieza y continuidad

- Tras la presentación (retornada o fallida), limpiar
  `RD_POLL.password`, `TEMP_PASSWORD_LENGTH` y el poll body con contraseña
  cuando ya no se necesiten.
- **No** borrar antes de `LISTEN`: `DOCUMENTO`, `FECHA_INGRESO` e
  `IDENTITY_EMAIL` pueden habilitar una segunda acción autorizada en la misma
  llamada.
- Exigir la limpieza de esos datos al final en `COMPLETE` y en `TRANSFER`.
- Retención permitida sólo `call-local`; nunca backend, LLM ni Firestore.

## 4. Validación sintética end-to-end sugerida (owner)

1. Desbloqueo: `COLLECT_IDENTITY → VALID → confirmación → EXECUTE_ACTION →`
   `SUCESSO → LISTEN`. El agente debe informar el éxito y preguntar si necesita
   algo más; sólo un cierre explícito del caller emite `COMPLETE`.
2. Reset: `EXECUTE_ACTION → SUCESSO → DELIVER_PASSWORD`; con playback devuelto o
   fallido, `PASSWORD_PRESENTATION_RESULT → LISTEN`, sin afirmar entrega de
   correo.
3. Off-topic con goal pendiente: una pregunta lateral responde y deja
   `LISTEN` sin forzar identidad.
4. Tercer `INVALID` consecutivo imputable al caller: `TRANSFER`.
