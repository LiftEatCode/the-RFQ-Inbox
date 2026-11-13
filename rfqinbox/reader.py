"""Reader: one .eml -> a Packet the model can read without guessing.

Everything here is deterministic. The aim is to hand the model the *structure*
that carries meaning in this inbox: which text is new and which is quoted
history, sheet names, merged headers, hidden sheets and rows, crossed-out text,
Word headings in order with their tables, PDF form fields, which pages are
scans, which images look like logos. Nothing in this module ever raises for a
bad attachment: it reports a status and a note instead.
"""

from __future__ import annotations

import csv
import hashlib
import html
import io
import re
from dataclasses import dataclass, field
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parseaddr
from html.parser import HTMLParser
from pathlib import Path

INTERNAL_DOMAIN = "ridgeline-supply.example"

MAX_PDF_TEXT_PAGES = 40     # text pages read from a PDF; the rest is noted as truncated
MAX_SCAN_PAGES = 6          # scanned pages rendered to images for the model
MAX_IMAGE_SIDE = 2000       # longest side of any image sent to the model
MAX_ATTACHMENT_CHARS = 60_000
MAX_EMAIL_DEPTH = 3         # attached emails inside attached emails
SCAN_CHARS_PER_PAGE = 25    # fewer text characters than this on a page = treat as a scan


@dataclass
class Attachment:
    filename: str
    mime: str
    size: int
    inline: bool = False
    kind: str = "unknown"   # spreadsheet document pdf csv text html image email unknown
    status: str = "ok"      # ok scanned logo encrypted unreadable empty unsupported
    text: str = ""
    images: list[bytes] = field(default_factory=list)   # PNG/JPEG bytes for the model
    source_sha: str = ""   # sha256 of the file as attached (stable across platforms; cache key for images)
    notes: list[str] = field(default_factory=list)


@dataclass
class Quoted:
    kind: str   # "reply" (earlier messages in the thread) or "forward" (content passed on)
    text: str


@dataclass
class Packet:
    id: str
    sender: str = ""
    sender_internal: bool = False
    to: str = ""
    date: str = ""
    subject: str = ""
    message_id: str = ""
    in_reply_to: str = ""
    references: str = ""
    body_new: str = ""
    quoted: list[Quoted] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    mentions_attachment: bool = False
    notes: list[str] = field(default_factory=list)


# =========================================================================== email

def read_email(path: Path) -> Packet:
    path = Path(path)
    raw = path.read_bytes()
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    return _packet_from_message(path.stem, msg, depth=0)


def _header(msg, name: str) -> str:
    try:
        v = msg.get(name)
        return str(v).strip() if v is not None else ""
    except Exception:  # malformed header
        return ""


def _packet_from_message(pid: str, msg: EmailMessage, depth: int) -> Packet:
    sender = _header(msg, "From")
    pk = Packet(
        id=pid,
        sender=sender,
        sender_internal=parseaddr(sender)[1].lower().endswith("@" + INTERNAL_DOMAIN),
        to=_header(msg, "To"),
        date=_header(msg, "Date"),
        subject=_header(msg, "Subject"),
        message_id=_header(msg, "Message-ID"),
        in_reply_to=_header(msg, "In-Reply-To"),
        references=_header(msg, "References"),
    )
    text_body, html_body = None, None
    try:
        parts = _walk(msg)
    except Exception as exc:
        pk.notes.append(f"MIME structure could not be walked: {exc}")
        parts = []
    for part in parts:
        ct = part.get_content_type()
        disp = part.get_content_disposition()
        if ct == "message/rfc822":
            pk.attachments.append(_read_attached_email(part, depth))
            continue
        filename = part.get_filename()
        if disp in ("attachment", "inline") and (filename or ct.split("/")[0] != "text"):
            pk.attachments.append(read_attachment(
                filename or f"unnamed.{ct.split('/')[-1]}", ct, _payload(part),
                inline=(disp == "inline")))
        elif ct == "text/plain" and text_body is None:
            text_body = _text(part)
        elif ct == "text/html" and html_body is None:
            html_body = _text(part)

    body = _choose_body(text_body, html_body)
    pk.body_new, pk.quoted = split_quoted(body, pk.subject)
    pk.mentions_attachment = mentions_attachment(pk.body_new)
    return pk


