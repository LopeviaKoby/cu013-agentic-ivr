# ADR-0012: Entregar la contraseña temporal por voz efímera

- Status: Accepted
- Fecha: 2026-09-25

## Contexto y problema

Tras un `RESET_PASSWORD` confirmado, XCALLY obtiene la contraseña temporal en su
ámbito local de llamada. El slice de vocalización exige que el agente pueda
dictarla, repetirla completa o desde un ancla, continuar desde un fragmento
repetido por el llamante, aclarar símbolos y mayúsculas/minúsculas, permanecer
en el contexto de presentación hasta que el llamante indique que terminó y
volver a la conversación normal, sin redespacho.

El correo (SendMail) quedó `Deferred` y no demuestra entrega; SMS nunca fue una
vía autorizada. Se necesita una decisión explícita sobre la vía de entrega y
sobre qué puede atravesar el backend.

## Impulsores de la decisión

- La voz es la vía disponible y verificable en la llamada actual.
- La contraseña es un secreto efímero de la llamada; XCALLY es su holder
  call-local.
- El modelo debe poder verbalizar el secreto exacto sin convertirlo en estado
  durable.
- Una sola llamada al modelo por turno, sin motor de spelling productivo.
- No introducir vault, Redis, DB temporal, caché ni cursor sensible persistido.

## Opciones consideradas

- Mantener SendMail como vía de entrega principal.
- Entregar por SMS mediante un proveedor o gateway nuevo.
- Entregar por voz efímera: XCALLY reenvía el secreto en cada turno de
  presentación y el backend lo usa sólo durante ese request.

## Decisión

Opción elegida: **voz efímera**.

- La vocalización de la contraseña temporal es la vía de entrega actual.
- SMS queda **DEFERRED**: no se introduce proveedor, gateway, webhook ni cola.
- Email/SendMail queda **superseded** como vía de entrega de la contraseña
  (ver la marca de supersesión en ADR-0005); los campos de email del plano
  durable se conservan sólo para lectura y migración y no participan en
  ninguna decisión ni evento nuevo.
- La contraseña temporal puede transitar efímeramente por XCALLY call-local,
  el request `/turns`, los objetos transitorios del backend, el `GraphState`
  del turno, la entrada y salida de Gemini, el mensaje HTTP y el TTS de
  XCALLY. No puede persistirse en Firestore, `SessionRecord`, memoria durable o
  reciente, logs, métricas, artefactos de evaluación, fixtures, documentos,
  informes, Git ni payloads de error.
- No existe caché de contraseña entre turnos: cada turno de presentación
  reenvía el secreto y el backend lo mantiene sólo en RAM durante ese request.
- La primera vocalización no exige un `PasswordPresentation` previo: es
  elegible cuando el runtime sabe, por estado durable no sensible, que el reset
  está confirmado y la presentación no ha terminado.
- La señal de fin (`caller_finished`) proviene de la decisión semántica del
  modelo y se persiste como un booleano no sensible.
- Se mantiene una sola llamada a Gemini por turno conversacional normal.

### Consecuencias

- Positiva: la entrega ocurre en la misma llamada, sin infraestructura nueva y
  sin afirmar una entrega por correo que no está demostrada.
- Positiva: el secreto permanece efímero y el runtime conserva legalidad,
  verdad e idempotencia.
- Negativa/riesgo: los logs IVR temporales de XCALLY pueden exponer el secreto
  hasta cerrar el slice; su retirada es una tarea manual del owner.
- Negativa/riesgo: el transcript del llamante puede repetir el secreto durante
  la presentación, por lo que la memoria reciente se desactiva en esos turnos.
