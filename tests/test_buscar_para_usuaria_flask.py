"""Flask route tests for /buscar-para-usuaria (regression for UnboundLocalError)."""
import server


def test_flask_buscar_para_usuaria_resuelve_por_email(monkeypatch):
    monkeypatch.setattr(server.base_de_datos, "configurada", lambda: True)

    class FakeConn:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(server.base_de_datos, "motor", lambda: type("M", (), {"begin": lambda self: FakeConn()})())
    from repositorio import RepositorioDeUsuaria
    monkeypatch.setattr(RepositorioDeUsuaria, "obtener_perfil", lambda self: None)
    import usuarias
    monkeypatch.setattr(usuarias, "id_por_emails", lambda emails, conexion: "uid-interno")
    # second call returns profile
    profiles = iter([None, {"rol": "Dev", "stack": ["react"], "modalidad": ["remoto"], "ubicacion": "Madrid", "salario_min": 50000}])
    monkeypatch.setattr(RepositorioDeUsuaria, "obtener_perfil", lambda self: next(profiles))
    import cuota
    monkeypatch.setattr(cuota, "es_exenta", lambda email: True)
    import real_jobs
    monkeypatch.setattr(real_jobs, "buscar_ofertas_reales", lambda **kw: {"ok": True, "ofertas": [], "total_encontradas": 0, "total_filtradas": 0})

    client = server.app.test_client()
    r = client.post("/buscar-para-usuaria", json={"usuario_id": "uid-notion", "email": "a@b.com", "top_n": 3}, headers={"X-Clave-Maquina": "test-clave"})
    # Should not 500; either 200 or 404/429 depending on mocks, but no UnboundLocalError
    assert r.status_code != 500
