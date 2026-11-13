# Running

> Model layer stage: the client, cache and cost report work; the prompt is a placeholder and
> no answers are recorded yet, so every email currently comes back flagged for review.

Requires Python 3.11+. Works natively on Windows, macOS and Linux.

## Setup (one step)

```
python -m pip install -r requirements.txt
```

## Run

```
python -m rfqinbox parse --emails data/dev/emails --out parsed.json
python data/check_format.py parsed.json --emails data/dev/emails
```

See what the model will be shown for one email:

```
python -m rfqinbox inspect data/dev/emails/E005.eml
```

Score against the dev answer key:

```
python -m rfqinbox score parsed.json
```

## Tests (no API key needed)

```
python -m pip install -r requirements-dev.txt
python -m pytest
```

## Model, cache and cost

- Model: OpenAI `gpt-4.1` (Chat Completions, strict JSON schema, images inline). Override with
  the `RFQINBOX_MODEL` environment variable.
- Every valid answer is saved to `cache/<sha256>.json` (committed). A second run makes no calls;
  a run with no key replays the cache and flags any email it has no answer for. `--cache <dir>`
  or `RFQINBOX_CACHE_DIR` moves the cache.
- `parse` writes `cost_report.json` next to `--out` (calls, tokens and dollars per email) and
  prints the totals on stderr.

## API key

`parse` reads `OPENAI_API_KEY` from the environment. Never put the key in a file
in this repository; `.env` files are git-ignored as a backstop.
