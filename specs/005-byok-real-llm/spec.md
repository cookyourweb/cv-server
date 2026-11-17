# Spec 005 — Usar la clave real de la usuaria en llm.py

Estado: borrador

## Contexto
El gate BYOK ya decide `key`, `trial` o `denegado`, pero la llamada LLM sigue usando la key global.

## Objetivo
Usar la key propia de la usuaria (Anthropic) para generar CV/carta, con fallback a Groq y sin Gemini.

## Decisiones
- Anthropic directo con key del usuario.
- Groq solo fallback.
- No Gemini para invitadas.
- Trial: 3 usos con la key general, marcado antes de llamar.

## Requisitos
- RF-1: si `key`, llamar a Anthropic con esa key.
- RF-2: si `trial`, usar trial + fallback solo Groq.
- RF-3: si `denegado`, error controlado.
- RF-4: registrar modo y resultado.
- RF-5: no caer a clave global silenciosamente si la key es inválida.

## Criterios
- tests de key válida
- tests de key inválida
- tests de trial
- tests de fallback
- tests de denegado
