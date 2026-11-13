"""Code-side checks: what code decides after the model has answered.

The model reads; code checks what can be checked without judgment:

per email   (checks.check_record)
- a line whose text is nowhere in the email was invented: drop it and flag the email
- a line that exists only in hidden or struck-through content is not a request: drop it
- `source` names the body or a real attachment
- a vague amount is null; a number that is only a size or rating is not a quantity
- an action email whose attachment is missing, unreadable, encrypted or truncated is flagged

across the inbox   (checks.link_records)
- the same request sent twice: the later Date is the duplicate
- a revision points at the email it revises, when that email is in the inbox

Every test builds its own emails. None of them knows anything about dev.
"""

from __future__ import annotations

import json
from email.message import EmailMessage

import pytest

import fixtures as fx
from conftest import make_eml
from rfqinbox import checks, model, reader
from rfqinbox.record import make_record
from test_model import FakeClient, answer, run_parse


# ------------------------------------------------------------------ helpers

def line(raw, qty=1, uom="EA", source="body", description=None):
    return {"raw": raw, "description": description or raw, "qty": qty, "uom": uom, "source": source}


def packet(tmp_path, body, attachments=None, **kw):
    return reader.read_email(make_eml(tmp_path / "e.eml", body, attachments=attachments, **kw))


def checked(tmp_path, body, lines, attachments=None, classification="rfq", **record_kw):
    pk = packet(tmp_path, body, attachments)
    return checks.check_record(pk, make_record(classification, lines, **record_kw))


def raws(record):
    return [item["raw"] for item in record["line_items"]]


BODY = 'Please quote:\n10 ea 2" 90 elbow sch 40\n4 ea 3" gate valve 150#\nThanks, Pat'
ELBOW = line('10 ea 2" 90 elbow sch 40', 10)
VALVE = line('4 ea 3" gate valve 150#', 4)


# ================================================================== invented lines

def test_lines_found_in_the_email_are_left_alone(tmp_path):
    record = make_record("rfq", [ELBOW, VALVE])
    assert checks.check_record(packet(tmp_path, BODY), record) == record


def test_a_line_that_is_nowhere_in_the_email_is_dropped_and_the_email_flagged(tmp_path):
    invented = line('25 ft 6" seamless pipe A106B', 25, "FT")

    out = checked(tmp_path, BODY, [ELBOW, invented, VALVE])

    assert raws(out) == [ELBOW["raw"], VALVE["raw"]]
    assert out["needs_review"] is True
    assert "1 line" in out["review_reason"] and "not found" in out["review_reason"]


def test_matching_ignores_case_spacing_and_table_punctuation(tmp_path):
    """The model may join a table row's cells differently than the reader printed them."""
    body = "ITEM | QTY | DESCRIPTION\n1 | 10 | 2\" 90 Elbow, SCH 40"
    out = checked(tmp_path, body, [line('1  10  2" 90 ELBOW sch 40', 10)])
    assert len(out["line_items"]) == 1 and out["needs_review"] is False


def test_lines_rebuilt_from_quoted_history_count_as_found(tmp_path):
    """A revision or a PO reply takes lines from the earlier message in the thread."""
    body = ("Go ahead with item 2.\n\nOn Mon, 5 Oct 2026, Sam <sam@ridgeline-supply.example> wrote:\n"
            "> 1) 10 ea 2\" 90 elbow sch 40\n> 2) 4 ea 3\" gate valve 150#\n")
    out = checked(tmp_path, body, [VALVE], classification="purchase_order")
    assert raws(out) == [VALVE["raw"]] and out["needs_review"] is False


def test_lines_read_from_a_picture_cannot_be_checked_and_are_kept(tmp_path):
    photo = ("list.png", "image/png", fx.picture(900, 700, "handwritten list"))
    scan = ("rfq.pdf", "application/pdf", fx.scanned_pdf_bytes())
    lines = [line("12 EA 2in tee", 12, source="list.png"), line("6 EA 4in cap", 6, source="rfq.pdf")]

    out = checked(tmp_path, "Lists attached.", lines, attachments=[photo, scan])

    assert len(out["line_items"]) == 2 and out["needs_review"] is False


def test_an_invented_line_blamed_on_a_readable_attachment_is_still_dropped(tmp_path):
    sheet = fx.xlsx_bytes(lambda wb: wb.active.append(["10", "EA", '2" 90 elbow sch 40']))
    att = ("rfq.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", sheet)
    lines = [line('10 EA 2" 90 elbow sch 40', 10, source="rfq.xlsx"),
             line('300 FT 8" pipe sch 80', 300, "FT", source="rfq.xlsx")]

    out = checked(tmp_path, "RFQ attached.", lines, attachments=[att])

    assert raws(out) == ['10 EA 2" 90 elbow sch 40'] and out["needs_review"] is True


