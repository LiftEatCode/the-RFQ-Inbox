"""Prompt v1: what a prompt can be held to without calling a model.

Whether the prompt *works* is measured by `rfqinbox score` on dev, not here. These
tests hold the things code can check:

- the prompt teaches the general properties of this inbox, and none of dev's answers;
- the model writes down its reading of the email before it answers, and that working
  never reaches parsed.json;
- an edited prompt can never replay answers recorded for the old one.
"""

from __future__ import annotations

import json
import re

import pytest

from conftest import DEV_EMAILS, ROOT, make_eml
from rfqinbox import cli, model, reader, score
from rfqinbox.record import CLASSES, UOMS
from test_model import FakeClient, answer, make_engine


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


PROMPT = model.SYSTEM_PROMPT
PROMPT_NORM = norm(PROMPT)


# ------------------------------------------------------------------ it is v1, and affordable

def test_prompt_version_is_v3():
    assert model.PROMPT_VERSION == "v3"


def test_prompt_is_short_enough_to_send_with_every_email():
    """It is paid for on every call (~4 characters per token)."""
    assert 1500 < len(PROMPT) < 9000


# ------------------------------------------------------------------ it states the contract

@pytest.mark.parametrize("value", CLASSES)
def test_prompt_defines_every_classification(value):
    assert value in PROMPT


def test_prompt_lists_the_allowed_units():
    for uom in UOMS:
        assert re.search(rf"\b{uom}\b", PROMPT), uom


def test_prompt_knows_who_we_are():
    assert reader.INTERNAL_DOMAIN in PROMPT       # our own reps forward customers' emails
    assert "Q-26" in PROMPT                       # our quote numbers (README world facts)


# ------------------------------------------------------------------ it teaches the general properties

# Each entry: a property of this inbox (CLAUDE.md, "What the dev data taught us") and
# words of which at least one must appear. Loose on purpose: this is a checklist that
# nothing was forgotten, not a test of wording.
PROPERTIES = {
    "quoted history is not a request": ["quoted history"],
    "forwarded content from our own rep counts": ["forward"],
    "hidden sheets and rows are old revisions": ["hidden"],
    "crossed-out lines are not requests": ["struck", "strike", "crossed"],
    "totals, prices and signatures are not lines": ["total", "signature"],
    "a supplier quoting us is not a request": ["supplier", "vendor"],
    "a bounce carrying our own RFQ is not a request": ["bounce", "undeliver"],
    "marketing price lists are not requests": ["promo", "marketing", "newsletter"],
    "headings scope only their own block": ["heading"],
    "defaults with per-line overrides": ["unless noted", "override"],
    "form fields, sheet names and column headers carry context": ["form field", "sheet name"],
    "ditto marks and 'same as above'": ["ditto", "same as above", "same size"],
    "a revision returns the complete order": ["complete order", "complete list"],
    "a PO reply takes its lines from our quote": ["go ahead"],
    "sizes, schedules and ratings are never quantities": ["never a quantity", "not a quantity",
                                                           "never quantities", "not quantities"],
    "spelled-out numbers count, vague amounts are null": ["spelled", "vague"],
    "never invent a spec": ["invent"],
    "raw stays close to the source": ["verbatim", "as written", "as it appears"],
    "attachment mentioned but missing": ["missing"],
    "password-protected or unreadable attachment": ["password", "encrypted", "unreadable"],
    "a logo is not the attachment": ["logo"],
    "items identified only by something not in the email": ["last order", "not in the email"],
    "a photo of one item, quantity in the body": ["photo", "nameplate", "picture"],
    # v2
    "a vendor quote answers something we asked for": ["we asked", "our request", "our rfq"],
    "sales mail nobody asked for is not a vendor quote": ["unsolicited"],
    "raw is one line of the source, never several joined": ["never join", "do not join", "not several lines"],
    "on a tag or plate, raw is the line that identifies the item": ["identifies the item", "identifying line"],
    # v3 (found by the probe inbox, not by dev)
    "an override replaces only what it restates; the rest of the default still applies":
        ["rest of the default", "only that attribute", "only the attribute"],
}


@pytest.mark.parametrize("words", PROPERTIES.values(), ids=PROPERTIES.keys())
def test_prompt_covers_each_general_property(words):
    assert any(norm(w) in PROMPT_NORM for w in words), f"prompt mentions none of {words}"


