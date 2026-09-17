# ADR-0010: Plan semántico durable separado de autorización, confirmación y verdad de operación externa

- Status: Accepted
- Fecha: 2026-09-16
- Relación: extiende [ADR-0009](0009-use-thin-firestore-session-repository.md); no lo sustituye

## Contexto y problema

El `SessionRecord` del Thin Session Repository ([ADR-0009](0009-use-thin-firestore-session-repository.md)) durabiliza `identity_validated`, `requested_action` y `pending_operation` en un mismo plano semántico. La evidencia del [Experimento 0005](../experiments/0005-xcally-voice-turn-diagnosis.md) y el gap [CNV-001](../gaps.md) demostraron que ese plano único no puede representar la intención de acción expresada antes de validar identidad, ni distinguir lo que el caller quiere de lo que está autorizado, confirmado, despachado o confirmado externamente.

El sistema necesita un plan conversacional durable que sobreviva al turno, sin que esa durabilidad implique autorización de side effects ni veracidad sobre operaciones externas.

## Decisión

El estado durable se organiza en planos semánticos separados, cada uno con su propia transición. Estos planos contienen, sin fusionarlos, los seis estados distintos declarados por la [SPEC del sistema](../specs/system.md): `conversation goal`, `identity authorization`, `verbal confirmation`, `authorized dispatch`, `pending external operation` y `confirmed external result`:

1. **Plan conversacional** — los goals soportados que el caller expresó y su revisión vigente. Responde "qué quiere el caller". Cambia por intención, corrección, cambio o cancelación del caller. Contiene el estado `conversation goal`.
2. **Autorización de identidad** — identidad validada, limitada a la llamada y con TTL absoluto de 30 minutos. Responde "quién es y puede solicitar". Contiene el estado `identity authorization`.
3. **Confirmación y despacho** — dos estados distintos dentro del mismo plano de legalidad del runtime: el challenge de confirmación HITL vigente por operación (`verbal confirmation`) y la decisión determinista del runtime de despachar (`authorized dispatch`). El challenge se invalida por timeout, silencio, ASR insuficiente o revisión del objetivo, y se re-solicita verbalmente; su semántica completa vive en la SPEC. Contiene los estados `verbal confirmation` y `authorized dispatch`.
4. **Verdad de operación externa** — la operación pendiente/activa y su resultado confirmado, incluido el estado `UNKNOWN` tras un despacho de resultado incierto. Responde "qué pasó realmente fuera". Sólo el boundary externo la produce. Contiene los estados `pending external operation` y `confirmed external result`.

Ningún plano ni estado implica a otro.

### Confirmación verbal ≠ autorización de despacho

La confirmación verbal es evidencia semántica del caller; no es la decisión de despacho. La autorización de despacho es una decisión determinista del runtime que se produce después de comprobar, como mínimo:

1. identidad vigente (llamada actual, TTL de 30 minutos no vencido);
2. confirmación/challenge vigente;
3. acción y revisión coincidentes entre goal, challenge y operación;
4. operación soportada;
5. ninguna operación externa activa incompatible;
6. guards de duplicado y legalidad aplicables.

La autorización de despacho, por sí sola, tampoco prueba que el side effect haya sido ejecutado ni que exista resultado: la verdad externa sólo la produce el boundary.

### Guard durable antes de side effect

Un side effect externo sólo se ejecuta después de persistir en Firestore el guard completo correspondiente a la autorización de despacho anterior. Existe como máximo una operación externa activa por conversación.

### Side effects fuera de transacciones reejecutables

Los side effects nunca se ejecutan dentro de una transacción de Firestore que pueda reintentarse: el guard se persiste primero, el side effect se dispara después y el resultado se reconcilia en escrituras posteriores. No existe garantía exactly-once ni se asigna todavía una semántica formal de delivery end-to-end. CU013 persiste un guard durable antes del side effect, mantiene una única operación lógica activa y no re-despacha automáticamente una operación cuyo resultado quedó `UNKNOWN`; el resultado tardío se reconcilia con esa misma operación. La semántica de idempotencia/delivery se cerrará con evidencia XCALLY/AD-TIVIT.

### Incertidumbre tras despacho

Tras un despacho cuyo resultado no es observable de inmediato, la verdad de la operación queda `UNKNOWN`: no se declara éxito ni fracaso al caller, no se repite el side effect automáticamente y un resultado tardío se reconcilia con la operación existente.

## Consecuencias

- Positiva: la intención previa a identidad es representable y retomable (resuelve la base de CNV-001; su implementación sigue pendiente).
- Positiva: la legalidad del runtime se vuelve verificable por transiciones de estado, no por reglas de prompt.
- Positiva: un crash entre guard y side effect deja un estado durable auditable, no una operación fantasma.
- Negativa: el `SessionRecord` y el grafo del turno crecen; las escrituras por turno pueden pasar de una cuando exista guard o resultado alrededor de un side effect.
- Negativa: el contrato AD/TIVIT exacto sigue sin evidencia; los nombres de campos y estados concretos siguen siendo discreción de ingeniería y no forman parte de esta decisión.

## Trazabilidad

- [ADR-0009 — Thin Firestore Session Repository](0009-use-thin-firestore-session-repository.md)
- [Especificación del sistema — Invariantes conversacionales transversales](../specs/system.md)
- [Especificación de acciones de cuenta](../specs/account-actions.md)
- [Experimento 0005 — XCALLY voice turn diagnosis](../experiments/0005-xcally-voice-turn-diagnosis.md)
- [Gaps de implementación](../gaps.md)