def test_when_every_line_was_invented_the_email_is_flagged_not_lost(tmp_path):
    out = checked(tmp_path, BODY, [line('300 FT 8" pipe sch 80', 300, "FT")])
    assert out["line_items"] == [] and out["needs_review"] is True and out["classification"] == "rfq"


# ================================================================== hidden and struck-through content

def workbook_with_old_revision(wb):
    from openpyxl.styles import Font

    ws = wb.active
    ws.title = "Rev B"
    ws.append(["QTY", "UOM", "DESCRIPTION"])
    ws.append([10, "EA", '2" 90 elbow sch 40'])
    ws.append([7, "EA", '1" union 3000#'])
    for cell in ws[3]:
        cell.font = Font(strike=True)
    ws.append([5, "EA", '4" blind flange 150#'])
    ws.row_dimensions[4].hidden = True
    old = wb.create_sheet("Rev A")
    old.append([99, "EA", '6" check valve 300#'])
    old.sheet_state = "hidden"


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def test_lines_only_in_hidden_or_struck_content_are_dropped(tmp_path):
    att = ("rfq.xlsx", XLSX, fx.xlsx_bytes(workbook_with_old_revision))
    lines = [line('10 EA 2" 90 elbow sch 40', 10, source="rfq.xlsx"),
             line('7 EA 1" union 3000#', 7, source="rfq.xlsx"),           # struck through
             line('5 EA 4" blind flange 150#', 5, source="rfq.xlsx"),     # hidden row
             line('99 EA 6" check valve 300#', 99, source="rfq.xlsx")]    # hidden sheet

    out = checked(tmp_path, "RFQ attached.", lines, attachments=[att])

    assert raws(out) == ['10 EA 2" 90 elbow sch 40']
    # These are not requests, so removing them is not a reason for a human to look.
    assert out["needs_review"] is False


def test_a_line_that_is_also_in_the_visible_content_is_kept(tmp_path):
    """The old revision usually repeats lines the current one still has."""
    def build(wb):
        wb.active.append([10, "EA", '2" 90 elbow sch 40'])
        old = wb.create_sheet("old")
        old.append([10, "EA", '2" 90 elbow sch 40'])
        old.sheet_state = "hidden"

    att = ("rfq.xlsx", XLSX, fx.xlsx_bytes(build))
    out = checked(tmp_path, "RFQ attached.", [line('10 EA 2" 90 elbow sch 40', 10, source="rfq.xlsx")],
                  attachments=[att])
    assert len(out["line_items"]) == 1


def test_struck_through_text_in_the_body_is_not_a_request(tmp_path):
    msg = EmailMessage()
    msg["From"], msg["To"] = "pat@customer.example", "rfq@ridgeline-supply.example"
    msg["Subject"], msg["Date"] = "Quote", "Mon, 05 Oct 2026 09:00:00 -0500"
    msg.set_content("see html")
    msg.add_alternative('<table><tr><td>10 ea 2" 90 elbow sch 40</td></tr>'
                        '<tr><td><s>4 ea 3" gate valve 150#</s></td></tr></table>', subtype="html")
    path = tmp_path / "e.eml"
    path.write_bytes(msg.as_bytes())

    out = checks.check_record(reader.read_email(path), make_record("rfq", [ELBOW, VALVE]))

    assert raws(out) == [ELBOW["raw"]]


# ================================================================== source

@pytest.mark.parametrize("given, expected", [
    ("body", "body"),
    ("rfq.xlsx", "rfq.xlsx"),
    ("RFQ.XLSX", "rfq.xlsx"),                       # wrong case
    ("attachment 1: rfq.xlsx", "rfq.xlsx"),         # decorated
    ("the spreadsheet", "rfq.xlsx"),                # made up: the text is in the attachment
    ("email", "rfq.xlsx"),
])
def test_source_is_the_body_or_a_real_attachment_name(tmp_path, given, expected):
    att = ("rfq.xlsx", XLSX, fx.xlsx_bytes(lambda wb: wb.active.append([10, "EA", '2" 90 elbow sch 40'])))
    out = checked(tmp_path, "RFQ attached.", [line('10 EA 2" 90 elbow sch 40', 10, source=given)],
                  attachments=[att])
    assert out["line_items"][0]["source"] == expected


