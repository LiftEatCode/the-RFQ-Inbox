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

Reading the baseline: flagging everything already gives zero silent losses —
which is why silent losses alone can't be the target. Every later change has to
keep that at 0 while lifting recall, and remove the 4 phantoms (vendor quote,
status inquiry, bounce, promo) without losing a real request.
