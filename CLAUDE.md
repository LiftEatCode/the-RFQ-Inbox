# CLAUDE.md — RFQ Inbox take-home

Instructions for coding agents working in this repo. Read `ASSESSMENT.md` (the brief)
and `data/README.md` (the output contract and grading) before changing behaviour.

## The task in one paragraph

Build `python -m rfqinbox parse --emails <dir> --out parsed.json`. For every `.eml`:
a classification (7 kinds), self-contained line items (raw, description, qty, uom,
source), revises / duplicate_of links, and needs_review. Graders run it on a held-out
inbox of ~40 emails (same kinds of surprises, different strings) with an OpenAI key,
then again with the key removed. It must replay from a committed cache, make no new
calls on a second run, never crash on a bad email, and report calls/tokens/$ per email.

## Hard rules

- **The API key never touches the repo or the session logs.** Read `OPENAI_API_KEY`
  from the environment only. Never print it, never write it, never `cat .env`.
- **Default model path is OpenAI.** Another provider may be an opt-in switch only.
- **No outbound calls except the model provider.** No email, no webhooks.
- **Runs on Windows natively.** pathlib, explicit UTF-8, no shell-outs, wheels-only deps.
- **Don't fit dev.** Unit tests use synthetic fixtures (`tests/fixtures.py`,
  `tests/conftest.py:make_eml`) that reproduce a *property* (hidden sheet, scan, logo),
  never assertions about specific dev emails. Dev is only for `rfqinbox score`.
- **Safe default = flag for review.** The most expensive grading failure is a silent
  loss (action email with no lines and no flag). Unknown/failed → `rfq` + needs_review.

## How we work

- TDD. For each chunk: write failing tests first (commit "… tests (failing)"),
  then the code (commit "Add …"). Run `python -m pytest` before every commit.
- After any behaviour change: regenerate `parsed.json`, run
  `python -m rfqinbox score parsed.json --quiet`, add a row to `eval/history.md`.
- Commit messages: one short human title + at most one sentence. No bullet walls.
- The human commits and pushes; the agent proposes the commands and messages.
- Check `git status` before proposing a commit (no `__pycache__`, no stray files).

## Layout

```
rfqinbox/cli.py       parse | score | inspect subcommands; per-email try/except; atomic write
rfqinbox/pipeline.py  process_email(path, engine) -> record: reader -> model -> contract rules
rfqinbox/model.py     OpenAIClient (urllib), Cache, Ledger, Engine.extract (validate, 1 repair retry)
rfqinbox/reader.py    .eml -> Packet (body_new, quoted[], attachments[]) + render() for the model
rfqinbox/record.py    output record helpers; review_record() = the safe default
rfqinbox/score.py     local scorer implementing data/README.md "What we grade"
eval/history.md       dev score after each behaviour change
tests/                pytest; no key needed
```

## Status

Done (each with tests):
1. Skeleton: CLI contract, safe-default stub, per-email isolation, atomic write.
2. Scorer: `python -m rfqinbox score parsed.json [--gate]`. Baseline 0 silent losses, 0/210 lines.
3. Reader: quoted/forward split, xlsx (sheet names, merged, HIDDEN sheets/rows, ~~strike~~),
   docx (headings in order with tables), PDF (text, form fields, scans -> page images,
   encrypted, capped at 40 text / 6 scan pages), images (logo detection, downscale),
   CSV, HTML tables (colspan), attached .eml recursively. `python -m rfqinbox inspect <eml>`.
4. Model layer (`rfqinbox/model.py`, `tests/test_model.py`), as specified below. Prompt is a
   placeholder (`PROMPT_VERSION = "v0"`); nothing has been recorded yet.

Model layer as built (tests use a fake client / fake urlopen; no key needed):
   - OpenAI client over stdlib `urllib` (no SDK dependency), Chat Completions with
     `response_format: json_schema` (strict) and images as base64 data URLs
     (`detail: low` for logos, `high` otherwise; see `reader.images_for_model`).
   - Cache: `cache/<sha256>.json`, key = hash(model, prompt version, schema, rendered
     packet, sha256 of each image's *original attachment bytes* — not the re-encoded image,
     which can differ between Pillow/pdfium builds). Committed to git. Hit → no call. Writes
     are atomic. With no key, an answer recorded with any model is replayed.
     **Editing SYSTEM_PROMPT without bumping PROMPT_VERSION replays stale answers.**
   - Cost ledger: calls, input/output tokens, $ per email (price table in code), written
     to `cost_report.json` (next to `--out`) and summarised on stderr. `calls`/`cost_usd` =
     what the answer cost when made or recorded; `new_*` = spent in this run.
   - Failures: no key, timeout, 429/5xx (retry with backoff, then give up), malformed JSON
     (schema-validate; one repair retry) → record flagged needs_review with the reason,
     run continues. Never crash.
   - Tests: second run makes zero calls; prompt-version change busts the cache; each
     failure mode degrades to a flagged record; cost totals add up.

Next:
5. Prompt v1 + recorded cache for dev (the human runs `parse` once with the key).
6. Code-side checks: duplicate detection (later Date = duplicate), revises via
   In-Reply-To/References/subject, every `raw` must appear in the source text, sizes are
   never quantities, needs_review rules (attachment mentioned but missing/unreadable/
   encrypted; items referenced but not present), model-down fallback.
7. Fixes driven by `rfqinbox score`, each with a test of the general property.
8. Docs: RUNNING.md (setup, model, cost), DECISIONS.md (<= 2 pages, 4 required
   sections), AI_USAGE.md (<= 1 page), ai-sessions/ logs.
Optional if time: catalog matcher (MATCHER.md), small web app.

## What the dev data taught us (the general properties, not answers)

- Context lives off the line: section headings scope only their block (and a later
  heading ends it); "UNLESS NOTED" headers with per-row overrides; PDF form fields
  (Material/Rating); spreadsheet sheet names; Word headings above tables; HTML colspan
  headers; ditto marks (",,") in handwriting; "same size" referring to the previous line.
- Not requests: hidden old-revision sheets, crossed-out lines, totals rows, prices,
  quoted history, signatures, promo price lists, a supplier quoting *us*, a bounce that
  carries *our own* outgoing RFQ.
- Exceptions to "ignore quoted history": a PO reply "go ahead with items 1, 2 and 4"
  takes its lines from our quoted quote; a revision must rebuild the complete order from
  the quoted original plus the changes ("line 2 is now 14", "drop line 6", "add …").
- Internal sender (`@ridgeline-supply.example`) forwarding a customer → classify as the
  customer's email; read the rep's note too.
- needs_review: body says "attached" but only a logo came; password-protected PDF;
  items identified only by something not in the email.
- A nameplate photo + "quote 3 of these" → one line, qty from the body.
- Same RFQ sent twice → later Date is the duplicate (classification kept, lines []).
