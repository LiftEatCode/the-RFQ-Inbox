# Running

> Skeleton stage. Setup, model and cost sections are filled in as those parts land.

Requires Python 3.11+. Works natively on Windows, macOS and Linux.

```
python -m rfqinbox parse --emails data/dev/emails --out parsed.json
python data/check_format.py parsed.json --emails data/dev/emails
```

Tests (no API key needed):

```
python -m pip install pytest
python -m pytest
```

## API key

`parse` reads `OPENAI_API_KEY` from the environment. Never put the key in a file
in this repository; `.env` files are git-ignored as a backstop.
