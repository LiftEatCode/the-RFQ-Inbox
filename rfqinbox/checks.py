"""Code-side checks: what code decides after the model has answered.

The model reads the email; this module checks its answer against what the reader
saw, using only rules that need no judgment.

check_record(packet, record)   one email
- a line whose text is nowhere in the email was invented: dropped, email flagged
- a line that exists only in hidden or struck-through content: dropped, no flag
- `source` is "body" or a real attachment filename
- a vague amount is null; a number that is only a size or rating is not a quantity (null)
- a request whose attachment is missing, unreadable, encrypted or truncated is flagged

link_records(headers, records)   the whole inbox
- the same request sent twice: the later Date is the duplicate. "The same" means the
  same sender, the same kind, and either identical lines or identical content (the same
  attached file, the same lines of text) that the model happened to read differently
- a revision points at the email it revises, when that email is in the inbox

Neither function changes its input, and neither ever turns a request into a
non-request: the worst they do is remove a line or raise the review flag.
"""

from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from email.utils import parseaddr, parsedate_to_datetime

from rfqinbox.record import ACTION_CLASSES, make_record

FOUND = 0.75          # share of a line's words that must sit together in the email
WINDOW = 3            # a line may be spread over this many consecutive source lines


# =========================================================================== text index

def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _split_visible(text: str) -> tuple[list[str], list[str]]:
    """(lines a person opening the file would see, hidden or struck-through text),
    using the markers the reader prints."""
    visible, excluded = [], []
    hidden_sheet = False
    for ln in (text or "").splitlines():
        if ln.startswith("=== "):
            hidden_sheet = ln.startswith("=== Sheet:") and "[HIDDEN SHEET" in ln
            continue
        if hidden_sheet or "[HIDDEN ROW]" in ln:
            excluded.append(ln)
            continue
        struck = re.findall(r"~~(.+?)~~", ln)
        if struck:
            excluded.append(" ".join(struck))
        visible.append(re.sub(r"~~.+?~~", " ", ln))
    return visible, excluded


class _Block:
    """One piece of text (the body, or one attachment) as windows of word sets."""

    def __init__(self, text: str, window: int = WINDOW):
        visible, excluded = _split_visible(text)
        self.visible = self._windows(visible, window)
        self.excluded = self._windows(excluded, window)

    @staticmethod
    def _windows(lines: list[str], window: int) -> list[set[str]]:
        sets = [s for s in (_tokens(ln) for ln in lines) if s]
        out = list(sets)
        for size in range(2, window + 1):
            out += [set().union(*sets[i:i + size]) for i in range(len(sets) - size + 1)]
        return out

    @staticmethod
    def _best(words: set[str], windows: list[set[str]]) -> float:
        if not words:
            return 0.0
        return max((len(words & w) / len(words) for w in windows), default=0.0)

    def seen(self, words: set[str]) -> float:
        return self._best(words, self.visible)

    def hidden(self, words: set[str]) -> float:
        return self._best(words, self.excluded)


def _blocks(pk, window: int = WINDOW) -> tuple[_Block, dict[str, _Block]]:
    body = "\n".join([pk.subject, pk.body_new, *(q.text for q in pk.quoted)])
    return _Block(body, window), {a.filename: _Block(a.text, window) for a in pk.attachments}


# =========================================================================== source

def _resolve_source(given: str, words: set[str], pk, body: _Block, files: dict[str, _Block]) -> str:
    if given == "body" or given in files:
        return given
    low = (given or "").lower()
    for name in files:
        if name.lower() == low:
            return name
    for name in files:
        if name.lower() in low:
            return name
    for a in pk.attachments:          # a file inside an attached email
        if given and re.search(rf"=== ATTACHMENT \d+: {re.escape(given)} \(", a.text):
            return given
    best_name, best = "body", max(body.seen(words), FOUND - 1e-9)
    for name, block in files.items():
        if block.seen(words) > best:
            best_name, best = name, block.seen(words)
    if best_name == "body" and body.seen(words) < FOUND:
        pictures = [a.filename for a in pk.attachments if a.images and a.status != "logo"]
        if len(pictures) == 1:
            return pictures[0]
    return best_name


