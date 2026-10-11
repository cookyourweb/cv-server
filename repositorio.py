"""Owner-scoped data access for the sign-up flow: profile, consent and account deletion.

`RepositorioDeUsuaria(conexion, usuario_id)` is built per request from the user id that
`@con_usuaria` resolved. Every statement filters by that id and no method accepts another
one, so a route cannot be written that reads or changes someone else's row (REQ-1.4).
A missing row is reported as None or False; the routes turn that into a 404 identical to
"does not exist".

The connection (and its transaction) belongs to the caller: nothing here commits.
"""
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints, field_validator
from sqlalchemy import text

# The consent text names every provider the CV may reach (Anthropic and Groq). When it
# changes in substance, bump the version: an older one stops authorising (REQ-2.2).
# The panel keeps the same constant in src/app/alta/dominio.ts.
VERSION_DE_CONSENTIMIENTO = "v1"
TIPOS_DE_CONSENTIMIENTO = ("almacenar_cv", "enviar_cv_a_ia")

_Texto = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
_Etiqueta = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
_Entero = Annotated[int, Field(strict=True)]


def _mayusculas(valor):
    return valor.strip().upper() if isinstance(valor, str) else valor


class PerfilEntrada(BaseModel):
    """The profile as the panel sends it (snake_case). Mirrors the CHECKs of `perfil`."""

    model_config = ConfigDict(extra="forbid")

    rol: _Texto
    anios_experiencia: Annotated[_Entero, Field(ge=0, le=60)]
    stack: Annotated[list[_Etiqueta], Field(max_length=50)]
    idiomas: Annotated[list[_Etiqueta], Field(max_length=20)]
    ubicacion: _Texto
    modalidad: Annotated[list[Literal["remoto", "hibrido", "presencial"]], Field(max_length=3)]
    salario_min: Annotated[_Entero, Field(ge=0, le=100_000_000)]
    salario_moneda: Annotated[str, BeforeValidator(_mayusculas), Field(pattern=r"^[A-Z]{3}$")]


class ConsentimientoEntrada(BaseModel):
    """A consent as the panel posts it. Only the current version is accepted: an old
    client must not record a consent that would never authorise anything (REQ-2.2)."""

    model_config = ConfigDict(extra="forbid", strict=True)

    tipo: Literal["almacenar_cv", "enviar_cv_a_ia"]
    version: str

    @field_validator("version")
    @classmethod
    def _version_vigente(cls, version: str) -> str:
        if version != VERSION_DE_CONSENTIMIENTO:
            raise ValueError("unknown consent version")
        return version


_CAMPOS = ("rol", "anios_experiencia", "stack", "idiomas", "ubicacion", "modalidad",
           "salario_min", "salario_moneda")


