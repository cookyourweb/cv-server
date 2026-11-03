"""Owner allowlist: the owner always generates, any other email keeps the fail-closed gate.

Only machine-key routes (/generar-cv, /generar-carta) reach the gate, so the allowlist
cannot be used by an anonymous caller.
"""
import byok


def test_owner_email_is_allowed_without_database(monkeypatch):
    monkeypatch.setenv("BYOK_PROPIETARIAS", "duena@example.com")
    decision = byok.resolver_generacion_por_email("Duena@Example.com ", None)
    assert decision["permitido"] is True and decision["modo"] == "propietaria"
    assert decision["clave"] is None


def test_owner_list_accepts_several_emails(monkeypatch):
    monkeypatch.setenv("BYOK_PROPIETARIAS", " uno@example.com , dos@example.com ")
    assert byok.resolver_generacion_por_email("dos@example.com", None)["permitido"] is True


def test_other_email_is_still_denied(monkeypatch):
    monkeypatch.setenv("BYOK_PROPIETARIAS", "duena@example.com")
    assert byok.resolver_generacion_por_email("otra@example.com", None)["permitido"] is False


def test_empty_or_missing_list_allows_nobody(monkeypatch):
    monkeypatch.delenv("BYOK_PROPIETARIAS", raising=False)
    assert byok.resolver_generacion_por_email("duena@example.com", None)["permitido"] is False
    monkeypatch.setenv("BYOK_PROPIETARIAS", "")
    assert byok.resolver_generacion_por_email("", None)["permitido"] is False
