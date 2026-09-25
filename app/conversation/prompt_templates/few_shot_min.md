# Ejemplos de decisión

Formato fijo de cada ejemplo: estado mínimo, turno del llamante y la semántica
estructurada esperada. No copies estas frases; aplica el criterio.

<ejemplo>
Estado: objetivo RESET_PASSWORD, paso actual sin completar.
Asistente anterior: "¿Pudiste abrir el portal de información de seguridad?"
Llamante: "sí, ya lo abrí"
Decisión: procedure_observation ADVANCE (respuesta inequívoca a la pregunta
directa de completitud); conserva el objetivo.
</ejemplo>

<ejemplo>
Estado: objetivo RESET_PASSWORD, paso actual sin completar.
Llamante: "bueno, sigamos con el cambio"
Decisión: procedure_observation NONE (una continuación no confirma que el paso
se completó); responde el paso actual sin avanzar.
</ejemplo>

<ejemplo>
Estado: objetivo RESET_PASSWORD, paso actual sin completar.
Llamante: "¿dónde dijiste que debía entrar?"
Decisión: procedure_observation NONE (pregunta lateral: no completa el paso ni
lo reinicia); repite la indicación del paso actual.
</ejemplo>

<ejemplo>
Estado: objetivo RESET_PASSWORD pendiente, identidad sin validar.
Llamante: "quiero restablecer mi contraseña"
Decisión: goal REQUEST + goal_focus PROGRESS (avanza el objetivo soportado); el
runtime pedirá la captura de identidad.
</ejemplo>

<ejemplo>
Estado: objetivo UNLOCK_ACCOUNT pendiente, identidad sin validar.
Llamante: "¿qué clima hace hoy?"
Decisión: goal_focus SIDE (off-topic): responde breve, no crea objetivo, no
fuerza identidad ni acción y preserva el objetivo.
</ejemplo>

<ejemplo>
Estado: operación UNLOCK_ACCOUNT confirmada, sin objetivo activo.
Llamante: "no, nada más, gracias"
Decisión: COMPLETE (cierre conversacional); no repite ni reactiva la operación.
</ejemplo>
