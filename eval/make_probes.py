"""Builds the probe inbox: invented emails that are NOT the dev set.

    python eval/make_probes.py        ->  eval/probes/emails/P*.eml + eval/probes/answer_key.json

Why: dev is what the prompt and the checks were built against, so a good dev score
says little about emails nobody has seen. Every probe here is made up - companies,
people, part numbers, wording - and reproduces a *kind* of surprise from the brief
(section headings, a hidden old revision, a resend, a revision, a forward, a tag
photo, a phone scan, a bounce ...). They were written once, before the system was
run on them, and are scored with the same scorer as dev:

    python -m rfqinbox parse --emails eval/probes/emails --out eval/probes/parsed.json --cache eval/probes/cache
    python -m rfqinbox score eval/probes/parsed.json --key eval/probes/answer_key.json

Limits, stated plainly: the author of these probes also wrote the prompt, so they
test whether the rules generalise to new strings, not whether the rules are the
right ones. A probe that fails is a finding; fix the general property, never the probe.

Needs the dev requirements (reportlab) as well as the runtime ones.
"""

from __future__ import annotations

import io
import json
from email.message import EmailMessage
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "probes"
RFQ_DESK = "Ridgeline RFQ Desk <rfq@ridgeline-supply.example>"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

EMAILS: dict[str, EmailMessage] = {}
KEY: dict[str, dict] = {}


# ------------------------------------------------------------------ builders

MESSAGE_IDS = {"P01": "<20261103081200.a41c@tidewaterprocess.example>"}


def email(pid, sender, subject, date, body, *, attachments=(), reply_to=None, to=RFQ_DESK):
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"], msg["Date"] = sender, to, subject, date
    msg["Message-ID"] = MESSAGE_IDS.get(pid, f"<{pid.lower()}.20261100@probe.example>")
    if reply_to:
        msg["In-Reply-To"] = reply_to
        msg["References"] = reply_to
    msg.set_content(body)
    for name, mime, data in attachments:
        if mime == "message/rfc822":
            msg.add_attachment(data)
        else:
            maintype, subtype = mime.split("/", 1)
            msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    EMAILS[pid] = msg
    return msg


def key(pid, classification, lines=(), *, revises=None, duplicate_of=None, needs_review=False):
    KEY[pid] = {
        "classification": classification, "revises": revises, "duplicate_of": duplicate_of,
        "needs_review": needs_review,
        "line_items": [dict(id=f"{pid}-{n}", **ln) for n, ln in enumerate(lines, 1)],
    }


def ln(raw, qty, uom="EA", source="body", must=(), must_not=(), qty_tol=0):
    return {"raw": raw, "qty": qty, "qty_tol": qty_tol, "uom": uom, "source": source,
            "must_mention": list(must), "must_not_mention": list(must_not)}


def font(size):
    return ImageFont.load_default(size=size)


def png(im) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


# ------------------------------------------------------------------ P01  headings, a default, an override

P01_BODY = """Morning,

Please price the following for the boiler feed rework. All pipe to be SCH 80 A106B seamless unless noted.

PIPE
a) 8 lengths 1-1/2"
b) 5 lengths 2"
c) 3 lengths 3" SCH 40

FITTINGS - 3000# forged steel, socket weld
d) 16 - 1-1/2" 90 ell
e) 6 - 2" tee
f) four 1-1/2" couplings

VALVES
g) 2 ea 2" gate valve, class 800, SW ends

Thanks,
Dana

Dana Whitlock
Tidewater Process Services
"""
PIPE = ("pipe", "a106", "smls|seamless")
FIT = ("3000", "socket weld|sw")
P01_LINES = {
    "a": ln('a) 8 lengths 1-1/2"', 8, must=(*PIPE, "sch 80"), must_not=("3000",)),
    "b": ln('b) 5 lengths 2"', 5, must=(*PIPE, "sch 80"), must_not=("3000",)),
    "c": ln('c) 3 lengths 3" SCH 40', 3, must=(*PIPE, "sch 40"), must_not=("sch 80", "3000")),
    "d": ln('d) 16 - 1-1/2" 90 ell', 16, must=FIT, must_not=("sch 80", "a106")),
    "e": ln('e) 6 - 2" tee', 6, must=FIT, must_not=("sch 80", "a106")),
    "f": ln('f) four 1-1/2" couplings', 4, must=FIT, must_not=("sch 80", "a106")),
    "g": ln('g) 2 ea 2" gate valve, class 800, SW ends', 2, must=("gate", "800"),
            must_not=("3000", "sch 80", "a106")),
}
email("P01", "Dana Whitlock <dwhitlock@tidewaterprocess.example>", "Pricing request - boiler feed rework",
      "Tue, 03 Nov 2026 08:12:00 -0600", P01_BODY)
