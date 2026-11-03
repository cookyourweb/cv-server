"""BYOK gate: trial consumption is committed, atomic, and the gate fails closed."""
import pytest

import base_de_datos
import byok
import server


class _Res:
    def __init__(self, fila=None):
        self._f = fila

    def first(self):
        return self._f

    def scalar_one(self):
        return 3

    rowcount = 1


class _Conn:
    def __init__(self, fila=None):
        self.sqls, self.fila = [], fila

    def execute(self, stmt, params=None):
        self.sqls.append(str(stmt))
        return _Res(self.fila)


def test_consumir_trial_is_one_atomic_update_returning():
    from repositorio import RepositorioDeUsuaria
    c = _Conn(fila=(2,))
    assert RepositorioDeUsuaria(c, "u1").consumir_trial() is True
    assert len(c.sqls) == 1
    sql = c.sqls[0].lower()
    assert "returning" in sql and "trial_generaciones > 0" in sql


def test_consumir_trial_false_when_no_row_updated():
    from repositorio import RepositorioDeUsuaria
    assert RepositorioDeUsuaria(_Conn(fila=None), "u1").consumir_trial() is False


class _Motor:
    def __init__(self):
        self.begin_usado = False

    def begin(self):
        self.begin_usado = True
        motor = self

        class _Ctx:
            def __enter__(s):
                return object()

            def __exit__(s, *a):
                return False
        return _Ctx()

    def connect(self):
        raise AssertionError("the gate must use begin() so the trial is committed")


def _preparar(monkeypatch, motor):
    monkeypatch.setattr(server, "CLAVE_MAQUINA", "k")
    monkeypatch.setattr(base_de_datos, "configurada", lambda: True)
    monkeypatch.setattr(base_de_datos, "motor", lambda: motor)
    monkeypatch.setattr(server, "buscar_usuario_por_email", lambda e: {"nombre": "D"})


def test_gate_uses_a_committing_transaction(monkeypatch):
    motor = _Motor()
    _preparar(monkeypatch, motor)
    monkeypatch.setattr(byok, "resolver_generacion_por_email",
                        lambda *a: {"permitido": False, "modo": "denegado", "motivo": "no"})
    r = server.app.test_client().post("/generar-cv", headers={"X-Clave-Maquina": "k"},
                                      json={"email": "a@b.com", "empresa": "A", "puesto": "D"})
    assert r.status_code == 403 and motor.begin_usado


def test_gate_fails_closed_when_the_database_breaks(monkeypatch):
    _preparar(monkeypatch, _Motor())

    def roto(*a):
        raise RuntimeError("db down")
    monkeypatch.setattr(byok, "resolver_generacion_por_email", roto)
    r = server.app.test_client().post("/generar-cv", headers={"X-Clave-Maquina": "k"},
                                      json={"email": "a@b.com", "empresa": "A", "puesto": "D"})
    assert r.status_code == 503


@pytest.mark.parametrize("email,conexion", [("", object()), ("a@b.com", None)])
def test_resolver_denies_without_user_or_connection(email, conexion):
    assert byok.resolver_generacion_por_email(email, conexion)["permitido"] is False


def test_resolver_denies_unknown_user(monkeypatch):
    import usuarias
    monkeypatch.setattr(usuarias, "id_por_emails", lambda e, c: None)
    assert byok.resolver_generacion_por_email("a@b.com", object())["permitido"] is False


def test_resolver_denies_when_lookup_raises(monkeypatch):
    import usuarias

    def roto(e, c):
        raise RuntimeError("x")
    monkeypatch.setattr(usuarias, "id_por_emails", roto)
    assert byok.resolver_generacion_por_email("a@b.com", object())["permitido"] is False


def test_resolver_uses_the_user_id_returned_by_id_por_emails(monkeypatch):
    import usuarias
    visto = {}
    monkeypatch.setattr(usuarias, "id_por_emails", lambda e, c: "uid-1")

    class _Repo:
        def __init__(self, c, uid):
            visto["uid"] = uid

        def tiene_clave_api(self, p):
            return False

        def consumir_trial(self):
            return True
    import repositorio
    monkeypatch.setattr(repositorio, "RepositorioDeUsuaria", _Repo)
    d = byok.resolver_generacion_por_email("A@B.com", object())
    assert visto["uid"] == "uid-1" and d["modo"] == "trial"


def test_repo_borrar_clave_api_deletes_the_row_scoped_to_the_user():
    from repositorio import RepositorioDeUsuaria
    c = _Conn()
    RepositorioDeUsuaria(c, "u1").borrar_clave_api("groq")
    sql = c.sqls[0].lower()
    assert "delete from claves_api" in sql and "usuario_id" in sql and "proveedor" in sql
