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
  "voice": "PRESENTATION_FAILED_BEFORE_PLAYBACK"
}
```

- `goal_revision` es un entero; el adapter v1 tolera la representación decimal
  canónica entre comillas. Los campos legacy de email ya no forman parte del
  evento activo: incluirlos produce `422`.
- Efecto en CU013: `next_step=LISTEN`, `operation_state=SUCCEEDED`; el reset
  permanece confirmado, no se re-despacha, no se crea operación nueva y no se
  promete correo.
- Para el caso de playback devuelto, usar `"voice": "PLAYBACK_RETURNED"` con el
  mismo body.

## 2b. Wiring de vocalización por voz (owner)

Flujo manual a configurar en Cally Square (sin inventar bloques no observados):

```text
ACCOUNT_ACTION_STATUS/SUCESSO (reset)
→ XCALLY conserva la contraseña call-local
→ POST /turns con header next-step-v1:
   { "temporary_password": "<secreto>", "transcript": null }
→ CU013 responde next_step=DELIVER_PASSWORD + message
→ XCALLY reproduce el message por TTS
→ POST /integration-events PASSWORD_PRESENTATION_RESULT (playback)
→ next_step=LISTEN; la presentación sigue activa
→ ASR captura la respuesta del llamante
→ POST /turns con { "temporary_password": "<mismo secreto>", "transcript": "<ASR>" }
→ repetición / ancla / aclaración → DELIVER_PASSWORD
→ "ya está" → LISTEN con caller_finished=true
```

- El secreto se reenvía en **cada** turno de presentación; CU013 no lo
  conserva entre turnos.
- No usar el carril legacy para estos turnos: rechaza `temporary_password` con
  `422`.
- Un `temporary_password` fuera de la presentación se ignora y nunca llega al
  modelo.

## 2c. Logs IVR (revisión del owner)

Sin tocar XCALLY desde el repo, el owner debe localizar y retirar tras el E2E
cualquier exposición temporal de:

- `RD_POLL.password`;
- el body RD con secreto;
- el body del request `/turns` (no debe loguearse);
- el `message` de respuesta con la contraseña.

No añadir logs nuevos. Mantener la evidencia existente sólo mientras sea
necesaria para cerrar el slice y, tras validar la vocalización, retirarla y
comprobar con un canary sintético que el secreto deja de aparecer. CU013 no
loguea el secreto, el transcript de presentación ni el message: si aparece en
logs, el origen es XCALLY.

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
