# ADR-001: Migración incremental del cv-server a FastAPI + Pydantic

**Estado:** Aceptado · 22 jul 2026
**Ámbito:** `cv-server` (repo `github.com/cookyourweb/cv-server`, rama `develop`)

> **Para quien retome esto (persona o IA):** este documento fija las decisiones de
> arquitectura de la migración. NO las re-derives ni las re-discutas de memoria: si vas a
> tocar un endpoint, léelo entero primero y respetá el patrón "core puro + wrapper HTTP".

---

## Contexto

- `cv-server` es hoy un monolito Flask (`cv_server_railway.py`, ~1500 líneas) con la lógica
  de negocio y la capa HTTP **mezcladas** en las rutas. Ejemplo: `generar_cv()` mezcla el
  parsing del request, la orquestación de Drive/Notion/LLM y el armado de la respuesta en la
  misma función.
- El módulo lee variables de entorno **requeridas al importarse** (`GROQ_API_KEY`,
  `NOTION_TOKEN`, `GOOGLE_CLIENT_ID/SECRET/REFRESH_TOKEN`). Eso dificulta testear: importar el
  módulo sin esas env vars revienta.
- Objetivos de la migración:
  1. Contratos tipados y validación de entrada/salida (guardrails para las pipelines de IA).
  2. Separar lógica de transporte: arquitectura limpia y testeable.
  3. Práctica REAL de FastAPI para el perfil AI Engineer de Vero (experiencia grounded, no
     inventada: se pone en el CV porque se hizo de verdad).

## Decisiones

1. **Coexistencia, no big-bang.** FastAPI se añade EN PARALELO en `api.py`; Flask
   (`cv_server_railway.py`) sigue vivo y sirviendo. Se migra endpoint por endpoint.
2. **Separar lógica del HTTP.** Se extrae el núcleo de cada endpoint a una función de
   orquestación (ej. `generar_cv_core(email, empresa, puesto, descripcion, idioma) -> dict`).
   La ruta Flask y la ruta FastAPI son wrappers finos que llaman al MISMO core. La extracción
   es behavior-preserving: la salida no cambia.
3. **Errores como excepción tipada.** El core lanza `CVError(status, message)`; cada capa HTTP
   la mapea a su formato (Flask: `jsonify` + status; FastAPI: `HTTPException`).
4. **Contratos Pydantic.** Request y response tipados (`GenerarCVRequest`, `GenerarCVResponse`).
   Es la materialización en código del posicionamiento "JSON structured outputs + validation +
   guardrails".
5. **TDD.** Test primero. Por el config-at-import, los tests setean env dummy y mockean el
   core / los helpers para no tocar Drive/Notion/LLM reales.

## Consecuencias

- **A favor:** lógica testeable y reutilizable; documentación OpenAPI automática que da FastAPI;
  base para ir migrando el resto; refuerza el perfil AI con evidencia real.
- **Coste:** temporalmente dos frameworks en el repo (Flask + FastAPI) hasta completar la
  migración; hace falta `uvicorn` para servir FastAPI.
- **Riesgo controlado:** la extracción del core está cubierta por tests y Flask queda como red
  de seguridad hasta que FastAPI cubra el endpoint en verde.

## Alternativas descartadas

- **Migración big-bang** (reescribir todo de una): riesgo alto sobre un servicio en producción.
- **Duplicar la lógica del endpoint en FastAPI:** duplicaría el prompt de ~290 líneas y con el
  tiempo divergiría. Se descarta a favor de extraer el core y compartirlo.

## Estado de implementación

- **Slice 1 (en curso):** `/generar-cv` → `generar_cv_core` + `api.py` (FastAPI/Pydantic) + tests.
- **Siguientes:** `/generar-carta`, `/usuarios`, `/crear-oferta`, etc., mismo patrón.

## Ejemplo de la API (para entenderla rápido)

Servir FastAPI en local: `uvicorn api:app --reload` (docs interactivas en `/docs`).

**Request OK** (`POST /generar-cv`):

```bash
curl -X POST http://localhost:8000/generar-cv \
  -H "Content-Type: application/json" \
  -d '{
    "email": "hello.cookyourweb@gmail.com",
    "empresa": "Hostaway",
    "puesto": "Senior Frontend Engineer",
    "descripcion": "React, TypeScript, design systems, testing",
    "idioma": "en"
  }'
```

**Respuesta 200** (validada contra `GenerarCVResponse`):

```json
{
  "ok": true,
  "link": "https://drive.google.com/file/d/1a-Bnd.../view",
  "modelo_usado": "llama-3.3-70b-versatile",
  "archivo": "cv-veronica-serna-perez-senior-frontend-engineer-2026.docx",
  "email": "hello.cookyourweb@gmail.com",
  "cv_master_usado": true,
  "idioma": "en",
  "cv_master_url": "https://docs.google.com/document/d/1XzZm1.../edit"
}
```

**Falta un campo requerido** (ej. sin `empresa`) → **422 automático**, sin que corra nada del
core. Ese es el guardrail de Pydantic en acción:

```json
{
  "detail": [
    {"type": "missing", "loc": ["body", "empresa"], "msg": "Field required"}
  ]
}
```

Es el contrato tipado: lo que no cumple la forma, no entra; lo que sale, sale con la forma exacta.

## Hallazgos relacionados (no bloquean esta migración)

- **DECISIÓN de precio (no es bug):** el CV se genera con **Groq (`llama-3.3-70b`) por ahora**,
  a propósito, por coste. `CV_MODEL=claude-haiku-4-5` está declarado, pero al no haber
  `CLAUDE_API_KEY` seteada, `call_llm_calidad` cae al fallback Groq. Claude daría mejor calidad,
  pero se difiere por precio (Vero, 22 jul). NO "arreglar" esto sin decisión explícita de Vero.
  Nota de coste: Claude Haiku 4.5 sale ~$0,02/CV según cabecera del código, o sea la diferencia
  es pequeña; si algún día la calidad del CV pesa más, el salto es barato.
- **Etiqueta `modelo_usado`:** la respuesta devuelve `GROQ_MODEL` hardcodeado (~L1359). HOY es
  correcto porque Groq es el que corre. Solo mentiría si se activara Claude y siguiera diciendo
  Groq. Menor; al migrar conviene que `generar_cv_core` devuelva el modelo REAL usado.

## Reglas para futuras sesiones (IA incluida)

- No volver a mezclar lógica y HTTP en las rutas. Todo endpoint nuevo o migrado: **core puro +
  wrapper HTTP**.
- No romper Flask hasta que FastAPI cubra ese endpoint con **tests verdes**.
- Tecnología al CV solo si es experiencia real: esta migración cuenta como práctica FastAPI
  grounded (se hizo de verdad).