# =========================================================================== quantities

_VAGUE = re.compile(r"\b(a couple|couple of|a few|few|some|several|enough|a handful|handful of|"
                    r"a bunch|as needed|as required|tbd)\b", re.I)
_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
          "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20,
          "thirty": 30, "forty": 40, "fifty": 50, "hundred": 100}
_NUMBER = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")
# What comes right before a number that makes it a spec, a reference or a line number.
_SPEC_BEFORE = re.compile(
    r"(?:\b(?:sch|sched|schedule|class|cl|ansi|nps|dn|gr|grade|astm|api|rev|item|line|no|pn|po|rfq)"
    r"\.?\s*|#\s*|[a-z])$", re.I)
_INCH = r"(?:\"|”|″|''|\s*in\b|\s*inch(?:es)?\b|\s*-?inch\b)"
_FOOT = r"(?:'|’|′|\s*ft\b|\s*feet\b|\s*foot\b)"
_POUND = r"(?:\s*lbs?\b)"
_SPEC_AFTER = r"(?:\s*#|\s*psi\b|\s*mm\b|\s*°|\s*deg\b|\s*degrees?\b|\s*wog\b|\s*class\b)"
_ANGLE_AFTER = re.compile(r"\s*(?:deg\b|°)?\s*(?:elbows?|ells?|els?|bends?)\b", re.I)


def _is_spec(raw: str, start: int, end: int, uom: str | None) -> bool:
    """Is the number at raw[start:end] a size, rating, length, angle or line number?"""
    before, after = raw[:start], raw[end:]
    if before.endswith("/") or re.match(r"/\d", after) or re.match(r"-\d+/\d", after):
        return True                                   # part of a fraction: 3/4, 1-1/2
    if re.search(r"\d-$", before) and re.match(r"/", raw[end:end + 1] or " "):
        return True
    if not before.strip() and re.match(r"[).]\s", after):
        return True                                   # "3) ..." is a line number
    if _SPEC_BEFORE.search(before):
        return True
    patterns = [_SPEC_AFTER]
    if uom != "IN":
        patterns.append(_INCH)
    if uom != "FT":
        patterns.append(_FOOT)
    if uom != "LB":
        patterns.append(_POUND)
    if any(re.match(p, after, re.I) for p in patterns):
        return True
    if raw[start:end] in ("45", "90", "180", "22", "11") and _ANGLE_AFTER.match(after):
        return True
    return False


def _quantity_evidence(raw: str, qty, uom: str | None) -> str:
    """'count' - the quantity is written in the line as a count;
    'spec'  - the number is in the line, but only as a size, rating, length or line number;
    'none'  - the number is not in the line at all (it came from somewhere else)."""
    if qty is None or isinstance(qty, bool):
        return "none"
    low = raw.lower()
    if any(value == qty and re.search(rf"\b{word}\b", low) for word, value in _WORDS.items()):
        return "count"
    found = "none"
    for m in _NUMBER.finditer(raw):
        try:
            value = float(m.group().replace(",", ""))
        except ValueError:
            continue
        if value != float(qty):
            continue
        if not _is_spec(raw, m.start(), m.end(), uom):
            return "count"
        found = "spec"
    return found


# =========================================================================== one email

_STATUS_REASON = {
    "encrypted": "'{name}' is password-protected and could not be read",
    "unreadable": "'{name}' could not be opened",
    "empty": "'{name}' is empty",
}


