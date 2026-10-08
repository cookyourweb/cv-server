# Cómo se trabaja en este repositorio

No es un manual de buenas intenciones: es lo que este repositorio **exige**, y una
parte la comprueba git solo antes de dejarte commitear.

## Activarlo, una vez por clon

```bash
git config core.hooksPath scripts/hooks
```

A partir de ahí, cada `git commit` corre la suite. Si está en rojo, no hay commit.

---

## El ciclo: rojo, verde, commit

**Primero el test que falla. Siempre.**

Un test que nunca has visto fallar no sabes si prueba algo. Escribirlo después del
código solo demuestra que el código hace lo que hace.

```
1. Escribe el test que describe el fallo o el comportamiento que falta
2. Ejecútalo y MIRA el rojo. Lee el mensaje: ¿dice lo que quieres que diga?
3. Escribe el código mínimo que lo pone en verde
4. Ejecuta la suite ENTERA, no solo tu test
5. Commit
```

El paso 2 no es ceremonia. El 28-ago-2026 un test escrito aquí pasó a la primera
estando el código mal: comparaba con `not in` y la subcadena que buscaba estaba
contenida en la forma correcta. Verlo en rojo primero es lo que lo destapa.

## Dónde viven los tests

En `tests/`, en la raíz del repositorio. No al lado del código que prueban.

Es la convención que ya se usó en la prueba técnica de osapiens, y aquí se adoptó
el 28-ago-2026 sacando 23 ficheros de test de la raíz. El movimiento destapó dos
tests que dependían de estar físicamente al lado del fuente que leían: una
dependencia que nadie sabía que existía porque nunca se habían movido.

## Idioma: commits y comentarios en inglés

Desde el 8 de octubre de 2026. El repositorio es público y lo leen empresas de
fuera, así que lo que se escribe a partir de ahora va en inglés:

- **Mensajes de commit y descripciones de PR, en inglés.** Son lo primero que se
  lee del historial. Se mantiene el formato convencional (`fix:`, `feat:`...) y
  la regla de explicar el porqué.
- **Comentarios del código nuevo o del que se toque, en inglés.**
- **Los nombres del dominio se quedan en español** (`Oferta`, `Candidatura`,
  `autenticacion`, `ClavesPublicas`...). Son el lenguaje del negocio, una
  búsqueda de empleo en España, y el código usa las mismas palabras (lenguaje
  ubicuo). No se renombran.
- **Los comentarios antiguos no se traducen de golpe:** pasan a inglés cuando se
  toca ese fichero. Traducirlo todo de una vez llena el historial de ruido.
- **La documentación sigue bilingüe:** `README.md` en inglés y `README.es.md` en
  español, con los mismos datos.

## Un commit, una unidad de trabajo

Un commit tiene que poder explicarse en una frase y revertirse sin arrastrar
nada más. Si el mensaje necesita un "y además", son dos commits.

Los tests viajan **con** el código que prueban, en el mismo commit. Un commit que
añade comportamiento sin su test está incompleto.

## El mensaje dice POR QUÉ, no qué

El "qué" ya está en el diff. Lo que se pierde es el porqué, y es lo que hace falta
dentro de seis meses.

Formato [convencional](https://www.conventionalcommits.org/): `fix:`, `feat:`,
`refactor:`, `docs:`, `test:`, `chore:`, `ci:`.

**`test:` es para commits que son SOLO tests**, y conviene distinguir dos cosas
que no son lo mismo:

```
test: add test suite with TDD for input validation   <- el test fue primero
test: add missing tests for the happy path           <- rellenar un hueco despues
```

Las dos son legítimas, pero no son iguales, y el mensaje tiene que decir cuál es.
Llamar TDD a rellenar huecos es engañarte a ti misma dentro de seis meses.

```
fix(guardrails): `_tecnologias_en` estaba definida dos veces y ganaba la mala

Medido sobre las 519 combinaciones del catalogo, difieren en 9, todas con
tecnologias de VARIAS palabras, donde el espacio del medio no es caracter de
palabra:

  "react native"  =>  {React Native}          correcto
                  =>  {React, React Native}   ingenua, se inventa React
```

Cuando hay un número, va el número. "Mejora el rendimiento" no dice nada;
"de 22 segundos a 3" sí.

## Los tests siguen al código

Si mueves una función a otro módulo, los tests que la miran se actualizan **en el
mismo commit**. Y ojo con esto, que muerde:

```python
# Esto YA NO parchea nada si `call_llm_calidad` vive en otro módulo:
patch.object(servidor, "call_claude", ...)

# Hay que apuntar donde la función VIVE, no donde se reexporta:
patch.object(llm, "call_claude", ...)
```

## Nunca se toca un test para que pase

Se toca un test cuando **lo que prueba** ha cambiado, o cuando mira detalles
internos que se han movido. Nunca para tapar un fallo.

La diferencia es la que separa un refactor de un destrozo: durante la división de
`server.py` en seis módulos, los 175 tests pasaron sin que ninguno se relajara.

## Antes de dar algo por terminado

- La suite entera en verde, no solo lo tuyo
- La CI en verde en GitHub
- Si tocaste algo que se despliega, comprobarlo **en producción**, no en tu máquina

Lo último no es paranoia. Ese mismo día un arreglo estuvo verde en local durante
horas mientras producción seguía sirviendo el código de la víspera.

---

## Lo que comprueba la máquina y lo que no

| | Quién |
|---|---|
| La suite en verde antes de commitear | El hook `scripts/hooks/pre-commit` |
| La suite en verde en cada push y PR | GitHub Actions |
| Los modelos retirados, una vez por semana | Cron de la CI, lunes 06:00Z |
| Un commit por unidad de trabajo | Tú |
| El mensaje que dice por qué | Tú |
| Ver el test en rojo antes de arreglarlo | Tú |

Las tres últimas no se pueden automatizar. Por eso están escritas.
