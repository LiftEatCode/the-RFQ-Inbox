"""Builders for small synthetic attachments. Each one reproduces a *property* of
real inbox files (a hidden old revision, a scan with no text layer, a logo in a
signature) without copying any dev email.
"""

from __future__ import annotations

import io

from PIL import Image, ImageDraw


def xlsx_bytes(build) -> bytes:
    """build(workbook) fills an openpyxl Workbook; returns the .xlsx bytes."""
    import openpyxl

    wb = openpyxl.Workbook()
    build(wb)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def docx_bytes(build) -> bytes:
    import docx

    d = docx.Document()
    build(d)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def text_pdf_bytes(pages: list[list[str]]) -> bytes:
    """A PDF with a real text layer; one list of lines per page."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    for lines in pages:
        y = 740
        for line in lines:
            c.drawString(50, y, line)
            y -= 16
        c.showPage()
    c.save()
    return buf.getvalue()


def form_pdf_bytes(fields: dict[str, str], lines: list[str]) -> bytes:
    """A PDF with AcroForm text fields filled in, plus some page text."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    y = 740
    for line in lines:
        c.drawString(50, y, line)
        y -= 16
    for i, (name, value) in enumerate(fields.items()):
        c.acroForm.textfield(name=name, value=value, x=300, y=700 - 30 * i, width=200, height=20)
    c.showPage()
    c.save()
    return buf.getvalue()


def encrypted_pdf_bytes(password: str = "s3cret") -> bytes:
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(text_pdf_bytes([["CONFIDENTIAL RFQ"]]))))
    writer.encrypt(user_password=password, owner_password=password + "-owner")
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def picture(w: int, h: int, text: str = "", fmt: str = "PNG") -> bytes:
    im = Image.new("RGB", (w, h), "white")
    if text:
        ImageDraw.Draw(im).text((10, 10), text, fill="black")
    buf = io.BytesIO()
    im.save(buf, format=fmt)
    return buf.getvalue()


def scanned_pdf_bytes(n_pages: int = 1) -> bytes:
    """Image-only PDF (what a phone scanner app produces): no text layer at all."""
    pages = [Image.new("RGB", (850, 1100), (235, 235, 235)) for _ in range(n_pages)]
    for i, p in enumerate(pages):
        ImageDraw.Draw(p).text((60, 60), f"RFQ FORM page {i + 1}  12 EA 2in tee", fill="black")
    buf = io.BytesIO()
    pages[0].save(buf, format="PDF", save_all=True, append_images=pages[1:])
    return buf.getvalue()