def _attachment_reasons(pk) -> list[str]:
    reasons = []
    real = [a for a in pk.attachments if a.status != "logo"]
    readable = [a for a in real if a.status in ("ok", "scanned")]
    for a in real:
        if a.status in _STATUS_REASON:
            reasons.append(_STATUS_REASON[a.status].format(name=a.filename))
        elif a.status == "unsupported" and pk.mentions_attachment and not readable:
            reasons.append(f"'{a.filename}' is a file type that could not be read")
        elif any("truncated" in n for n in a.notes):
            reasons.append(f"'{a.filename}' was only partly read (too long)")
    if pk.mentions_attachment and not real:
        only = " (only a logo or signature image)" if pk.attachments else ""
        reasons.append(f"the message refers to an attachment but none was received{only}")
    return reasons


def check_record(pk, record: dict) -> dict:
    """Hold one email's record to what the reader actually saw. Returns a new record."""
    record = copy.deepcopy(record)
    if record["classification"] not in ACTION_CLASSES:
        return record

    body, files = _blocks(pk)
    has_pictures = any(a.images and a.status != "logo" for a in pk.attachments)
    kept, invented = [], 0
    for item in record["line_items"]:
        words = _tokens(item.get("raw") or "")
        item["source"] = _resolve_source(item.get("source"), words, pk, body, files)
        blocks = [body, *files.values()]
        seen = max(b.seen(words) for b in blocks)
        if seen < FOUND:
            if max(b.hidden(words) for b in blocks) >= FOUND:
                continue                      # only in hidden or struck-through content: not a request
            if not has_pictures:
                invented += 1                 # nowhere in the email, and no picture it could have come from
                continue
        raw = item.get("raw") or ""
        evidence = _quantity_evidence(raw, item.get("qty"), item.get("uom"))
        if item.get("qty") is not None and evidence != "count":
            if _VAGUE.search(raw):
                item["qty"] = None            # "a couple", "some": the request as written
            elif evidence == "spec":
                # The number is a size or rating, not a count. Blank it for the rep to fill
                # in; not a review flag (README: that is for emails we cannot read or resolve).
                item["qty"] = None
        kept.append(item)
    record["line_items"] = kept

    reasons = []
    if invented:
        reasons.append(f"{invented} line{'s' if invented > 1 else ''} returned by the model "
                       f"{'were' if invented > 1 else 'was'} not found in the email and removed")
    reasons += _attachment_reasons(pk)
    if not kept and not reasons and not record["needs_review"]:
        reasons.append("no line items are left after removing hidden and struck-through content")
    if reasons:
        own = (record["review_reason"] or "").strip() if record["needs_review"] else ""
        record["needs_review"] = True
        record["review_reason"] = "; ".join([own, *reasons] if own else reasons)
    return record


# =========================================================================== the whole inbox

def _address(sender: str) -> str:
    return parseaddr(sender or "")[1].strip().lower()


def _when(date: str) -> datetime | None:
    try:
        parsed = parsedate_to_datetime(date)
    except (TypeError, ValueError, IndexError):
        return None
    if parsed is None:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _order(headers: dict, email_id: str):
    pk = headers.get(email_id)
    when = _when(pk.date) if pk is not None else None
    return (when is None, when or datetime.max.replace(tzinfo=timezone.utc), email_id)


def _fingerprint(record: dict) -> tuple:
    def qty(value):
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    return tuple(sorted((" ".join(sorted(_tokens(i.get("raw") or ""))), repr(qty(i.get("qty"))))
                        for i in record["line_items"]))


def _all_in(lines: list[dict], own, other) -> bool:
    """Is every one of these lines (read from `own`) also in the email `other`?
    Either it came from a file that `other` carries byte-for-byte, or all of its words
    sit on one single line of `other` - one line, so that a changed quantity is never
    explained away by the same number appearing on a neighbouring line."""
    own_files = {a.filename: a.source_sha for a in own.attachments}
    other_files = {a.source_sha for a in other.attachments if a.source_sha}
    body, files = _blocks(other, window=1)
    for item in lines:
        if own_files.get(item.get("source")) in other_files:
            continue
        words = _tokens(item.get("raw") or "")
        if not words or max(b.seen(words) for b in (body, *files.values())) < 1.0:
            return False
    return True


