# Gaps de implementación

Este artefacto registra sólo incógnitas activas que requieren integración, ejecución o evidencia. La evidencia documental disponible ya fue agotada; estos gaps no presuponen que exista documentación adicional por descubrir.

| ID | Área | Evidencia conocida | Gap | Cómo se resolverá | Estado |
|---|---|---|---|---|---|
| `XC-001` | Contrato CU013↔XCALLY | XML CU013/RD, `DOC_API_RD.pdf` y comportamiento confirmado por el propietario | Contrato target completo entre CU013 y XCALLY | Validación integrada y traslado del contrato aceptado a SPEC y código | Discovered |
| `XC-002` | Correlación | `CALLERID(Name)` aparece en `POST /call/{CALLERID(Name)}` y `GET /consutcall/{CALLERID(Name)}` | Semántica, estabilidad y suficiencia de `CALLERID(Name)` o identificador equivalente | Trazas integradas PII-safe con llamadas concurrentes y resultados tardíos | Discovered |
| `XC-003` | Idempotencia | Existen comandos `reset` y `desbloqueio`, polling y estados externos observados | Manejo de duplicados, idempotencia y late results | Pruebas controladas de repetición/concurrencia y adopción posterior de una política explícita | Discovered |
| `XC-004` | Polling y retries | `GET /consutcall/{CALLERID(Name)}` realiza polling y `NONE` representa estado pendiente en el flujo de referencia | Cadencia, deadline, terminación y retries efectivos | Medición integrada y trazas antes de autorizar retries desde CU013 | Discovered |
| `XC-005` | Resultados y errores | Se observaron body común, rutas y statuses literales en XML/API | Shape completo de responses y errors reales | Captura PII-safe durante integración y traslado a contratos canónicos | Discovered |
| `XC-006` | Respuesta y escalamiento | Existen statuses literales y ruta de handoff/escalamiento XCALLY | Mapeo exacto status → respuesta al caller o escalamiento | Debugging guiado por logs y pruebas con callers; actualizar SPEC al aceptarse | Discovered |
| `MAIL-001` | SendMail | CU013 sólo debe recibir el estado del envío y nunca la contraseña temporal | Resultado exacto de SendMail | Secuencia: persistence spike → AD/TIVIT integration → log-driven debugging/caller tests → SendMail | Deferred |
| `FS-002` | Deadline de I/O de sesión | `reliability.md` exige deadline o timeout explícito en toda I/O externa; el repositorio de sesión depende de los defaults de la SDK de Firestore | Deadline explícito para load/save de Firestore en el camino de voz | Fijarlo al definir el presupuesto de latencia de voz y el boundary HTTP, con evidencia de medición | Discovered |

Ciclo de vida:

```text
discovered → investigated/experimented → resolved → moved to canonical artifact → removed from gaps
```

Al resolver un gap, su resultado pasa a la SPEC, ADR, experimento, runbook o `CONTEXT.md` correspondiente y la fila se elimina. No se conserva aquí una historia extensa; Git mantiene el historial.