def test_prompt_uses_the_readers_own_section_names():
    """The prompt and the rendered email must speak the same language: when the prompt
    says what to do with quoted history, it uses the title the reader prints."""
    rendered_titles = ("NEW MESSAGE", "QUOTED HISTORY", "FORWARDED CONTENT", "ATTACHMENT")
    for title in rendered_titles:
        assert title in PROMPT, title


# ------------------------------------------------------------------ it does not fit dev

def test_prompt_contains_nothing_from_the_dev_inbox():
    """Don't fit dev: no dev email id, no dev sender, no dev subject, and no line from
    the answer key may appear in the prompt. Examples in the prompt must be invented."""
    assert not re.search(r"\bE\d{3}\b", PROMPT), "prompt names a dev email id"

    leaked = []
    for path in sorted(DEV_EMAILS.glob("*.eml")):
        pk = reader.read_email(path)
        address = pk.sender.split("<")[-1].strip("> ").lower()
        domain = address.split("@")[-1]
        if domain and domain != reader.INTERNAL_DOMAIN and domain in PROMPT.lower():
            leaked.append(f"{path.stem}: sender domain {domain}")
        subject = norm(re.sub(r"^\s*((re|fw|fwd)\s*:\s*)+", "", pk.subject, flags=re.I))
        if len(subject) >= 12 and subject in PROMPT_NORM:
            leaked.append(f"{path.stem}: subject")

    key = score.load_key(ROOT / "data" / "dev" / "answer_key.json")
    for email_id, entry in key.items():
        for line in entry.get("line_items", []):
            for field in ("raw", "description"):
                text = norm(str(line.get(field) or ""))
                if len(text) >= 12 and text in PROMPT_NORM:
                    leaked.append(f"{email_id}: {field} {text!r}")
    assert leaked == []


def dev_texts() -> dict[str, str]:
    """Everything a dev email says: subject, new text, quoted history and attachment
    text - the customers' words only, without the reader's own section titles."""
    out = {}
    # The probe inbox is measurement data too: quoting it in the prompt would fit it.
    for path in sorted([*DEV_EMAILS.glob("*.eml"), *(ROOT / "eval" / "probes" / "emails").glob("*.eml")]):
        pk = reader.read_email(path)
        text = "\n".join([pk.subject, pk.body_new, *(q.text for q in pk.quoted),
                          *(a.text for a in pk.attachments)])
        # An attached email is rendered with the reader's section titles; those are ours.
        out[path.stem] = "\n".join(ln for ln in text.splitlines() if not ln.startswith("=== "))
    return out


def brief_text() -> str:
    """The public brief. Wording that is in the brief itself is not a dev leak."""
    return "\n".join((ROOT / name).read_text(encoding="utf-8")
                     for name in ("ASSESSMENT.md", "data/README.md"))


def shingles(text: str, n: int) -> set[tuple[str, ...]]:
    words = norm(text).split()
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def test_prompt_shares_no_phrase_with_any_dev_email():
    """Stronger than checking answer-key lines: no run of five words from any dev email
    (body, quoted history, attachments) may appear in the prompt, unless the brief itself
    uses it. A rule learned from dev has to be restated as a rule, not quoted."""
    allowed = shingles(brief_text(), 5)
    prompt = shingles(PROMPT, 5) - allowed
    leaked = {eid: sorted(" ".join(s) for s in prompt & shingles(text, 5))
              for eid, text in dev_texts().items()}
    assert {eid: hits for eid, hits in leaked.items() if hits} == {}


