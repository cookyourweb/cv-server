# ADR-004: LiteLLM se escribe y se deja apagado, no se adopta

**Estado:** Aceptado · 29 ago 2026
**Ámbito:** `cv-server`, módulo `llm.py`, variable de entorno `LLM_BACKEND`

> **Para quien retome esto (persona o IA):** este documento fija POR QUÉ la cascada
> de LLMs sigue siendo tres llamadas con `requests` en vez de LiteLLM, teniendo el
> adaptador de LiteLLM ya escrito y probado en el repo. Si vas a encenderlo, lee
> antes la sección "Los números". No se rechazó por desconocimiento: se midió.

---

## Contexto

`llm.py` resuelve la cascada Groq, Gemini y Claude con tres bloques de `requests`
escritos a mano, unas sesenta líneas. Cada bloque tiene su URL, su forma de sacar
el texto de una respuesta con una forma distinta, y su `try/except`.

Eso ha costado dinero real dos veces:

- **16 ago 2026:** Groq retiró `llama-3.3-70b-versatile`. El buscador estuvo diez
  días sin traer una sola oferta.
- **28 ago 2026:** se retiraron **tres modelos en un día** (Groq, y dos de Gemini).
- **28 ago 2026:** al extraer `llm.py` del monolito, el `import anthropic` se quedó
  atrás. La capa de calidad murió y **los CVs enviados los escribió el fallback**
  durante un día entero sin que nadie se enterase.

Los tres son el mismo problema de fondo: **mantener a mano la integración con
varios proveedores es trabajo recurrente y sus fallos son silenciosos.**

[LiteLLM](https://github.com/BerriAI/litellm) es la respuesta estándar del sector:
una sola llamada, nombres de modelo normalizados, `fallbacks` de serie, y una
librería que sigue los cambios de los proveedores por ti.

## El problema

LiteLLM no es gratis. Medido en este mismo repo, con la versión `1.98.0` instalada
en el venv de `cv-server`:

## Los números

| | cascada casera | con LiteLLM |
|---|---|---|
| Dependencias nuevas | 0 | litellm, openai, tokenizers, tiktoken |
| Disco | 0 MB | **+146 MB** (litellm 114, openai 20, tokenizers 8,8, tiktoken 3) |
| `import` del módulo | inmediato | **+5,96 s** |
| RAM del proceso | 9 MB | **207 MB** |

Cómo se midieron, para que se puedan repetir:

```bash
.venv/bin/python -c "from importlib.metadata import version; print(version('litellm'))"
du -sh .venv/lib/python3.14/site-packages/litellm
.venv/bin/python -c "
import os, resource, time
def mb(): return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024*1024)
base, t = mb(), time.time()
import litellm
print(f'{time.time()-t:.2f}s   {base:.0f} MB -> {mb():.0f} MB')
"
```

**Multiplicar por 23 la memoria del proceso y añadir seis segundos al arranque en
frío, para sustituir sesenta líneas que funcionan, no lo paga este servicio hoy.**
Es un servidor web pequeño, y ya se arregló un timeout el 28 de agosto porque una
petición tardaba 10,7 segundos contra un límite de 8.

## Decisión

**El adaptador se escribe, se prueba y se documenta. Se deja APAGADO.**

1. `llm.py` define un `Protocol` llamado `BackendLLM` con dos implementaciones:
   `CascadaCasera` (por defecto) y `CascadaLiteLLM`.
2. Se elige con la variable de entorno `LLM_BACKEND`. Un valor desconocido lanza
   `ValueError` y no degrada en silencio a otro backend.
3. **El `import litellm` vive DENTRO del método**, nunca al principio del módulo.
   Mientras nadie encienda el backend, el proceso no paga ni un byte.
4. `litellm` **no entra en `requirements.txt`**. Vive en
   `requirements-litellm.txt`, que solo se instala si se va a encender.

El contrato del punto 3 no depende de la buena voluntad de quien edite el fichero:
lo vigila `tests/test_backend_llm.py::test_importar_llm_no_carga_litellm`, que
arranca un proceso limpio y comprueba que `import llm` no mete `litellm` en
`sys.modules`.

## Cuándo encenderlo

Cuando se cumpla **cualquiera** de estas:

- El plan de alojamiento deja de tener la memoria justa, o el servicio deja de
  sufrir arranques en frío.
- Aparece un cuarto proveedor. A partir de ahí el coste de mantener la cascada a
  mano crece más rápido que el de la librería.
- Se necesita algo que la casera no da y LiteLLM sí: contabilidad de coste por
  llamada, reintentos con backoff, o enrutado por presupuesto.

Encenderlo es `pip install -r requirements-litellm.txt`, poner
`LLM_BACKEND=litellm` y reiniciar. Ni una línea de código.

## Consecuencias

**A favor**

- El coste de la decisión está medido y escrito, no intuido.
- Cambiar de backend deja de ser un refactor y pasa a ser una variable.
- El adaptador está probado hoy, así que el día que se encienda no se estrena.
- Segundo sitio del repo donde el principio abierto/cerrado se aplica de verdad,
  después del registro de guardrails.

**En contra**

- Hay dos caminos que mantener en vez de uno. Se acepta porque el segundo son
  quince líneas y está cubierto por tests.
- El backend apagado se prueba contra un doble de `litellm`, no contra la librería
  real. El día que se encienda hay que hacer una llamada de verdad antes de
  confiar en él.

## Ver también

- `llm.py`, docstring de `BackendLLM` (las tres formas de romper el contrato)
- `tests/test_backend_llm.py`
- `tests/test_capa_calidad.py` (el `import` que faltaba y por qué el fallback lo tapó)
- `ADR-002` (por qué el CV lo escribe Sonnet)
