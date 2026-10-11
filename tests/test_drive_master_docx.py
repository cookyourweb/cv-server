"""A DOCX master in Drive is read as text (regression: Document was never imported)."""
import io

import googleapiclient.http
from docx import Document as NuevoDocumento

import drive


def _docx(*parrafos):
    doc = NuevoDocumento()
    for p in parrafos:
        doc.add_paragraph(p)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


class _Peticion:
    def __init__(self, resultado):
        self._resultado = resultado

    def execute(self):
        return self._resultado


class _Archivos:
    def get(self, **_):
        return _Peticion({"mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                          "name": "master.docx"})

    def get_media(self, **_):
        return object()


class _Servicio:
    def files(self):
        return _Archivos()


def _descarga_falsa(contenido):
    class _Descarga:
        def __init__(self, buf, _req):
            self._buf = buf

        def next_chunk(self):
            self._buf.write(contenido)
            return None, True
    return _Descarga


def test_a_docx_master_is_read_as_its_paragraph_text(monkeypatch):
    monkeypatch.setattr(drive, "get_drive_service", lambda: _Servicio())
    monkeypatch.setattr(drive, "elegir_master", lambda usuario, idioma: ("id-falso", "https://example.test/master"))
    monkeypatch.setattr(googleapiclient.http, "MediaIoBaseDownload",
                        _descarga_falsa(_docx("Frontend senior", "Angular y React")))

    master = drive.leer_cv_master_desde_drive({}, "es")

    assert "Frontend senior" in master.texto and "Angular y React" in master.texto
