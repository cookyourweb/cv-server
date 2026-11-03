import pytest
from byok import ErrorDeCifrado, resolver_generacion


class FakeRepo:
    def __init__(self, tiene=False, clave=None, invalid=False, trial=0):
        self._tiene = tiene
        self._clave = clave
        self._invalid = invalid
        self._trial = trial
        self.consumidos = 0

    def tiene_clave_api(self, proveedor):
        return self._tiene

    def obtener_clave_api(self, proveedor):
        if self._invalid:
            raise ErrorDeCifrado("invalid")
        return self._clave

    def trial_restante(self):
        return self._trial - self.consumidos

    def consumir_trial(self):
        if self._trial - self.consumidos <= 0:
            return False
        self.consumidos += 1
        return True


def test_resolver_con_key():
    repo = FakeRepo(tiene=True, clave="sk-ant-test")
    r = resolver_generacion(repo)
    assert r["permitido"]
    assert r["modo"] == "key"
    assert r["clave"] == "sk-ant-test"


def test_resolver_sin_key_con_trial():
    repo = FakeRepo(tiene=False, trial=3)
    r = resolver_generacion(repo)
    assert r["permitido"]
    assert r["modo"] == "trial"


def test_resolver_sin_key_ni_trial():
    repo = FakeRepo(tiene=False, trial=0)
    r = resolver_generacion(repo)
    assert not r["permitido"]
    assert r["modo"] == "denegado"


def test_resolver_clave_invalida():
    repo = FakeRepo(tiene=True, clave="broken", invalid=True)
    r = resolver_generacion(repo)
    assert not r["permitido"]
    assert r["motivo"] == "La clave guardada ya no es válida."