# BYOK — Bring Your Own Key

## Flujo
1. El usuario entra en la cuenta por Google.
2. Las generaciones usan primero su propia key.
3. Si no tiene key, las primeras 3 generaciones son de prueba.
4. Al llegar a 0, se exige una key propia.
5. No hay fallback silencioso a claves compartidas.

## Seguridad
- La key se cifra en reposo.
- Nunca se imprime en logs.
- Un usuario solo ve su propio estado.
- `CLAVE_MAQUINA` protege los endpoints máquina; la cuenta usa Google.
- La puerta falla cerrada: sin cuenta en Neon, sin BD o con error, se deniega.
- `BYOK_PROPIETARIAS` (emails separados por comas) son las dueñas del servicio:
  generan siempre con la key del servidor (modo `propietaria`). Solo llegan a la
  puerta las rutas con clave de máquina, así que no es una puerta trasera pública.

## Onboarding para desarrolladores
- Cada una trae su key de Anthropic o Groq.
- La plataforma no cobra la inferencia.
- Si no configuran key, quedan bloqueadas tras el trial.
- La API devuelve `403` con mensaje educativo.

## Referencias
- `specs/003-byok-cv-carta`
- `byok.py`
- `/clave-api`
- `/generar-cv` y `/generar-carta`