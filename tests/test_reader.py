"""The reader: one .eml -> a structured packet the model can read without guessing.

Every test builds its own small file with one property of real inbox mail.
"""

from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path

import pytest

import fixtures as fx
from conftest import make_eml
from rfqinbox import cli, reader


def write_msg(path: Path, msg: EmailMessage) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(msg.as_bytes())
    return path


def base_msg(subject="Quote request", sender="Pat Buyer <pat@customer.example>") -> EmailMessage:
    m = EmailMessage()
    m["From"] = sender
    m["To"] = "rfq@ridgeline-supply.example"
    m["Subject"] = subject
    m["Date"] = "Mon, 05 Oct 2026 09:00:00 -0500"
    m["Message-ID"] = "<x@test.example>"
    return m


def one_attachment(tmp_path, name, mime, data, body="See attached."):
    p = make_eml(tmp_path / "e.eml", body, attachments=[(name, mime, data)])
    pk = reader.read_email(p)
    assert len(pk.attachments) == 1
    return pk, pk.attachments[0]


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


# ------------------------------------------------------------------ headers and body

def test_headers_and_internal_sender(tmp_path):
    p = make_eml(tmp_path / "e.eml", "hi", sender="Rep <rep@ridgeline-supply.example>", subject="FW: list")
    pk = reader.read_email(p)
    assert pk.id == "e"
    assert pk.subject == "FW: list"
    assert pk.sender_internal is True
    assert reader.read_email(make_eml(tmp_path / "c.eml", "hi")).sender_internal is False


def test_reply_quote_is_split_from_new_text(tmp_path):
    body = (
        "Line 2 is now 14 instead of 10.\n\nThanks\n\n"
        "On Tue, Oct 6, 2026 at 8:47 AM Pat Buyer <pat@customer.example> wrote:\n"
        "> Need pricing on:\n> 1) 10 jts - 3\"\n> 2) 6 ea - 2\" tee\n"
    )
    pk = reader.read_email(make_eml(tmp_path / "e.eml", body, subject="Re: pricing"))
    assert "14 instead of 10" in pk.body_new
    assert "jts" not in pk.body_new
    assert len(pk.quoted) == 1
    q = pk.quoted[0]
    assert q.kind == "reply"
    assert "1) 10 jts - 3\"" in q.text  # '>' prefixes removed so lines read as written


def test_outlook_style_header_block_starts_a_quote(tmp_path):
    body = (
        "Any update on this?\n\nGwen\n\n"
        "From: Gwen Smith\nSent: Friday, October 2, 2026 10:15 AM\n"
        "To: RFQ Desk <rfq@ridgeline-supply.example>\nSubject: RFQ - skid\n\n"
        "10 ea - 6\" 90 elbow\n"
    )
    pk = reader.read_email(make_eml(tmp_path / "e.eml", body, subject="RE: RFQ - skid"))
    assert "90 elbow" not in pk.body_new
    assert pk.quoted and pk.quoted[0].kind == "reply"
    assert "90 elbow" in pk.quoted[0].text


def test_forwarded_original_message_is_labelled_forward(tmp_path):
    body = (
        "RFQ desk - please quote this.\n\n-----Original Message-----\n"
        "From: Buyer <b@customer.example>\nSent: Monday\nSubject: list\n\nList attached.\n"
    )
    pk = reader.read_email(make_eml(tmp_path / "e.eml", body, subject="FW: list"))
    assert pk.quoted[0].kind == "forward"
    assert "List attached" in pk.quoted[0].text
    assert "please quote" in pk.body_new


def test_plain_email_has_no_quote(tmp_path):
    pk = reader.read_email(make_eml(tmp_path / "e.eml", "Please quote 10 ea 2\" tee.\n\nThanks"))
    assert pk.quoted == []
    assert "10 ea" in pk.body_new


def test_html_table_with_spanning_header_keeps_header_and_rows(tmp_path):
    m = base_msg()
    m.set_content(
        "<p>Table below.</p><table><tr><th colspan='3'>316 SS - THREADED</th></tr>"
        "<tr><th>Qty</th><th>Description</th><th>Size</th></tr>"
        "<tr><td>10</td><td>90&deg; elbow</td><td>1/2&Prime;</td></tr></table>"
        "<p>Thanks</p>",
        subtype="html",
    )
    pk = reader.read_email(write_msg(tmp_path / "e.eml", m))
    assert "316 SS - THREADED" in pk.body_new
    row = next(l for l in pk.body_new.splitlines() if "elbow" in l)
    assert row.count("|") >= 2 and "10" in row and "1/2" in row
    table = [l for l in pk.body_new.splitlines() if l.startswith("|")]
    lines = pk.body_new.splitlines()
    assert lines.index(table[-1]) - lines.index(table[0]) == len(table) - 1  # rows are contiguous


