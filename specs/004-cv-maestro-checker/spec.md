# Spec 004 — CV maestro checker

Estado: implementada

## Contexto y objetivo
El sistema debe diagnosticar huecos de evidencia en el CV maestro antes de generar candidaturas. No debe inventar experiencia, solo detectar y proponer.

## Ubicación inicial
`cv-server`.

## Input
- Markdown (formato principal, versionable y diferenciable)
- PDF
- Texto pegado (compatibilidad)
No se acepta Word en esta versión.

## Output
- checklist de hallazgos
- propuestas marcadas, no aplicadas

## Usuarios / actores
- Usuario que prepara su CV maestro
- cv-server como analizador/validador

## Historias de usuario
- HU-1: Como usuario, quiero un checklist claro de lo que le falta a mi CV maestro.
- HU-2: Como sistema, quiero detectar claims, skills y gaps sin evidencia antes de generar otra candidatura.
- HU-3: Como usuario, quiero propuestas no destructivas.

## Alcance primera versión
Diagnóstico determinista sobre:
- estructura del CV
- experiencias y fechas
- métricas faltantes
- claims vagos
- skills sin evidencia
- gaps temporales
- secciones recuperables

## Requisitos funcionales
- RF-1: CUANDO cv-server recibe el CV maestro, EL SISTEMA extrae experiencia, roles, habilidades, fechas y resultados.
- RF-2: CUANDO una claim no tenga métrica, EL SISTEMA la marca como `needs-evidence`.
- RF-3: CUANDO una habilidad no tenga evidencia, EL SISTEMA la marca como `unsupported-skill`.
- RF-4: CUANDO haya un gap temporal, EL SISTEMA lo marca como `gap`.
- RF-5: SI el CV es demasiado corto o no se puede analizar, ENTONCES EL SISTEMA devuelve `insufficient-content`.
- RF-6: EL SISTEMA no añade, edita ni completa experiencia por su cuenta.
- RF-7: CUANDO detecta un hueco, EL SISTEMA propone una acción recuperable, no una reescritura automática.
- RF-8: EL SISTEMA guarda el análisis como parte estable del CV maestro.
- RF-9: CUANDO se cambia el CV maestro, EL SISTEMA mantiene historial o marca la versión anterior.

## Requisitos no funcionales
- Reglas deterministas primero.
- No logs con datos personales.
- Tests unitarios del checker.
- No inventar experiencia.
- Resultado estable y comparable entre versiones.

## Casos límite
- CV con una sola experiencia
- fechas faltantes
- skills sin métrica
- PDF mal parseado
- claims contradictorios
- CV demasiado detallado pero sin resultados
- idiomas mezclados

## Fuera de alcance
- autocompletado automático
- entrevista automática
- ranking de candidatos
- reescritura final del CV

## Criterios de finalización
- parser de texto/PDF usable
- checker con reglas mínimas
- tests unitarios
- checklist legible
- sin mutación automática del CV maestro

## Dudas abiertas
- [RESUELTO] El checker vive en `cv-server`, con input texto/Markdown/PDF manual; el análisis se versiona por hash + fecha.
- [RESUELTO] El resultado se guarda junto al CV maestro versionado.
- [RESUELTO] `insufficient-content` solo si faltan secciones mínimas o hay menos de una experiencia analizable.
- [RESUELTO] Evidencia = cifra, alcance, timeframe o resultado verificable.
- [RESUELTO] Gap marcado solo si el hueco es mayor de 6 meses y no está explicado.
- [RESUELTO] `hash_cv` único; mismo hash devuelve el análisis existente sin duplicar.
- [RESUELTO] Contrato de salida: `status`, `findings`, `proposals`, `hash_cv`, `version_label`.
- [NECESITA ACLARACIÓN] Si el usuario importa un PDF, ¿se convierte a Markdown primero o se analiza directamente?