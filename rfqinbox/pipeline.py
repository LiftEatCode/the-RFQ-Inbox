"""Turns one .eml file into one output record.

Skeleton stage: reads the message and returns the safe default (flagged for
review). Extraction is added in later commits behind this same function.
"""

from __future__ import annotations

from email import policy
from email.parser import BytesParser
from pathlib import Path

from rfqinbox.record import review_record


def process_email(path: Path) -> dict:
    raw = path.read_bytes()
    if not raw.strip():
        return review_record("email file is empty")
    BytesParser(policy=policy.default).parsebytes(raw)
    return review_record("not processed: extraction not implemented yet")
