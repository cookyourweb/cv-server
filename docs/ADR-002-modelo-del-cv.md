# ADR-002: El CV lo escribe Sonnet 4.6, no Haiku 4.5

**Estado:** Propuesto · 27 jul 2026
**Ámbito:** `cv-server`, variable de entorno `CV_MODEL`
**Sustituye a:** la nota de coste del `ADR-001` (sección "Nota de coste")

> **Para quien retome esto (persona o IA):** este documento fija POR QUE el CV se
> genera con Sonnet y no con Haiku. Si vas a bajar el modelo otra vez por coste,
> lee primero la seccion "Los numeros" y la de "Evidencia".

---

## Contexto

Desde el arranque, `CV_MODEL=claude-haiku-4-5` y `CARTA_MODEL=claude-sonnet-4-6`.
La eleccion fue **deliberada y esta documentada**:

- `CHANGELOG.md`: *"CV adaptado (`/generar-cv`): Claude Haiku 4.5 (`CV_MODEL`), **barato y obediente**."*
- `ADR-001`: *"a proposito, por coste... **la diferencia es pequena; si algun dia la calidad del CV pesa mas, el salto es barato**."*

O sea: **el documento critico (el CV) lo escribe el modelo pequeno, y el documento
secundario (la carta) lo escribe el grande.** Esta invertido.

## El problema

El prompt de `/generar-cv` tiene **~68 directivas distintas** (~1.650 tokens solo de
reglas), mas el CV Master (~2.200 tokens), mas la descripcion de la oferta. Haiku 4.5
cumple la mayoria y **se salta unas cuantas, de forma no determinista**.

### Evidencia (27-jul-2026)

Las reglas incumplidas **ya estaban escritas en el prompt**. No falta ninguna regla:

| Regla del prompt | Donde esta | Se incumplio |
|---|---|---|
| Prohibicion de cuantificadores vagos ("millions of", "miles de") | `cv_server_railway.py:1683` | CV de Malwarebytes: *"platform handling **millions of transactions**"* |
| Escribe la ACCION, nunca el efecto atribuido | `cv_server_railway.py:1755` | Revolut: *"reducing manual effort and error rates"*. Malwarebytes: *"improving operational efficiency"* |
| REGLA DE EVIDENCIA (solo lo respaldado por el Master) | `cv_server_railway.py:1679` | Malwarebytes: *"I have **designed backend services**"*. El Master solo dice *"Integrated REST APIs and coordinated data contracts **with** the backend team"* |
| El titular es una identidad real, no el titulo de la vacante | HEADLINE RULES | Con puesto `Senior Product Engineer (Fullstack)` el titular salio duplicado y con la vacante dentro; con `Applied AI Engineer` salio perfecto **en el mismo commit** |

**El ultimo caso es el diagnostico:** mismo codigo, mismo commit en PROD, resultados
distintos segun el puesto de entrada. Un bug de codigo falla SIEMPRE igual. Esto falla
DISTINTO cada vez, que es la firma de un modelo pequeno saturado por el numero de
restricciones simultaneas.

**Corolario:** anadir mas reglas al prompt EMPEORA el problema. Seria pedirle a un
modelo que ya se satura que sostenga 75 restricciones en vez de 68.

## Los numeros

**MEDIDOS, no estimados** (27-jul-2026, `POST /v1/messages/count_tokens` con el prompt
real: reglas + CV Master EN + una oferta de Remotive; 13.816 caracteres):

| Modelo | Precio ($/1M in-out) | Tokens in | $/CV | **40 CVs/mes** | vs Haiku |
|---|---|---|---|---|---|
| Haiku 4.5 (actual) | 1 / 5 | 3.532 | $0,0117 | **$0,47** | — |
| **Sonnet 4.6 (propuesto)** | 3 / 15 | 3.532 | $0,0352 | **$1,41** | **+$0,94** |
| Sonnet 5 (intro hasta 31-ago-2026) | 2 / 10 | **5.313** | $0,0353 | $1,41 | +$0,94 |

**El sobrecoste real es $0,94 al mes. Menos de un euro. Once dolares al ano.**

> Una estimacion previa de este ADR decia $0,019/CV con Haiku y ~1,50 EUR/mes de
> sobrecoste. Estaba **inflada en un 70%**: sobreestimaba el prompt. Los numeros de
> arriba salen de la API de conteo, no de un calculo a ojo.

