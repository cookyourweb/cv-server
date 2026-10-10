# Guía de uso

Sistema que cada mañana te manda ofertas por email y, al aprobar una, genera el CV
adaptado y la carta de presentación.

**Estado:** beta privada. Hace falta invitación.

Si lo que buscas es el detalle técnico, está en el [README](../README.es.md).

---

## Cómo empezar

El servicio es una **beta privada**. No hay formulario público: el acceso es por
invitación y la cuenta la crea la administradora.

### Paso 1. Pide tu invitación

Escribe a administración y cuéntale qué buscas, en tus propias palabras. Para crearte la
cuenta necesita:

- Nombre completo
- Email, el que usarás para recibir las ofertas
- Perfil libre: qué buscas

Opcionales, pero cuanto más completes más precisas salen las ofertas:

- Rol objetivo (por ejemplo "Senior Frontend Developer" o "Tech Lead")
- Ciudad, para los filtros de híbrido
- Modalidad preferida: remoto, híbrido Madrid, híbrido Barcelona o presencial
- Stack técnico
- Salario mínimo anual en euros
- LinkedIn, la URL completa

### Paso 2. Aporta tu CV Master

El sistema adapta TU CV a cada oferta, así que necesita una versión base de la que partir.

**Opción A, recomendada.** Sube un `.txt` con tu CV completo a tu Google Drive, hazlo
público con "cualquiera con el enlace puede ver", y manda el enlace a administración.

**Opción B.** Manda el CV a administración y lo sube a la carpeta compartida con el
nombre `CV_Master_{tu_email_con_guiones}.txt`.

### Paso 3. Espera el primer envío

Cuando la administradora crea tu cuenta, el sistema lanza una primera búsqueda y recibes
tus primeras ofertas por email. Desde ahí, el envío es diario a las 9:00.

Si alguien visita la dirección del servicio sin invitación, solo ve una página que explica
que es una beta privada. Es normal: no hay nada que rellenar.

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
Más adelante habrá una forma de editar tu perfil tú misma.

---

## Si algo falla

**La página del servicio tarda en cargar.** Espera 60 segundos, que el servidor se despierta
con la primera visita del día. Si a los dos minutos sigue igual, avisa.

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
Sí, los emails están adaptados.

**¿Puedo invitar a alguien?**
Todavía no. Manda el contacto a administración y se da de alta a mano.

---

## Contacto

Cualquier incidencia, duda o comentario: responde a cualquier email del sistema y llega
a administración.