def _walk(msg) -> list:
    """Leaf parts in order; message/rfc822 parts are returned whole (not descended into)."""
    out, stack = [], [msg]
    while stack:
        part = stack.pop(0)
        if part.get_content_type() == "message/rfc822":
            out.append(part)
            continue
        if part.is_multipart():
            stack[0:0] = list(part.iter_parts())
            continue
        out.append(part)
    return out


def _payload(part) -> bytes:
    try:
        return part.get_payload(decode=True) or b""
    except Exception:
        return b""


def _text(part) -> str:
    try:
        return part.get_content()
    except Exception:
        return _payload(part).decode("utf-8", "replace")


def _choose_body(text_body: str | None, html_body: str | None) -> str:
    """Plain text, unless the HTML carries a table or struck-out text the plain part loses."""
    if html_body and (not text_body or re.search(r"<(table|s|strike|del)\b", html_body, re.I)):
        return html_to_text(html_body)
    return (text_body or "").replace("\r\n", "\n")


def _read_attached_email(part, depth: int) -> Attachment:
    name = part.get_filename() or "attached.eml"
    att = Attachment(filename=name, mime="message/rfc822", size=0, kind="email",
                     inline=part.get_content_disposition() == "inline")
    try:
        inner = part.get_payload(0) if part.is_multipart() else BytesParser(
            policy=policy.default).parsebytes(_payload(part))
        att.size = len(inner.as_bytes())
        if depth >= MAX_EMAIL_DEPTH:
            att.status = "unsupported"
            att.notes.append("attached email nested too deeply; not read")
            return att
        sub = _packet_from_message(Path(name).stem, inner, depth + 1)
        att.text = render(sub, header=False)
        for a in sub.attachments:
            att.images += a.images
        att.source_sha = hashlib.sha256(
            "".join(a.source_sha for a in sub.attachments if a.images).encode("ascii")).hexdigest()
    except Exception as exc:
        att.status = "unreadable"
        att.notes.append(f"attached email could not be read: {exc}")
    return att


# =========================================================================== quoted history

_REPLY_HDR = re.compile(r"^\s*On\b.{0,200}\bwrote:\s*$", re.I)
_ORIG = re.compile(r"^\s*-{2,}\s*Original Message\s*-{2,}\s*$", re.I)
_FWD = re.compile(r"^\s*-{2,}\s*Forwarded message\s*-{2,}\s*$|^\s*Begin forwarded message:\s*$", re.I)
_FROM = re.compile(r"^\s*\*?From:\*?\s", re.I)
_SENT = re.compile(r"^\s*\*?(Sent|Date):\*?\s", re.I)
_FW_SUBJ = re.compile(r"^\s*(fw|fwd)\s*:", re.I)


def split_quoted(body: str, subject: str = "") -> tuple[str, list[Quoted]]:
    """Split the new text from quoted history at the first quote marker."""
    lines = body.split("\n")
    cut, marker = None, None
    for i, line in enumerate(lines):
        if _FWD.match(line):
            cut, marker = i, "forward"
        elif _ORIG.match(line):
            cut, marker = i, "original"
        elif _REPLY_HDR.match(line) or (
            # "On Tue, Oct 6, 2026 at 8:47 AM Name <addr>" wrapped onto the next line
            re.match(r"^\s*On\b", line, re.I) and i + 1 < len(lines) and lines[i + 1].strip().endswith("wrote:")
        ):
            cut, marker = i, "reply"
        elif _FROM.match(line) and any(_SENT.match(l) for l in lines[i + 1: i + 5]) and i > 0:
            cut, marker = i, "original"
        elif line.startswith(">") and i > 0 and _new_text_before(lines[:i]):
            cut, marker = i, "reply"
        if cut is not None:
            break
    if cut is None:
        return body.strip("\n"), []
    if marker == "forward" or (marker == "original" and _FW_SUBJ.match(subject or "")):
        kind = "forward"
    else:
        kind = "reply"
    quoted = "\n".join(_unquote(l) for l in lines[cut:]).strip("\n")
    return "\n".join(lines[:cut]).strip("\n"), [Quoted(kind, quoted)]


def _new_text_before(lines: list[str]) -> bool:
    return any(l.strip() for l in lines)


def _unquote(line: str) -> str:
    return re.sub(r"^> ?", "", line)


