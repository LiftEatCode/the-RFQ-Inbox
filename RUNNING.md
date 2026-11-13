# Running

> Reader stage. Model and cost sections are filled in as those parts land.

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

## API key

`parse` reads `OPENAI_API_KEY` from the environment. Never put the key in a file
in this repository; `.env` files are git-ignored as a backstop.