key("P01", "rfq", P01_LINES.values())

# ------------------------------------------------------------------ P02  unsolicited promo

email("P02", "Brazos Valve Outlet <deals@brazosvalveoutlet.example>",
      "November clearance: ball valves from $9", "Tue, 03 Nov 2026 05:00:00 -0600", """NOVEMBER CLEARANCE - overstock must go

Brass ball valve, full port, 600 WOG, threaded
  1/2"   $9.10
  3/4"   $12.45
  1"     $18.90
Bronze gate valve, class 125, threaded
  1"     $27.00
  2"     $61.50

Quantities limited. Order online or call 979-555-0117.

You are on this list because you requested a catalog. Reply STOP to opt out.
Brazos Valve Outlet, 410 Depot St, Bryan TX
""")
key("P02", "other")

# ------------------------------------------------------------------ P03  a supplier answering our request

email("P03", "Lena Ortiz <lortiz@coastalforge.example>", "RE: Ridgeline RFQ R-5521 - forged fittings",
      "Tue, 03 Nov 2026 14:40:00 -0600", """Priya,

Per your request, pricing and delivery below. Quote CF-90417, valid 15 days, FOB our dock.

1) 150 ea 1" 3000# SW 90 ell A105 - $4.12 ea - stock
2) 80 ea 1" 3000# SW tee A105 - $5.60 ea - stock
3) 40 ea 2" 3000# SW coupling A105 - $7.95 ea - 2 weeks

Let me know if you want to release.

Lena Ortiz
Coastal Forge & Fitting

On Mon, Nov 2, 2026 at 3:15 PM Priya Nair <pnair@ridgeline-supply.example> wrote:
> Lena, please quote price and delivery:
> 150 ea 1" 3000# SW 90 ell A105
> 80 ea 1" 3000# SW tee A105
> 40 ea 2" 3000# SW coupling A105
""")
key("P03", "vendor_quote")

# ------------------------------------------------------------------ P04  status, P05  out of office

email("P04", "Theo Lindqvist <tlindqvist@prairiewindethanol.example>", "Q-26-1187",
      "Wed, 04 Nov 2026 09:05:00 -0600", """Hi,

Any update on quote Q-26-1187? I need the lead time on the basket strainers before our Thursday meeting.

Theo
""")
key("P04", "status_inquiry")

email("P05", "Marta Kowalczyk <mkowalczyk@ironwoodpackaging.example>", "Automatic reply: Quote Q-26-1203",
      "Wed, 04 Nov 2026 09:06:00 -0600", """I am out of the office through Monday November 16 with limited access to email.

For urgent orders please contact the storeroom at 555-0164.

Marta Kowalczyk
Ironwood Packaging
""")
key("P05", "auto_reply")

# ------------------------------------------------------------------ P06  spreadsheet: merged header, struck row, hidden old revision
# ------------------------------------------------------------------ P07  the same request sent again


