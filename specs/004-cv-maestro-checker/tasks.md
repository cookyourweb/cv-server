# Tasks 004 — CV maestro checker

- [x] T1. Definir contrato de entrada/salida y status. RF-8, RF-9
  - Hecho cuando: schema documentado y test smoke que valide claves esperadas.

- [x] T2. Normalizar texto Markdown a estructura base. RF-1, RF-5
  - Hecho cuando: parser devuelve experiencia, fechas, skills y estado válido.

- [x] T3. Detectar claims sin métrica. RF-2
  - Hecho cuando: tests cubren 3 casos positivos y 2 negativos.

- [x] T4. Detectar skills sin evidencia. RF-3
  - Hecho cuando: tests cubren skill soportada y no soportada.

- [x] T5. Detectar gaps temporales. RF-4
  - Hecho cuando: tests cubren cero, uno y varios gaps.

- [x] T6. Marcar secciones recuperables. RF-7
  - Hecho cuando: salida incluye lista de secciones faltantes.

- [x] T7. Gestionar PDF a texto. RF-1
  - Hecho cuando: función produce texto normalizado con test de error controlado.

- [x] T8. Persistir análisis por hash y evitar duplicados. RF-8
  - Hecho cuando: misma entrada repite; versión distinta crea nueva entrada; hash repetido no duplica.

- [x] T9. Endpoint de preview/checker. RF-1
  - Hecho cuando: respuesta incluye status, findings, proposals, hash.

- [x] T10. Sincronizar MEMORY.md y docs. RF-9
  - Hecho cuando: MEMORY.md resume decisión y pendientes.