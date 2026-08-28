"""TDD - los CVs generados NO pueden caer en la carpeta de masters.

Bug: `subir_cv_a_drive` usaba FOLDER_CV_MASTERS como destino, asi que cada CV
generado se mezclaba con los CV Master. A varios CVs por dia, la carpeta de
masters se vuelve inusable y el riesgo real es leer un master equivocado.
"""
from unittest.mock import MagicMock, patch

import cv_server_railway as srv


def _subir_y_capturar_parents():
    service = MagicMock()
    service.files().create().execute.return_value = {"id": "X", "webViewLink": "https://drive/x"}
    with patch.object(srv, "get_drive_service", return_value=service):
        srv.subir_cv_a_drive(b"contenido-docx", "cv-prueba.docx")
    # Ultima llamada real a create() con body
    for call in reversed(service.files().create.call_args_list):
        if "body" in call.kwargs:
            return call.kwargs["body"]["parents"]
    raise AssertionError("no se llamo a files().create con body")


def test_los_cvs_generados_van_a_la_carpeta_de_generados():
    assert _subir_y_capturar_parents() == [srv.FOLDER_CV_GENERADOS]


def test_los_cvs_generados_no_van_a_la_carpeta_de_masters():
    assert srv.FOLDER_CV_MASTERS not in _subir_y_capturar_parents()


def test_las_dos_carpetas_son_distintas():
    assert srv.FOLDER_CV_GENERADOS != srv.FOLDER_CV_MASTERS