def test_a_made_up_source_for_body_text_becomes_body(tmp_path):
    out = checked(tmp_path, BODY, [dict(ELBOW, source="message text")])
    assert out["line_items"][0]["source"] == "body"


# ================================================================== quantities

@pytest.mark.parametrize("raw", [
    'a couple of 2" ball valves',
    'a few 3/4" nipples',
    'some 1" pipe sch 80',
    'several 4" gaskets',
    'enough 2" pipe for the job',
    'a handful of 1/2" plugs',
])
def test_a_vague_amount_is_null_whatever_the_model_guessed(tmp_path, raw):
    out = checked(tmp_path, f"Need:\n{raw}\n", [line(raw, 2)])
    assert out["line_items"][0]["qty"] is None
    assert out["needs_review"] is False       # a vague amount is the request as written


@pytest.mark.parametrize("raw, qty", [
    ('2" 90 elbow sch 40', 2),            # the size
    ('2" 90 elbow sch 40', 40),           # the schedule
    ('3" gate valve 150#', 150),          # the rating
    ("pipe 21' lengths A53", 21),         # the length
    ('3/4" x 6" nipple sch 80', 6),       # a dimension
    ('1-1/2" union class 3000', 3000),    # the class
])
def test_a_number_that_is_only_a_size_or_rating_is_not_a_quantity(tmp_path, raw, qty):
    out = checked(tmp_path, f"Need:\n{raw}\n", [line(raw, qty)])
    assert out["line_items"][0]["qty"] is None
    # Not a reason for review: README keeps needs_review for emails that cannot be fully
    # read or resolved. The rep sees a blank quantity and fills it in.
    assert out["needs_review"] is False and out["review_reason"] is None


@pytest.mark.parametrize("raw, qty", [
    ('2 ea 2" 90 elbow sch 40', 2),       # the same number is also a count
    ('2" 90 elbow sch 40 - qty 40', 40),
    ('40 - 2" sch 40 nipples', 40),
    ('2" 90 elbow | 12 | EA', 12),
    ('two 2" ball valves', 2),            # spelled out
    ('2" ball valve', 3),                 # the count came from somewhere else (body, column header)
    ('(6) 6" 150# RF weld neck flanges', 6),
    ('3" 300# blind flange A105 x 8', 8),   # "x 8" after the item is a count, not a dimension
    ('8 x 3" 300# blind flange', 8),
])
def test_real_quantities_are_left_alone(tmp_path, raw, qty):
    out = checked(tmp_path, f"Need:\n{raw}\n", [line(raw, qty)])
    assert out["line_items"][0]["qty"] == qty and out["needs_review"] is False


# ================================================================== needs_review

PDF = "application/pdf"


@pytest.mark.parametrize("name, mime, data, word", [
    ("rfq.pdf", PDF, fx.encrypted_pdf_bytes(), "password"),
    ("rfq.pdf", PDF, b"%PDF-1.7 this is not really a pdf", "rfq.pdf"),
    ("rfq.xlsx", XLSX, b"PK\x03\x04 broken zip", "rfq.xlsx"),
    ("rfq.dwg", "application/octet-stream", b"AC1027 binary drawing", "rfq.dwg"),
    ("rfq.pdf", PDF, b"", "rfq.pdf"),
], ids=["encrypted", "corrupt-pdf", "corrupt-xlsx", "unsupported-type", "empty"])
def test_a_request_with_an_attachment_nobody_could_read_is_flagged(tmp_path, name, mime, data, word):
    out = checked(tmp_path, BODY + "\nFull list attached.", [ELBOW, VALVE], attachments=[(name, mime, data)])

    assert out["needs_review"] is True and word in out["review_reason"]
    assert raws(out) == [ELBOW["raw"], VALVE["raw"]]        # what could be read is still returned


def test_attached_is_mentioned_but_only_a_logo_came(tmp_path):
    logo = ("logo.png", "image/png", fx.picture(400, 60, "ACME"))
    out = checked(tmp_path, "Please quote the attached list.", [], attachments=[logo])
    assert out["needs_review"] is True and "attach" in out["review_reason"]


def test_attached_is_mentioned_and_nothing_came(tmp_path):
    out = checked(tmp_path, BODY + "\nSee attached drawing for the rest.", [ELBOW, VALVE])
    assert out["needs_review"] is True and len(out["line_items"]) == 2