def test_html_is_preferred_when_it_has_a_table(tmp_path):
    m = base_msg()
    m.set_content("Qty Description\n10 elbow")
    m.add_alternative("<table><tr><td>10</td><td>elbow</td></tr></table>", subtype="html")
    pk = reader.read_email(write_msg(tmp_path / "e.eml", m))
    assert any(l.count("|") >= 2 and "elbow" in l for l in pk.body_new.splitlines())


def test_html_strikethrough_is_marked(tmp_path):
    m = base_msg()
    m.set_content("<p>6 ea tee</p><p><s>3 ea ball valve</s></p>", subtype="html")
    pk = reader.read_email(write_msg(tmp_path / "e.eml", m))
    assert "~~3 ea ball valve~~" in pk.body_new


@pytest.mark.parametrize("body, expected", [
    ("BOM attached, need pricing by Thursday.", True),
    ("Please see the attachment.", True),
    ("Please quote 10 ea 2\" tee.", False),
    ("Please quote 10 ea tee.\n\nThis message and any attachments are confidential and intended "
     "only for the addressee.", False),
])
def test_mentions_attachment(tmp_path, body, expected):
    assert reader.read_email(make_eml(tmp_path / "e.eml", body)).mentions_attachment is expected


# ------------------------------------------------------------------ spreadsheets

def _bom_workbook(wb):
    ws = wb.active
    ws.title = "Rev B"
    ws["A1"] = "ALL FITTINGS BW SCH 40 UNLESS NOTED"
    ws.merge_cells("A1:D1")
    ws.append(["ITEM", "QTY", "SIZE", "DESCRIPTION"])
    ws.append([1, 12.0, '6"', "90 LR elbow"])
    ws.append([2, 4, '8"', "Cap"])
    from openpyxl.styles import Font
    for c in ws[4]:
        c.font = Font(strike=True)
    old = wb.create_sheet("Rev A (old)")
    old.append(["ITEM", "QTY", "SIZE", "DESCRIPTION"])
    old.append([1, 8, '6"', "90 LR elbow"])
    old.sheet_state = "hidden"


def test_xlsx_keeps_sheet_names_merged_header_rows_hidden_and_strike(tmp_path):
    _, att = one_attachment(tmp_path, "bom.xlsx", XLSX, fx.xlsx_bytes(_bom_workbook))
    t = att.text
    assert att.kind == "spreadsheet" and att.status == "ok"
    assert "Rev B" in t and "Rev A (old)" in t
    assert "ALL FITTINGS BW SCH 40 UNLESS NOTED" in t and "merged" in t.lower()
    rows = t.splitlines()
    assert any("| 1 | 12 |" in r and "90 LR elbow" in r for r in rows)  # 12.0 printed as 12
    assert any("~~" in r and "Cap" in r for r in rows)
    hidden_idx = t.index("Rev A (old)")
    assert "HIDDEN" in t[hidden_idx - 40: hidden_idx + 80]


def test_xlsx_hidden_rows_are_marked(tmp_path):
    def build(wb):
        ws = wb.active
        ws.append(["QTY", "DESCRIPTION"])
        ws.append([5, "visible tee"])
        ws.append([9, "old line"])
        ws.row_dimensions[3].hidden = True

    _, att = one_attachment(tmp_path, "l.xlsx", XLSX, fx.xlsx_bytes(build))
    line = next(l for l in att.text.splitlines() if "old line" in l)
    assert "HIDDEN" in line


def test_csv_rows_and_bom(tmp_path):
    data = '﻿Qty,UOM,Size,Description\n60,FT,"1-1/2""","Pipe, SCH 80"\n'.encode("utf-8")
    _, att = one_attachment(tmp_path, "list.csv", "text/csv", data)
    assert att.status == "ok"
    assert "| Qty | UOM |" in att.text
    assert any('1-1/2"' in l and "Pipe, SCH 80" in l for l in att.text.splitlines())