def bom_workbook() -> bytes:
    import openpyxl
    from openpyxl.styles import Font

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "BOM Rev 2"
    ws.append(["ALL FITTINGS BLACK MALLEABLE IRON 150# THREADED"])
    ws.merge_cells("A1:D1")
    ws.append(["ITEM", "QTY", "UOM", "DESCRIPTION"])
    ws.append([1, 24, "EA", '1" 90 elbow'])
    ws.append([2, 12, "EA", '1" tee'])
    ws.append([3, 6, "EA", '1-1/4" union'])
    for cell in ws[5]:
        cell.font = Font(strike=True)
    ws.append([4, 10, "EA", '1-1/4" x 1" reducing coupling'])
    ws.append([5, 40, "FT", '1" pipe SCH 40 A53B T&C'])
    ws.append(["", "", "", "TOTAL LINES: 4"])
    old = wb.create_sheet("Rev 1 (superseded)")
    old.append(["ITEM", "QTY", "UOM", "DESCRIPTION"])
    old.append([1, 30, "EA", '3/4" 90 elbow'])
    old.append([2, 18, "EA", '3/4" tee'])
    old.append([3, 60, "FT", '3/4" pipe SCH 40'])
    old.sheet_state = "hidden"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


BOM = bom_workbook()
BOM_NAME = "BOM_NG-7730.xlsx"
MI = ("malleable|mi", "150", "threaded|npt|thd")
email("P06", "Omar Reyes <oreyes@northgatemech.example>", "RFQ NG-7730 hydronic piping",
      "Wed, 04 Nov 2026 10:30:00 -0600", "Hi,\n\nBill of material attached for pricing.\n\nThanks\nOmar\n",
      attachments=[(BOM_NAME, XLSX, BOM)])
key("P06", "rfq", [
    ln('1 | 24 | EA | 1" 90 elbow', 24, source=BOM_NAME, must=MI),
    ln('2 | 12 | EA | 1" tee', 12, source=BOM_NAME, must=MI),
    ln('4 | 10 | EA | 1-1/4" x 1" reducing coupling', 10, source=BOM_NAME, must=MI),
    ln('5 | 40 | FT | 1" pipe SCH 40 A53B T&C', 40, "FT", source=BOM_NAME,
       must=("pipe", "sch 40", "a53"), must_not=("malleable",)),
])
email("P07", "Omar Reyes <oreyes@northgatemech.example>", "2nd try - RFQ NG-7730 hydronic piping",
      "Thu, 05 Nov 2026 07:50:00 -0600",
      "Sending this again, I am not sure yesterday's went through. Same BOM attached, nothing changed.\n\nOmar\n",
      attachments=[(BOM_NAME, XLSX, BOM)])
key("P07", "rfq", duplicate_of="P06")

# ------------------------------------------------------------------ P08  a revision of P01

QUOTED_P01 = "\n".join("> " + line for line in P01_BODY.strip().splitlines())
email("P08", "Dana Whitlock <dwhitlock@tidewaterprocess.example>", "Re: Pricing request - boiler feed rework",
      "Wed, 04 Nov 2026 16:22:00 -0600", f"""Dana here again - a few changes before you price it:

- item b should be 7 lengths, not 5
- cancel the couplings (f), the contractor is supplying those
- please add 4 ea 3" 150# RF weld neck flanges, A105

Everything else stays as sent.

On Tue, Nov 3, 2026 at 8:12 AM Dana Whitlock <dwhitlock@tidewaterprocess.example> wrote:
{QUOTED_P01}
""", reply_to=MESSAGE_IDS["P01"])
key("P08", "rfq_revision", [
    P01_LINES["a"],
    dict(P01_LINES["b"], qty=7),
    P01_LINES["c"], P01_LINES["d"], P01_LINES["e"], P01_LINES["g"],
    ln('please add 4 ea 3" 150# RF weld neck flanges, A105', 4, must=("weld neck|wn", "150", "a105"),
       must_not=("3000", "sch 80")),
], revises="P01")

# ------------------------------------------------------------------ P09  a PO that accepts part of our quote

