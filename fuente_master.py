"""Where the CV master comes from: the `FuenteDeMaster` port and its resolution order.

Two adapters read a master in one language:
- `MasterEnBase`: the encrypted master stored in Neon (AAD `cv_master:{usuario_id}:{idioma}`).
- the legacy Drive read (`drive.leer_cv_master_desde_drive`), wrapped by `MasterEnDrive`.

`resolver_master` is the only place that knows the order, so the generation routes carry
no ifs about where a master lives:

    Neon in the requested language -> Drive in that language -> Neon in the other
    language (`master_traducido=True`) -> empty

AI consent: a Neon master is only returned while the user has an active `enviar_cv_a_ia`
consent (both languages); otherwise the Neon sources are skipped like a missing master.

Legacy mode: without DATABASE_URL, or for a mailbox with no Neon user, there is no Neon
source and the result is exactly the Drive read, as before. A Neon failure (database down,
row that does not authenticate) degrades to the next source and logs only the exception
type; a Drive failure still propagates so the routes keep answering 502.

Who is the user: the generation routes are called by n8n with the machine key and the
user's mailbox. When the database is configured that mailbox is mapped to a user id
through `usuario_emails`. Decrypted CV text is never logged (see privacidad.py).
"""
import logging
from typing import NamedTuple, Optional

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

import base_de_datos
import cifrado
import drive
from privacidad import registrar_fallo
from repositorio import RepositorioDeUsuaria

logger = logging.getLogger(__name__)

IDIOMAS = ("es", "en")


class LecturaMaster(NamedTuple):
    """What one source read. Empty `texto` means "nothing in that language"."""
    texto: str
    url: str          # Drive URL actually read; empty for Neon
    idioma_real: str  # language of the master that was read


class MasterResuelto(NamedTuple):
    """Result of `resolver_master`. `master_traducido` is True when the master is in the
    other language than the one requested, so the guardrails can relax the checks that
    a translation breaks (C10)."""
    texto: str
    url: str
    idioma_real: str
    master_traducido: bool


def _otro(idioma: str) -> str:
    return "en" if idioma == "es" else "es"


class MasterEnBase:
    """The user's master stored encrypted in Neon. Never raises: any problem is "no master"."""

    def __init__(self, repo):
        self._repo = repo

    def leer(self, idioma: str) -> LecturaMaster:
        vacio = LecturaMaster("", "", idioma)
        try:
            # A stored master goes to the model, so it needs the same consent /extraccion
            # requires (active, current version). Fail closed on any error.
            if not self._repo.tiene_consentimiento("enviar_cv_a_ia"):
                logger.info("Master en base de datos omitido: falta el consentimiento enviar_cv_a_ia")
                return vacio
            fila = self._repo.obtener_cv(idioma)
            if fila is None:
                return vacio
            texto = cifrado.descifrar(fila.clave_version, bytes(fila.nonce), bytes(fila.cifrado),
                                      self._repo.usuario_id, idioma)
        except Exception as e:  # fail closed on this source, never leak the message
            registrar_fallo(logger, "Lectura del master en base de datos", e)
            return vacio
        return LecturaMaster(texto, "", idioma)


class MasterEnDrive:
    """The legacy master in Drive for a Notion user (`elegir_master` picks the file)."""

    def __init__(self, usuario_notion: dict, leer=None):
        self._usuario = usuario_notion
        self._leer = leer or drive.leer_cv_master_desde_drive

    def leer(self, idioma: str) -> LecturaMaster:
        master = self._leer(self._usuario, idioma)
        return LecturaMaster(master.texto, master.url, idioma)


class _RepoEfimero:
    """Repository that opens a short transaction per read, so no connection is held while
    a slow Drive call runs."""

    def __init__(self, usuario_id):
        self.usuario_id = usuario_id

    def obtener_cv(self, idioma):
        with base_de_datos.transaccion() as c:
            return RepositorioDeUsuaria(c, self.usuario_id).obtener_cv(idioma)

    def tiene_consentimiento(self, tipo):
        with base_de_datos.transaccion() as c:
            return RepositorioDeUsuaria(c, self.usuario_id).tiene_consentimiento(tipo)


def usuario_id_por_email(conexion, email: str):
    """The id of the user who owns this mailbox, or None."""
    return conexion.execute(
        text("SELECT usuario_id FROM usuario_emails WHERE email = :e"),
        {"e": email.strip().lower()}).scalar_one_or_none()


def base_para_email(email: str) -> Optional[MasterEnBase]:
    """The Neon source for this mailbox, or None (legacy mode, unknown mailbox, database down)."""
    if not base_de_datos.configurada() or not (email or "").strip():
        return None
    try:
        with base_de_datos.transaccion() as c:
            usuario_id = usuario_id_por_email(c, email)
    except (SQLAlchemyError, base_de_datos.ErrorDeBaseDeDatos) as e:
        registrar_fallo(logger, "Búsqueda de la usuaria en base de datos", e)
        return None
    return None if usuario_id is None else MasterEnBase(_RepoEfimero(usuario_id))


_AUTO = object()


def resolver_master(usuario: dict, idioma: str, email: str = "", *, base=_AUTO, leer_drive=None) -> MasterResuelto:
    """Resolve the master for a generation. `base` and `leer_drive` are injectable for tests;
    by default the Neon source is built from `email` and Drive is read with the legacy reader."""
    if base is _AUTO:
        base = base_para_email(email)
    en_drive = MasterEnDrive(usuario, leer_drive)

    if base is not None:
        lectura = base.leer(idioma)
        if lectura.texto:
            return MasterResuelto(lectura.texto, lectura.url, idioma, False)

    lectura = en_drive.leer(idioma)
    if lectura.texto or lectura.url:
        return MasterResuelto(lectura.texto, lectura.url, idioma, False)

    if base is not None:
        otro = _otro(idioma)
        lectura = base.leer(otro)
        if lectura.texto:
            return MasterResuelto(lectura.texto, lectura.url, otro, True)

    return MasterResuelto(lectura.texto, lectura.url, idioma, False)