class RepositorioDeUsuaria:
    def __init__(self, conexion, usuario_id):
        self._c = conexion
        self._usuario_id = usuario_id

    # --- profile -------------------------------------------------------------------------

    def obtener_perfil(self):
        """The profile in the wire format, or None when there is none."""
        fila = self._c.execute(
            text(f"SELECT {', '.join(_CAMPOS)} FROM perfil WHERE usuario_id = :u"),
            {"u": self._usuario_id}).mappings().first()
        return None if fila is None else {campo: fila[campo] for campo in _CAMPOS}

    def guardar_perfil(self, perfil: PerfilEntrada) -> None:
        """Create or replace the profile."""
        self._c.execute(text("""
            INSERT INTO perfil (usuario_id, rol, anios_experiencia, stack, idiomas, ubicacion,
                                modalidad, salario_min, salario_moneda)
            VALUES (:u, :rol, :anios_experiencia, CAST(:stack AS text[]), CAST(:idiomas AS text[]),
                    :ubicacion, CAST(:modalidad AS text[]), :salario_min, :salario_moneda)
            ON CONFLICT (usuario_id) DO UPDATE SET
                rol = EXCLUDED.rol, anios_experiencia = EXCLUDED.anios_experiencia,
                stack = EXCLUDED.stack, idiomas = EXCLUDED.idiomas, ubicacion = EXCLUDED.ubicacion,
                modalidad = EXCLUDED.modalidad, salario_min = EXCLUDED.salario_min,
                salario_moneda = EXCLUDED.salario_moneda, actualizado_en = now()"""),
            {"u": self._usuario_id, **perfil.model_dump()})

    # --- consent ---------------------------------------------------------------------------

    def registrar_consentimiento(self, tipo: str, version: str) -> None:
        """Record a consent; recording the same (type, version) again changes nothing."""
        self._c.execute(
            text("INSERT INTO consentimientos (usuario_id, tipo, version) VALUES (:u, :t, :v) "
                 "ON CONFLICT (usuario_id, tipo, version) DO NOTHING"),
            {"u": self._usuario_id, "t": tipo, "v": version})

    def tiene_consentimiento(self, tipo: str) -> bool:
        """True only for a consent of the CURRENT version that was not revoked."""
        return self._c.execute(
            text("SELECT 1 FROM consentimientos WHERE usuario_id = :u AND tipo = :t AND version = :v "
                 "AND revocado_en IS NULL"),
            {"u": self._usuario_id, "t": tipo, "v": VERSION_DE_CONSENTIMIENTO}).first() is not None

    # --- CV master (stored encrypted; the content never leaves this class in plaintext) ----------

    def guardar_cv(self, idioma: str, formato: str, clave_version: int, nonce: bytes, cifrado: bytes,
                   caracteres: int) -> None:
        """Create or replace the master of one language."""
        self._c.execute(text("""
            INSERT INTO cv_master (usuario_id, idioma, formato, clave_version, nonce, cifrado, caracteres)
            VALUES (:u, :idioma, :formato, :clave_version, :nonce, :cifrado, :caracteres)
            ON CONFLICT (usuario_id, idioma) DO UPDATE SET
                formato = EXCLUDED.formato, clave_version = EXCLUDED.clave_version,
                nonce = EXCLUDED.nonce, cifrado = EXCLUDED.cifrado,
                caracteres = EXCLUDED.caracteres, subido_en = now()"""),
            {"u": self._usuario_id, "idioma": idioma, "formato": formato, "clave_version": clave_version,
             "nonce": nonce, "cifrado": cifrado, "caracteres": caracteres})

    def listar_cvs(self) -> list:
        """Metadata of her masters. Never the content, not even encrypted."""
        filas = self._c.execute(
            text("SELECT idioma, formato, subido_en FROM cv_master WHERE usuario_id = :u ORDER BY idioma"),
            {"u": self._usuario_id}).all()
        return [{"idioma": f.idioma, "formato": f.formato, "subido_en": f.subido_en.isoformat()} for f in filas]

    def cv_mas_reciente(self):
        """The encrypted row of her latest upload (idioma, clave_version, nonce, cifrado, caracteres), or None."""
        return self._c.execute(
            text("SELECT idioma, clave_version, nonce, cifrado, caracteres FROM cv_master "
                 "WHERE usuario_id = :u ORDER BY subido_en DESC, idioma LIMIT 1"),
            {"u": self._usuario_id}).first()

    def borrar_cv(self, idioma: str) -> bool:
        """Delete her master in `idioma`. False when she has none."""
        resultado = self._c.execute(
            text("DELETE FROM cv_master WHERE usuario_id = :u AND idioma = :i"),
            {"u": self._usuario_id, "i": idioma})
        return resultado.rowcount == 1

    # --- account deletion ----------------------------------------------------------------------

    def borrar_cuenta(self) -> bool:
        """Delete the user and everything she owns, in the caller's transaction.

        Each owned table is cleared explicitly and the user row last, so the result does
        not depend only on the FK cascade settings. Ledger rows (`extracciones`) are not
        deleted: the foreign key sets their `usuario_id` to NULL, which leaves an
        anonymous aggregate that keeps the spend cap and the one-extraction rule honest
        (REQ-2.4). Returns False when the user no longer exists.
        """
        for tabla in ("consentimientos", "cv_master", "perfil", "usuario_emails"):
            self._c.execute(text(f"DELETE FROM {tabla} WHERE usuario_id = :u"), {"u": self._usuario_id})
        return self._eliminar_usuaria()

    def _eliminar_usuaria(self) -> bool:
        resultado = self._c.execute(text("DELETE FROM usuarios WHERE id = :u"), {"u": self._usuario_id})
        return resultado.rowcount == 1