def test_prompt_names_no_person_company_or_part_number_from_dev():
    """Names and identifiers are the purest dev strings: sender names, company names,
    and anything that looks like a model, RFQ or PO number (letters and digits mixed)."""
    brief = norm(brief_text())
    generic = {"sales", "purchasing", "supply", "pipe", "valve", "flange", "industrial", "team",
               "desk", "warehouse", "company", "service", "services", "group", "steel", "mill"}
    names, identifiers = set(), set()
    for path in sorted([*DEV_EMAILS.glob("*.eml"), *(ROOT / "eval" / "probes" / "emails").glob("*.eml")]):
        pk = reader.read_email(path)
        display, _, address = pk.sender.rpartition("<")
        domain = address.strip("> ").split("@")[-1]
        if domain == reader.INTERNAL_DOMAIN:
            continue
        for word in norm(display).split() + norm(domain.split(".")[0]).split():
            if len(word) >= 4 and word not in generic:
                names.add(word)
        for token in re.findall(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+|[A-Za-z]+\d+[A-Za-z0-9]*", reader.render(pk)):
            if len(token) >= 6 and re.search(r"[A-Za-z]", token) and re.search(r"\d{2,}", token):
                identifiers.add(token.lower())
    prompt_words = set(PROMPT_NORM.split())
    leaked_names = sorted(n for n in names if n in prompt_words and n not in brief.split())
    leaked_ids = sorted(i for i in identifiers if i in PROMPT.lower() and norm(i) not in brief)
    assert (leaked_names, leaked_ids) == ([], [])


def test_examples_in_the_prompt_are_not_dev_lines():
    """Every quoted example in the prompt must be absent from every dev email."""
    examples = [e for e in re.findall(r'"([^"\n]{12,})"|\'([^\'\n]{12,})\'', PROMPT)]
    texts = {eid: norm(text) for eid, text in dev_texts().items()}
    brief = norm(brief_text())
    leaked = []
    for pair in examples:
        example = norm(pair[0] or pair[1])
        if len(example.split()) < 3 or example in brief:
            continue
        leaked += [f"{eid}: {example!r}" for eid, text in texts.items() if example in text]
    assert leaked == []


# ------------------------------------------------------------------ think first, then answer

def test_schema_asks_for_the_reading_before_the_answer():
    """A non-reasoning model answers in the order the schema lists fields. `analysis`
    comes first so the classification and lines are written after the thinking."""
    props = list(model.OUTPUT_SCHEMA["properties"])
    assert props[0] == "analysis"
    assert model.OUTPUT_SCHEMA["required"][0] == "analysis"
    assert model.OUTPUT_SCHEMA["properties"]["analysis"]["type"] == "string"
    assert "analysis" in PROMPT


def test_a_reply_without_the_analysis_is_malformed(tmp_path):
    no_analysis = json.loads(answer())
    del no_analysis["analysis"]
    client = FakeClient(json.dumps(no_analysis), answer())
    engine, _ = make_engine(tmp_path, client)

    engine.extract("E1", "EMAIL TEXT", [])

    assert len(client.calls) == 2          # sent back once for repair


def test_the_analysis_is_kept_in_the_cache_but_never_reaches_parsed_json(tmp_path, monkeypatch, check_format):
    make_eml(tmp_path / "inbox" / "E1.eml")
    reply = json.loads(answer())
    reply["analysis"] = "ZEBRA-MARKER the new message asks for elbows"
    monkeypatch.setattr(model, "make_client", lambda: FakeClient(json.dumps(reply)))
    out = tmp_path / "parsed.json"

    cli.main(["parse", "--emails", str(tmp_path / "inbox"), "--out", str(out),
              "--cache", str(tmp_path / "cache")])

    assert "ZEBRA-MARKER" not in out.read_text(encoding="utf-8")
    assert check_format.check(json.loads(out.read_text(encoding="utf-8"))) == []
    cached = "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "cache").glob("*.json"))
    assert "ZEBRA-MARKER" in cached        # there for a human asking "why did it say that?"


# ------------------------------------------------------------------ an edited prompt busts the cache

def test_editing_the_prompt_text_busts_the_cache_even_if_the_version_is_not_bumped(tmp_path, monkeypatch):
    """Forgetting to bump PROMPT_VERSION must not replay answers to the old prompt."""
    client = FakeClient()
    make_engine(tmp_path, client)[0].extract("E1", "EMAIL TEXT", [])
    assert len(client.calls) == 1

    monkeypatch.setattr(model, "SYSTEM_PROMPT", model.SYSTEM_PROMPT + "\nOne more rule.")
    make_engine(tmp_path, client)[0].extract("E1", "EMAIL TEXT", [])
    assert len(client.calls) == 2
    assert "One more rule." in json.dumps(client.calls[1])     # and the new text is what was sent

    monkeypatch.undo()
    make_engine(tmp_path, client)[0].extract("E1", "EMAIL TEXT", [])
    assert len(client.calls) == 2                               # the original is still cached
