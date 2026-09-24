# Ejemplos de decisión

Formato fijo de cada ejemplo: estado mínimo, turno del llamante y la semántica
estructurada esperada. No copies estas frases; aplica el criterio.

<ejemplo>
Estado: objetivo RESET_PASSWORD, paso actual sin completar.
Llamante: "bueno, sigamos con el cambio"
Decisión: procedure_observation NONE (una continuación no confirma que el paso
se completó); responde el paso actual sin avanzar.
</ejemplo>

<ejemplo>
Estado: sin objetivo (el llamante canceló antes).
Llamante: "de nuevo quiero restablecer mi contraseña"
Decisión: goal REQUEST/RESET_PASSWORD (cancelar no prohíbe pedirlo de nuevo);
el runtime aplica las reglas normales de objetivo.
</ejemplo>