# Running

Requires **Python 3.11+**. No Docker, no shell-outs, no system packages: every dependency
ships prebuilt wheels for Windows, macOS and Linux. Developed on Linux; written for native
Windows (pathlib, explicit UTF-8, LF output) but **not yet run on Windows** — see DECISIONS.md.

## Setup (one step)

```
python -m pip install -r requirements.txt
```

## Run

```
python -m rfqinbox parse --emails <dir> --out parsed.json
```

- Reads every `.eml` in `<dir>`, writes `parsed.json`, and writes `cost_report.json` next to it.
- Reads `OPENAI_API_KEY` from the environment. For local runs a `.env` file in the current
  folder is also loaded (`OPENAI_API_KEY=...`); a variable already set in the environment wins.
  `.env` is git-ignored.
- Each line also gets the optional catalog answer (`sku`, `match`, `match_reason`,
  `candidates`) from `data/catalog.csv`: code only, no model call. `--catalog <csv>` uses
  another catalog; `--no-match` leaves the fields out. See `MATCHER.md`.
- With **no key** it replays recorded answers from `cache/` and flags any email it has no
  answer for (`rfq` + `needs_review`). It never crashes on a missing key or a failed call.
- A second run on the same inbox makes **no model calls**: answers are cached under a hash of
  everything the model was shown. New answers (for example the held-out inbox) are written to
  `cache/`; `--cache <dir>` or `RFQINBOX_CACHE_DIR` moves it.

Dev, exactly as committed (no key needed):

```
python -m rfqinbox parse --emails data/dev/emails --out parsed.json
python data/check_format.py parsed.json --emails data/dev/emails
python -m rfqinbox score parsed.json
```

## Model and cost

- **Model:** OpenAI `gpt-4.1`, Chat Completions, strict JSON-schema output, images sent inline.
  One call per email (a second only if the reply is malformed). Override with `RFQINBOX_MODEL`.
- **Dev run:** 24 emails, 24 calls, 66,139 input / 19,913 output tokens, **$0.29**
  (about 1.2 cents per email; median 0.9 cents; the dearest are a 44-line PDF and a two-page
  phone scan at about 3.5 cents each). About 2 minutes, sequential.
- **Per email:** `cost_report.json` lists calls, tokens and dollars for every email;
  `calls`/`cost_usd` are what the answer cost when it was made, `new_calls`/`new_cost_usd` are
  what this run spent (zero on a replay). The totals are printed on stderr.
- **Expect** roughly $0.50 and 3–4 minutes for a 40-email inbox.
- Prices are a table in `rfqinbox/model.py` ($2.00 / $8.00 per million input / output tokens).

## Other commands

```
python -m rfqinbox inspect data/dev/emails/E005.eml     # what the model is shown for one email
python -m rfqinbox score parsed.json --gate             # exit 1 on any silent loss; also prints the matcher numbers
```

## Tests (no key, no network)

```
python -m pip install -r requirements-dev.txt
python -m pytest
```

The tests remove `OPENAI_API_KEY` and switch `.env` loading off, so they can never spend money.

## The probe inbox

`eval/probes/` holds 17 invented emails (not dev) with their own key and cache; see
`eval/make_probes.py` and `eval/history.md`.

```
python -m rfqinbox parse --emails eval/probes/emails --out eval/probes/parsed.json --cache eval/probes/cache
python -m rfqinbox score eval/probes/parsed.json --key eval/probes/answer_key.json
```

## Screen recording

https://drive.google.com/file/d/1-T8-vitqAR0bmA1h8A4JjyT9Gd2EM4WX/view?usp=drive_link
