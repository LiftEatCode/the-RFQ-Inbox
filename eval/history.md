# Dev score history

One row per commit that changes behaviour. Produced with:

```
python -m rfqinbox parse --emails data/dev/emails --out parsed.json
python -m rfqinbox score parsed.json --quiet
```

The scorer is our reading of data/README.md's grading rules (see the docstring
in `rfqinbox/score.py`); the graders' own numbers may differ in detail.

| commit | change | silent losses | halluc. lines | lost | phantom | class. acc | line R | line P | qty | uom | source | context | links | NR P / R |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| skeleton | stub: every email `rfq` + needs_review | 0 | 0 | 0 | 4 | 70.8% | 0.0% (0/210) | n/a | n/a | n/a | n/a | n/a | 0.0% | 8.3% / 100% |
| reader | emails and attachments read into packets; output still the stub | 0 | 0 | 0 | 4 | 70.8% | 0.0% (0/210) | n/a | n/a | n/a | n/a | n/a | 0.0% | 8.3% / 100% |
| model layer | client, cache, cost ledger wired in; run with no key and an empty cache, so every email takes the model-down path | 0 | 0 | 0 | 4 | 70.8% | 0.0% (0/210) | n/a | n/a | n/a | n/a | n/a | 0.0% | 8.3% / 100% |
| prompt v1 | first recorded run: gpt-4.1, one call per email, $0.26 for 24 emails; no code-side checks yet | 0 | 45 | 0 | 0 | 95.8% | 99.5% (209/210) | 82.3% (209/254) | 93.8% | 100% | 100% | 100% | 0.0% | 100% / 100% |
| code checks | duplicates, revises links, invented/hidden lines, source, vague and size-as-quantity rules, attachment review rules; same cached answers, no new calls | 0 | 1 | 0 | 0 | 95.8% | 99.5% (209/210) | 99.5% (209/210) | 94.3% | 100% | 100% | 100% | 100% | 100% / 100% |
| checks v2 | size-as-quantity nulls without a review flag; duplicates also match when the content is the same but the model read it differently; no change on dev | 0 | 1 | 0 | 0 | 95.8% | 99.5% (209/210) | 99.5% (209/210) | 94.3% | 100% | 100% | 100% | 100% | 100% / 100% |
| page bands | large page images sent as a reduced overview plus full-resolution bands (the provider shrinks images to 768 px on the short side); one email re-read | 0 | 1 | 0 | 0 | 95.8% | 99.5% (209/210) | 99.5% (209/210) | 100% | 100% | 100% | 100% | 100% | 100% / 100% |
| prompt v2 | vendor quote must answer our request (promo now `other`); raw is one source line; dev wording removed from the prompt; full re-run $0.28. The nameplate raw is still joined: rule stated, model did not follow it | 0 | 1 | 0 | 0 | 100% | 99.5% (209/210) | 99.5% (209/210) | 100% | 100% | 100% | 100% | 100% | 100% / 100% |

Reading the baseline: flagging everything already gives zero silent losses —
which is why silent losses alone can't be the target. Every later change has to
keep that at 0 while lifting recall, and remove the 4 phantoms (vendor quote,
status inquiry, bounce, promo) without losing a real request.

## Probe inbox (not dev)

17 invented emails in `eval/probes/` (see `eval/make_probes.py`), written before the system was
run on them. Same scorer, their own cache:

```
python -m rfqinbox parse --emails eval/probes/emails --out eval/probes/parsed.json --cache eval/probes/cache
python -m rfqinbox score eval/probes/parsed.json --key eval/probes/answer_key.json --quiet
```

| commit | change | silent losses | halluc. lines | lost | phantom | class. acc | line R | line P | qty | uom | source | context | links | NR P / R |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| probes | first run, prompt v2, $0.12 for 17 emails | 0 | 1 | 0 | 0 | 100% | 97.4% (38/39) | 97.4% (38/39) | 100% | 100% | 100% | 94.7% | 100% | 100% / 100% |

What the first run found (both are general, neither is a dev string):
- A tag photo's `raw` comes back as every line of the tag joined (also dev's one remaining miss).
- A line that overrides one attribute of a default ("all pipe SCH 80 A106B seamless unless
  noted" ... "3 lengths 3 in SCH 40") lost the rest of the default: the description kept SCH 40
  but dropped A106B seamless.