def test_a_truncated_attachment_is_flagged(tmp_path):
    big = fx.text_pdf_bytes([[f"page {i} line item"] for i in range(reader.MAX_PDF_TEXT_PAGES + 3)])
    out = checked(tmp_path, "RFQ attached.", [line("page 1 line item", 1, source="rfq.pdf")],
                  attachments=[("rfq.pdf", PDF, big)])
    assert out["needs_review"] is True and "rfq.pdf" in out["review_reason"]


def test_a_readable_attachment_and_a_logo_need_no_review(tmp_path):
    sheet = ("rfq.xlsx", XLSX, fx.xlsx_bytes(lambda wb: wb.active.append([10, "EA", '2" 90 elbow sch 40'])))
    logo = ("logo.png", "image/png", fx.picture(400, 60, "ACME"))
    out = checked(tmp_path, "RFQ attached.", [line('10 EA 2" 90 elbow sch 40', 10, source="rfq.xlsx")],
                  attachments=[sheet, logo])
    assert out["needs_review"] is False


def test_the_models_own_reason_is_kept_when_code_adds_one(tmp_path):
    out = checked(tmp_path, BODY + "\nRest is attached.", [ELBOW], needs_review=True,
                  review_reason="Items 3-5 refer to a previous order.",
                  attachments=[("rfq.pdf", PDF, fx.encrypted_pdf_bytes())])
    assert "previous order" in out["review_reason"] and "password" in out["review_reason"]


@pytest.mark.parametrize("classification", ["vendor_quote", "status_inquiry", "auto_reply", "other"])
def test_emails_that_are_not_requests_are_never_flagged(tmp_path, classification):
    """README: needs_review is only for rfq, rfq_revision and purchase_order."""
    out = checked(tmp_path, "Out of office. See attached.", [], classification=classification,
                  attachments=[("x.pdf", PDF, fx.encrypted_pdf_bytes())])
    assert out == make_record(classification)


def test_check_record_does_not_change_its_input(tmp_path):
    record = make_record("rfq", [ELBOW, line('300 FT 8" pipe', 300, "FT")])
    before = json.dumps(record)
    checks.check_record(packet(tmp_path, BODY), record)
    assert json.dumps(record) == before


# ================================================================== across the inbox

def eml(inbox, stem, body, *, sender="Pat Buyer <pat@customer.example>", subject="Quote request",
        date="Mon, 05 Oct 2026 09:00:00 -0500", reply_to=None, references=None, message_id=None,
        attachments=None):
    msg = EmailMessage()
    msg["From"], msg["To"] = sender, "rfq@ridgeline-supply.example"
    msg["Subject"], msg["Date"] = subject, date
    msg["Message-ID"] = message_id or f"<{stem}@customer.example>"
    if reply_to:
        msg["In-Reply-To"] = reply_to
    if references:
        msg["References"] = references
    msg.set_content(body)
    for name, mime, data in attachments or []:
        maintype, subtype = mime.split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / f"{stem}.eml").write_bytes(msg.as_bytes())


class Scripted(FakeClient):
    """Replies by what the email says: {marker in the email: reply}."""

    def __init__(self, replies: dict):
        super().__init__()
        self.by_marker = replies

    def complete(self, messages, schema):
        self.calls.append(messages)
        sent = json.dumps(messages)
        for marker, reply in self.by_marker.items():
            if marker in sent:
                return model.Completion(text=reply, input_tokens=100, output_tokens=50)
        return model.Completion(text=answer("other"), input_tokens=100, output_tokens=50)


TWO_LINES = [ELBOW, VALVE]
MON, TUE, WED = (f"{d}, 0{n} Oct 2026 09:00:00 -0500" for d, n in (("Mon", 5), ("Tue", 6), ("Wed", 7)))


def parse(tmp_path, monkeypatch, replies):
    rc, data = run_parse(tmp_path, monkeypatch, Scripted(replies))
    assert rc == 0
    return data


def test_the_same_request_sent_twice_the_later_date_is_the_duplicate(tmp_path, monkeypatch, check_format):
    inbox = tmp_path / "inbox"
    # File names are in the opposite order to the dates: Date decides, not the file name.
    eml(inbox, "A1", "Resending in case it got lost. [second]\n" + BODY, date=TUE, subject="RESEND: Quote request")
    eml(inbox, "B2", "[first]\n" + BODY, date=MON)
    again = [dict(ELBOW, raw='10 EA  2" 90 Elbow SCH 40'), VALVE]     # the second reading differs slightly

    data = parse(tmp_path, monkeypatch, {"[first]": answer("rfq", TWO_LINES), "[second]": answer("rfq", again)})

    assert check_format.check(data) == []
    assert data["B2"]["duplicate_of"] is None and len(data["B2"]["line_items"]) == 2
    assert data["A1"] == {"classification": "rfq", "revises": None, "duplicate_of": "B2",
                          "needs_review": False, "review_reason": None, "line_items": []}


