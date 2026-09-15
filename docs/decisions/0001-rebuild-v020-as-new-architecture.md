# ADR-0001: Reconstruir CU013 v0.2.0 como una arquitectura nueva

- Status: Accepted
- Fecha: 2026-09-11

## Contexto y problema

El prototipo previo contiene evidencia útil, pero también contratos y complejidad no aceptados. Usarlo como arquitectura target haría permanentes decisiones accidentales.

## Impulsores de la decisión

- Evitar heredar fallos y complejidad del core anterior.
- Separar evidencia reutilizable de autoridad arquitectónica.
- Construir cada incremento contra SPEC y decisions vigentes.

## Opciones consideradas

- Reconstruir v0.2.0 desde una base gobernada por SPEC/ADR.
- Preservar o refactorizar V1 como arquitectura de partida.

## Decisión

Opción elegida: **reconstruir v0.2.0**. El código anterior no pertenece al nuevo core salvo decisión explícita. Git conserva la referencia histórica; no se crea una carpeta legacy.

### Consecuencias

- Positiva: elimina contratos y abstracciones no aceptados del camino crítico.
- Positiva: permite validar propiedades vigentes.
- Negativa: las capacidades previas deberán reconstruirse.
- Negativa: el repositorio puede carecer temporalmente de runtime.

## Confirmación

- No debe existir runtime v0.1 activo.
- Cada artefacto conservado debe trazarse a autoridad vigente.
- El tag de auditoría debe recuperar el baseline pre-limpieza.

## Criterios de revocación

Sólo se reconsiderará si una SPEC posterior demuestra que una pieza previa satisface íntegramente los contratos e invariantes target.

## Trazabilidad

- [Especificación del sistema](../specs/system.md)
- [Especificación de acciones de cuenta](../specs/account-actions.md)
