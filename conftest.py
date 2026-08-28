"""Config de tests.

Ya no hace falta inyectar credenciales: desde el 28-ago-2026 los modulos se
importan sin ninguna variable de entorno. La validacion vive en `server.py` y
reporta las que faltan al arrancar, no al importar.

Ver `tests/test_modulos_sin_entorno.py`, que lo comprueba en un proceso limpio.
"""
