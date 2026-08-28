# Diseño: ciclo de vida de una corrección

**28-ago-2026** · Estado: propuesto

Este servicio genera un CV adaptado a una oferta con un LLM. La persona que lo recibe
lo corrige a mano antes de enviarlo, y de esas correcciones salen reglas.

Este documento decide qué pasa con esas correcciones.

---

## Criterio de éxito

**El sistema funciona cuando el número de correcciones baja.** No cuando genera un CV
que se lee bien.

Un documento correcto que hay que retocar cada vez es el estado actual, y el estado
actual es el problema. De ahí sale la única métrica del diseño: **correcciones por
CV**.

---

## El problema, tal cual está hoy

Las reglas de adaptación existen y están escritas. Lo que no existe es el eslabón que
las aplica: **una persona las copia al prompt a mano**.

```
Ficheros de reglas de adaptacion
          |
          +-- las copia una PERSONA al prompt, a mano
```

El código no los lee. Cada regla nueva depende de que alguien se acuerde de pegarla.

### El diagnóstico, que no es el que parece

| Pieza | Estado |
|---|---|
| **Capturar reglas** | Resuelto. Están escritas y validadas contra feedback externo |
| **Aplicarlas** | **No existe.** Depende de una copia manual |
| **Medir si funcionan** | **No existe.** No hay forma de saber si hoy se corrige menos que hace un mes |

No faltan reglas. Falta el eslabón que las aplica.

---

## Sección 1: una corrección no es una regla

Una corrección es una **candidata**. Se convierte en regla cuando se repite.

El instinto dice lo contrario, y por eso se escribe: si cada corrección entrase como
regla al momento, el prompt se llenaría de casos únicos que se contradicen entre sí, y
la calidad bajaría según se usa el sistema. La señal de que una corrección generaliza
es que se hizo más de una vez.

| Estado | Qué es | Dónde vive |
|---|---|---|
| Corrección | Lo que se cambió en ESTE documento | Junto a la oferta |
| Candidata | Una corrección vista dos veces | Lista de pendientes de revisar |
| Regla | Promovida por la persona, entra al prompt | Los ficheros de reglas, que ahora **sí** lee el código |

**La métrica**: correcciones por CV. Si no baja, las reglas no generalizan y solo se
está engordando el prompt. Es el único dato que distingue un sistema que aprende de uno
que acumula.

---

## Sección 2: dos ejes de reglas, no uno

Hoy hay una sola persona usando el sistema. El diseño de usuario multicuenta ya existe
(ver `ADR-003`), así que la decisión se toma ahora para no reescribirla después.

| | Reglas del sistema | Reglas del usuario |
|---|---|---|
| Ejemplo | No inventar cifras que no estén en el documento fuente. No atribuir años de experiencia a la tecnología equivocada | Preferencias de estilo y de formato de cada persona |
| ¿De quién? | De todos | De una persona |
| ¿Quién las cambia? | Quien mantiene el producto | Cada usuario, las suyas |
| Dónde viven | **En el repositorio**, versionadas en git | **Con la ficha del usuario** |

Las del sistema **ya existen y funcionan**: son los seis guardrails, en código y con
tests. Ese eje está resuelto.

El que no existe es el segundo, y hoy las reglas personales están en ficheros dentro
del repositorio, que es exactamente donde no pueden estar las de otra persona.

**La decisión barata que evita reescribirlo todo**: las reglas de usuario se guardan
desde el primer día asociadas a un usuario, aunque hoy haya uno solo. No se construye
nada multiusuario. Solo se guarda con la clave puesta.

Diferencia de ponerla hoy: media hora. De no ponerla: reescribir el almacén y migrar lo
que hubiera dentro.

---

## Sección 3: cómo se captura una corrección

Las dos formas puras fallan:

- **Inferirla del diff.** Cero fricción, pero el sistema no distingue una errata de un
  criterio. Reglas basura.
- **Pedirla en blanco.** Señal limpia, pero nadie rellena una caja de texto vacía
  después de corregir un documento.

**El diff propone, la persona confirma:**

```
Genera el CV
     |
     v
Lo corrige a mano
     |
     v
El sistema detecta QUE cambio y pregunta UNA cosa:

  "Cambiaste X por Y en el titular.
   ¿Siempre, solo para este tipo de oferta, o solo esta vez?"

     [ Siempre ]  [ Solo este tipo ]  [ Solo esta ]
```

Tres botones, una pregunta. No se escribe una regla: **se elige su alcance**, que es lo
único que el sistema no puede adivinar, y es exactamente el campo que separa una regla
global de una acotada a un tipo de oferta.

Aquí es donde el LLM se gana el sitio: convertir un diff sucio en una frase legible que
se pueda confirmar. No genera contenido, **estructura una observación humana**.

**Riesgo, y va escrito a propósito**: preguntar en cada documento cansa, y una persona
cansada pulsa "Siempre" a todo para quitárselo de encima. El sistema se envenenaría
solo. Por eso solo se pregunta por cambios que **ya se repitieron**: la candidata nace
del diff, y la pregunta aparece la segunda vez.

---

## Sección 4: reglas que se contradicen

Cuando una regla nueva contradice a una vigente, **gana la nueva y la vieja se marca
como superada, con la fecha y la regla que la sustituye**. Igual que un ADR.

Nunca se borra. Una regla borrada se lleva consigo el porqué, y dentro de tres meses
nadie sabe si aquello se quitó por una razón o por un descuido.

---

## Orden del trabajo

El orden importa y no es el intuitivo:

1. **Que el código lea los ficheros de reglas.** El cambio más pequeño de todo esto y
   el que más efecto tiene: ese día una regla escrita es una regla aplicada.
2. **Contar correcciones por CV.** Sin línea base, "esto va mejorando" es una
   sensación.
3. **El bucle de captura** (el diff propone, la persona confirma).

El bucle va el tercero a propósito: cuando las reglas se apliquen solas, se verá cuáles
frenan correcciones de verdad. Sin ese dato, el bucle recogería reglas sin saber si
alguna sirve.

---

## Lo que NO se hace, a propósito

- Motor de reglas genérico
- Base de datos nueva
- Panel de administración de reglas
- Reglas compartidas entre usuarios

Nada de eso hace falta con un usuario, y cada pieza añadida hoy es una que hay que
mantener antes de saber si se necesita.

---

## Preguntas abiertas

- **Los ficheros de reglas están en otro repositorio que el código que los leería.** Un
  servicio no puede leer ficheros de un repositorio que no despliega. Tres salidas:
  1. **Mover las reglas a este repositorio**, junto al prompt que las consume. Lo más
     simple.
  2. Dejarlas donde están y leerlas por HTTP. Añade una dependencia de red en el
     arranque, para nada.
  3. Duplicarlas. Se descarta: dos copias de la misma regla se desincronizan, que es
     justo la enfermedad que este documento viene a curar.

  Recomendación: la 1. Cambia dónde se editan las reglas cada día, así que la decide
  quien las escribe.
- **Cuántas repeticiones promueven una candidata a regla.** El diseño dice dos. Es un
  número elegido, no medido. Se revisa cuando haya datos de correcciones por CV.
- **Dónde vive exactamente la línea base de correcciones.** Junto a la oferta es lo
  natural, pero hay que ver si el esquema aguanta sin ensuciarse.