email("P09", "Hal Brennan <hbrennan@cypressbend.example>", "RE: Quote Q-26-1191", "Thu, 05 Nov 2026 11:02:00 -0600",
      """Priya,

Please proceed with lines 1 and 3 only. PO 88213, ship to the plant. Hold off on the strainer for now.

Hal

From: Priya Nair <pnair@ridgeline-supply.example>
Sent: Wednesday, November 4, 2026 2:10 PM
To: Hal Brennan <hbrennan@cypressbend.example>
Subject: Quote Q-26-1191

Hal, pricing as requested:

1) 6 ea 4" butterfly valve, lug style, 150#, ductile iron body - $212.00 ea
2) 2 ea 4" Y-strainer, 150# flanged, cast iron - $388.00 ea
3) 12 ea 4" full face gasket, 1/8" EPDM - $6.40 ea

Total $2,125.60. Valid 30 days.
""")
key("P09", "purchase_order", [
    ln('1) 6 ea 4" butterfly valve, lug style, 150#, ductile iron body - $212.00 ea', 6,
       must=("butterfly", "lug", "150"), must_not=("strainer",)),
    ln('3) 12 ea 4" full face gasket, 1/8" EPDM - $6.40 ea', 12, must=("gasket", "epdm"),
       must_not=("strainer",)),
])

# ------------------------------------------------------------------ P10  our own rep forwards a customer, with a note

email("P10", "Priya Nair <pnair@ridgeline-supply.example>", "FW: need a price", "Thu, 05 Nov 2026 13:45:00 -0600",
      """Team - from Glenrock, please quote. He called afterwards and wants two more of the check valves, so 5 total.

---------- Forwarded message ----------
From: Sam Otero <sotero@glenrockdairy.example>
Date: Thu, Nov 5, 2026 at 12:58 PM
Subject: need a price
To: Priya Nair <pnair@ridgeline-supply.example>

Hi Priya,

Need a price on these for the CIP skid:
3 - 2" swing check valve, 316SS, 150# flanged
10 - 2" 150# ring gaskets, PTFE

Sam
""")
key("P10", "rfq", [
    ln('3 - 2" swing check valve, 316SS, 150# flanged', 5, must=("check", "316", "150")),
    ln('10 - 2" 150# ring gaskets, PTFE', 10, must=("gasket", "ptfe", "150")),
])

# ------------------------------------------------------------------ P11  "attached" but only a logo came


def logo() -> bytes:
    im = Image.new("RGB", (420, 70), (20, 60, 110))
    ImageDraw.Draw(im).text((14, 18), "HARBORLINE MARINE", fill="white", font=font(30))
    return png(im)


email("P11", "Ines Varga <ivarga@harborlinemarine.example>", "dock repair material",
      "Fri, 06 Nov 2026 08:20:00 -0600",
      "Good morning,\n\nMaterial list for the dock repair is attached, need pricing by Friday.\n\nInes Varga\nHarborline Marine\n",
      attachments=[("image001.png", "image/png", logo())])
key("P11", "rfq", needs_review=True)

# ------------------------------------------------------------------ P12  a photo of a tag, quantity in the body


def tag_photo() -> bytes:
    im = Image.new("RGB", (1000, 700), (92, 88, 80))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((90, 80, 910, 620), radius=24, fill=(206, 204, 196), outline=(60, 60, 60), width=4)
    y = 110
    for text, size in [("DELMAR CONTROLS", 54), ("PRESSURE REGULATOR", 40), ("MODEL  DR-250-B", 44),
                       ("SIZE  1 IN NPT", 40), ("INLET MAX  300 PSI", 40), ("SPRING RANGE  25-75 PSI", 40),
                       ("BODY  BRASS", 40)]:
        d.text((130, y), text, fill=(25, 25, 25), font=font(size))
        y += size + 26
    buf = io.BytesIO()
    im.rotate(-2.5, expand=False, fillcolor=(92, 88, 80)).save(buf, format="JPEG", quality=82)
    return buf.getvalue()


email("P12", "Curt Maddox <curt@maddoxgin.example>", "replacement regulator", "Fri, 06 Nov 2026 12:31:00 -0600",
      "Need four like the one on this tag. Whats your lead time\n\nCurt\n\nSent from my phone\n",
      attachments=[("IMG_2291.jpg", "image/jpeg", tag_photo())])
