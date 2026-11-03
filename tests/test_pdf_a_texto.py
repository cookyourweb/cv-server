import pytest
from checker import normalizar_pdf_a_texto


def test_pdf_invalido():
    with pytest.raises(ValueError):
        normalizar_pdf_a_texto(b"esto no es pdf")