_ATTACH = re.compile(
    r"\battach(?:ed|ment|ments|ing)?\b|\benclosed\b|\bsee (?:the )?(?:pdf|file|sheet|spreadsheet)\b",
    re.I,
)


_DISCLAIMER = re.compile(r"confidential|intended (?:only )?for|intended recipient|privileged|"
                         r"received (?:it|this) in error", re.I)


def mentions_attachment(text: str) -> bool:
    """Does the new text point at an attachment? Legal footers ("this message and any
    attachments are confidential") don't count."""
    for para in re.split(r"\n\s*\n", text or ""):
        if _ATTACH.search(para) and not _DISCLAIMER.search(para):
            return True
    return False


# =========================================================================== HTML

class _HtmlToText(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "blockquote", "hr"}
    STRIKE = {"s", "strike", "del"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.cell_span = 1
        self.skip = 0
        self.quote_depth = 0

    def _emit(self, s: str):
        (self.cell if self.cell is not None else self.out).append(s)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("style", "script", "head"):
            self.skip += 1
        elif tag == "tr":
            self.row = []
        elif tag in ("td", "th"):
            self.cell = []
            try:
                self.cell_span = int(a.get("colspan") or 1)
            except ValueError:
                self.cell_span = 1
        elif tag in self.STRIKE:
            self._emit("~~")
        elif tag == "blockquote":
            self.quote_depth += 1
            self.out.append("\n")
        elif tag in self.BLOCK:
            self._emit("\n")

    def handle_endtag(self, tag):
        if tag in ("style", "script", "head"):
            self.skip = max(0, self.skip - 1)
        elif tag in ("td", "th") and self.cell is not None:
            text = re.sub(r"\s+", " ", "".join(self.cell)).strip()
            if self.cell_span > 1:
                text += f" [spans {self.cell_span} columns]"
            if self.row is not None:
                self.row.append(text)
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.out.append("\n| " + " | ".join(self.row) + " |")
            self.row = None
        elif tag in self.STRIKE:
            self._emit("~~")
        elif tag == "blockquote":
            self.quote_depth = max(0, self.quote_depth - 1)
            self.out.append("\n")
        elif tag in self.BLOCK:
            self._emit("\n")

    def handle_data(self, data):
        if self.skip:
            return
        if self.quote_depth and self.cell is None:
            data = "\n".join("> " + l if l.strip() else l for l in data.split("\n"))
        self._emit(data)


def html_to_text(src: str) -> str:
    p = _HtmlToText()
    try:
        p.feed(src)
        p.close()
    except Exception:
        return re.sub(r"<[^>]+>", " ", html.unescape(src))
    text = "".join(p.out)
    lines = [re.sub(r"[ \t ]+", " ", l).strip() for l in text.split("\n")]
    out, blank = [], 0
    for l in lines:
        blank = blank + 1 if not l else 0
        if blank <= 1:
            out.append(l)
    return "\n".join(out).strip()


# =========================================================================== attachments

_EXT_KIND = {
    ".xlsx": "spreadsheet", ".xlsm": "spreadsheet", ".xls": "spreadsheet",
    ".docx": "document", ".doc": "document",
    ".pdf": "pdf", ".csv": "csv", ".tsv": "csv", ".txt": "text",
    ".htm": "html", ".html": "html", ".eml": "email",
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".gif": "image", ".bmp": "image",
    ".tif": "image", ".tiff": "image", ".webp": "image", ".heic": "image",
}
_MIME_KIND = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "spreadsheet",
    "application/vnd.ms-excel.sheet.macroenabled.12": "spreadsheet",
    "application/vnd.ms-excel": "spreadsheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "document",
    "application/msword": "document",
    "application/pdf": "pdf",
    "text/csv": "csv", "text/tab-separated-values": "csv",
    "text/plain": "text", "text/html": "html",
    "message/rfc822": "email",
}


