# ADR-0005: Usar AD/TIVIT mediado por XCALLY para las acciones de cuenta iniciales

- Status: Accepted
- Superseded (entrega de la contraseña temporal): la vía SendMail queda sustituida por la voz efímera de [ADR-0012](0012-use-ephemeral-voice-for-temporary-password.md); la ruta XCALLY/Orchestrator/TIVIT/AD permanece aceptada.
- Fecha: 2026-09-11

## Contexto y problema

Las acciones de cuenta dependen de Orchestrator/TIVIT/AD. La ruta corporativa inicial disponible usa bloques REST de Cally Square, mientras CU013 intercambia órdenes y resultados con XCALLY.

## Impulsores de la decisión

- Respetar la integración corporativa disponible.
- Mantener el boundary inmediato de CU013 en XCALLY.
- No inventar un contrato TIVIT directo.
- Obtener evidencia integrada antes de introducir otro adapter.

## Opciones consideradas

- CU013 → XCALLY/Cally Square → Orchestrator/TIVIT/AD.
- CU013 → adapter desacoplado → Orchestrator/TIVIT/AD.

## Decisión

Opción elegida: **Orchestrator/TIVIT/AD mediado por XCALLY como estrategia experimental inicial**. CU013 no llamará directamente a TIVIT en esta fase. La alternativa desacoplada no se implementa ahora.

La contraseña temporal, cuando exista, será obtenida y enviada por Cally Square mediante SendMail. CU013 recibirá sólo el estado del envío.

### Consecuencias

- Positiva: usa el flujo corporativo disponible.
- Positiva: minimiza la exposición de CU013 a secretos.
- Negativa: añade dependencia de la latencia y semántica de XCALLY.
- Negativa: correlación, retries, códigos y resultados tardíos siguen desconocidos.

## Confirmación

- No debe existir un cliente directo TIVIT.
- La validación integrada debe medir latencia, fiabilidad, retries, correlación y estados literales.
- La contraseña temporal no debe entrar al LLM, Firestore, logs, telemetría o fixtures.

## Criterios de revocación

Reevaluar si evidencia integrada demuestra problemas materiales de latencia, fiabilidad, retries, correlación, códigos de estado o complejidad de Cally Square. Una ruta distinta requiere deliberación y ADR sustituto.

## Trazabilidad

- [Especificación de acciones de cuenta](../specs/account-actions.md#boundary-xcally--orchestrator--tivit)
