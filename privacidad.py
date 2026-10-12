"""Privacy rules for CV content (REQ-3.5): it never reaches a log or an exception message.

Generation logs (tests/test_registros_sin_datos_de_la_usuaria.py) carry no email, company or
position either: at most `etiqueta_opaca(email)` and the count of findings.

The rules, enforced by tests/test_privacidad_logs.py:
- Code that handles a CV (lectura_cv, rutas_alta, extraccion) logs the exception TYPE and
  a fixed label, never the exception text, the file name or any part of the document.
- Exceptions raised for the caller carry a fixed code, with no chained cause.
- The parsing libraries are kept quiet: their warnings can quote the document.

`volcar_registros` is the canary helper: it flattens every log record (message, args,
formatted exception, extra attributes) into one string so a test can assert that a
sentinel planted in a CV never appears in it.
"""
import hashlib
import hmac
import logging
import secrets
import traceback

_BIBLIOTECAS = ("pypdf", "docx", "lxml", "PIL", "fontTools")


def silenciar_bibliotecas() -> None:
    """Raise the level of the parsing libraries' loggers above CRITICAL."""
    for nombre in _BIBLIOTECAS:
        logging.getLogger(nombre).setLevel(logging.CRITICAL + 1)


silenciar_bibliotecas()


def tipo_de(error: BaseException) -> str:
    """The only thing about an exception that is safe to log: its class name."""
    return type(error).__name__


def registrar_fallo(logger: logging.Logger, etiqueta: str, error: BaseException) -> None:
    """Log a failure as `<label>: <ExceptionType>`; never the message or the traceback."""
    logger.error("%s: %s", etiqueta, tipo_de(error))


# Per-process key: the label correlates the lines of one process (CV and letter of the same
# mailbox) but cannot be reversed with a dictionary of emails, and it changes on every restart.
_CLAVE_DE_ETIQUETAS = secrets.token_bytes(32)


def etiqueta_opaca(valor: str) -> str:
    """A short opaque label for a value that must not be logged (a mailbox).

    Same value (case and surrounding spaces ignored), same label within a process; no way back
    to the value. Log this instead of the email, the company or the position.
    """
    huella = hmac.new(_CLAVE_DE_ETIQUETAS, (valor or "").strip().lower().encode(), hashlib.sha256)
    return huella.hexdigest()[:8]


def volcar_registros(registros) -> str:
    """Everything a set of `logging.LogRecord`s could expose, as one string (for canary tests)."""
    trozos = []
    for registro in registros:
        trozos.append(registro.name)
        trozos.append(str(registro.msg))
        trozos.append(repr(registro.args))
        try:
            trozos.append(registro.getMessage())
        except Exception:  # a malformed record must not hide the rest
            pass
        if registro.exc_info:
            trozos.extend(traceback.format_exception(*registro.exc_info))
        if registro.exc_text:
            trozos.append(registro.exc_text)
        if registro.stack_info:
            trozos.append(registro.stack_info)
        extras = set(vars(registro)) - set(vars(logging.makeLogRecord({})))
        trozos.extend(repr(getattr(registro, nombre)) for nombre in extras)
    return "\n".join(trozos)
