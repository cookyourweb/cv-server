# Plan 003 — BYOK + trial de 3 generaciones

## Objetivo
Permitir una key por usuaria con control estricto y un modo demo de 3 usos gratuitos.

## Bloques
1. modelo y almacenamiento cifrado de key por usuario.
2. trial counter persistente.
3. validación de key al guardarla.
4. integración con generación de CV/carta.
5. fallo controlado si falta o falla la key.
6. panel mínimo para añadir/ver estado de la key.
7. trazabilidad con logs sin secretos.

## Decisiones
- trial: 3 por usuaria
- no reset
- sin fallback global
- key válida desactiva trial

## Criterios
- tests de seguridad
- tests de trial
- flujo completo demo -> key propia