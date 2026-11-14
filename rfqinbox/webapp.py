"""The optional web app: `python -m rfqinbox serve --emails <dir> --parsed parsed.json`.

One email walked through the system for a rep: the email and its attachments as the reader
sees them, the extracted lines and where each was read from, and each line's catalog
decision, which the rep can accept or overturn.

It only reads. The emails go through the same reader as `parse`; the answers come from
parsed.json; nothing here calls the model. A rep's decisions are written to a separate
review.json, so parsed.json stays exactly what the pipeline produced. Standard library only,
and it listens on this machine only.
"""

from __future__ import annotations

import csv
import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from rfqinbox import checks, matcher, reader

MAX_POST = 64 * 1024
FOUND_AT = 0.8          # share of a line's words that must be on one source line to point at it
MATCH_FIELDS = ("sku", "match", "match_reason", "candidates")


# --------------------------------------------------------------------------- locating a line

def _best_line(raw: str, lines: list[str]) -> int | None:
    """Index of the source line that holds (nearly) all the words of `raw`, or None."""
    words = checks._tokens(raw or "")
    if not words:
        return None
    best, best_score = None, 0.0
    for i, text in enumerate(lines):
        score = len(words & checks._tokens(text)) / len(words)
        if score > best_score:
            best, best_score = i, score
    return best if best_score >= FOUND_AT else None


def _locate(line: dict, body: list[str], quoted: list[list[str]], attachments: list[dict]) -> dict | None:
    """Where an extracted line was read from: {"where": "body" | "quoted" | filename, "line": n}.
    A line read from a picture points at the picture (line None). Not found -> None."""
    source = (line.get("source") or "body").strip()
    raw = line.get("raw") or ""
    named = [a for a in attachments if a["filename"].lower() == source.lower()]
    for att in named + ([] if source.lower() == "body" else [a for a in attachments if a not in named]):
        i = _best_line(raw, [ln["text"] for ln in att["lines"]])
        if i is not None:
            return {"where": att["filename"], "line": i}
        if att in named and att["images"]:
            return {"where": att["filename"], "line": None}
        if att in named:
            break
    i = _best_line(raw, body)
    if i is not None:
        return {"where": "body", "line": i}
    for k, block in enumerate(quoted):
        i = _best_line(raw, block)
        if i is not None:
            return {"where": "quoted", "block": k, "line": i}
    return None


# --------------------------------------------------------------------------- the app

