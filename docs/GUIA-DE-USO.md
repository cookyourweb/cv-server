# Guía de uso

Sistema que cada mañana te manda ofertas por email y, al aprobar una, genera el CV
adaptado y la carta de presentación.

**Estado:** beta privada. Hace falta invitación.

Si lo que buscas es el detalle técnico, está en el [README](../README.md).

---

## Cómo empezar

### Paso 1. Abre el formulario de registro

**[cv-server-ggd8.onrender.com/registro](https://cv-server-ggd8.onrender.com/registro)**

La primera vez puede tardar entre 30 y 60 segundos en cargar: el servidor está en el
plan gratuito de Render y se duerme tras 15 minutos sin actividad. Si parece colgado,
espera un minuto antes de recargar.

### Paso 2. Rellena el formulario

Obligatorios:

- Nombre completo
- Email, el que usarás para recibir las ofertas
- Perfil libre: qué buscas, en tus propias palabras

Opcionales, pero cuanto más completes más precisas salen las ofertas:

- Rol objetivo (por ejemplo "Senior Frontend Developer" o "Tech Lead")
- Ciudad, para los filtros de híbrido
- Modalidad preferida: remoto, híbrido Madrid, híbrido Barcelona o presencial
- Stack técnico
- Salario mínimo anual en euros
- LinkedIn, la URL completa
- CV Master URL, que es el importante y va en el paso siguiente

### Paso 3. Sube tu CV Master a Drive

El sistema adapta TU CV a cada oferta, así que necesita una versión base de la que partir.

**Opción A, recomendada.** Sube un `.txt` con tu CV completo a tu Google Drive, hazlo
público con "cualquiera con el enlace puede ver", y pega el enlace en el campo
"CV Master URL".

**Opción B.** Deja el campo vacío y pide a quien te invitó que suba tu CV a la carpeta
compartida con el nombre `CV_Master_{tu_email_con_guiones}.txt`.

### Paso 4. Envía el formulario

Si es tu primer registro, verás "Listo, mañana a las 9:00 recibirás tus primeras ofertas".

Si tu email ya existe, verás dos botones: **Buscar ahora**, que te manda las ofertas en
unos minutos, o **Mañana a las 9**, que espera al envío programado.

---

## El día a día

### El email de la mañana

Cada día a las 9:00 recibes un email con ofertas reales: empresa, puesto, salario,
modalidad, enlace y contacto de recursos humanos. Cada una trae dos botones,
**Aprobar** y **Descartar**, dentro del propio email. No hace falta abrir nada más.

### Al aprobar una oferta

En uno o dos minutos llega un segundo email con:

- La carta de presentación, personalizada para esa empresa y ese puesto
- El enlace al CV adaptado, un DOCX en tu Drive
- Un botón **Mandar a empresa**, que marca la oferta como enviada y te manda un tercer
  email de confirmación con los datos de contacto

### Lo que haces tú

Abres el CV, lo revisas, y mandas el email a la empresa. **El sistema nunca envía nada
a la empresa por su cuenta**: solo te lo deja preparado.

---

## Cambiar tus preferencias

Tu perfil vive en una base de datos de Notion. Para cambiar email, stack o salario,
pausar los envíos sin borrarte, o eliminar tu cuenta, contacta con quien te invitó.
Más adelante habrá un botón de "editar mi perfil" en el propio formulario.

---

## Si algo falla

**El formulario no carga.** Espera 60 segundos, que el servidor se despierta con la
primera visita del día. Si a los dos minutos sigue igual, avisa.

**No llega el email de las ofertas.** Mira en spam y en promociones, y comprueba el
remitente. Si no aparece, avisa indicando el email con el que te registraste.

**Aprobé una oferta y no llegó el CV.** El flujo tarda uno o dos minutos: el modelo
escribe la carta, adapta el CV y lo sube a Drive. Si pasan cinco minutos sin nada,
avisa y se revisan los logs.

**El CV generado tiene datos de otra persona.** Casi seguro que tu CV Master no está
subido y el sistema tiró de uno de reserva. Comprueba que lo subiste y avisa.

### Los estados de una oferta

| Estado | Qué significa |
|---|---|
| Pendiente | Recién llegada, sin decidir |
| Aprobado | Pulsaste "Aprobar", carta y CV en camino |
| En proceso | Carta y CV generados, esperando que la mandes |
| Enviado a empresa | Pulsaste "Mandar", candidatura enviada |
| Descartado | Pulsaste "Descartar" |
| Rechazado | La empresa respondió que no |
| Caducada | La oferta ya no está disponible |

---

## Privacidad

- Tu perfil está en una base de datos privada de Notion, con acceso solo de administración.
- Los CVs adaptados se guardan en Drive, en una carpeta con tu email como nombre.
- La generación usa la API de Claude (Anthropic) con tu CV Master y la descripción de la oferta.
- Ningún dato se vende ni se comparte con terceros.
- Para borrar tu cuenta entera, avisa y se elimina en 24 horas.

---

## Preguntas frecuentes

**¿Las ofertas son reales?**
Sí. Entran de portales de empleo reales: Adzuna, Tecnoempleo y los feeds RSS de LinkedIn.
Antes de llegarte pasan por filtros de modalidad, ubicación y encaje con tu perfil.

**¿Cuánto cuesta?**
Nada. Es una beta privada cerrada. Si pasa a producto comercial se avisa antes.

**¿Cuántas ofertas recibo?**
Las que superen los filtros ese día, con un tope diario. Fines de semana y festivos
también, no hay pausa.

**¿Puedo usarlo desde el móvil?**
Sí, el formulario y los emails están adaptados.

**¿Puedo invitar a alguien?**
Todavía no. Manda el contacto a administración y se añade a mano.

---

## Contacto

Cualquier incidencia, duda o comentario: responde a cualquier email del sistema y llega
a administración.