def _same_request(a_pk, a_rec: dict, b_pk, b_rec: dict) -> bool:
    """Two readings of the same content: nothing in either email is missing from the other."""
    return _all_in(a_rec["line_items"], a_pk, b_pk) and _all_in(b_rec["line_items"], b_pk, a_pk)


def _message_ids(text: str) -> list[str]:
    return [m.strip().lower() for m in re.findall(r"<([^<>\s]+)>", text or "")]


def _subject(subject: str) -> str:
    s = (subject or "").strip()
    while True:
        stripped = re.sub(r"^\s*(?:re|fw|fwd|resend|resending|aw|wg)\s*:\s*", "", s, flags=re.I)
        if stripped == s:
            break
        s = stripped
    return " ".join(re.findall(r"[a-z0-9]+", s.lower()))


def link_records(headers: dict, records: dict[str, dict], load=None) -> dict[str, dict]:
    """Set duplicate_of and revises across the inbox. headers: id -> reader Packet
    (headers only is enough). load(id) -> the full Packet, or None; it is only called
    for possible duplicate pairs whose lines differ. Emails without readable headers
    are left as they are."""
    records = copy.deepcopy(records)
    ids = sorted((i for i in records if i in headers), key=lambda i: _order(headers, i))
    loaded: dict[str, object] = {}

    def full(email_id: str):
        if email_id not in loaded:
            try:
                loaded[email_id] = load(email_id) if load else None
            except Exception:  # noqa: BLE001 — an email we cannot re-read is simply not compared
                loaded[email_id] = None
        return loaded[email_id]

    # The same request sent twice: same sender, same kind, same lines. The later Date
    # is the duplicate. Emails with no lines are never duplicates: there is nothing to compare.
    originals: dict[tuple, list[str]] = {}
    for email_id in ids:
        rec = records[email_id]
        if rec["classification"] not in ACTION_CLASSES or not rec["line_items"]:
            continue
        earlier = originals.setdefault((_address(headers[email_id].sender), rec["classification"]), [])
        original = next((o for o in earlier if _fingerprint(records[o]) == _fingerprint(rec)), None)
        if original is None:
            # Not the same lines - but possibly the same content, read differently.
            for o in earlier:
                a_pk, b_pk = full(o), full(email_id)
                if a_pk is not None and b_pk is not None and _same_request(a_pk, records[o], b_pk, rec):
                    original = o
                    break
        if original is None:
            earlier.append(email_id)
        else:
            records[email_id] = make_record(rec["classification"], [], duplicate_of=original)

    by_message_id = {}
    for email_id in ids:
        for mid in _message_ids(headers[email_id].message_id):
            by_message_id.setdefault(mid, email_id)

    def is_request(email_id: str) -> bool:
        return records[email_id]["classification"] in ACTION_CLASSES

    for email_id in ids:
        rec = records[email_id]
        if rec["classification"] != "rfq_revision" or rec["duplicate_of"]:
            continue
        pk = headers[email_id]
        thread = _message_ids(pk.in_reply_to) + list(reversed(_message_ids(pk.references)))
        target = next((by_message_id[m] for m in thread
                       if m in by_message_id and by_message_id[m] != email_id), None)
        if target is None and _subject(pk.subject) and _when(pk.date) is not None:
            earlier = [i for i in ids
                       if i != email_id and is_request(i)
                       and _address(headers[i].sender) == _address(pk.sender)
                       and _subject(headers[i].subject) == _subject(pk.subject)
                       and _when(headers[i].date) is not None and _when(headers[i].date) < _when(pk.date)]
            target = earlier[-1] if earlier else None
        if target is not None:
            target = records[target]["duplicate_of"] or target
            rec["revises"] = target
    return records
