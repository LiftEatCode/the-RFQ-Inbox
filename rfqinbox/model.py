"""The model layer: OpenAI client, response cache, cost ledger, failure handling.

    Engine.extract(email_id, text, images) -> {"analysis", "classification", "needs_review",
                                               "review_reason", "line_items"}

What the model decides is in that dict. Everything around it is code:

- the answer is validated against the output contract (one repair retry, then give up);
- a valid answer is cached under a hash of everything the model saw, so a second run
  makes no calls and a run with no key replays what was recorded;
- every call is counted (calls, tokens, dollars) per email;
- anything that goes wrong raises ModelError with a reason a rep can read. The
  pipeline turns that into a record flagged for review. Failures are never cached.

Only the standard library is used: one HTTPS POST does not need an SDK.
The API key is read from the environment, sent in one header, and never logged.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from rfqinbox.record import CLASSES, UOMS

DEFAULT_MODEL = "gpt-4.1"
PROMPT_VERSION = "v1"
API_URL = "https://api.openai.com/v1/chat/completions"
REPO_ROOT = Path(__file__).resolve().parents[1]

# USD per 1M tokens (input, output). Check against the provider's price page when
# changing DEFAULT_MODEL; a model missing here is reported at $0 with price_known false.
PRICES: dict[str, tuple[float, float]] = {
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
}

SYSTEM_PROMPT = """\
You work the RFQ inbox of Ridgeline Industrial Supply, a distributor of pipe, fittings, flanges,
valves, gaskets and bolting. You are given ONE email, already unpacked into labelled sections,
and you return JSON: what kind of email it is, and exactly the items the customer is asking for.
An inside sales rep will quote from your lines without re-reading the email.

HOW THE EMAIL IS LAID OUT
- "NEW MESSAGE" is what this email itself says. Classify what the NEW MESSAGE does - not the
  subject line and not what earlier messages did.
- "QUOTED HISTORY" is earlier messages in the thread. They were handled when they arrived.
  Never take lines from quoted history, with the two exceptions under THREADS.
- "FORWARDED CONTENT" is a message the sender passed on. When the sender is one of our own reps
  (@ridgeline-supply.example), the forwarded customer email IS the request: classify the email as
  the customer's, take the lines from the forwarded content and its attachments, and read the
  rep's own note too - it may add, remove or change something.
- "ATTACHMENT" sections give each file's text, or its pictures after the text. "[note]" lines
  are facts from the program that unpacked the file (unreadable, password-protected, truncated,
  probably a logo). Trust them.
- "[HIDDEN SHEET]" and "[HIDDEN ROW]" mark spreadsheet content the customer hid: an old revision
  or working copy. ~~Text like this~~ was struck through. Neither is a request.

CLASSIFICATION (exactly one)
- rfq: asks us to price or check availability of items.
- rfq_revision: changes a request made earlier in the same thread (quantities, additions, removals).
- purchase_order: commits to buy - a PO, "please process", "go ahead with items 1 and 3".
- vendor_quote: a supplier quoting or answering US, however much it looks like a list of items.
  Our own quotes are numbered Q-26-...; a document pricing items for Ridgeline is a vendor's.
- status_inquiry: asks about an existing quote or order (any update? ETA? tracking?).
- auto_reply: machine-generated - out-of-office, bounce / undeliverable notice, read receipt.
  A bounce that carries our own outgoing message, even one full of items, is still auto_reply.
- other: everything else - marketing, promo price lists, newsletters, invoices, remittances,
  job applications, internal chatter, "we went with someone else".
Only rfq, rfq_revision and purchase_order have line_items and needs_review. For the other four
return line_items [] and needs_review false.

LINE ITEMS - one per thing the customer is asking for
Not lines: headings, notes, totals and subtotals, prices, signatures, contact details, hidden or
struck-through rows, old revisions, examples of what they do not want, items in quoted history.
- raw: the line verbatim, as it appears where you found it (a table row's cells on one line,
  in order). For a picture or scan, your careful reading of that line. Do not tidy, expand or
  correct it.