key("P12", "rfq", [ln("MODEL DR-250-B", 4, source="IMG_2291.jpg",
                      must=("regulator", "brass", "1 in|1\"|1 inch", "25-75|25 to 75"))])

# ------------------------------------------------------------------ P13  a phone scan of a form: small text, section rows

SCAN_NAME = "scan_rfq_0412.pdf"
SCAN_ROWS = [
    ("BALL VALVES - 2 PC BRASS, 600 WOG, THREADED", None),
    (1, 14, "EA", '1/2"', "ball valve"), (2, 9, "EA", '3/4"', "ball valve"), (3, 22, "EA", '1"', "ball valve"),
    (4, 7, "EA", '1-1/4"', "ball valve"), (5, 11, "EA", '1-1/2"', "ball valve"), (6, 3, "EA", '2"', "ball valve"),
    ("Y-STRAINERS - CAST IRON, 125#, THREADED", None),
    (7, 5, "EA", '1"', "Y-strainer"), (8, 8, "EA", '1-1/2"', "Y-strainer"), (9, 13, "EA", '2"', "Y-strainer"),
    ("HOSE - EPDM, 150 PSI", None),
    (10, 75, "FT", '3/4"', "water hose"), (11, 120, "FT", '1"', "water hose"),
]


def scan_pdf() -> bytes:
    im = Image.new("RGB", (1700, 2200), (236, 234, 228))
    d = ImageDraw.Draw(im)
    d.text((110, 110), "RIDGECREST FOODS - REQUEST FOR QUOTATION", fill="black", font=font(44))
    d.text((110, 180), "RFQ No. 0412      Date 11/06/2026      Buyer B. Tran", fill="black", font=font(30))
    cols, y = [110, 250, 400, 560, 800], 290
    for x, head in zip(cols, ["ITEM", "QTY", "UOM", "SIZE", "DESCRIPTION"]):
        d.text((x, y), head, fill="black", font=font(30))
    y += 48
    for row in SCAN_ROWS:
        d.line((100, y - 8, 1600, y - 8), fill=(120, 120, 120), width=2)
        if row[1] is None:
            d.rectangle((100, y - 6, 1600, y + 40), fill=(205, 203, 197))
            d.text((110, y), row[0], fill="black", font=font(30))
        else:
            for x, cell in zip(cols, row):
                d.text((x, y), str(cell), fill="black", font=font(30))
        y += 50
    d.text((110, y + 40), "Please quote price and delivery. No substitutions.", fill="black", font=font(28))
    page = im.rotate(1.2, expand=False, fillcolor=(70, 66, 60))
    buf = io.BytesIO()
    page.save(buf, format="PDF", resolution=150)
    return buf.getvalue()


SECTION_MUST = {"ball valve": ("ball", "brass", "600"), "Y-strainer": ("strainer", "cast iron|ci", "125"),
                "water hose": ("hose", "epdm", "150")}
email("P13", "Bao Tran <btran@ridgecrestfoods.example>", "RFQ 0412", "Fri, 06 Nov 2026 15:10:00 -0600",
      "RFQ form attached - scanned it at the front desk, hope it is readable.\n\nBao\n",
      attachments=[(SCAN_NAME, "application/pdf", scan_pdf())])
key("P13", "rfq", [ln(f"{r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]}", r[1], r[2], source=SCAN_NAME,
                      must=SECTION_MUST[r[4]]) for r in SCAN_ROWS if r[1] is not None])

# ------------------------------------------------------------------ P14  items identified only by something we do not have

email("P14", "Joanne Pruitt <jpruitt@redclaybrick.example>", "requote", "Mon, 09 Nov 2026 08:02:00 -0600",
      "Hi,\n\nCan you requote what we bought in August for the north kiln line, same quantities? Budget is being finalized this week.\n\nThanks,\nJoanne\n")
