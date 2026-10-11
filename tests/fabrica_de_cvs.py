"""Tiny CV files built in memory, so the tests need no binary fixtures.

`pdf_con_texto` writes a minimal one-font PDF by hand (pypdf can read it back);
`docx_con_parrafos` uses python-docx; the hostile files (zip bomb, scanned PDF,
encrypted PDF) are built from the same pieces.
"""
import io
import zipfile

from docx import Document
from pypdf import PdfWriter

# A Spanish and an English CV body, each well above the 300-character threshold.
CV_ES = [
    "Desarrolladora frontend con experiencia en aplicaciones web de gran escala.",
    "Trabajo con Angular y TypeScript en equipos de producto desde hace muchos años.",
    "Lideré la migración de una aplicación heredada y mejoré el rendimiento del cliente.",
    "Me interesa el desarrollo de interfaces accesibles y el trabajo con diseño.",
]
CV_EN = [
    "Frontend developer with experience building large scale web applications.",
    "I work with Angular and TypeScript in product teams and I have done so for years.",
    "Led the migration of a legacy application and improved the performance for the client.",
    "I care about accessible interfaces and about working closely with the design team.",
]


def _escapar(linea: str) -> bytes:
    return linea.encode("cp1252").replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def pdf_con_texto(lineas, paginas: int = 1) -> bytes:
    """A valid PDF with `paginas` pages, each showing every line of `lineas`."""
    objetos = {}
    ids_paginas = [4 + 2 * n for n in range(paginas)]
    objetos[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objetos[2] = ("<< /Type /Pages /Kids [%s] /Count %d >>" % (
        " ".join(f"{i} 0 R" for i in ids_paginas), paginas)).encode()
    objetos[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    flujo = b"BT /F1 11 Tf 14 TL 40 780 Td\n" + b"".join(b"(" + _escapar(x) + b") Tj T*\n" for x in lineas) + b"ET"
    for id_pagina in ids_paginas:
        objetos[id_pagina] = (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            "/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % (id_pagina + 1)).encode()
        objetos[id_pagina + 1] = b"<< /Length %d >>\nstream\n" % len(flujo) + flujo + b"\nendstream"
    salida = io.BytesIO()
    salida.write(b"%PDF-1.4\n")
    posiciones = {}
    for numero in sorted(objetos):
        posiciones[numero] = salida.tell()
        salida.write(b"%d 0 obj\n" % numero + objetos[numero] + b"\nendobj\n")
    inicio = salida.tell()
    total = max(objetos) + 1
    salida.write(b"xref\n0 %d\n0000000000 65535 f \n" % total)
    for numero in range(1, total):
        salida.write(b"%010d 00000 n \n" % posiciones[numero])
    salida.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (total, inicio))
    return salida.getvalue()


def pdf_escaneado(paginas: int = 1) -> bytes:
    """Pages with no text layer, like a scan."""
    escritor = PdfWriter()
    for _ in range(paginas):
        escritor.add_blank_page(width=595, height=842)
    salida = io.BytesIO()
    escritor.write(salida)
    return salida.getvalue()


def pdf_cifrado() -> bytes:
    escritor = PdfWriter(clone_from=io.BytesIO(pdf_con_texto(CV_ES)))
    escritor.encrypt("secreto-de-prueba")
    salida = io.BytesIO()
    escritor.write(salida)
    return salida.getvalue()


def docx_con_parrafos(parrafos, celdas=()) -> bytes:
    documento = Document()
    for parrafo in parrafos:
        documento.add_paragraph(parrafo)
    if celdas:
        tabla = documento.add_table(rows=1, cols=len(celdas))
        for celda, texto in zip(tabla.rows[0].cells, celdas):
            celda.text = texto
    salida = io.BytesIO()
    documento.save(salida)
    return salida.getvalue()


def zip_con(archivos: dict) -> bytes:
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as z:
        for nombre, contenido in archivos.items():
            z.writestr(nombre, contenido)
    return salida.getvalue()


def docx_bomba(megas: int = 11) -> bytes:
    """A few KB on the wire that inflate to `megas` MB: has word/document.xml."""
    return zip_con({"word/document.xml": b"\x00" * (megas * 1024 * 1024)})