# ------------------------------------------------------------------ word

def test_docx_headings_stay_with_their_tables_in_order(tmp_path):
    def build(d):
        d.add_paragraph("Material list")
        d.add_heading("Carbon Steel Pipe - SCH 80", level=2)
        t = d.add_table(rows=2, cols=2)
        t.cell(0, 0).text, t.cell(0, 1).text = "Qty", "Size"
        t.cell(1, 0).text, t.cell(1, 1).text = "10 jts", '2"'
        d.add_heading("Socket Weld Fittings - 3000#", level=2)
        t2 = d.add_table(rows=2, cols=2)
        t2.cell(0, 0).text, t2.cell(0, 1).text = "Qty", "Item"
        t2.cell(1, 0).text, t2.cell(1, 1).text = "24", "90 elbow"
        p = d.add_paragraph()
        p.add_run("12 ea old union").font.strike = True

    _, att = one_attachment(tmp_path, "list.docx", DOCX, fx.docx_bytes(build))
    t = att.text
    assert att.kind == "document" and att.status == "ok"
    i_h1, i_pipe = t.index("Carbon Steel Pipe"), t.index("10 jts")
    i_h2, i_ell = t.index("Socket Weld Fittings"), t.index("90 elbow")
    assert i_h1 < i_pipe < i_h2 < i_ell
    assert "## Carbon Steel Pipe" in t
    assert "~~12 ea old union~~" in t


# ------------------------------------------------------------------ pdf

def test_text_pdf(tmp_path):
    pdf = fx.text_pdf_bytes([["REQUEST FOR QUOTATION", "Material: ASTM A105", "1 7 EA 1/2\" WELD NECK FLANGE"]])
    _, att = one_attachment(tmp_path, "rfq.pdf", "application/pdf", pdf)
    assert att.kind == "pdf" and att.status == "ok"
    assert "Material: ASTM A105" in att.text and "WELD NECK FLANGE" in att.text
    assert att.images == []


def test_pdf_form_fields_are_extracted(tmp_path):
    pdf = fx.form_pdf_bytes({"Material": "ASTM A105", "Rating": "150# RF"}, ["ITEM QTY SIZE"])
    _, att = one_attachment(tmp_path, "form.pdf", "application/pdf", pdf)
    assert "ASTM A105" in att.text and "150# RF" in att.text


def test_scanned_pdf_becomes_page_images(tmp_path):
    _, att = one_attachment(tmp_path, "scan.pdf", "application/pdf", fx.scanned_pdf_bytes(2))
    assert att.status == "scanned"
    assert len(att.images) == 2


def test_encrypted_pdf_is_detected_not_fatal(tmp_path):
    _, att = one_attachment(tmp_path, "secure.pdf", "application/pdf", fx.encrypted_pdf_bytes())
    assert att.status == "encrypted"
    assert att.images == []


def test_huge_pdf_is_capped_and_says_so(tmp_path):
    pages = [[f"page {i} line item {i}"] for i in range(1, 301)]
    _, att = one_attachment(tmp_path, "big.pdf", "application/pdf", fx.text_pdf_bytes(pages))
    assert "page 1 line item 1" in att.text
    assert "page 300 line item" not in att.text
    assert any("truncated" in n.lower() for n in att.notes)


def test_huge_scan_sends_a_capped_number_of_pages(tmp_path):
    _, att = one_attachment(tmp_path, "scan.pdf", "application/pdf", fx.scanned_pdf_bytes(15))
    assert 0 < len(att.images) <= reader.MAX_SCAN_PAGES
    assert any("truncated" in n.lower() for n in att.notes)


# ------------------------------------------------------------------ images

def test_photo_is_passed_to_the_model(tmp_path):
    _, att = one_attachment(tmp_path, "IMG_1.jpg", "image/jpeg", fx.picture(900, 700, "8 - 2in tee", "JPEG"))
    assert att.kind == "image" and att.status == "ok"
    assert len(att.images) == 1


def test_wide_short_image_is_flagged_as_logo_but_kept(tmp_path):
    _, att = one_attachment(tmp_path, "image001.png", "image/png", fx.picture(443, 64, "Acme Fab"))
    assert att.status == "logo"
    assert len(att.images) == 1  # still shown to the model, cheaply: shape alone can't prove it


