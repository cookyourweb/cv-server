# Google OAuth y el token de Drive

**Estado:** vigente · **Fecha:** 18 de agosto de 2026

Este fichero existe porque el mismo fallo ha caído tres veces (24-jul, 11-ago y
18-ago) y las tres veces se rediagnosticó desde cero. El dato que faltaba no era
el mecanismo: era **qué proyecto de Google**.

## Los datos

| Qué | Valor |
|---|---|
| Proyecto de Google | `sylvan-surf-138623`, número de proyecto `36051363838` |
| Cómo se identificó | CONFIRMADO por Vero el 18-ago-2026 en la consola de Google. Antes era solo una inferencia por eliminación |
| Cliente que usa Render | `cv-server-render-web`, tipo Aplicación web, creado el 2 may 2026, ID `36051363838-6fpkf...` |
| Otro cliente del proyecto | `subirCv`, tipo Escritorio, creado el 9 abr 2026, ID `36051363838-9ton5...`. NO es el de Render |
| Cómo distinguirlos | Por los caracteres tras el guion en `GOOGLE_CLIENT_ID`: `6fpkf` es el web de Render, `9ton5` es el de escritorio |
| Permiso solicitado | `https://www.googleapis.com/auth/drive` (Drive completo, categoría restringida) |
| Dónde viven las credenciales | Render, servicio `cv-server`, pestaña Environment |
| Variables | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN` |
| Servicio desplegado | `https://cv-server-ggd8.onrender.com` |

**El otro proyecto, `n8n-asistente-correo`, NO es este.** Ese es el del
asistente de correo, su cliente es de tipo Web con redirección a n8n, y ya está
publicado en producción.

## Por qué se muere el token, con la cita

Documentación de Google, `developers.google.com/identity/protocols/oauth2`:

> A Google Cloud Platform project with an OAuth consent screen configured for an
> external user type and a publishing status of "Testing" is issued a refresh
> token expiring in 7 days, unless the only OAuth scopes requested are a subset
> of name, email address, and user profile

cv-server pide Drive completo, que no está en ese subconjunto. Por tanto, en modo
Testing **el token muere cada siete días exactos**. El error que aparece es
`invalid_grant: Token has been expired or revoked`.

Las fechas lo confirman: token regenerado el 24-jul, muerto el 31-jul, y no se
notó hasta el 11-ago porque el sistema estuvo parado del 24-jul al 5-ago.
Regenerado el 11-ago, muerto el 18-ago.

## El arreglo definitivo, una vez

Publicar la pantalla de consentimiento:

`console.cloud.google.com/auth/audience?project=sylvan-surf-138623` y pulsar
PUBLICAR APLICACIÓN.

Al pasar a "In production" desaparece la caducidad de siete días. Sale un aviso
de aplicación no verificada, y es irrelevante: Vero es la única usuaria de su
propia aplicación y el límite sin verificar son 100 usuarios.

## El arreglo de arquitectura, cuando toque

Usar una **cuenta de servicio** en vez de consentimiento de usuario. Un servidor
que lee un documento sin que haya nadie delante no debería depender de un
consentimiento humano. Se comparte el CV Master con la dirección de la cuenta de
servicio y se usa su clave. Ninguna de las siete causas de expiración que lista
Google aplica a una cuenta de servicio.

## Regenerar el token a mano: SON DOS PASOS

Uno solo no basta, y ya se falló por esto el 11-ago.

```bash
# 1. generar. Ojo: el venv es oculto y las dependencias no estan en el python del sistema
~/Desktop/proyectosActivosCookyourweb/cv-server/.venv/bin/python \
  ~/Desktop/proyectosActivosCookyourweb/cv-server/scripts/regenera_token.py
# abre localhost:8080, se elige la cuenta dueña del Drive,
# guarda el token en .env y verifica que lee CV_MASTER_VERONICA_ES

# 2. llevarlo a produccion
#    Render > cv-server > Environment > GOOGLE_REFRESH_TOKEN, pegar y desplegar
```

Generar el token sin pegarlo en Render deja el sistema exactamente igual de roto.

## Cómo comprobar si está vivo

`/health` NO comprueba Drive, así que no sirve para esto. La única prueba real es
aprobar una oferta en Notion y ver si el CV se genera, o mirar el payload del
Error Trigger de n8n en `execution.error.description`, que es donde está el
mensaje útil. El estado de la ejecución sale `success` aunque haya fallado.

## Registro: 18 de agosto de 2026, resuelto

1. Confirmado en la consola que el proyecto es `sylvan-surf-138623` y que el
   cliente de Render es `cv-server-render-web`, tipo Aplicación web.
2. **Publicada la aplicación a producción.**
3. Regenerado el token DESPUÉS de publicar, que es el orden que importa.
   Verificado por el propio script: `REFRESH OK` y `LEE EL MASTER:
   'CV_MASTER_VERONICA_ES'`.
4. Pegado en Render y redespliegue.

**Este token ya no caduca a los siete días.** Si vuelve a fallar, la causa es
otra y este documento ya no la explica.

## Dos trampas del procedimiento, para la próxima

**La URL de consentimiento puede quedar invisible.** Si el script se lanza sin
terminal, Python almacena la salida en un búfer y el enlace no aparece: parece
colgado cuando en realidad está esperando en `localhost:8080`. Se lanza con
`python -u` para que la salida salga al momento.

Y si un intento anterior quedó vivo, el puerto está ocupado y el segundo intento
choca. Se comprueba con:

```bash
lsof -nP -iTCP:8080 -sTCP:LISTEN
```

**El script imprime el token en claro** en la última línea. Si se lanza desde una
herramienta que registra la salida, el token queda escrito en ese registro. Para
llevarlo a Render sin mostrarlo:

```bash
pbcopy < <(rg -o '^1//[A-Za-z0-9_-]+$' ruta/de/la/salida)
```

Conviene comparar la longitud del original con la del portapapeles antes de
pegar: un salto de línea de más rompe la autenticación y el error que da Google
es el mismo `invalid_grant`, así que se diagnostica mal.
