"""usuarias.id_por_emails: find the Neon user behind a Notion user's mailboxes. Read-only."""
import uuid

import pytest
from sqlalchemy import text

import usuarias
from test_migracion_0001 import _usuario, c, motor  # noqa: F401

pytestmark = pytest.mark.bd


def _correo(c, uid, email, principal=False):
    c.execute(text("INSERT INTO usuario_emails (email, usuario_id, principal) VALUES (:e, :u, :p)"),
              {"e": email, "u": uid, "p": principal})


def test_any_mailbox_of_the_account_finds_it_including_a_secondary_one(c):
    uid = _usuario(c)
    sufijo = uuid.uuid4().hex[:8]
    principal, segundo = f"p{sufijo}@ejemplo.es", f"s{sufijo}@ejemplo.es"
    _correo(c, uid, principal, True)
    _correo(c, uid, segundo)
    assert usuarias.id_por_emails([principal], c) == uid
    assert usuarias.id_por_emails(["nadie@ejemplo.es", segundo.upper()], c) == uid


def test_an_unknown_mailbox_is_none_and_nothing_is_created(c):
    antes = c.execute(text("SELECT count(*) FROM usuarios")).scalar_one()
    assert usuarias.id_por_emails([f"{uuid.uuid4().hex}@ejemplo.es"], c) is None
    assert usuarias.id_por_emails([], c) is None
    assert c.execute(text("SELECT count(*) FROM usuarios")).scalar_one() == antes