def test_big_image_is_downscaled(tmp_path):
    from PIL import Image
    import io

    _, att = one_attachment(tmp_path, "big.png", "image/png", fx.picture(4000, 3000))
    w, h = Image.open(io.BytesIO(att.images[0])).size
    assert max(w, h) <= reader.MAX_IMAGE_SIDE


def test_inline_image_is_marked_inline(tmp_path):
    m = base_msg()
    m.set_content("Please price this: [cid:image002.png]")
    m.add_attachment(fx.picture(444, 210, "QTY UOM"), maintype="image", subtype="png",
                     filename="image002.png", disposition="inline", cid="<image002.png>")
    pk = reader.read_email(write_msg(tmp_path / "e.eml", m))
    assert pk.attachments[0].inline is True


# ------------------------------------------------------------------ attached emails, broken and odd files

def test_attached_email_is_read_recursively(tmp_path):
    inner = base_msg(subject="Quote request - 2in valves", sender="Desk <rfq@ridgeline-supply.example>")
    inner.set_content("1. 12 ea 2\" gate valve")
    outer = base_msg(subject="Delivery Status Notification (Failure)", sender="MAILER-DAEMON@mx.example")
    outer.set_content("Delivery failed permanently.")
    outer.add_attachment(inner, filename="original_message.eml")
    pk = reader.read_email(write_msg(tmp_path / "e.eml", outer))
    att = pk.attachments[0]
    assert att.kind == "email"
    assert "Quote request - 2in valves" in att.text and "12 ea 2\" gate valve" in att.text


@pytest.mark.parametrize("name, mime", [
    ("bom.xlsx", XLSX), ("list.docx", DOCX), ("rfq.pdf", "application/pdf"), ("pic.jpg", "image/jpeg"),
])
def test_corrupt_attachment_is_unreadable_not_fatal(tmp_path, name, mime):
    _, att = one_attachment(tmp_path, name, mime, b"this is not really a " + name.encode() * 50)
    assert att.status == "unreadable"
    assert att.notes  # says why


def test_empty_attachment(tmp_path):
    _, att = one_attachment(tmp_path, "list.xlsx", XLSX, b"")
    assert att.status == "empty"


def test_unknown_type_is_unsupported(tmp_path):
    _, att = one_attachment(tmp_path, "drawings.zip", "application/zip", b"PK\x03\x04" + b"\0" * 100)
    assert att.status == "unsupported"


def test_octet_stream_is_sniffed_by_extension(tmp_path):
    _, att = one_attachment(tmp_path, "list.csv", "application/octet-stream", b"Qty,Item\n4,tee\n")
    assert att.kind == "csv" and "| 4 | tee |" in att.text


def test_garbage_email_file_still_reads(tmp_path):
    p = tmp_path / "g.eml"
    p.write_bytes(bytes(range(256)) * 20)
    pk = reader.read_email(p)
    assert pk.id == "g"


# ------------------------------------------------------------------ render + inspect

def test_render_labels_every_part(tmp_path):
    body = "Please quote the attached.\n\nOn Mon, Oct 5, 2026 at 9:00 AM Rep wrote:\n> old list\n"
    p = make_eml(tmp_path / "e.eml", body, subject="Re: list",
                 attachments=[("bom.xlsx", XLSX, fx.xlsx_bytes(_bom_workbook))])
    out = reader.render(reader.read_email(p))
    assert "NEW MESSAGE" in out
    assert "QUOTED" in out and "old list" in out
    assert out.index("NEW MESSAGE") < out.index("QUOTED")
    assert "bom.xlsx" in out and "HIDDEN" in out
    assert "Subject: Re: list" in out


def test_render_says_when_sender_is_internal(tmp_path):
    p = make_eml(tmp_path / "e.eml", "pls quote", sender="Rep <rep@ridgeline-supply.example>")
    assert "Ridgeline" in reader.render(reader.read_email(p)).split("NEW MESSAGE")[0]


def test_inspect_command_prints_the_packet(tmp_path, capsys):
    p = make_eml(tmp_path / "e.eml", "Please quote 10 ea 2\" tee.")
    assert cli.main(["inspect", str(p)]) == 0
    out = capsys.readouterr().out
    assert "NEW MESSAGE" in out and "10 ea 2\" tee" in out
