# Prompts versionados (LLMOps)

Los prompts de generación de CV y carta viven aquí, versionados por carpeta.

- `v1/` — versión actual en producción (extraída de `server.py`).
- `PROMPT_CV.txt`, `PROMPT_CARTA.txt`, `PROMPT_ESTRUCTURA_EN.txt`, `PROMPT_ESTRUCTURA_ES.txt`.

## Cómo se usan
`server.py` carga los prompts desde estas archivos si existen; si no, usa los
constantes hardcodeados como fallback (compatibilidad).

## Versionado
Al cambiar un prompt:
1. Crear `v2/` con la nueva versión.
2. Actualizar `server.py` para cargar `v2/` (o parametrizar por env `PROMPT_VERSION`).
3. Añadir casos en `evals/casos/` y correr `evals/run_eval.py` para detectar regresiones.
4. Comparar métricas antes/después.