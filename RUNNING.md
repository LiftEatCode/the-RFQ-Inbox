# Running

> The dev inbox is recorded in `cache/`, so `parse` on dev runs with no key. Code-side checks
> (duplicates, revisions, invented lines, quantity rules) run on every email after the model.

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

`parse` reads `OPENAI_API_KEY` from the environment. For local runs it also loads a `.env`
file from the current folder if there is one (`OPENAI_API_KEY=...`); a variable already set
in the environment wins. `.env` is git-ignored: never commit the key.