def kind_of(filename: str, mime: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in _EXT_KIND:
        return _EXT_KIND[ext]
    mime = (mime or "").lower()
    if mime in _MIME_KIND:
        return _MIME_KIND[mime]
    if mime.startswith("image/"):
        return "image"
    return "unknown"


def read_attachment(filename: str, mime: str, data: bytes, inline: bool = False) -> Attachment:
    att = Attachment(filename=filename, mime=mime, size=len(data), inline=inline,
                     kind=kind_of(filename, mime), source_sha=hashlib.sha256(data).hexdigest())
    if not data.strip():
        att.status = "empty"
        att.notes.append("attachment is empty (0 bytes of content)")
        return att
    reader = _READERS.get(att.kind)
    if reader is None:
        att.status = "unsupported"
        att.notes.append(f"file type not readable here ({mime or 'unknown'}, {Path(filename).suffix or 'no extension'})")
        return att
    try:
        reader(att, data)
    except Exception as exc:  # any library error on a broken file
        att.status = "unreadable"
        att.text, att.images = "", []
        att.notes.append(f"could not open {att.kind}: {type(exc).__name__}: {str(exc)[:200]}")
    if len(att.text) > MAX_ATTACHMENT_CHARS:
        att.text = att.text[:MAX_ATTACHMENT_CHARS]
        att.notes.append(f"text truncated to the first {MAX_ATTACHMENT_CHARS} characters")
    return att


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v).replace("\n", " ").strip()


def _row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


# ---------------------------------------------------------------- spreadsheet

def _read_spreadsheet(att: Attachment, data: bytes) -> None:
    if Path(att.filename).suffix.lower() == ".xls" or data[:4] == b"\xd0\xcf\x11\xe0":
        att.status = "unsupported"
        att.notes.append("legacy .xls workbook; not readable here")
        return
    import openpyxl
    from openpyxl.utils import get_column_letter

    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    out = []
    for ws in wb.worksheets:
        state = ws.sheet_state
        label = f"=== Sheet: {ws.title}"
        if state != "visible":
            label += f"  [HIDDEN SHEET ({state}) - not shown when the workbook is opened]"
        out.append(label + " ===")
        merged = {}
        for rng in ws.merged_cells.ranges:
            merged[(rng.min_row, rng.min_col)] = str(rng)
        max_col = ws.max_column or 1
        hidden_cols = {k for k, d in ws.column_dimensions.items() if d.hidden}
        for r in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=max_col):
            vals, any_val = [], False
            notes = []
            for c in r:
                if c.value is None:
                    vals.append("")
                    continue
                any_val = True
                v = _fmt(c.value)
                if c.font is not None and c.font.strike:
                    v = f"~~{v}~~"
                if get_column_letter(c.column) in hidden_cols:
                    v = f"[hidden column] {v}"
                if (c.row, c.column) in merged:
                    notes.append(f"merged across {merged[(c.row, c.column)]}")
                if c.comment is not None:
                    notes.append(f"comment on {c.coordinate}: {c.comment.text.strip()}")
                vals.append(v)
            if not any_val:
                continue
            while vals and vals[-1] == "":
                vals.pop()
            line = f"R{r[0].row}: " + _row(vals)
            if ws.row_dimensions[r[0].row].hidden:
                line = f"R{r[0].row}: [HIDDEN ROW] " + _row(vals)
            if notes:
                line += "  (" + "; ".join(notes) + ")"
            out.append(line)
        out.append("")
    att.text = "\n".join(out).strip()


def _read_csv(att: Attachment, data: bytes) -> None:
    text = _decode(data)
    delim = "\t" if Path(att.filename).suffix.lower() == ".tsv" or text.count("\t") > text.count(",") else ","
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delim) if any(c.strip() for c in r)]
    att.text = "\n".join(_row([c.strip() for c in r]) for r in rows)


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def _read_text(att: Attachment, data: bytes) -> None:
    att.text = _decode(data).replace("\r\n", "\n").strip()


def _read_html(att: Attachment, data: bytes) -> None:
    att.text = html_to_text(_decode(data))


# ---------------------------------------------------------------- word

def _read_document(att: Attachment, data: bytes) -> None:
    if Path(att.filename).suffix.lower() == ".doc" or data[:4] == b"\xd0\xcf\x11\xe0":
        att.status = "unsupported"
        att.notes.append("legacy .doc document; not readable here")
        return
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = docx.Document(io.BytesIO(data))
    out = []
    for sec in d.sections:
        for p in sec.header.paragraphs:
            if p.text.strip():
                out.append(f"[page header] {p.text.strip()}")
    for el in d.element.body.iterchildren():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "p":
            line = _docx_paragraph(Paragraph(el, d))
            if line:
                out.append(line)
        elif tag == "tbl":
            out.append(_docx_table(Table(el, d)))
    for sec in d.sections:
        for p in sec.footer.paragraphs:
            if p.text.strip():
                out.append(f"[page footer] {p.text.strip()}")
    att.text = "\n".join(out).strip()


