# Decisions

Time spent: about 3 hours hands-on on 13 November for the required work (commits run
09:59–11:34 and 15:38–16:48), plus reading the brief; then about an hour on 14 November for
the optional matcher (03:40–05:00). One model call per email; everything checkable without
judgment is code.

## Something in the data that surprised me

The biggest source of wrong output was an email the model read perfectly. A customer resent
an RFQ a day later with different wording and the byte-identical PDF. The model extracted all 44 lines
correctly, and every one of them was wrong, because the README says the later copy has no
lines. 44 of the first run's 45 hallucinated lines were that one email. Whether an answer is
right depended on a different email, so no prompt could fix it. That moved duplicates and
revision links out of the model entirely (`checks.link_records`).

## Something in the brief I disagree with, and what I did

`needs_review` is allowed only on requests. That leaves no honest answer for "I could not read
this and do not know what it is": calling it `other` risks a silent loss, the most expensive
failure. So anything unreadable or failed becomes `rfq` + `needs_review`. I accept the cost: if
the model is down, a vendor quote is reported as a request needing review (a phantom) rather
than dropped. I would rather the contract had an `unknown` class or allowed the flag everywhere.

Second, smaller: `raw` for a picture is "your reading of it", but lines are paired on `raw`
tokens. A nameplate has no single line, and the dev key uses only the model-number line. I
followed that (a code rule keeps the identifying line), but it is a guess from one example.

## Predicted held-out numbers, and the two kinds of email I expect to get wrong

Dev is 210/210 lines and my own 17-email probe set is 39/39, but dev shaped the rules and I
wrote the probes, so I discount both.

| | prediction (~40 emails) |
|---|---|
| silent losses | 0–1 (a request classified as a non-request is both lost and silent) |
| hallucinated lines | 0–10; one missed duplicate of a long RFQ alone could add 40+ |
| lost / phantom requests | 0–1 / 0–1 |
| classification | 93–97% |
| line recall / precision | 94–98% / 93–98% |
| qty / uom / source | 96–99% / 97–100% / 97–100% |
| context carried | 90–96% |
| revises / duplicate links | 70–100% (few emails, so coarse) |
| needs_review precision / recall | 75–100% / 80–100% |

1. **Dense phone scans and photos.** One scanned form gave 12 wrong quantities; sending pages
   in full-resolution bands brought that to 0, 0 and 1 over the next three runs. So
   small digits are still occasionally misread, and code cannot check a number that exists
   only in a picture.
2. **Threads and resends that do not look like dev's.** Duplicates need the same sender and
   either identical lines or provably identical content; a resend from a colleague's address,
   or a re-typed list, stays a normal request and all its lines count as hallucinated. A
   revision whose original is not quoted is rebuilt from whatever is in the email.

## How this runs for real

- **3,000 emails a day by webhook.** Each email is independent until linking, about 5 s and
  1.2 cents (roughly $36/day). *Built:* per-email isolation, atomic writes, a content-keyed
  cache, cost per email. *Not built:* the queue and workers; linking duplicates and revisions
  against a rolling window of earlier mail instead of one folder.
- **Provider down for two hours.** *Built:* timeouts, three retries with backoff on 429/5xx
  and network errors, then the email is flagged with the reason; failures are never cached,
  so the next run retries only those. *Not built:* a retry queue. In production I would park
  the email and alert, not emit a flagged record once the retries run out.
- **A 300-page PDF.** *Built:* the reader stops at 40 text pages, 6 scanned pages and 60,000
  characters, says so in the text the model sees, and code flags the email for review with
  the lines it did read. *Not built:* splitting a long document across several calls.
- **The same email delivered twice.** *Built:* the second copy costs nothing (same cache key)
  and is marked `duplicate_of` the first. *Not built:* a lock. Two runs started at once both
  pay; I did this by accident and it cost $0.16.

## Where the model decides and where code decides

The model decides what kind of email it is, which text is a request, and what applies to each
line (headings, defaults and overrides, form fields, the rep's note on a forward). It writes
an `analysis` field first, kept in the cache and never in `parsed.json`.

Code decides everything that needs no judgment: what is quoted history, hidden or struck
through (the reader marks it before the model sees it); the output schema (one repair retry);
that every line's words appear in the email, else it is dropped and the email flagged; that
lines found only in hidden or struck content are dropped; `source` names; vague amounts and
sizes are not quantities; missing, unreadable, encrypted or truncated attachments are
flagged; duplicates and `revises`; and that a request with no lines is never left unflagged.

## How I measured

`rfqinbox score` implements the README's grading as I read it (the pairing threshold is my
guess); `eval/history.md` has a row per behaviour change. Dev alone could not tell me whether
I had fitted it, so I wrote `eval/probes/`: 17 invented emails. Their first run found two
real faults dev never showed (a partial override dropping the rest of a default; a nameplate
`raw`). Tests fail if the prompt contains any five-word run, name or part number from a dev
or probe email. That guard caught three dev phrases I had used as examples in prompt v1.

## Rejected, broken, next

- **Rejected:** the OpenAI SDK (one POST does not need it); a rule-based classifier for when
  the model is down (a wrong confident answer is worse than a flag); fuzzy duplicate
  thresholds (a real one-line change would vanish); flagging a doubtful quantity for review
  (the README keeps that flag for emails we cannot read). *Not tried:* separate classify and
  extract calls, a second model, local OCR. One call per email was enough on dev.
- **Known broken or unverified:** not run on Windows; replay with no key depends on the
  reader producing the same text with the graders' library versions (unpinned); the tag rule
  relies on a list of field names; the price table is not checked against the live price list.
- **Next:** read scans twice and flag disagreements; pin versions; a queue. The optional
  matcher is built: see `MATCHER.md`.
