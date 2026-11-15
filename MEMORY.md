# MEMORY.md

## Proyecto
- Servidor Flask de generación de CVs y Drive.

## Tests
- pytest

## Riesgos
- Secretos
- Drive
- Modelos LLM
- migraciones DB

## Spec 004 — CV maestro checker
- Ubicación: `cv-server/specs/004-cv-maestro-checker/`
- Input principal: Markdown; compatibilidad con texto y PDF.
- Checklist determinista + propuestas marcadas, sin auto-completado.
- Versionado por hash y persistencia junto al CV maestro.
- Implementado hasta T8:
  - contrato
  - normalización
  - claims sin métrica
  - skills sin evidencia
  - gaps temporales
  - secciones recuperables
  - PDF a texto
  - persistencia sin duplicados
- Pendiente:
  - T9 endpoint `/cv-master/check`
  - validación RF por RF con bt-reviewer