def _docx_runs(p) -> str:
    parts = []
    for run in p.runs:
        t = run.text
        if t and run.font is not None and run.font.strike:
            t = f"~~{t}~~"
        parts.append(t)
    text = "".join(parts)
    return text if text.strip() else p.text


def _docx_paragraph(p) -> str:
    text = _docx_runs(p).strip()
    if not text:
        return ""
    style = (p.style.name if p.style is not None else "") or ""
    m = re.match(r"Heading\s*(\d)", style)
    if m:
        return "#" * min(int(m.group(1)) + 0, 6) + " " + text if int(m.group(1)) > 1 else "# " + text
    if style.lower() == "title":
        return "# " + text
    return text


def _docx_table(t) -> str:
    lines = []
    for row in t.rows:
        cells, last = [], None
        for c in row.cells:
            if c._tc is last:  # merged cell repeated by python-docx
                continue
            last = c._tc
            cells.append(" / ".join(_docx_runs(p).strip() for p in c.paragraphs if p.text.strip()))
        lines.append(_row(cells))
    return "\n".join(lines)


# ---------------------------------------------------------------- pdf

def _read_pdf(att: Attachment, data: bytes) -> None:
    import pypdf
    import pypdfium2 as pdfium

    reader = pypdf.PdfReader(io.BytesIO(data))
    password = None
    if reader.is_encrypted:
        if not reader.decrypt(""):
            att.status = "encrypted"
            att.notes.append("PDF is password-protected; contents cannot be read")
            return
        password = ""
    fields = {}
    try:
        for name, f in (reader.get_fields() or {}).items():
            v = f.get("/V")
            if v not in (None, ""):
                fields[name] = str(v)
    except Exception:
        pass

    doc = pdfium.PdfDocument(data, password=password)
    n = len(doc)
    pages_text, scanned_pages = [], []
    for i in range(min(n, MAX_PDF_TEXT_PAGES)):
        page = doc[i]
        text = page.get_textpage().get_text_bounded().replace("\r\n", "\n").replace("\r", "\n").strip()
        # A scan is a page with (almost) no text layer that carries a picture. A short
        # text page — one line item on a last page — is not a scan.
        if len(re.sub(r"\s", "", text)) < SCAN_CHARS_PER_PAGE and _has_image(page, pdfium):
            scanned_pages.append(i)
        pages_text.append(text)

    out = []
    if fields:
        out.append("[form fields]")
        out += [f"{k}: {v}" for k, v in fields.items()]
    for i, t in enumerate(pages_text):
        out.append(f"--- page {i + 1} of {n} ---")
        out.append(t if i not in scanned_pages else "[no text layer on this page - scanned image, see page image]")
    att.text = "\n".join(out).strip()
    if n > MAX_PDF_TEXT_PAGES:
        att.notes.append(f"truncated: read the first {MAX_PDF_TEXT_PAGES} of {n} pages")

    if scanned_pages:
        att.status = "scanned"
        for i in scanned_pages[:MAX_SCAN_PAGES]:
            pil = doc[i].render(scale=_pdf_scale(doc[i])).to_pil()
            att.images.append(_encode_image(pil))
        if len(scanned_pages) > MAX_SCAN_PAGES or n > MAX_PDF_TEXT_PAGES and not pages_text:
            att.notes.append(
                f"truncated: {len(scanned_pages)} scanned pages, only the first {MAX_SCAN_PAGES} sent as images")
        if len(scanned_pages) < len(pages_text):
            att.notes.append(f"pages {', '.join(str(i + 1) for i in scanned_pages)} are scans; the rest have text")


def _has_image(page, pdfium) -> bool:
    try:
        return any(True for _ in page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_IMAGE], max_depth=3))
    except Exception:
        return True  # can't tell: safer to show the model the page


def _pdf_scale(page) -> float:
    w, h = page.get_size()
    return max(0.5, min(3.0, 1600 / max(w, h, 1)))