def test_three_copies_all_point_at_the_first(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    for stem, date in (("C", WED), ("A", MON), ("B", TUE)):
        eml(inbox, stem, f"[req]\n{BODY}", date=date)

    data = parse(tmp_path, monkeypatch, {"[req]": answer("rfq", TWO_LINES)})

    assert [data[s]["duplicate_of"] for s in "ABC"] == [None, "A", "A"]


def not_a_duplicate_cases():
    """(second email's headers, second email's body, first kind, second kind, second lines).
    The first email is always BODY from Pat, read as TWO_LINES."""
    more_elbows = line('12 ea 2" 90 elbow sch 40', 12)
    return {
        "different-sender": (dict(sender="Lee <lee@elsewhere.example>"), BODY, "rfq", "rfq", TWO_LINES),
        "different-kind": (dict(), BODY, "rfq", "purchase_order", TWO_LINES),      # they ordered what they asked for
        "different-quantity": (dict(), BODY.replace("10 ea", "12 ea"), "rfq", "rfq", [more_elbows, VALVE]),
        "extra-line": (dict(), BODY + "\n6 ea 4in cap", "rfq", "rfq", [*TWO_LINES, line("6 ea 4in cap", 6)]),
    }


@pytest.mark.parametrize("case", not_a_duplicate_cases().values(), ids=not_a_duplicate_cases().keys())
def test_similar_emails_that_are_not_the_same_request_are_both_kept(tmp_path, monkeypatch, case):
    second_kw, second_body, first_class, second_class, second_lines = case
    inbox = tmp_path / "inbox"
    eml(inbox, "A", "[first]\n" + BODY, date=MON)
    eml(inbox, "B", "[second]\n" + second_body, date=TUE, **second_kw)

    data = parse(tmp_path, monkeypatch, {"[first]": answer(first_class, TWO_LINES),
                                         "[second]": answer(second_class, second_lines)})

    assert data["A"]["duplicate_of"] is None and data["B"]["duplicate_of"] is None
    assert len(data["B"]["line_items"]) == len(second_lines)


def test_emails_with_no_lines_are_never_called_duplicates(tmp_path, monkeypatch):
    """Two requests nobody could read are two emails a human must look at, not one."""
    inbox = tmp_path / "inbox"
    eml(inbox, "A", "[req] see attached", date=MON)
    eml(inbox, "B", "[req] see attached", date=TUE)
    flagged = answer("rfq", [], needs_review=True, reason="attachment missing")

    data = parse(tmp_path, monkeypatch, {"[req]": flagged})

    assert all(d["duplicate_of"] is None and d["needs_review"] for d in data.values())


def test_a_revision_points_at_the_email_it_replies_to(tmp_path, monkeypatch, check_format):
    inbox = tmp_path / "inbox"
    eml(inbox, "E1", "[orig]\n" + BODY, date=MON, message_id="<orig-123@customer.example>")
    eml(inbox, "E2", "[rev] make the elbows 12\n\n> " + BODY.replace("\n", "\n> "), date=TUE,
        subject="Re: Quote request", reply_to="<orig-123@customer.example>")
    revised = [dict(ELBOW, raw='12 ea 2" 90 elbow sch 40', qty=12), VALVE]

    data = parse(tmp_path, monkeypatch, {"[rev]": answer("rfq_revision", revised),
                                         "[orig]": answer("rfq", TWO_LINES)})

    assert check_format.check(data) == []
    assert data["E2"]["revises"] == "E1" and data["E2"]["duplicate_of"] is None
    assert len(data["E2"]["line_items"]) == 2          # the complete order, not emptied
    assert data["E1"]["revises"] is None and data["E1"]["line_items"][0]["qty"] == 10


def test_a_revision_is_found_through_references_when_in_reply_to_is_missing(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    eml(inbox, "E1", "[orig]\n" + BODY, date=MON, message_id="<orig-123@customer.example>")
    eml(inbox, "E2", "[rev] drop the valve", date=TUE, subject="Re: Quote request",
        references="<older-000@customer.example> <orig-123@customer.example>")

    data = parse(tmp_path, monkeypatch, {"[rev]": answer("rfq_revision", [ELBOW]),
                                         "[orig]": answer("rfq", TWO_LINES)})

    assert data["E2"]["revises"] == "E1"


def test_a_revision_with_no_thread_headers_is_matched_by_subject_and_sender(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    eml(inbox, "E1", "[orig]\n" + BODY, date=MON, subject="Pricing - north tank farm")
    eml(inbox, "E2", "[other]\n" + BODY, date=MON, subject="Pricing - south tank farm")
    eml(inbox, "E3", "[rev] drop the valve", date=TUE, subject="RE: FW: Pricing - North Tank Farm")
    eml(inbox, "E4", "[late]\n" + BODY, date=WED, subject="Pricing - north tank farm",
        sender="Lee <lee@elsewhere.example>")

    data = parse(tmp_path, monkeypatch, {"[rev]": answer("rfq_revision", [ELBOW]),
                                         "[orig]": answer("rfq", TWO_LINES),
                                         "[other]": answer("rfq", TWO_LINES),
                                         "[late]": answer("rfq", TWO_LINES)})

    assert data["E3"]["revises"] == "E1"      # same subject and sender, earlier; not E2, not the later E4


def test_a_revision_of_something_not_in_the_inbox_has_no_link(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    eml(inbox, "E1", "[unrelated]\n" + BODY, date=MON, subject="Valves for unit 4",
        sender="Lee <lee@elsewhere.example>")
    eml(inbox, "E2", "[rev] make the elbows 12\n> " + BODY.replace("\n", "\n> "), date=TUE,
        subject="Re: Quote request", reply_to="<never-received@customer.example>")

    data = parse(tmp_path, monkeypatch, {"[rev]": answer("rfq_revision", TWO_LINES),
                                         "[unrelated]": answer("rfq", TWO_LINES)})

    assert data["E2"]["revises"] is None and data["E2"]["classification"] == "rfq_revision"


def test_only_revisions_get_a_revises_link(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    eml(inbox, "E1", "[orig]\n" + BODY, date=MON, message_id="<orig-123@customer.example>")
    eml(inbox, "E2", "[status] any update on this?", date=TUE, subject="Re: Quote request",
        reply_to="<orig-123@customer.example>")

    data = parse(tmp_path, monkeypatch, {"[status]": answer("status_inquiry"),
                                         "[orig]": answer("rfq", TWO_LINES)})

    assert data["E2"]["revises"] is None


def test_bad_dates_and_missing_headers_do_not_break_linking(tmp_path, monkeypatch, check_format):
    inbox = tmp_path / "inbox"
    eml(inbox, "A", "[req]\n" + BODY, date="not a date at all")
    eml(inbox, "B", "[req]\n" + BODY, date=MON)
    (inbox / "C.eml").write_bytes(b"")

    data = parse(tmp_path, monkeypatch, {"[req]": answer("rfq", TWO_LINES)})

    assert set(data) == {"A", "B", "C"} and check_format.check(data) == []
    # One of the two readable copies is kept with its lines; nothing is lost.
    assert sum(1 for s in "AB" if data[s]["line_items"]) == 1


def test_a_crash_while_linking_keeps_every_record(tmp_path, monkeypatch, check_format):
    inbox = tmp_path / "inbox"
    eml(inbox, "A", "[req]\n" + BODY, date=MON)
    eml(inbox, "B", "[req]\n" + BODY, date=TUE)

    def boom(*args, **kwargs):
        raise RuntimeError("simulated failure while linking")

    monkeypatch.setattr(checks, "link_records", boom)

    data = parse(tmp_path, monkeypatch, {"[req]": answer("rfq", TWO_LINES)})

    assert check_format.check(data) == []
    assert all(len(d["line_items"]) == 2 for d in data.values())


def test_checks_run_inside_parse(tmp_path, monkeypatch):
    """End to end: an invented line from the model does not reach parsed.json."""
    eml(tmp_path / "inbox", "E1", "[req]\n" + BODY)
    invented = line('300 FT 8" pipe sch 80', 300, "FT")

    data = parse(tmp_path, monkeypatch, {"[req]": answer("rfq", [ELBOW, invented])})

    assert raws(data["E1"]) == [ELBOW["raw"]] and data["E1"]["needs_review"] is True


# ================================================================== duplicates the model read differently

# The model reads each copy on its own, and two readings of the same content are not
# always identical. Whether the *content* is the same is something code can check
# without the model: the attached file is byte-for-byte the same, or the line is
# written in the other email too.

SHEET_LINES = [line('10 EA 2" 90 elbow sch 40', 10, source="rfq.xlsx"),
               line('4 EA 3" gate valve 150#', 4, source="rfq.xlsx")]


def sheet(name="rfq.xlsx"):
    def build(wb):
        wb.active.append([10, "EA", '2" 90 elbow sch 40'])
        wb.active.append([4, "EA", '3" gate valve 150#'])
    return (name, XLSX, fx.xlsx_bytes(build))


def test_same_attachment_read_differently_the_second_time_is_still_a_duplicate(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    att = sheet()
    eml(inbox, "A", "[first] RFQ attached.", date=MON, attachments=[att])
    eml(inbox, "B", "[second] Resending, same file attached again.", date=TUE, attachments=[att])
    second_reading = [SHEET_LINES[0], dict(SHEET_LINES[1], raw='4 EA 3" gate valve 150 lb')]

    data = parse(tmp_path, monkeypatch, {"[first]": answer("rfq", SHEET_LINES),
                                         "[second]": answer("rfq", second_reading)})

    assert data["B"]["duplicate_of"] == "A" and data["B"]["line_items"] == []
    assert len(data["A"]["line_items"]) == 2


def test_a_copy_the_model_read_less_of_is_still_a_duplicate(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    eml(inbox, "A", "[first]\n" + BODY, date=MON)
    eml(inbox, "B", "[second] sending again\n" + BODY, date=TUE)

    data = parse(tmp_path, monkeypatch, {"[first]": answer("rfq", TWO_LINES),
                                         "[second]": answer("rfq", [ELBOW])})      # missed the valve

    assert data["B"]["duplicate_of"] == "A"


def test_the_same_file_under_another_name_is_a_duplicate(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    eml(inbox, "A", "[first] RFQ attached.", date=MON, attachments=[sheet("rfq.xlsx")])
    eml(inbox, "B", "[second] RFQ attached.", date=TUE, attachments=[sheet("rfq (1).xlsx")])
    renamed = [dict(SHEET_LINES[0], source="rfq (1).xlsx")]                         # and one line short

    data = parse(tmp_path, monkeypatch, {"[first]": answer("rfq", SHEET_LINES),
                                         "[second]": answer("rfq", renamed)})

    assert data["B"]["duplicate_of"] == "A"


def test_a_re_saved_file_with_the_same_rows_is_a_duplicate(tmp_path, monkeypatch):
    """Different bytes (line endings), same content."""
    rows = 'QTY,UOM,DESCRIPTION\n10,EA,2" 90 elbow sch 40\n4,EA,3" gate valve 150#\n'
    inbox = tmp_path / "inbox"
    eml(inbox, "A", "[first] RFQ attached.", date=MON,
        attachments=[("rfq.csv", "text/csv", rows.encode())])
    eml(inbox, "B", "[second] RFQ attached.", date=TUE,
        attachments=[("rfq.csv", "text/csv", rows.replace("\n", "\r\n").encode())])
    lines = [dict(item, source="rfq.csv") for item in SHEET_LINES]

    data = parse(tmp_path, monkeypatch, {"[first]": answer("rfq", lines),
                                         "[second]": answer("rfq", lines[:1])})

    assert data["B"]["duplicate_of"] == "A"


def test_the_same_attachment_with_an_extra_item_in_the_body_is_a_new_request(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    att = sheet()
    eml(inbox, "A", "[first] RFQ attached.", date=MON, attachments=[att])
    eml(inbox, "B", "[second] RFQ attached again. Also add:\n6 ea 4in cap", date=TUE, attachments=[att])
    more = [*SHEET_LINES, line("6 ea 4in cap", 6)]

    data = parse(tmp_path, monkeypatch, {"[first]": answer("rfq", SHEET_LINES),
                                         "[second]": answer("rfq", more)})

    assert data["B"]["duplicate_of"] is None and len(data["B"]["line_items"]) == 3


def test_a_resend_that_drops_an_item_is_a_new_request(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    eml(inbox, "A", "[first]\n" + BODY, date=MON)
    eml(inbox, "B", '[second] corrected list\n10 ea 2" 90 elbow sch 40\nThanks, Pat', date=TUE)

    data = parse(tmp_path, monkeypatch, {"[first]": answer("rfq", TWO_LINES),
                                         "[second]": answer("rfq", [ELBOW])})

    assert data["B"]["duplicate_of"] is None and len(data["B"]["line_items"]) == 1


def test_a_changed_quantity_is_never_mistaken_for_a_different_reading(tmp_path, monkeypatch):
    """The new number also appears on the neighbouring line; that must not hide the change."""
    first = 'Please quote:\n10 ea 2" 90 elbow sch 40\n12 ea 3" gate valve 150#'
    second = 'Please quote:\n12 ea 2" 90 elbow sch 40\n12 ea 3" gate valve 150#'
    inbox = tmp_path / "inbox"
    eml(inbox, "A", "[first]\n" + first, date=MON)
    eml(inbox, "B", "[second]\n" + second, date=TUE)
    valve = line('12 ea 3" gate valve 150#', 12)

    data = parse(tmp_path, monkeypatch, {
        "[first]": answer("rfq", [ELBOW, valve]),
        "[second]": answer("rfq", [line('12 ea 2" 90 elbow sch 40', 12), valve])})

    assert data["B"]["duplicate_of"] is None
    assert data["B"]["line_items"][0]["qty"] == 12


# ================================================================== raw is one line: tags and nameplates

# README: raw is "the line's text as it appears where you found it". A tag or nameplate
# has several printed lines, and the model tends to return all of them joined. The prompt
# says not to; this is the code-side backstop. It keeps the line that carries the model,
# part, catalog or figure number. The description is not touched.

PHOTO = ("tag.jpg", "image/jpeg", fx.picture(900, 700, "a tag", fmt="JPEG"))


def tag_line(raw, qty=2):
    return line(raw, qty, source="tag.jpg", description="Orbex centrifugal pump CX-40-2, 6.5 in impeller, 3500 rpm")


@pytest.mark.parametrize("raw, expected", [
    ("ORBEX PUMP CO\nCENTRIFUGAL PUMP\nMODEL CX-40-2\nIMPELLER 6.5 IN\n3500 RPM", "MODEL CX-40-2"),
    ("ORBEX PUMP CO. CENTRIFUGAL PUMP MODEL: CX-40-2 IMPELLER: 6.5 IN SPEED: 3500 RPM", "MODEL: CX-40-2"),
    ("KELTON\nP/N 7741-KX\n1/2 NPT", "P/N 7741-KX"),
    ("STEAM TRAP\nCAT. NO. 88-204A\n150 PSI", "CAT. NO. 88-204A"),
    ("BRONZE GATE VALVE\nFIG. 1140B\nSIZE 2", "FIG. 1140B"),
    ("Type: gear pump Part No: GP-3310 Rating: 150 PSI", "Part No: GP-3310"),
], ids=["lines", "labelled-fields", "part-number", "catalog-number", "figure-number", "mixed-case"])
def test_a_tag_read_as_several_lines_keeps_only_the_identifying_one(tmp_path, raw, expected):
    out = checked(tmp_path, "Need two like the one in the picture.", [tag_line(raw)], attachments=[PHOTO])

    item = out["line_items"][0]
    assert item["raw"] == expected
    assert item["description"] == tag_line(raw)["description"] and item["qty"] == 2
    assert item["source"] == "tag.jpg" and out["needs_review"] is False


@pytest.mark.parametrize("raw", [
    "STEAM TRAP\n1/2 IN\n150 PSI",                    # several lines, but none identifies the item
    "MODEL YEAR\nUNKNOWN",                             # a label with no number after it
    "S/N 44817-22\nMFG 2019",                          # a serial number is this unit, not the item
], ids=["no-identifier", "label-without-number", "serial-only"])
def test_a_tag_with_no_identifying_line_is_left_as_the_model_read_it(tmp_path, raw):
    out = checked(tmp_path, "Need two like the one in the picture.", [tag_line(raw)], attachments=[PHOTO])
    assert out["line_items"][0]["raw"] == raw


@pytest.mark.parametrize("raw", [
    "12 EA 2in tee",                                    # one line of a handwritten list
    "Qty: 4  2in ball valve model BV-22",               # one line that happens to mention a model
    '3 | 22 | EA | 1" | ball valve',                    # one row of a scanned form
    "6 - model 4410 hose clamps",
])
def test_an_ordinary_line_from_a_picture_is_not_cut_down(tmp_path, raw):
    out = checked(tmp_path, "List attached.", [line(raw, 4, source="tag.jpg")], attachments=[PHOTO])
    assert out["line_items"][0]["raw"] == raw


def test_only_lines_read_from_pictures_are_cut_down(tmp_path):
    """Text the reader extracted can be checked against the email; it is never rewritten."""
    body = "Please quote:\nPump tag reads: Type: gear pump Part No: GP-3310 Rating: 150 PSI\n"
    raw = "Pump tag reads: Type: gear pump Part No: GP-3310 Rating: 150 PSI"
    out = checked(tmp_path, body, [line(raw, 1)])
    assert out["line_items"][0]["raw"] == raw
