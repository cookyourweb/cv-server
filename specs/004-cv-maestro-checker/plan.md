# Plan 004 — CV maestro checker

## Objetivo
Implementar el diagnóstico del CV maestro en dos pasos:
1. análisis estructural y documental;
2. checklist de hallazgos y propuestas recuperables.

## Archivos y responsabilidades
- `cv-server/extraccion.py`
  - Parsear texto/PDF y normalizar a estructura.
- `cv-server/checker.py` (nuevo)
  - Orquestar las reglas del diagnóstico.
- `cv-server/checks/
  - reglas deterministas: fechas, claims, skills, métricas, huecos.
- `cv-server/rutas_cv.py` o modulo equivalente
  - endpoint de preview/checker.
- `cv-server/storage.py` o tabla equivalente
  - guardar el análisis estable.
- `tests/test_cv_checker.py`
  - casos de documentación y estructura.

## Funciones puras
- `normalizar_cv(markdown_o_texto)`
- `extraer_experiencias(bloques)`
- `normalizar_fechas(texto)`
- `detectar_claims_sin_metrica(texto)`
- `detectar_skills_sin_evidencia(habilidades, experiencia)`
- `detectar_gaps_temporales(fechas)`
- `normalizar_pdf_a_texto(bytes)`
- `persistir_analisis(hash_cv, analisis)`
- `obtener_analisis_por_hash(hash_cv)`

## Reglas
- entrada principal: Markdown
- fallback: texto pegado
- fallback: PDF normalizado a texto
- cada regla es determinista
- no inventar experiencia
- propuestas solo como texto recuperable

## Algoritmo
1. Recibir documento.
2. Normalizar a Markdown o texto plano.
3. Extraer secciones:
   - perfil
   - experiencia
   - habilidades
   - educación
   - logros
4. Extraer fechas y normalizar a intervalos.
5. Detectar:
   - skills sin evidencia
   - claims sin métrica
   - gaps
   - secciones faltantes
6. Construir checklist.
7. Guardar análisis como documento versionado por hash.
8. Devolver resumen + lista de propuestas.

## Interfaz
- Entrada: `POST /cv-master/check` (propuesta).
- Salida: JSON con `status`, `findings`, `proposals`, `hash_cv`, `version_label`.
- `status`: `ok`, `warning`, `insufficient-content`.

Contrato de salida cerrado:
- `findings`: hallazgos normalizados, no texto libre.
- `proposals`: propuestas recuperables, no aplicadas.
- `hash_cv`: identificador estable del documento analizado.
- `version_label`: fecha o etiqueta manual opcional.

## Decisiones y alternativas
- Markdown preferido sobre PDF porque se puede diffear.
- Reglas deterministas antes que LLM para no inventar.
- PDF se normaliza a texto, no se interpreta visualmente.
- LLM queda como futuro asistente de propuestas, no como verdad.

## Estrategia de tests
- tests de fecha local
- tests de claims sin métrica
- tests de skills sin evidencia
- tests de gaps
- tests de importación PDF simulada
- tests de persistencia por hash

## Qué RF cubre cada parte
- RF-1, RF-2: extracción y validación
- RF-3: skills sin evidencia
- RF-4: gaps
- RF-5: insufficient-content
- RF-6: no mutation del CV
- RF-7: propuestas recuperables
- RF-8: persistencia
- RF-9: historial/editor de hash