# Plan: extracción de core puro para 7 endpoints (migración Flask→FastAPI)

ADR-001: core puro (sin Flask/FastAPI) + wrapper HTTP fino + `CVError` + Pydantic.
Behavior-preserving: no se cambia lógica de negocio, solo se mueve.

## Módulos nuevos

- `alta_core.py` — cores de subir_cv, listar_cvs, borrar_cv, fijar_extraccion, extraer_perfil.
- `encaje_core.py` — cores de encaje_de_oferta y encajes (batch).
- `errores.py` — `CVError` movido aquí (sin deps); `server.py` lo reexporta para compat.
- Pydantic compartidos: `AjusteDeExtraccion` y modelos de encaje en los módulos core (importados por Flask y FastAPI).

## Contrato de error (paridad)

`CVError(status, message, extra={})`. Los wrappers:
- Flask: `jsonify({"ok": False, "error": message, **extra}), status`.
- FastAPI: exception handler global que renderiza el mismo cuerpo (no `{"detail":...}`).

## Endpoints

### 1. POST /cv (subir_cv)
Core: `subir_cv_core(usuario_id, contenido: bytes) -> dict`
- Abre transacción, crea `RepositorioDeUsuaria`.
- Si no hay consentimiento `almacenar_cv` → `CVError(403, "consentimiento necesario")`.
- `leer_cv(contenido)` → `ErrorDeLectura` → `CVError(status, msg, extra={"motivo": motivo})` (mapa `_RECHAZOS_DE_CV`).
- `cifrar(...)` → `ErrorDeCifrado` → log + `CVError(503, "servicio no disponible")`.
- `repo.guardar_cv(...)`.
- Devuelve `{"idioma":..., "formato":..., "caracteres":...}`.
Deps: base_de_datos, RepositorioDeUsuaria, leer_cv, cifrar, privacidad, logger.
Wrapper HTTP: extrae `request.files["archivo"]` (422 si falta), lee bytes con límite `LIMITE_BYTES+1`, auth, status 201. Flask conserva errorhandler 413.

### 2. GET /cv (listar_cvs)
Core: `listar_cvs_core(usuario_id) -> list[dict]`
- Si no configurada o usuario_id None → `CVError(503, "servicio no disponible")`.
- Transacción + `repo.listar_cvs()`.
Wrapper: auth, 200.

### 3. DELETE /cv/<idioma>
Core: `borrar_cv_core(usuario_id, idioma: str) -> None`
- Si `idioma not in IDIOMAS` o `not repo.borrar_cv(idioma)` → `CVError(404, "no encontrado")`.
Wrapper: auth, 204 vacío.

### 4. PUT /ajustes/extraccion
Core: `fijar_extraccion_core(activa: bool) -> dict`
- Si no configurada → `CVError(503,...)`.
- Transacción + `extraccion.fijar_interruptor(conexion, activa)`.
- DB error → log + `CVError(503,...)`.
- Devuelve `{"activa": activa}`.
Wrapper (machine key): valida body Pydantic, auth machine, 200.

### 5. POST /extraccion
Core: `extraer_perfil_core(usuario_id) -> dict`
- Preserva orden: kill switch → consentimiento → CV (sin transacción abierta durante LLM).
- Transacciones internas exactamente como `_extraer`.
- Manual states devueltos como dict `{"estado":"manual","motivo":...}` (200).
- Propuesta: `{"estado":"propuesta","propuestas":...}` (200).
- Errores → `CVError`.
- Reserva completada/fallida en `finally`.
Deps: base_de_datos, extraccion, llm, privacidad, propuestas, cifrado, repositorio, logger.

### 6. GET /ofertas/<id>/encaje
Core: `encaje_de_oferta_core(usuario_id, email, oferta_id) -> dict`
- Mueve `_usuario_notion`, `_ofertas_propias`, `_evaluar`, `_perfil_de` a `encaje_core` parametrizados por `usuario_id`/`email` (sin `g`).
- Si no propias → `CVError(404, "no encontrado")`.
- Devuelve el match dict.
Wrapper: auth, 200.

### 7. POST /encajes (batch)
Core: `encajes_batch_core(usuario_id, email, ids: list[str]) -> dict`
- Valida ids (max 50, str, len≤64) → `CVError(422, "datos no validos", extra={"campos":["ids"]})`.
- `_ofertas_propias(ids)`; si vacío → `{}`.
- `_evaluar(...)`; construye salida keyed por id original con dedup por id normalizado.
- Devuelve dict (posiblemente vacío).

## Código compartido Flask/FastAPI

- Cores (un solo lugar).
- Modelos Pydantic (AjusteDeExtraccion, ClaveApiEntrada ya en repositorio/server).
- CVError + exception handler.
- Helpers puros ya existentes (leer_cv, cifrar, match.evaluar, fuente_master.resolver_master, extraccion.*).

## Tests de paridad

Por cada endpoint:
- Characterization tests sobre Flask (ya existen en test_rutas_alta.py / test_rutas_encaje.py / test_ruta_extraccion.py) deben seguir pasando sin cambios.
- Nuevos tests FastAPI en test_api_alta.py / test_api_encaje.py que repliquen los casos de éxito y error y comparen status + cuerpo.
- Mocks de notion/llm/drive/cuota para no tocar servicios reales; verificar conteos de llamadas y side effects (ledger reserva completada/fallida).
- Cross-user isolation y no-oracle 404 (encaje).
- Upload: tipos, tamaño, cifrado round-trip.
- Performance baseline antes/después.

## Orden de implementación

1. Prep: `errores.py` + exception handler FastAPI.
2. listar_cvs (bajo riesgo).
3. borrar_cv.
4. fijar_extraccion.
5. subir_cv.
6. encaje single + batch.
7. extraer_perfil (alto riesgo; preservar transacción/modelo).
8. Parity tests + limpieza (eliminar duplicación en blueprints).

## Riesgos clave

- Transacción abierta durante LLM en `_extraer`: no abrir; mantener patrón.
- `g` global en encaje: parametrizar bien; riesgo de olvidar email/usuario_id.
- 413 de Flask pre-lectura: replicar límite en FastAPI.
- Body de error debe ser idéntico (exception handler).
- Idempotencia delete y 204.
- Notion no configurado → 503 (no 404).
- Master leído una vez por idioma (caché en `_evaluar`).
- Orden kill switch → consentimiento → CV.
- Cierre de reserva en `finally` aunque haya bug.