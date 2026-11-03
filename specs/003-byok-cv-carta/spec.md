# Spec 003 — BYOK: clave de IA propia y trial de 3 generaciones

Estado: implementada (backend y gate; UI panel pendiente)

## Contexto y objetivo
Cada usuaria debe poder usar su propia key de IA sin compartir costes ni claves. Antes de obligar a la key propia, se permite un modo demo de 3 generaciones gratuitas para probar la funcionalidad. No hay fallback silencioso a clave global.

## Usuarios / actores
- Usuario panel
- cv-server
- `buscartrabajo` (como integración opcional)
- Panel dinámico para entrada de la key

## Historias de usuario
- HU-1: Como usuaria, quiero usar mi propia key de IA para controlar el gasto.
- HU-2: Como usuaria, quiero una prueba gratuita sin fricción inicial.
- HU-3: Como backend, quiero no exponer la clave ni caer en fallback compartido.
- HU-4: Como dueña del sistema, quiero transparencia de límite y consumo.

## Decisiones cerradas
- Trial: 3 generaciones gratuitas por usuario, no reseteable.
- Modo demo: desactivado al añadir key propia.
- Sin fallback a clave global/sistema.
- Errors claros y guía si falta key.
- CV maestro checker de Spec 004 puede correr antes o después del trial.

## Alcance V1
- Almacenar una API key por usuaria, cifrada.
- Generar CV/carta solo si la usuaria tiene key válida o cuota trial disponible.
- Verificación mínima de la key al guardarla.
- UI panel para alta/cambio de key.
- Logs sin secretos.
- Comunicación clara de por qué existe el trial.

## Requisitos funcionales
- RF-1: CUANDO la usuaria entra, EL SISTEMA permite hasta 3 generaciones sin key.
- RF-2: CUANDO se alcanza la cuota, EL SISTEMA bloquea nuevas generaciones sin key real.
- RF-3: SI el CV/carta se puede generar por trial, EL SISTEMA registra consumo.
- RF-4: SI la usuaria añade una key válida, EL SISTEMA desactiva trial y usa su key.
- RF-5: SI la key es inválida, EL SISTEMA la marca y no la usa.
- RF-6: CUANDO falta key, EL SISTEMA devuelve error controlado con guía.
- RF-7: CUANDO se genera una candidatura, EL SISTEMA usa la key de la usuaria activa.
- RF-8: Cada llamada LLM deja registro de modelo y cuota consumida.
- RF-9: No se cae a claves compartidas en ningún caso.

## Requisitos no funcionales
- No secretos en logs.
- cifrado en reposo.
- rollback por feature flag.
- audit trail básico.
- billing transparente.

## Casos límite
- clave inválida al guardarla
- clave revocada después de guardar
- trial agotado
- usuario con key propia pero generación fallida
- concurrencia en actualización de key
- usuario que importa CV maestro antes de configurar key
- modo demo sin key y sin consumo

## Fuera de alcance
- Facturación exacta por token en esta versión
- múltiples claves por usuario
- marketplace de proveedores
- subscription management

## Criterios de finalización
- tests de auth + key management
- test de trial agotado
- test de clave inválida
- demo completo con y sin key
- docs de onboarding claro