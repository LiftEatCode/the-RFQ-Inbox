"""Local scorer: data/README.md's "What we grade", implemented against answer_key.json.

    python -m rfqinbox score parsed.json [--key data/dev/answer_key.json] [--gate]

This is our reading of the README, not the graders' code. Where the README is
silent we chose (and say so here):
- lines are paired within an email on the tokens of `raw` (Dice similarity of
  token multisets, >= 0.5, best pairs first); sizes like 1-1/2 stay one token
  so 1/2 and 1-1/2 lines don't swap partners
- hallucinated = predicted lines with no partner (on any email)
- lost = a key request (rfq / rfq_revision / purchase_order) predicted as a
  non-request; phantom = the reverse
- link accuracy is computed over emails where the key or the prediction sets
  `revises` or `duplicate_of`
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

ACTION = {"rfq", "rfq_revision", "purchase_order"}
PAIR_THRESHOLD = 0.5

# --------------------------------------------------------------------------- mentions

# README: "case, spaces and punctuation ignored, and common spellings of the same
# spec count as equal". Each rule maps spellings to one canonical form.
_CANON = [
    (r"\bschedule\b", "sch"),
    (r"\bclass\s*(\d+)", r"\1#"),
    (r"(\d+)\s*(?:#|lbs?\b|lb\.)", r"\1#"),
    (r"\bbutt\s*-?\s*weld(?:ed)?\b", "bw"),
    (r"\b(?:npt|thd|thrd|threaded)\b", "thd"),
    (r"\bseamless\b", "smls"),
    (r"\bgalvani[sz]ed\b", "galv"),
    (r"\bspiral\s*-?\s*wound\b", "spw"),
    (r"\bmalleable\s+iron\b", "mi"),
    (r"\bcarbon\s+steel\b", "cs"),
    (r"\bfull\s*-?\s*port\b", "fp"),
    (r"\b(?:elbows?|ells)\b", "ell"),
    (r"\bvalves?\b", "vlv"),
    (r"\bflanges?\b", "flg"),
    (r"\bgaskets?\b", "gskt"),
    (r"\breducers?\b", "red"),
    (r"\bcouplings?\b", "cplg"),
]


def _plain(s: str) -> str:
    return re.sub(r"[\W_]+", "", s.lower())


def _canon(s: str) -> str:
    s = s.lower()
    for pat, rep in _CANON:
        s = re.sub(pat, rep, s)
    return _plain(s)


def mentions(description: str, phrase: str) -> bool:
    """True if the description contains the phrase (any `a|b` alternative).

    Checked both as written and after canonical spellings, so "malleable" still
    matches "malleable iron" and "150#" matches "Class 150".
    """
    for alt in phrase.split("|"):
        alt = alt.strip()
        if not alt:
            continue
        if _plain(alt) in _plain(description) or _canon(alt) in _canon(description):
            return True
    return False


# --------------------------------------------------------------------------- pairing

_TOKEN = re.compile(r"\d+(?:[-/.]\d+)*|[a-z]+")


def _tokens(raw: str) -> Counter:
    return Counter(_TOKEN.findall((raw or "").lower()))


def similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    n = sum(ta.values()) + sum(tb.values())
    return 2 * sum((ta & tb).values()) / n if n else 0.0


def pair_lines(key_lines: list[dict], pred_lines: list[dict]) -> list[tuple[int, int]]:
    """Best-first one-to-one pairing of key and predicted lines in one email."""
    cands = []
    for i, k in enumerate(key_lines):
        for j, p in enumerate(pred_lines):
            s = similarity(k.get("raw", ""), p.get("raw", ""))
            if s >= PAIR_THRESHOLD:
                bonus = 0.01 if k.get("qty") == p.get("qty") else 0.0
                cands.append((s + bonus, i, j))
    cands.sort(key=lambda c: (-c[0], c[1], c[2]))
    used_k, used_p, pairs = set(), set(), []
    for _, i, j in cands:
        if i not in used_k and j not in used_p:
            used_k.add(i)
            used_p.add(j)
            pairs.append((i, j))
    return sorted(pairs)


# --------------------------------------------------------------------------- field checks

def qty_ok(key_line: dict, pred_line: dict) -> bool | None:
    """None = unscored (qty_tol is null)."""
    tol = key_line.get("qty_tol")
    if tol is None:
        return None
    k, p = key_line.get("qty"), pred_line.get("qty")
    if k is None or p is None:
        return k is None and p is None
    return abs(p - k) <= tol * abs(k) + 1e-9


def uom_ok(key_line: dict, pred_line: dict) -> bool:
    return (key_line.get("uom") or "EA") == (pred_line.get("uom") or "EA")


def source_ok(key_line: dict, pred_line: dict) -> bool:
    return (key_line.get("source") or "").strip().lower() == (pred_line.get("source") or "").strip().lower()


def context_check(key_line: dict, description: str) -> tuple[list[str], list[str]]:
    missing = [m for m in key_line.get("must_mention", []) if not mentions(description, m)]
    forbidden = [m for m in key_line.get("must_not_mention", []) if mentions(description, m)]
    return missing, forbidden


def _ratio(num: int, den: int) -> float | None:
    return num / den if den else None


# --------------------------------------------------------------------------- score

def score(pred: dict, key: dict) -> dict:
    """pred: parsed.json content. key: answer_key.json["emails"]."""
    silent, lost, phantom, cls_wrong = [], [], [], []
    missed, halluc_detail, ctx_fail, field_fail = [], [], [], []
    n_key_lines = n_pred_lines = n_paired = 0
    qty = [0, 0]; uom = [0, 0]; src = [0, 0]; ctx = [0, 0]
    links = [0, 0]
    nr_tp = nr_pred = nr_key = 0

    for eid in sorted(set(key) | set(pred)):
        k, p = key.get(eid), pred.get(eid)
        p_lines = (p or {}).get("line_items") or []
        if k is None:  # email not in key: every predicted line is unpaired
            n_pred_lines += len(p_lines)
            halluc_detail += [(eid, ln.get("raw")) for ln in p_lines]
            continue
        k_lines = k.get("line_items") or []
        n_key_lines += len(k_lines)
        n_pred_lines += len(p_lines)

        needs_action = bool(k_lines) or bool(k.get("needs_review"))
        if p is None:
            if needs_action:
                silent.append(eid)
            cls_wrong.append(eid)
            missed += [ln.get("id") for ln in k_lines]
            nr_key += bool(k.get("needs_review"))
            continue

        if needs_action and not p_lines and not p.get("needs_review"):
            silent.append(eid)
        kc, pc = k.get("classification"), p.get("classification")
        if kc != pc:
            cls_wrong.append(eid)
        if kc in ACTION and pc not in ACTION:
            lost.append(eid)
        if kc not in ACTION and pc in ACTION:
            phantom.append(eid)

        if any(k.get(f) or p.get(f) for f in ("revises", "duplicate_of")):
            links[1] += 1
            links[0] += all(k.get(f) == p.get(f) for f in ("revises", "duplicate_of"))

        nr_key += bool(k.get("needs_review"))
        nr_pred += bool(p.get("needs_review"))
        nr_tp += bool(k.get("needs_review")) and bool(p.get("needs_review"))

        pairs = pair_lines(k_lines, p_lines)
        n_paired += len(pairs)
        paired_k = {i for i, _ in pairs}
        paired_p = {j for _, j in pairs}
        missed += [ln.get("id") for i, ln in enumerate(k_lines) if i not in paired_k]
        halluc_detail += [(eid, ln.get("raw")) for j, ln in enumerate(p_lines) if j not in paired_p]

        for i, j in pairs:
            kl, pl = k_lines[i], p_lines[j]
            q = qty_ok(kl, pl)
            if q is not None:
                qty[1] += 1
                qty[0] += q
            u, s = uom_ok(kl, pl), source_ok(kl, pl)
            uom[1] += 1; uom[0] += u
            src[1] += 1; src[0] += s
            if q is False or not u or not s:
                field_fail.append({
                    "id": kl.get("id"),
                    "qty": (kl.get("qty"), pl.get("qty")) if q is False else None,
                    "uom": (kl.get("uom"), pl.get("uom")) if not u else None,
                    "source": (kl.get("source"), pl.get("source")) if not s else None,
                })
            missing, forbidden = context_check(kl, pl.get("description") or "")
            ctx[1] += 1
            ok = not missing and not forbidden
            ctx[0] += ok
            if not ok:
                ctx_fail.append({"id": kl.get("id"), "missing": missing, "forbidden": forbidden,
                                 "description": pl.get("description")})

    n_key = len(key)
    return {
        "emails": n_key,
        "silent_losses": silent,
        "hallucinated_lines": len(halluc_detail),
        "hallucinated_detail": halluc_detail,
        "lost_requests": lost,
        "phantom_requests": phantom,
        "classification_accuracy": _ratio(n_key - len(cls_wrong), n_key),
        "misclassified": cls_wrong,
        "key_lines": n_key_lines,
        "pred_lines": n_pred_lines,
        "paired_lines": n_paired,
        "line_recall": _ratio(n_paired, n_key_lines),
        "line_precision": _ratio(n_paired, n_pred_lines),
        "missed_lines": missed,
        "qty_accuracy": _ratio(*qty),
        "uom_accuracy": _ratio(*uom),
        "source_accuracy": _ratio(*src),
        "field_failures": field_fail,
        "context_accuracy": _ratio(*ctx),
        "context_failures": ctx_fail,
        "link_accuracy": _ratio(*links),
        "needs_review_precision": _ratio(nr_tp, nr_pred),
        "needs_review_recall": _ratio(nr_tp, nr_key),
    }


# --------------------------------------------------------------------------- report

def _pct(x: float | None) -> str:
    return "  n/a" if x is None else f"{100 * x:5.1f}%"


def format_report(r: dict, verbose: bool = True) -> str:
    out = [
        f"Emails scored: {r['emails']}",
        "",
        "HEADLINE (lower is better)",
        f"  silent losses        {len(r['silent_losses']):4d}  {' '.join(r['silent_losses'])}",
        f"  hallucinated lines   {r['hallucinated_lines']:4d}",
        f"  lost requests        {len(r['lost_requests']):4d}  {' '.join(r['lost_requests'])}",
        f"  phantom requests     {len(r['phantom_requests']):4d}  {' '.join(r['phantom_requests'])}",
        "",
        "ACCURACY",
        f"  classification       {_pct(r['classification_accuracy'])}  wrong: {' '.join(r['misclassified'])}",
        f"  line recall          {_pct(r['line_recall'])}  ({r['paired_lines']}/{r['key_lines']})",
        f"  line precision       {_pct(r['line_precision'])}  ({r['paired_lines']}/{r['pred_lines']})",
        f"  qty                  {_pct(r['qty_accuracy'])}",
        f"  uom                  {_pct(r['uom_accuracy'])}",
        f"  source               {_pct(r['source_accuracy'])}",
        f"  context carried      {_pct(r['context_accuracy'])}",
        f"  revises/duplicate_of {_pct(r['link_accuracy'])}",
        f"  needs_review P / R   {_pct(r['needs_review_precision'])} / {_pct(r['needs_review_recall'])}",
    ]
    if verbose:
        if r["hallucinated_detail"]:
            out += ["", "HALLUCINATED"] + [f"  {e}: {raw!r}" for e, raw in r["hallucinated_detail"]]
        if r["missed_lines"]:
            out += ["", "MISSED", "  " + " ".join(str(m) for m in r["missed_lines"])]
        if r["field_failures"]:
            out += ["", "FIELD ERRORS (key, ours)"]
            for f in r["field_failures"]:
                bits = [f"{k}={v}" for k, v in f.items() if k != "id" and v is not None]
                out.append(f"  {f['id']}: {', '.join(bits)}")
        if r["context_failures"]:
            out += ["", "CONTEXT ERRORS"]
            for f in r["context_failures"]:
                out.append(f"  {f['id']}: missing={f['missing']} forbidden={f['forbidden']} | {f['description']}")
    return "\n".join(out)


def load_key(path: Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data["emails"] if "emails" in data else data