key("P14", "rfq", needs_review=True)

# ------------------------------------------------------------------ P15  a bounce carrying our own outgoing RFQ


def our_outgoing_rfq() -> EmailMessage:
    m = EmailMessage()
    m["From"] = "Priya Nair <pnair@ridgeline-supply.example>"
    m["To"] = "purchasing@pinebluffpaper.example"
    m["Subject"] = "RFQ R-5530 - bolting"
    m["Date"] = "Mon, 09 Nov 2026 09:14:00 -0600"
    m.set_content("Please quote price and delivery:\n\n200 ea 5/8\" x 3-1/2\" B7 stud w/ 2 2H nuts\n"
                  "120 ea 3/4\" x 4\" B7 stud w/ 2 2H nuts\n\nPriya Nair\nRidgeline Industrial Supply\n")
    return m


email("P15", "Mail Delivery Subsystem <mailer-daemon@mx.pinebluffpaper.example>",
      "Undeliverable: RFQ R-5530 - bolting", "Mon, 09 Nov 2026 09:15:00 -0600",
      """This is an automatically generated delivery status notification.

Delivery to the following recipient failed permanently:

    purchasing@pinebluffpaper.example

550 5.1.1 The email account that you tried to reach does not exist.

The original message is attached.
""", attachments=[("original.eml", "message/rfc822", our_outgoing_rfq())])
key("P15", "auto_reply")

# ------------------------------------------------------------------ P16  spelled-out, vague, and sizes that are not quantities

email("P16", "Ruth Calloway <rcalloway@elmforkutilities.example>", "small order quote",
      "Mon, 09 Nov 2026 10:40:00 -0600", """Hi, need a quote on these for the lift station:

two 6" resilient wedge gate valves, MJ ends
twelve 6" MJ accessory kits
6" DI pipe, class 350 - enough to run about 60 ft
a couple 6" MJ 45 bends
1 - 6" x 4" MJ reducer

Thanks
Ruth

Ruth Calloway | Purchasing | Elm Fork Utilities | 555-0188
""")
key("P16", "rfq", [
    ln('two 6" resilient wedge gate valves, MJ ends', 2, must=("gate", "mj|mechanical joint")),
    ln('twelve 6" MJ accessory kits', 12, must=("mj|mechanical joint",)),
    ln('6" DI pipe, class 350 - enough to run about 60 ft', None, None, must=("pipe", "350"), qty_tol=None),
    ln('a couple 6" MJ 45 bends', None, None, must=("45",)),
    ln('1 - 6" x 4" MJ reducer', 1, must=("reducer",)),
])

# ------------------------------------------------------------------ P17  a password-protected PDF


def locked_pdf() -> bytes:
    from pypdf import PdfReader, PdfWriter
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 720, "RFQ LC-2209   6 EA 3in 300# RF blind flange A105")
    c.save()
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(buf.getvalue())))
    writer.encrypt(user_password="k0mpress", owner_password="k0mpress-owner")
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


email("P17", "Gil Navarro <gnavarro@lonestarcompress.example>", "RFQ LC-2209", "Mon, 09 Nov 2026 14:05:00 -0600",
      "RFQ attached. It is locked per our IT policy - password is the usual one.\n\nGil\n",
      attachments=[("RFQ_LC-2209.pdf", "application/pdf", locked_pdf())])
key("P17", "rfq", needs_review=True)


# ------------------------------------------------------------------ write

def main() -> None:
    emails_dir = OUT / "emails"
    emails_dir.mkdir(parents=True, exist_ok=True)
    for pid, msg in sorted(EMAILS.items()):
        (emails_dir / f"{pid}.eml").write_bytes(msg.as_bytes())
    (OUT / "answer_key.json").write_text(
        json.dumps({"version": 1, "emails": dict(sorted(KEY.items()))}, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")
    lines = sum(len(v["line_items"]) for v in KEY.values())
    print(f"{len(EMAILS)} probe emails, {lines} key lines -> {OUT}")


if __name__ == "__main__":
    main()
