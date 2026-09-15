# ADR-0003: Usar un monolito modular

- Status: Accepted
- Fecha: 2026-09-11

## Contexto y problema

CU013 necesita separar capacidades sin distribuir prematuramente el sistema ni aumentar la superficie operacional.

## Impulsores de la decisión

- Un único deployment inicial.
- Organización por vertical slices.
- Límites explícitos con jerarquía poco profunda.
- Evitar coordinación e infraestructura distribuidas sin evidencia.

## Opciones consideradas

- Monolito modular por capacidades.
- Monolito sin límites internos.
- Arquitectura distribuida.

## Decisión

Opción elegida: **monolito modular por capacidades**. Este ADR no define módulos, clases ni interfaces concretas.

### Consecuencias

- Positiva: mantiene operación y despliegue simples.
- Positiva: permite límites de capacidad claros.
- Negativa: las capacidades comparten ciclo de despliegue.
- Negativa: exige disciplina para conservar límites internos.

## Confirmación

- Debe existir un solo runtime desplegable.
- La estructura futura debe responder a necesidades observables, no a capas preventivas.

## Criterios de revocación

Se reconsiderará si evidencia operacional demuestra que un único deployment impide cumplir requisitos aceptados.

## Trazabilidad

- [Especificación del sistema](../specs/system.md#alcance-y-stack)
