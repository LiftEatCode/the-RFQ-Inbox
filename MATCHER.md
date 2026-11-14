# Matcher (designed and built)

Each extracted line becomes one catalog part, a decision that Ridgeline does not stock it, or
a question for the customer. `parse` adds `sku`, `match`, `match_reason` and `candidates` to
every line (`rfqinbox/matcher.py`, no model, no cost; `--no-match` switches it off).

**Principle:** a wrong part is a wrong quote, so the matcher never picks the nearest part. It
compares attributes exactly, and when they do not agree it says which one and stops.

## What I normalise

`catalog.csv` is already structured (`product`, `size`, `spec`, `material`, `ends`, `extra`),
so a line's `description` is read into those same fields, and the catalog's own fields go
through the same reader, so both sides are compared in one vocabulary.

- **Product:** synonyms and ERP abbreviations (`ELL`, `WN`, `CPLG`, `all-thread`). A word
  for something we do not stock (a gauge, a hose, an olet, a ring gasket) is recognised as that.
- **Size:** `1 1/2"`, `1.5`, `1½` are one size; reducers are large x small; bolting is
  diameter x length (`3/4" stud, 4-1/2" long`; the 13 in `1/2"-13` is the thread).
- **Spec:** two kinds, schedule (`S/40`, `STD`, stainless `SCH 10` = `10S`) and pressure
  rating (`CL150`, `150 lb`, `600 WOG`). A flange's bore schedule is not a mismatch; a class
  150 fitting is not the schedule fitting of the same size.
- **Material:** tags, not strings. `316L` is also `316` and stainless; `A105` is also carbon
  steel; so "carbon steel" matches the stocked grade and `316L` does not match plain `316 SS`.
  Materials and joints the catalog has none of (ductile, PVC, mechanical joint, grooved) are
  read so that stating one rules every part out.
- **Ends and extra:** `NPT`/`screwed`, `bevelled`, facing, port, radius, trim.

## Which attributes must agree, and how candidates are found

Candidates are the rows with the same product and size (a dictionary lookup over 937 rows; no
embeddings or fuzzy search, which rank "one attribute off" as a near-perfect hit). Then every
attribute the customer **stated** must agree. An attribute they did not state rules nothing out.

| candidates left | answer |
|---|---|
| exactly one, and at least one attribute beyond product and size was confirmed | `matched` |
| none: product or size not stocked, or a stated attribute disagrees | `not_in_catalog`; the reason names it |
| several, differing on something the customer did not state | `ambiguous`, `candidates` listed |
| one, but only product and size were read | `ambiguous`, that one part as the candidate |

**Not in catalog** = the customer was specific and we do not have it. **Ask the customer** =
they left out something that changes the part. If every remaining candidate agrees on the
missing attribute there is nothing to ask. A part that is exactly what was written beats one
that is that and more ("316 SS" is the `316 SS` part; no locking handle asked, none given).

`match_reason` is built by code from the comparison: `FLG WN 2" 300# A105 RF: one part fits`;
`weld neck flange 2: asked 600#, stocked 150#, 300#`; `90 elbow 1: ends not given (SW or THD)`.

## Where a model helps, and what it must never decide

Nowhere, in what is built: the extraction step already writes a self-contained description,
and code reads it. If the tables stop coping I would let the model fill the six fields in the
existing call. It would never return a SKU, see the catalog, call two schedules or grades
"equivalent", or fill in an attribute the customer did not state. Code does the lookup, so a
SKU that is not in `catalog.csv` cannot come out.

## How I measured it

`rfqinbox score` reports, on paired lines: **wrong SKUs** first (we named a part and it is not
the key's), match accuracy, a 3 x 3 confusion table, and `not_in_catalog` precision / recall.

| | wrong sku | accuracy | not_in_catalog P / R |
|---|---|---|---|
| dev, first run | 0 | 87.6% (184/210) | 47% / 100% |
| dev, after five general fixes | 0 | 100% (210/210) | 100% / 100% |

The 26 first-run misses were all too cautious, never a wrong part: a flange's "STD bore" read
as a valve port, `SO` / `BL` flange codes, thread pitch read as a size, a length written as
"long", and a close nipple. The first-run number is the honest estimate for a new inbox.

Dev has no `ambiguous` line and my probe key has no catalog answers, so I checked the probe
inbox (39 lines) by hand against the catalog. It found the one wrong SKU: a waterworks gate
valve with mechanical-joint ends matched the only 6" gate valve we stock, because nothing it
said was understood and nothing contradicted. That produced the "at least one confirmed
attribute" rule and the unstocked-joint vocabulary. After it: 13 matched (all correct),
22 not in catalog, 4 ambiguous (pipe with no end finish given).

**Held-out prediction:** wrong SKU 0–3, accuracy 85–93%, errors mostly `not_in_catalog` or
`ambiguous` where the key says `matched`.

## Known weak points

- An attribute the customer states in words the tables do not know is ignored, not flagged.
  The confirmation rule only catches the case where nothing at all was understood.
- Families (`CS` pipe: A53B or A106B?) come back `ambiguous`; a rep would often just pick.
- An extraction error (a wrong size digit on a scan) becomes a confident wrong SKU.
- Tests use an invented catalog; one test checks that every part in the shipped catalog,
  written from its own fields, comes back as itself.