# ---------------------------------------------------------------- images

def _read_image(att: Attachment, data: bytes) -> None:
    from PIL import Image, ImageOps

    im = Image.open(io.BytesIO(data))
    im.load()
    im = ImageOps.exif_transpose(im)
    w, h = im.size
    att.text = f"[image {w}x{h} px - shown to the model]"
    if looks_like_logo(w, h):
        att.status = "logo"
        att.notes.append(f"{w}x{h} wide, short image: probably a logo or signature graphic")
    att.images.append(_encode_image(im))


def looks_like_logo(w: int, h: int) -> bool:
    return (h <= 120 and w >= 3 * h) or (w * h <= 12_000)


def _encode_image(im) -> bytes:
    from PIL import Image

    if im.mode not in ("RGB", "L"):
        bg = Image.new("RGB", im.size, "white")
        try:
            bg.paste(im, mask=im.convert("RGBA").split()[-1])
        except Exception:
            bg.paste(im.convert("RGB"))
        im = bg
    if max(im.size) > MAX_IMAGE_SIDE:
        im = im.copy()
        im.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _read_email_bytes(att: Attachment, data: bytes) -> None:
    inner = BytesParser(policy=policy.default).parsebytes(data)
    sub = _packet_from_message(Path(att.filename).stem, inner, depth=1)
    att.text = render(sub, header=False)
    for a in sub.attachments:
        att.images += a.images


_READERS = {
    "spreadsheet": _read_spreadsheet,
    "document": _read_document,
    "pdf": _read_pdf,
    "csv": _read_csv,
    "text": _read_text,
    "html": _read_html,
    "image": _read_image,
    "email": _read_email_bytes,
}


# =========================================================================== render

def render(pk: Packet, header: bool = True) -> str:
    """The packet as the model reads it. Section titles say what each part is."""
    out = []
    if header:
        out.append(f"EMAIL {pk.id}")
    who = " (one of OUR OWN Ridgeline reps)" if pk.sender_internal else ""
    out += [
        f"From: {pk.sender}{who}",
        f"To: {pk.to}",
        f"Date: {pk.date}",
        f"Subject: {pk.subject}",
    ]
    if pk.in_reply_to:
        out.append(f"In-Reply-To: {pk.in_reply_to}")
    out.append("")
    out.append("=== NEW MESSAGE (what this email itself says) ===")
    out.append(pk.body_new or "[empty]")
    for q in pk.quoted:
        out.append("")
        if q.kind == "forward":
            out.append("=== FORWARDED CONTENT (passed on by the sender) ===")
        else:
            out.append("=== QUOTED HISTORY (earlier messages in this thread) ===")
        out.append(q.text)
    for i, a in enumerate(pk.attachments, 1):
        out.append("")
        flags = a.status if a.status != "ok" else "readable"
        where = ", inline in the body" if a.inline else ""
        out.append(f"=== ATTACHMENT {i}: {a.filename} ({a.kind}, {flags}{where}) ===")
        for n in a.notes:
            out.append(f"[note] {n}")
        if a.text:
            out.append(a.text)
        if a.images:
            out.append(f"[{len(a.images)} image(s) of this attachment follow, labelled '{a.filename}']")
    for n in pk.notes:
        out.append(f"[note] {n}")
    return "\n".join(out)


def images_for_model(pk: Packet) -> list[tuple[str, bytes, str]]:
    """(label, image bytes, detail) for every image, logos at low detail."""
    out = []
    for a in pk.attachments:
        for j, img in enumerate(a.images, 1):
            label = a.filename if len(a.images) == 1 else f"{a.filename} (page {j})"
            out.append((label, img, "low" if a.status == "logo" else "high"))
    return out


def image_keys(pk: Packet) -> list[bytes]:
    """One cache-key token per image from images_for_model, in the same order.

    The images themselves are re-encoded by Pillow/pdfium, and those bytes can differ
    between library builds and platforms. The attached file's own bytes cannot, so the
    cache is keyed on them: a cache recorded on one machine replays on another.
    """
    out = []
    for a in pk.attachments:
        for j, img in enumerate(a.images, 1):
            src = a.source_sha or hashlib.sha256(img).hexdigest()
            out.append(f"{src}:{j}/{len(a.images)}".encode("ascii"))
    return out
