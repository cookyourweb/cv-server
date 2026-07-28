# ADR-003: Un usuario, varias cuentas de correo

**Estado:** Aceptado · 28 jul 2026
**Ámbito:** `cv-server`, `buscar_usuario_por_email`, base `Users` de Notion

> **Para quien retome esto (persona o IA):** si vuelve a aparecer un segundo registro
> de la misma persona en `Users`, no lo "arregles" copiando campos a mano. Lee la
> seccion "Por que no vale duplicar el registro": el parche se rompe solo.

---

## Contexto

A Vero le llegan ofertas a **dos buzones**: `hello.cookyourweb@gmail.com` y
`verseper@hotmail.com`. `buscar_usuario_por_email` filtraba la base `Users` por el
campo `Email` con `equals`, asi que solo reconocia una direccion.

La solucion que se adopto en su momento fue **crear un segundo registro** en `Users`,
con el otro correo. Funcionaba: las ofertas de ambos buzones encontraban usuario.

## El problema

**Dos registros de la misma persona derivan.** No es una hipotesis: paso.

Estado al detectarlo (28jul2026):

| Campo | `hello.cookyourweb@gmail.com` | `verseper@hotmail.com` |
|---|---|---|
| `Name` | Verónica Serna Pérez | veronica serna |
| `Email CV` | verserper@gmail.com | **vacio** |
| `CV Master URL` | **8.702 chars, con `PERFIL BASE`** | **4.689 chars, SIN `PERFIL BASE`** |
| `Ciudad` | Valdemorillo, Madrid | madrid |
| `Rol objetivo` | AI Engineer · Full-Stack · Tech Lead… | Senior Frontend Develo**p**er *(typo)* |
| `Perfil` | 3 lineas (IA, RAG, agentes) | "Desarrolladora frontend developer senior" |
| `Stack` | React, TS, Vue, Node, Python, AI/ML… | solo "React Typescript" |

El CV de PANEL Sistemas se genero contra el segundo registro. Consecuencias, todas
en el documento que ve un recruiter:

1. Cabecera con `madrid` y `verseper@hotmail.com`.
2. Titular `Tech Lead Full Stack | Java · Angular · APIs REST | Arquitectura de
   Microservicios`: **el titulo literal de la vacante**. Eco puro, prohibido por las
   HEADLINE RULES.
3. Tecnologias ajenas al Master bueno (Maven, Oracle Cloud).

**Y el guardrail del titular no salto.** No por un bug: ese Master no tiene bloque
`PERFIL BASE`, asi que no habia contrato contra el que validar. Un guardrail que
depende de un dato solo protege cuando el dato existe.

## Por que no vale duplicar el registro

La duplicacion es un parche con una fecha de caducidad que nadie ve venir: **funciona
el dia que se crea y se degrada en silencio**. Cada vez que se afina el Master, el
perfil o el stack, se toca UN registro. El otro se queda atras, y no hay ningun aviso
— hasta que una oferta entra por el buzon equivocado y sale un CV con la identidad de
otra persona.

El modelo del dominio es claro: **la persona es UNA. Lo que hay son varias direcciones
de entrada.** Un registro por buzon confunde la identidad con el canal.

## Decision

**Un registro de usuario puede declarar N direcciones.**

- `Email` (email) sigue siendo la direccion **principal**. No cambia.
- **`Emails alias`** (rich_text, NUEVO): direcciones adicionales, separadas por coma,
  punto y coma o salto de linea.

`buscar_usuario_por_email` hace **dos pasadas**:

1. `Email equals <email>` — camino rapido, comportamiento de siempre.
2. Si no hay resultado: `Emails alias contains <email>`, y **verifica la coincidencia
   exacta en Python**.

### Por que la verificacion en Python no es opcional

El filtro `contains` de Notion es de **subcadena**: `vero@gmail.com` casa con
`notvero@gmail.com`. Sin la verificacion final, un usuario podria recibir el CV de
otro. Cubierto por `test_no_coincide_por_subcadena`.

### Funciones puras

- `emails_de_usuario(props) -> set[str]` — todas las direcciones, normalizadas a
  minusculas y sin espacios. Descarta lo que no tenga forma de email, para que una
  nota suelta en el campo ("(el viejo)") no se convierta en direccion.
- `usuario_tiene_email(props, email) -> bool` — comparacion exacta.

Ambas son puras y testeables sin tocar Notion (15 tests en
`test_usuario_multicuenta.py`).

## Consecuencias

- **A favor:** un solo sitio donde mantener Master, perfil, stack y ciudad. Añadir un
  buzon es escribir un correo mas en un campo, no clonar un registro.
- **Coste:** una segunda consulta a Notion cuando el email no es el principal. Solo en
  ese caso; el camino habitual sigue siendo una sola llamada.
- **Compatible hacia atras:** si el campo `Emails alias` no existe, la segunda pasada
  devuelve 400, se registra en el log y la funcion se comporta como antes.

## Migracion (manual, en Notion)

1. En `Users`, añadir la propiedad **`Emails alias`** de tipo **Text**.
2. En el registro bueno (`Verónica Serna Pérez` / `hello.cookyourweb@gmail.com`),
   poner en `Emails alias`: `verseper@hotmail.com`
3. En las ofertas cuyo campo `Usuario` apunte al registro duplicado, reapuntarlas al
   bueno.
4. **Desactivar** (`Activo` = off) el registro `veronica serna` / `verseper@hotmail.com`.
   Desactivar antes que borrar: si alguna oferta historica lo referencia, la relacion
   no se rompe.
5. Verificar: `POST /generar-cv` con `email: verseper@hotmail.com` debe devolver un CV
   con la cabecera de `Verónica Serna Pérez` y `verserper@gmail.com`.

## Pendiente

- [ ] El paso 3 de la migracion no esta automatizado. Si aparecen muchas ofertas
      apuntando al registro viejo, merece un script.
- [ ] Ningun guardrail avisa de que un Master **no tiene bloque `PERFIL BASE`**. Es lo
      que dejo pasar el titular con eco. Un aviso al leer el Master lo cubriria, y es
      independiente del modelo y de este ADR.

---

**Relacionado:** `ADR-002-modelo-del-cv.md`, `ONBOARDING-MULTIUSUARIO.md`,
`test_usuario_multicuenta.py`.