- description: the item made self-contained - the line's own words plus everything written
  elsewhere that applies to it, and nothing that does not:
  - a heading applies only to the lines in its own block; the next heading ends it;
  - a default such as "all pipe sch 40 unless noted" applies to every line it covers, except a
    line that states its own value - that line's own value overrides the default, and the
    default must then not appear in its description;
  - a note addressed to one section or one item does not spread to the others;
  - sheet names, merged header cells, column headers, Word headings above a table, PDF form
    field values (material, rating, project spec) and the subject line can all carry the spec;
  - ditto marks, "same as above", "same size", "as line 2" mean: copy that value from the
    line referred to.
  Never invent a spec the email does not give. If the schedule or material is not stated
  anywhere, leave it out.
- qty: the number the customer stated, not converted. A spelled-out number is a number
  ("two boxes" is 2 BX, "three dozen" is 3 DZ, "a pair" is 1 PR). A vague amount ("a couple",
  "some", "enough for the job") is null. A size, schedule, length, pressure rating, part number,
  line number or price is never a quantity: in '6 - 2" sch 80 nipples x 4" long' only 6 is.
- uom: one of EA FT M IN BX PK PR DZ RL LB SET GAL BAG CS, as the customer wrote it
  (pcs / each -> EA, feet / ' as a length ordered -> FT, joints or lengths or sticks -> EA).
  null when no unit is stated.
- source: "body" for the email text (including forwarded or quoted text), otherwise the exact
  filename of the attachment or picture the line came from.
A photo, nameplate or screenshot of a single item with "quote 3 of these" in the body is one
line: describe the item from the picture, qty from the body, source the picture's filename.

THREADS
- rfq_revision: return the COMPLETE order as the customer now intends it, not just the changes.
  Rebuild it from the original request in the quoted history plus the changes in the new message
  ("line 2 is now 14", "drop line 6", "add ..."). Unchanged lines keep their original raw text;
  removed lines disappear; a changed line carries the new value.
- purchase_order that refers to our quote ("go ahead with items 1, 2 and 4"): take exactly those
  items from the quoted quote, with its quantities unless the customer changes them.
If the earlier message these depend on is not in the email, set needs_review.

NEEDS_REVIEW - a human must look before anyone quotes this
true when the request cannot be fully read or resolved from this email alone:
- the message points at an attachment ("see attached", "list enclosed") that is missing, empty,
  unreadable, password-protected / encrypted, of an unsupported type, or truncated - or the only
  thing attached is a logo or signature graphic;
- the items are identified only by something that is not in the email ("same as our last order",
  "the usual", "per the drawing" with no drawing);
- a picture or scan is too poor to read some lines with confidence.
Say why in review_reason, in one sentence a rep can act on, and still return every line you
could read. Do not flag an email just because a spec is missing or a quantity is vague - that is
the customer's request as written.

HOW TO ANSWER
Write analysis first, briefly: who is writing and what the NEW MESSAGE does; where the items
are; which headings, defaults, notes or form fields apply to which lines and which lines override
them; what you are leaving out and why (quoted history, hidden, struck, totals). Then give
classification, needs_review, review_reason and line_items consistent with that analysis.
"""

_NULLABLE_STRING = {"type": ["string", "null"]}
OUTPUT_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["analysis", "classification", "needs_review", "review_reason", "line_items"],
    "properties": {
        # First on purpose: the model writes fields in this order, so it reasons before it answers.
        "analysis": {"type": "string"},
        "classification": {"type": "string", "enum": list(CLASSES)},
        "needs_review": {"type": "boolean"},
        "review_reason": _NULLABLE_STRING,
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["raw", "description", "qty", "uom", "source"],
                "properties": {
                    "raw": {"type": "string"},
                    "description": {"type": "string"},
                    "qty": {"type": ["number", "null"]},
                    "uom": {"type": ["string", "null"], "enum": [*UOMS, None]},
                    "source": {"type": "string"},
                },
            },
        },
    },
}


class ModelError(Exception):
    """The model step could not produce a usable answer. str(e) is the reason."""


@dataclass
class Completion:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


# =========================================================================== client

class OpenAIClient:
    """Chat Completions over urllib. `opener` and `sleep` are injectable for tests."""

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, *, timeout: float = 120,
                 max_retries: int = 3, opener=None, sleep=time.sleep, backoff: float = 2.0):
        self._api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self._opener = opener or urllib.request.urlopen
        self._sleep = sleep
        self._backoff = backoff

    def __repr__(self) -> str:
        return f"OpenAIClient(model={self.model!r})"

    def redact(self, text: str) -> str:
        return text.replace(self._api_key, "[redacted]") if self._api_key else text

    def complete(self, messages: list[dict], schema: dict) -> Completion:
        payload = json.dumps({
            "model": self.model,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "rfq_email", "strict": True, "schema": schema},
            },
        }).encode("utf-8")
        attempts = self.max_retries + 1
        problem = "no attempt made"
        for attempt in range(attempts):
            if attempt:
                self._sleep(self._backoff * 2 ** (attempt - 1))
            request = urllib.request.Request(API_URL, data=payload, method="POST", headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            })
            try:
                with self._opener(request, timeout=self.timeout) as response:
                    body = response.read()
            except urllib.error.HTTPError as exc:
                problem = f"HTTP {exc.code}{_api_message(exc)}"
                if exc.code == 429 or exc.code >= 500:
                    continue
                raise ModelError(self.redact(f"model request rejected: {problem}")) from None
            except TimeoutError:
                problem = f"timed out after {self.timeout:g}s"
                continue
            except OSError as exc:  # URLError, connection reset, DNS, TLS
                problem = f"network error ({type(exc).__name__}: {str(exc)[:200]})"
                continue
            return self._parse(body)
        raise ModelError(self.redact(f"model unavailable: {problem} ({attempts} attempts)"))

    def _parse(self, body: bytes) -> Completion:
        try:
            data = json.loads(body.decode("utf-8"))
            message = data["choices"][0]["message"]
            usage = data.get("usage") or {}
        except (ValueError, LookupError, TypeError, AttributeError):
            raise ModelError("model API returned an unreadable response") from None
        if message.get("refusal"):
            raise ModelError(f"model refused: {str(message['refusal'])[:200]}")
        if not isinstance(message.get("content"), str):
            raise ModelError("model API returned no content")
        return Completion(message["content"], int(usage.get("prompt_tokens") or 0),
                          int(usage.get("completion_tokens") or 0))


def _api_message(exc: urllib.error.HTTPError) -> str:
    try:
        detail = json.loads(exc.read().decode("utf-8", "replace"))["error"]["message"]
        return f" ({str(detail)[:200]})"
    except Exception:  # noqa: BLE001 — the status code alone is enough
        return ""


def make_client() -> OpenAIClient | None:
    """The default client, or None when there is no key (replay from cache only)."""
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return None
    return OpenAIClient(key, model=os.environ.get("RFQINBOX_MODEL", "").strip() or DEFAULT_MODEL)


# =========================================================================== messages

def _mime(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def _as_image(i: int, image) -> tuple[str, bytes, str]:
    return image if isinstance(image, tuple) else (f"image {i}", image, "high")


def build_messages(text: str, images=()) -> list[dict]:
    """images: (label, bytes, detail) as reader.images_for_model returns them."""
    parts: list[dict] = [{"type": "text", "text": text}]
    for i, image in enumerate(images, 1):
        label, data, detail = _as_image(i, image)
        parts.append({"type": "text", "text": f"Image: {label}"})
        parts.append({"type": "image_url", "image_url": {
            "url": f"data:{_mime(data)};base64,{base64.b64encode(data).decode('ascii')}",
            "detail": detail,
        }})
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": parts}]


# =========================================================================== cache

def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def request_key(prompt_version: str, schema: dict, text: str, images) -> str:
    """Everything the model is shown, without which model is shown it."""
    return _sha(_canonical({
        "prompt_version": prompt_version,
        "schema": schema,
        "text": text,
        "images": [hashlib.sha256(bytes(b)).hexdigest() for b in images],
    }))


def cache_key(model: str, prompt_version: str, schema: dict, text: str, images) -> str:
    return _sha(_canonical({"model": model, "request": request_key(prompt_version, schema, text, images)}))


def write_text_atomic(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _dump(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


class Cache:
    """One JSON file per answered request: <dir>/<sha256>.json. Committed to git."""

    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self._by_request: dict[str, dict] | None = None

    def get(self, key: str) -> dict | None:
        return self._load(self.dir / f"{key}.json")

    def put(self, key: str, entry: dict) -> None:
        write_text_atomic(self.dir / f"{key}.json", _dump(entry))
        self._by_request = None

    def find_request(self, request: str) -> dict | None:
        """An answer to this request recorded with any model (used when there is no key)."""
        if self._by_request is None:
            self._by_request = {}
            for path in sorted(self.dir.glob("*.json")) if self.dir.is_dir() else []:
                entry = self._load(path)
                if entry and isinstance(entry.get("request"), str):
                    self._by_request.setdefault(entry["request"], entry)
        return self._by_request.get(request)

    @staticmethod
    def _load(path: Path) -> dict | None:
        try:
            entry = json.loads(path.read_bytes().decode("utf-8"))
        except (OSError, ValueError):
            return None
        return entry if isinstance(entry, dict) else None


def default_cache_dir() -> Path:
    return Path(os.environ.get("RFQINBOX_CACHE_DIR", "").strip() or REPO_ROOT / "cache")


# =========================================================================== cost

def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = PRICES.get(model, (0.0, 0.0))
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


_FIELDS = ("calls", "new_calls", "input_tokens", "output_tokens", "cost_usd", "new_cost_usd")


class Ledger:
    """Per email: `calls`/tokens/`cost_usd` are what its answer cost when it was made
    (now, or when the cached answer was recorded); `new_*` is what this run spent."""

    def __init__(self):
        self.model: str | None = None
        self.prompt_version: str | None = None
        self._rows: dict[str, dict] = {}

    def touch(self, email_id: str) -> dict:
        return self._rows.setdefault(email_id, dict.fromkeys(_FIELDS, 0))

    def add(self, email_id: str, model: str, input_tokens: int, output_tokens: int,
            *, cached: bool, calls: int = 1) -> None:
        row = self.touch(email_id)
        cost = cost_usd(model, input_tokens, output_tokens)
        row["calls"] += calls
        row["input_tokens"] += input_tokens
        row["output_tokens"] += output_tokens
        row["cost_usd"] += cost
        if not cached:
            row["new_calls"] += calls
            row["new_cost_usd"] += cost

    def report(self) -> dict:
        emails = {}
        for email_id in sorted(self._rows):
            row = dict(self._rows[email_id])
            row["cost_usd"] = round(row["cost_usd"], 6)
            row["new_cost_usd"] = round(row["new_cost_usd"], 6)
            emails[email_id] = row
        totals = {"emails": len(emails)}
        for name in _FIELDS:
            total = sum(row[name] for row in emails.values())
            totals[name] = round(total, 6) if name.endswith("usd") else total
        return {
            "model": self.model,
            "prompt_version": self.prompt_version,
            "price_known": self.model in PRICES,
            "totals": totals,
            "emails": emails,
        }

    def write(self, path: Path) -> None:
        write_text_atomic(Path(path), json.dumps(self.report(), indent=2, ensure_ascii=False) + "\n")


# =========================================================================== validation

def validate_output(text: str) -> dict:
    """Parse and check a model reply against the output contract. Raises ValueError
    with what is wrong (that message is sent back to the model for the repair retry)."""
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"not valid JSON ({exc})") from None
    if not isinstance(data, dict):
        raise ValueError("the reply must be one JSON object")
    for name in OUTPUT_SCHEMA["required"]:
        if name not in data:
            raise ValueError(f"missing field {name!r}")
    if not isinstance(data["analysis"], str):
        raise ValueError("analysis must be a string")
    if data["classification"] not in CLASSES:
        raise ValueError(f"classification {data['classification']!r} is not one of {', '.join(CLASSES)}")
    if not isinstance(data["needs_review"], bool):
        raise ValueError("needs_review must be true or false")
    if data["review_reason"] is not None and not isinstance(data["review_reason"], str):
        raise ValueError("review_reason must be a string or null")
    if not isinstance(data["line_items"], list):
        raise ValueError("line_items must be a list")
    lines = []
    for n, item in enumerate(data["line_items"], 1):
        if not isinstance(item, dict):
            raise ValueError(f"line item {n} must be an object")
        for name in ("raw", "description", "source"):
            if not isinstance(item.get(name), str):
                raise ValueError(f"line item {n}: {name} must be a string")
        qty = item.get("qty")
        if qty is not None and (isinstance(qty, bool) or not isinstance(qty, (int, float))):
            raise ValueError(f"line item {n}: qty must be a number or null")
        if item.get("uom") is not None and item["uom"] not in UOMS:
            raise ValueError(f"line item {n}: uom {item['uom']!r} is not one of {', '.join(UOMS)} or null")
        lines.append({k: item.get(k) for k in ("raw", "description", "qty", "uom", "source")})
    return {
        "analysis": data["analysis"],
        "classification": data["classification"],
        "needs_review": data["needs_review"],
        "review_reason": data["review_reason"],
        "line_items": lines,
    }


# =========================================================================== engine

class Engine:
    """Cache -> model -> validate (one repair retry) -> cache. Raises ModelError."""

    def __init__(self, client, cache: Cache, ledger: Ledger, prompt_version: str = PROMPT_VERSION):
        self.client = client
        self.cache = cache
        self.ledger = ledger
        self.prompt_version = prompt_version
        self.model = client.model if client is not None else (
            os.environ.get("RFQINBOX_MODEL", "").strip() or DEFAULT_MODEL)
        ledger.model, ledger.prompt_version = self.model, prompt_version

    def extract(self, email_id: str, text: str, images=(), image_keys=None) -> dict:
        """images: raw bytes or (label, bytes, detail). image_keys: what stands for each
        image in the cache key (default: the image bytes themselves)."""
        images = [_as_image(i, image) for i, image in enumerate(images, 1)]
        keyed = list(image_keys) if image_keys is not None else [data for _, data, _ in images]
        # The prompt text is part of the key: an edited prompt never replays old answers,
        # even if PROMPT_VERSION was not bumped.
        version = f"{self.prompt_version}:{_sha(SYSTEM_PROMPT)[:16]}"
        request = request_key(version, OUTPUT_SCHEMA, text, keyed)
        key = cache_key(self.model, version, OUTPUT_SCHEMA, text, keyed)

        entry = self.cache.get(key)
        if entry is None and self.client is None:
            entry = self.cache.find_request(request)
        if entry is not None:
            try:
                output = validate_output(json.dumps(entry["output"]))
                usage = entry.get("usage") or {}
                self.ledger.add(email_id, str(entry.get("model") or self.model),
                                int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0),
                                cached=True, calls=int(usage.get("calls") or 1))
                return output
            except (KeyError, ValueError, TypeError):
                pass  # a damaged entry is a miss
        if self.client is None:
            raise ModelError("OPENAI_API_KEY is not set and this email has no cached answer")

        messages = build_messages(text, images)
        usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
        problem = ""
        for _ in range(2):
            done = self._call(email_id, messages, usage)
            try:
                output = validate_output(done.text)
            except ValueError as exc:
                problem = str(exc)
                messages = messages + [
                    {"role": "assistant", "content": done.text},
                    {"role": "user", "content": f"That reply was not usable: {problem}. "
                                                "Reply again with only the complete JSON object."},
                ]
                continue
            self.cache.put(key, {"model": self.model, "prompt_version": self.prompt_version,
                                 "request": request, "email": email_id, "usage": usage, "output": output})
            return output
        raise ModelError(f"model reply was malformed twice ({problem[:200]})")

    def _call(self, email_id: str, messages: list[dict], usage: dict) -> Completion:
        try:
            done = self.client.complete(messages, OUTPUT_SCHEMA)
        except ModelError:
            raise
        except Exception as exc:  # noqa: BLE001 — nothing from the model step may crash the run
            redact = getattr(self.client, "redact", lambda s: s)
            raise ModelError(redact(f"unexpected error ({type(exc).__name__}: {str(exc)[:200]})")) from None
        self.ledger.add(email_id, self.model, done.input_tokens, done.output_tokens, cached=False)
        usage["calls"] += 1
        usage["input_tokens"] += done.input_tokens
        usage["output_tokens"] += done.output_tokens
        return done