class App:
    def __init__(self, emails_dir, parsed_path, review_path=None, catalog_path=None):
        self.emails_dir = Path(emails_dir)
        self.parsed_path = Path(parsed_path)
        self.review_path = Path(review_path) if review_path else self.parsed_path.resolve().parent / "review.json"
        self.catalog_path = Path(catalog_path) if catalog_path else matcher.default_catalog_path()
        self._parts: dict[str, str] | None = None

    # ---- data

    def parsed(self) -> dict:
        return json.loads(self.parsed_path.read_text(encoding="utf-8"))

    def review(self) -> dict:
        try:
            data = json.loads(self.review_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def parts(self) -> dict[str, str]:
        """sku -> the catalog's description. Empty if there is no catalog."""
        if self._parts is None:
            try:
                with self.catalog_path.open(encoding="utf-8-sig", newline="") as f:
                    self._parts = {r["sku"].strip(): (r.get("description") or "").strip()
                                   for r in csv.DictReader(f) if (r.get("sku") or "").strip()}
            except (OSError, KeyError, ValueError):
                self._parts = {}
        return self._parts

    def _packet(self, email_id: str):
        try:
            return reader.read_email(self.emails_dir / f"{email_id}.eml"), None
        except Exception as exc:  # noqa: BLE001 — the page must still show what was extracted
            return None, f"could not read this email ({type(exc).__name__}: {exc})"

    def view(self, email_id: str) -> dict:
        """Everything the email page shows, as plain data."""
        record = self.parsed()[email_id]
        pk, error = self._packet(email_id)
        body = [{"text": t, "lines": []} for t in (pk.body_new.splitlines() if pk else [])]
        quoted = [{"kind": q.kind, "lines": [{"text": t, "lines": []} for t in q.text.splitlines()]}
                  for q in (pk.quoted if pk else [])]
        attachments = [{"filename": a.filename, "kind": a.kind, "status": a.status, "notes": list(a.notes),
                        "images": len(a.images),
                        "lines": [{"text": t, "lines": []} for t in a.text.splitlines()]}
                       for a in (pk.attachments if pk else [])]
        decisions = self.review().get(email_id, {})
        parts = self.parts()
        lines = []
        for i, ln in enumerate(record.get("line_items") or []):
            found = _locate(ln, [b["text"] for b in body], [[x["text"] for x in q["lines"]] for q in quoted],
                            attachments) if pk else None
            if found and found["line"] is not None:
                if found["where"] == "body":
                    target = body
                elif found["where"] == "quoted":
                    target = quoted[found["block"]]["lines"]
                else:
                    target = next(a for a in attachments if a["filename"] == found["where"])["lines"]
                target[found["line"]]["lines"].append(i)
            item = {k: ln.get(k) for k in ("raw", "description", "qty", "uom", "source")}
            item.update({k: ln.get(k) for k in MATCH_FIELDS})
            item.update({
                "index": i, "found": found,
                "part": parts.get(ln.get("sku") or ""),
                "candidate_parts": [{"sku": s, "description": parts.get(s, "")} for s in ln.get("candidates") or []],
                "decision": decisions.get(str(i)),
            })
            lines.append(item)
        return {
            "id": email_id, "error": error,
            "subject": pk.subject if pk else "", "sender": pk.sender if pk else "",
            "to": pk.to if pk else "", "date": pk.date if pk else "",
            "notes": list(pk.notes) if pk else [],
            "classification": record.get("classification"), "revises": record.get("revises"),
            "duplicate_of": record.get("duplicate_of"), "needs_review": bool(record.get("needs_review")),
            "review_reason": record.get("review_reason"),
            "body": body, "quoted": quoted, "attachments": attachments, "lines": lines,
        }

    # ---- decisions

    def decide(self, payload) -> tuple[bool, str]:
        """Record a rep's accept / overturn in review.json. Returns (ok, message)."""
        if not isinstance(payload, dict):
            return False, "expected an object"
        parsed = self.parsed()
        email_id, index, action = payload.get("email"), payload.get("line"), payload.get("action")
        if not isinstance(email_id, str) or email_id not in parsed:
            return False, "unknown email"
        lines = parsed[email_id].get("line_items") or []
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(lines):
            return False, "unknown line"
        ours = lines[index].get("sku")
        if action == "accept":
            decision = {"action": "accept", "sku": ours, "was": ours}
        elif action == "overturn":
            sku = payload.get("sku")
            if sku is not None and (not isinstance(sku, str) or sku not in self.parts()):
                return False, "that sku is not in the catalog"
            decision = {"action": "overturn", "sku": sku, "was": ours}
        else:
            return False, "action must be accept or overturn"
        review = self.review()
        review.setdefault(email_id, {})[str(index)] = decision
        from rfqinbox.cli import write_json_atomic
        write_json_atomic(review, self.review_path)
        return True, "saved"

    # ---- http

    def handle(self, method: str, path: str, body: bytes | None = None) -> tuple[int, str, bytes]:
        """(status, content type, body). No sockets: the server and the tests both call this."""
        try:
            parts = [p for p in path.split("?", 1)[0].split("/") if p]
            if method == "POST" and parts == ["decision"]:
                return self._post_decision(body or b"")
            if method != "GET":
                return _page(405, "Not allowed", "<p>Method not allowed.</p>")
            if not parts:
                return _page(200, "RFQ inbox", self._inbox_html())
            parsed = self.parsed()
            if parts[0] == "email" and len(parts) == 2 and parts[1] in parsed:
                return _page(200, parts[1], self._email_html(self.view(parts[1])))
            if parts[0] == "image" and len(parts) == 4 and parts[1] in parsed:
                return self._image(parts[1], parts[2], parts[3])
            return _page(404, "Not found", '<p>Nothing here. <a href="/">Back to the inbox</a></p>')
        except Exception as exc:  # noqa: BLE001 — a bad page must not take the server down
            return _page(500, "Error", f"<p>Something went wrong: {_e(type(exc).__name__)}: {_e(exc)}</p>")

    def _post_decision(self, body: bytes) -> tuple[int, str, bytes]:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            payload = None
            ok, message = False, "not JSON"
        else:
            ok, message = self.decide(payload)
        out = json.dumps({"ok": ok, "message": message}).encode("utf-8")
        return (200 if ok else 400), "application/json; charset=utf-8", out

    def _image(self, email_id: str, att: str, n: str) -> tuple[int, str, bytes]:
        pk, _ = self._packet(email_id)
        try:
            data = pk.attachments[int(att)].images[int(n)]
        except (AttributeError, ValueError, IndexError):
            return _page(404, "Not found", "<p>No such picture.</p>")
        return 200, ("image/png" if data[:4] == b"\x89PNG" else "image/jpeg"), data

    # ---- pages

    def _inbox_html(self) -> str:
        parsed, review = self.parsed(), self.review()
        rows = []
        for eid in sorted(parsed):
            rec = parsed[eid]
            try:
                hd = reader.read_headers(self.emails_dir / f"{eid}.eml")
                subject, sender = hd.subject, hd.sender
            except Exception:  # noqa: BLE001
                subject, sender = "(could not read this email)", ""
            n = len(rec.get("line_items") or [])
            flags = []
            if rec.get("needs_review"):
                flags.append('<span class="tag warn">needs review</span>')
            if rec.get("duplicate_of"):
                flags.append(f'<span class="tag">duplicate of {_e(rec["duplicate_of"])}</span>')
            if rec.get("revises"):
                flags.append(f'<span class="tag">revises {_e(rec["revises"])}</span>')
            done = len(review.get(eid, {}))
            if n and any("match" in ln for ln in rec["line_items"]):
                flags.append(f'<span class="tag">{done}/{n} reviewed</span>')
            rows.append(f'<tr><td><a href="/email/{_e(eid)}">{_e(eid)}</a></td>'
                        f'<td><span class="tag cls">{_e(rec.get("classification"))}</span></td>'
                        f'<td class="num">{n}</td><td>{_e(subject)}<div class="dim">{_e(sender)}</div></td>'
                        f'<td>{" ".join(flags)}</td></tr>')
        return ('<h1>RFQ inbox</h1><p class="dim">Read from parsed.json. Nothing here calls the model.</p>'
                '<table class="inbox"><tr><th>Email</th><th>Kind</th><th>Lines</th><th>Subject</th><th></th></tr>'
                + "".join(rows) + "</table>")

    def _email_html(self, v: dict) -> str:
        head = [f'<p><a href="/">&larr; Inbox</a></p><h1>{_e(v["id"])}: {_e(v["subject"]) or "(no subject)"}</h1>',
                f'<p><span class="tag cls">{_e(v["classification"])}</span> ']
        if v["needs_review"]:
            head.append(f'<span class="tag warn">needs review</span> {_e(v["review_reason"])} ')
        for field, label in (("duplicate_of", "duplicate of"), ("revises", "revises")):
            if v[field]:
                head.append(f'<span class="tag">{label} <a href="/email/{_e(v[field])}">{_e(v[field])}</a></span> ')
        head.append("</p>")
        if v["error"]:
            head.append(f'<p class="warnbox">{_e(v["error"])}. The lines below are what was extracted.</p>')

        left = [f'<h2>1. The email</h2><div class="hdr"><b>From</b> {_e(v["sender"])}<br><b>To</b> {_e(v["to"])}'
                f'<br><b>Date</b> {_e(v["date"])}</div>',
                "<h3>New text</h3>", _source_block("body", v["body"]) or '<p class="dim">(empty)</p>']
        for k, q in enumerate(v["quoted"]):
            label = "Forwarded content" if q["kind"] == "forward" else "Quoted history (not a request unless the new text says so)"
            left.append(f'<h3 class="dim">{label}</h3>' + _source_block(f"quoted-{k}", q["lines"], "quoted"))
        for a_i, a in enumerate(v["attachments"]):
            notes = "".join(f'<div class="dim">{_e(n)}</div>' for n in a["notes"])
            left.append(f'<h3 id="att-{a_i}" data-file="{_e(a["filename"])}">Attachment: {_e(a["filename"])} '
                        f'<span class="tag">{_e(a["kind"])}</span> <span class="tag">{_e(a["status"])}</span></h3>{notes}')
            left.append(_source_block(f"att-{a_i}", a["lines"]))
            left += [f'<img class="pic" src="/image/{_e(v["id"])}/{a_i}/{n}" alt="{_e(a["filename"])} picture {n + 1}">'
                     for n in range(a["images"])]

        files = {a["filename"]: i for i, a in enumerate(v["attachments"])}
        rows = []
        for ln in v["lines"]:
            rows.append(f'<tr class="line" data-target="{_e(_target(ln["found"], files))}">'
                        f'<td class="num">{ln["index"] + 1}</td>'
                        f'<td class="num">{_e("" if ln["qty"] is None else ln["qty"])} {_e(ln["uom"] or "")}</td>'
                        f'<td>{_e(ln["description"])}<div class="dim raw">{_e(ln["raw"])}</div></td>'
                        f'<td>{_where(ln)}</td><td>{_match_cell(v["id"], ln)}</td></tr>')
        right = ['<h2>2. Lines extracted, and 3. the catalog decision</h2>']
        if rows:
            right.append('<p class="dim">Click a line to see where it was read from.</p>'
                         '<table class="lines"><tr><th>#</th><th>Qty</th><th>Description <span class="dim">/ as written</span></th>'
                         '<th>Read from</th><th>Catalog</th></tr>' + "".join(rows) + "</table>")
        else:
            right.append('<p class="dim">No lines were extracted from this email.</p>')
        datalist = "".join(f'<option value="{_e(s)}">{_e(d)}</option>' for s, d in sorted(self.parts().items()))
        return ("".join(head) + '<div class="cols"><section>' + "".join(left) + "</section><section>"
                + "".join(right) + f'</section></div><datalist id="skus">{datalist}</datalist>')


# --------------------------------------------------------------------------- html helpers

def _e(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _source_block(prefix: str, lines: list[dict], cls: str = "") -> str:
    if not lines:
        return ""
    out = []
    for i, ln in enumerate(lines):
        used = " used" if ln["lines"] else ""
        badge = "".join(f'<span class="ref">{n + 1}</span>' for n in ln["lines"])
        out.append(f'<div class="src{used}" id="{prefix}-{i}">{badge}{_e(ln["text"]) or "&nbsp;"}</div>')
    return f'<div class="source {cls}">' + "".join(out) + "</div>"


def _target(found: dict | None, files: dict[str, int]) -> str:
    if not found:
        return ""
    if found["where"] == "body":
        return f'body-{found["line"]}'
    if found["where"] == "quoted":
        return f'quoted-{found["block"]}-{found["line"]}'
    a = files.get(found["where"])
    return f"att-{a}" if found["line"] is None else f'att-{a}-{found["line"]}'


def _where(ln: dict) -> str:
    found = ln["found"]
    if not found:
        return f'{_e(ln["source"])}<div class="dim">not located in the email text</div>'
    if found["line"] is None:
        return f'{_e(found["where"])}<div class="dim">read from the picture</div>'
    place = {"body": "body", "quoted": "quoted history"}.get(found["where"], found["where"])
    return f'{_e(place)}<div class="dim">line {found["line"] + 1}</div>'


_LABELS = {"matched": ("ok", "matched"), "not_in_catalog": ("no", "not in catalog"), "ambiguous": ("ask", "ask the customer")}


def _match_cell(email_id: str, ln: dict) -> str:
    if not ln["match"]:
        return '<span class="dim">no catalog answer (parsed without the matcher)</span>'
    cls, label = _LABELS.get(ln["match"], ("", ln["match"]))
    out = [f'<span class="tag {cls}">{_e(label)}</span> ']
    if ln["sku"]:
        out.append(f'<b>{_e(ln["sku"])}</b> {_e(ln["part"])}')
    out.append(f'<div class="dim">{_e(ln["match_reason"])}</div>')
    if ln["candidate_parts"]:
        out.append('<div class="dim">Candidates: ' + "; ".join(
            f'{_e(c["sku"])} {_e(c["description"])}' for c in ln["candidate_parts"]) + "</div>")
    d = ln["decision"]
    if d:
        if d["action"] == "accept":
            out.append('<div class="decided">Rep: accepted</div>')
        elif d["sku"]:
            out.append(f'<div class="decided">Rep: overturned to <b>{_e(d["sku"])}</b></div>')
        else:
            out.append('<div class="decided">Rep: overturned to not stocked</div>')
    key = f'data-email="{_e(email_id)}" data-line="{ln["index"]}"'
    out.append(f'<div class="act" {key}><button data-do="accept">Accept</button> '
               f'<input list="skus" placeholder="other sku" size="10" aria-label="Other sku"> '
               f'<button data-do="sku">Use this part</button> <button data-do="none">Not stocked</button></div>')
    return "".join(out)


_CSS = """
:root{--bg:#fff;--fg:#1a1a1a;--dim:#666;--line:#ddd;--hl:#fff3b0;--used:#eef6ff;--ok:#d9f2dd;--no:#f9dcdc;--ask:#fdebc8;--card:#f7f7f7}
@media (prefers-color-scheme:dark){:root{--bg:#161616;--fg:#e8e8e8;--dim:#9a9a9a;--line:#3a3a3a;--hl:#5c4d00;--used:#1d2c3d;--ok:#1f4527;--no:#55262a;--ask:#54421a;--card:#202020}}
body{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;margin:0;padding:16px}
a{color:inherit}h1{font-size:20px;margin:0 0 8px}h2{font-size:16px;margin:16px 0 8px}h3{font-size:13px;margin:14px 0 4px}
.dim{color:var(--dim);font-size:12px}.raw{font-family:ui-monospace,monospace}
.cols{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.2fr);gap:24px}
@media (max-width:900px){.cols{grid-template-columns:minmax(0,1fr)}}
table{border-collapse:collapse;width:100%}th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
.num{white-space:nowrap}.tag{display:inline-block;border:1px solid var(--line);border-radius:4px;padding:0 6px;font-size:12px}
.tag.warn{background:var(--ask)}.tag.ok{background:var(--ok)}.tag.no{background:var(--no)}.tag.ask{background:var(--ask)}.tag.cls{background:var(--card)}
.warnbox{background:var(--ask);padding:8px;border-radius:4px}.hdr{background:var(--card);padding:8px;border-radius:4px}
.source{font:12px/1.5 ui-monospace,monospace;border:1px solid var(--line);border-radius:4px;padding:6px;overflow-x:auto;white-space:pre-wrap;word-break:break-word}
.source.quoted{color:var(--dim)}.src.used{background:var(--used)}.src.hl,h3.hl{background:var(--hl)}
.ref{display:inline-block;min-width:16px;text-align:center;border:1px solid var(--line);border-radius:8px;font-size:10px;margin-right:4px}
.pic{max-width:100%;border:1px solid var(--line);margin-top:6px}
tr.line{cursor:pointer}tr.line.sel{background:var(--used)}
.act{margin-top:6px}.act button,.act input{font:inherit;font-size:12px}.decided{margin-top:4px;font-weight:600}
"""

_JS = """
document.querySelectorAll('tr.line').forEach(function(row){
  row.addEventListener('click',function(ev){
    if(ev.target.closest('.act'))return;
    document.querySelectorAll('.hl').forEach(function(x){x.classList.remove('hl')});
    document.querySelectorAll('tr.sel').forEach(function(x){x.classList.remove('sel')});
    row.classList.add('sel');
    var t=row.dataset.target&&document.getElementById(row.dataset.target);
    if(t){t.classList.add('hl');t.scrollIntoView({block:'center',behavior:'smooth'});}
  });
});
document.querySelectorAll('.act button').forEach(function(b){
  b.addEventListener('click',function(){
    var box=b.parentElement,body={email:box.dataset.email,line:Number(box.dataset.line)};
    if(b.dataset.do==='accept'){body.action='accept';}
    else{body.action='overturn';body.sku=b.dataset.do==='none'?null:box.querySelector('input').value.trim();}
    fetch('/decision',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
      .then(function(r){return r.json()}).then(function(j){if(j.ok){location.reload()}else{alert(j.message)}});
  });
});
"""


def _page(status: int, title: str, body: str) -> tuple[int, str, bytes]:
    doc = (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
           f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>{_e(title)}</title>'
           f"<style>{_CSS}</style></head><body>{body}<script>{_JS}</script></body></html>")
    return status, "text/html; charset=utf-8", doc.encode("utf-8")


# --------------------------------------------------------------------------- server

def make_server(app: App, port: int = 8000, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    """An HTTP server for the app. It binds to this machine only by default."""

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, ctype: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            self._send(*app.handle("GET", self.path))

        def do_POST(self):  # noqa: N802
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if not 0 <= length <= MAX_POST:
                self._send(400, "application/json; charset=utf-8", b'{"ok": false, "message": "too large"}')
                return
            self._send(*app.handle("POST", self.path, self.rfile.read(length)))

        def log_message(self, *args):  # quiet: this is a local tool
            pass

    return ThreadingHTTPServer((host, port), Handler)
