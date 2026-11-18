# Agents

The rules of this project are in **[CONTRIBUTING.md](CONTRIBUTING.md)**.

SDD activo:
- Lee `docs/constitution.md` y la spec activa antes de tocar código.
- Tests: `pytest`
- Secretos solo por entorno; nunca en repo.
- Tras cambios, verificar endpoints y flujo CV/Drive.
- Endpoint `GET /resumen-pendientes` (clave máquina): resumen Markdown de ofertas en estado "Pendiente" del CRM de Notion. Solo lectura. Módulo: `notion_resumen.py`.
- Endpoint SSE `GET /buscar-para-usuaria/progress`: token va en query param `?token=...` (EventSource no envía cabeceras). Acepta clave máquina (n8n) o JWT de Google (panel). Validado con hmac.compare_digest / firma OIDC (fail-closed). Cierre de conexión al recibir `done`/`error` o al destruir el componente.
- Migración FastAPI completa: cores puros en `alta_core.py`/`encaje_core.py`, `CVError` en `errores.py`. Exception handler global en FastAPI para paridad de body. Todos los endpoints migrados (incl. `/extraccion`). Flask se mantiene como respaldo.
- T5 (más fuentes): añadido `filtrar_spam` (TAGS_SPAM) y `filtrar_por_salario` (salario mínimo hard filter) en `real_jobs.py`, integrados en el pipeline de `buscar_ofertas_reales` con eventos de progreso.
- RAG con citations: `rag.py` (chunkear, recuperar, responder, preguntar_cv) + endpoint `POST /rag/preguntar`. Cumple RAG pipeline ownership.