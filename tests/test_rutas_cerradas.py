"""TDD - Rebanada cero: rutas que no pueden quedar abiertas al mundo.

Caso real (2oct2026), revisando cv-server antes de abrirlo a otras usuarias:

- `/debug` llamaba al LLM con la clave de la duena. Cualquiera que conociera la
  direccion le gastaba saldo, sin limite y sin dejar rastro.
- `/usuarios` devolvia nombre y email de las usuarias activas a quien lo pidiera,
  y el formulario de alta (ya retirado) tenia un enlace visible a ella.

`/debug` desaparece: lo que hacia ya lo dice `/health` sin gastar nada.
`/usuarios` exige la clave de maquina, la misma que llevaran despues las llamadas
de n8n (ADR-003). Sin clave configurada no abre nunca: falla cerrado.
"""
import pytest

import server as srv

CLAVE = "clave-de-prueba-larga-y-aleatoria"


class _RespuestaNotion:
    def raise_for_status(self):
        pass

    def json(self):
        return {"results": []}


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setattr(srv, "CLAVE_MAQUINA", CLAVE)
    monkeypatch.setattr(srv, "NOTION_DB_USUARIOS", "db-de-prueba")
    monkeypatch.setattr(srv.requests, "post", lambda *a, **k: _RespuestaNotion())
    with srv.app.test_client() as c:
        yield c


# ── /debug ──────────────────────────────────────────────

def test_debug_ya_no_existe(cliente):
    assert cliente.get("/debug").status_code == 404


def test_debug_no_llama_al_modelo(cliente, monkeypatch):
    llamadas = []
    monkeypatch.setattr(srv, "call_llm", lambda *a, **k: llamadas.append(a))
    cliente.get("/debug")
    assert llamadas == []


# ── /usuarios ───────────────────────────────────────────

def test_usuarios_sin_clave_responde_401(cliente):
    assert cliente.get("/usuarios").status_code == 401


def test_usuarios_con_clave_equivocada_responde_401(cliente):
    r = cliente.get("/usuarios", headers={"X-Clave-Maquina": "otra"})
    assert r.status_code == 401


def test_usuarios_con_la_clave_buena_responde(cliente):
    r = cliente.get("/usuarios", headers={"X-Clave-Maquina": CLAVE})
    assert r.status_code == 200
    assert r.get_json()["ok"] is True


def test_el_401_no_revela_datos(cliente):
    cuerpo = cliente.get("/usuarios").get_data(as_text=True)
    assert "@" not in cuerpo
    assert "usuarios" not in cuerpo.lower() or "error" in cuerpo.lower()


@pytest.mark.parametrize("configurada", ["", None])
def test_sin_clave_configurada_no_abre_nunca(monkeypatch, configurada):
    # Falla cerrado: si en Render falta la variable, la ruta no queda abierta,
    # ni siquiera para quien mande una cabecera vacia.
    monkeypatch.setattr(srv, "CLAVE_MAQUINA", configurada)
    monkeypatch.setattr(srv.requests, "post", lambda *a, **k: _RespuestaNotion())
    with srv.app.test_client() as c:
        assert c.get("/usuarios").status_code == 401
        assert c.get("/usuarios", headers={"X-Clave-Maquina": ""}).status_code == 401