**Hallazgo que refuerza la decision 3 (no ir a Sonnet 5):** Sonnet 5 cuenta **5.313
tokens donde Haiku y Sonnet 4.6 cuentan 3.532** — un 50% mas para el MISMO texto,
porque lleva tokenizador nuevo. Su precio introductorio mas bajo ($2/$10 frente a
$3/$15) se lo come entero: el coste por CV sale practicamente identico al de Sonnet
4.6 ($0,0353 vs $0,0352). No hay ahorro, y si el riesgo de truncado por adaptive
thinking. La decision de quedarse en Sonnet 4.6 se sostiene por dos motivos
independientes.

El CV es el unico artefacto que ve un recruiter. Una tecnologia inventada o una cifra
falsa no cuesta $0,94: cuesta el proceso entero, y es indefendible en la entrevista.

## Decisiones

1. **`CV_MODEL=claude-sonnet-4-6`.** Es una variable de entorno en Render: sin cambio
   de codigo, sin despliegue, reversible en 30 segundos.
2. **NO se toca el prompt en el mismo cambio.** Primero se aisla la variable modelo. Si
   con Sonnet los fallos desaparecen, el prompt estaba bien todo este tiempo. Solo si
   persisten se toca el prompt.
3. **NO se sube a Sonnet 5 todavia**, aunque hoy sea mejor Y mas barato que Sonnet 4.6
   por el precio introductorio. Motivo: Sonnet 5 lleva **adaptive thinking activado por
   defecto**, y el thinking consume del mismo `max_tokens` que la respuesta. Con
   `max_tokens=4096` el CV podria truncarse. Requiere subir `max_tokens` o pasar
   `thinking: {"type": "disabled"}`, y eso ya es cambio de codigo.

### Por que el cambio es seguro

`call_claude()` (`cv_server_railway.py:194`) envia **solo** `model`, `max_tokens` y
`messages`. No pasa `temperature`, `top_p`, `top_k` ni `thinking`. Esos son justo los
parametros que rompen (400) al subir de modelo. **No hay ninguna incompatibilidad de
API entre Haiku 4.5 y Sonnet 4.6 en este codigo.**

## Consecuencias

- **A favor:** un modelo con capacidad sobrada para 68 directivas simultaneas; menos
  correcciones a mano; menos riesgo de invencion en el documento que ve el recruiter.
- **Coste:** ~1,50 EUR/mes mas.
- **Riesgo controlado:** es una variable de entorno. Si no mejora, se revierte al
  instante y el diagnostico pasa a ser del prompt, no del modelo.

## Como verificarlo

1. Cambiar `CV_MODEL` en Render a `claude-sonnet-4-6`.
2. Aprobar en Notion **una** oferta con descripcion completa (Tecnoempleo o Remotive,
   no LinkedIn ni Indeed: esas traen 172-245 caracteres y no hay material que adaptar).
3. Descargar el CV generado y pasarlo por el checklist del
   `buscartrabajo/docs/09-RUNBOOK-OFERTA-CONTACTO-DIRECTO`, mas estos cuatro casos
   concretos, que son los que fallaron con Haiku:
   - cuantificadores vagos no respaldados ("millions of", "thousands of")
   - coletillas de beneficio sin metrica ("improving X", "reducing Y")
   - afirmaciones de alcance de rol no respaldadas por el Master ("designed backend
     services", "led X across distributed systems")
   - titular duplicado o con el nombre de la vacante dentro
4. Comparar contra el crudo de Malwarebytes del 25-jul (`1uW3wHeuebl4GsSjWbqdeHKl2BhmqXnd8`),
   que es el caso base con Haiku.

## Pendiente

- [ ] Cambiar `CV_MODEL` en Render y regenerar un CV de control.
- [ ] Si con Sonnet siguen apareciendo fallos, ENTONCES tocar el prompt.
- [ ] **Ampliar el guardrail a afirmaciones de ROL.** Hoy detecta tecnologias
      (`tecnologias_no_respaldadas`) y cifras (`cifras_no_respaldadas`), ambas por
      coincidencia de texto contra el Master. No detecta "diseno backend services",
      que es semantico. Es el agujero real de los guardrails, independiente del modelo.
- [ ] Evaluar Sonnet 5 cuando se pueda tocar `max_tokens` (mejor y, hasta el
      31-ago-2026, mas barato que Sonnet 4.6).

---

**Relacionado:** `ADR-001-migracion-fastapi.md` (seccion "Nota de coste"),
`CHANGELOG.md`, `buscartrabajo/docs/09-RUNBOOK-OFERTA-CONTACTO-DIRECTO`.
