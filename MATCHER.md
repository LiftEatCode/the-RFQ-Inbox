# Matcher (design, not built)

Each extracted line becomes one catalog part, a decision that Ridgeline does not stock it, or
a question for the customer. This is how I would build it. `parse` does not emit `sku` /
`match` today.

**Principle:** a wrong part is a wrong quote, so the matcher never picks the nearest part. It
compares attributes exactly, and when they do not agree it says which one and stops.

## What I normalise

`catalog.csv` (937 parts) is already structured: `product` (36 values), `size`, `spec`
(22 schedules and pressure classes), `material` (30), `ends` (12), `extra`. So the work is
turning a line's `description` into those same six fields, in the catalog's vocabulary:

- **Product:** synonyms and ERP abbreviations to one name (`ELL`, `elbow`, `90` -> `90 elbow`;
  `WN`, `weldneck` -> `weld neck flange`; `CONC RED` -> `concentric reducer`).
- **Size:** fractions, decimals, inch marks and typographic quotes to one form (`1.5`,
  `1 1/2"` -> `1-1/2`); reducing sizes ordered large x small; bolting as diameter x length.
- **Spec:** `S40`, `SCH40`, `STD` -> `SCH 40`; `CL150`, `150 LB`, `150#` -> `150#`. `STD`
  and `XS` map to a schedule only in the sizes where they are the same wall.
- **Material:** grade to the catalog's form (`316L` on a butt-weld fitting -> `A403 WP316L`,
  on a flange -> `A182 F316L`). A family word (`CS`, `stainless`) is kept as a family, which
  can match several grades.
- **Ends and extra:** `NPT`/`FNPT`/`screwed` -> `THD`; `bevelled` -> `BE`/`BW`; facing
  (`RF`/`FF`/`RTJ`); port, trim, radius.

Each field is `stated`, `stated as a family`, or `not stated`. That distinction drives
everything below. The extraction step already carries headings and defaults into the
description, so the matcher reads the description only and never goes back to the email.

## Which attributes must agree, and how candidates are found

Candidates: the catalog rows with the same `product` and `size`. With 937 rows this is a
dictionary lookup; no embeddings, no fuzzy text search (both rank "one attribute off" as a
near-perfect hit, which is the failure the brief warns about).

Then every attribute the customer **stated** must equal the row's. A family must contain the
row's grade. An attribute the customer did not state rules nothing out.

| candidates left | answer |
|---|---|
| exactly one | `matched`, `sku` set |
| none, because product or size is not stocked | `not_in_catalog` |
| none, because a stated attribute disagrees | `not_in_catalog`; the reason names the near miss |
| several, differing on an attribute the customer did not state | `ambiguous`, `candidates` listed |
| the description could not be parsed into a product and a size | `ambiguous`, no candidates |

`match_reason` is one line built by code from the comparison, so a rep can check it:
`2" 150# RF weld neck A105: one part fits`, `stocked in SCH 40 and SCH 80 only, asked SCH 160`,
`material not given: A105 or A182 F316L`.

**Not in catalog** means the customer was specific and we do not have it. **Ask the customer**
means the customer was not specific and the choice changes the part. Two cases I would not
collapse: a missing attribute where all remaining candidates agree is still `matched` (there is
nothing to ask); and a line that is really two parts (a stud "with two nuts") is
`not_in_catalog` as a single line unless the catalog sells the assembly.

In the catalog 224 of the 564 product + size + spec groups hold more than one part, so
material and ends decide the answer often, and a matcher that stops at size and class would be
wrong or ambiguous on about 40% of groups.

## Where a model helps, and what it must never decide

A model is good at one step: reading a messy description into the six fields (trade slang,
odd word order, a manufacturer's figure number). I would start with code tables and add the
model only for lines the tables cannot parse, as extra fields in the existing per-email call,
so cost and cache behaviour do not change.

The model never: returns a SKU; sees the catalog and chooses from it; decides that a
different schedule, class or material is "equivalent"; or fills in an attribute the customer
did not state. Code does the lookup, so a SKU that is not in `catalog.csv` cannot come out,
and the same line always gets the same answer.

## How I would measure it

On lines paired with the key (`sku` / `match` / `candidates` in `dev/answer_key.json`),
added to `rfqinbox score`:

1. **Wrong-SKU rate** (we said `matched` and the SKU is not the key's). The headline number;
   the target is zero, and I would give up match rate to get it.
2. A 3 x 3 confusion table of `matched` / `not_in_catalog` / `ambiguous`, with precision and
   recall for `not_in_catalog`.
3. Match accuracy overall, and separately on lines the extraction step got exactly right, so
   matcher errors are not confused with extraction errors.

Dev has 194 `matched`, 16 `not_in_catalog` and **no** `ambiguous` line, so dev cannot test the
"ask the customer" rule at all. I would write invented probe lines for it, the way
`eval/probes/` was built: for each catalog group with several parts, a request that leaves out
the attribute they differ on, and a request that states a value none of them has.

## What I expect to go wrong

- Abbreviation tables fitted to dev wording. Same guard as the prompt: test on invented lines.
- Families and equivalents (`CS` pipe: A53B or A106B?). I would answer `ambiguous`; a rep
  would often just pick, so this will look too cautious until someone writes the house rules.
- An extraction error (wrong size digit on a scan) becomes a confident wrong SKU. The matcher
  cannot see that; reading scans twice is the fix, upstream.
