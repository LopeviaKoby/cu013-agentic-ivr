# ADR-0006: Usar GitHub Actions para CI/CD

- Status: Accepted
- Fecha: 2026-09-11

## Contexto y problema

El repositorio necesita una plataforma CI/CD canónica. Cloud Build pertenecía al prototipo y no define la reconstrucción.

## Impulsores de la decisión

- Decisión explícita del propietario.
- Una sola plataforma CI/CD.
- Separar la futura identidad deployer del runtime.

## Opciones consideradas

- GitHub Actions.
- Conservar Cloud Build.

## Decisión

Opción elegida: **GitHub Actions**. Workflows, WIF, triggers, environments y promoción se decidirán en un incremento posterior.

### Consecuencias

- Positiva: elimina ambigüedad sobre la plataforma futura.
- Negativa: CI/CD permanece ausente hasta su incremento autorizado.

## Confirmación

- La automatización futura debe residir en GitHub Actions.
- Cloud Build no debe reintroducirse como plataforma paralela sin un ADR nuevo.

## Criterios de revocación

Sólo se reconsiderará mediante instrucción explícita respaldada por requisitos operacionales o corporativos nuevos.

## Trazabilidad

- [Especificación del sistema](../specs/system.md#entrega-y-validación)
