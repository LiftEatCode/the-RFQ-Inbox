"""Turns one .eml file into one output record.

Reader stage: every email is read into a Packet (rfqinbox.reader). There is no
model step yet, so the record is still the safe default (flagged for review),
but now with the reason a human would need.
"""

from __future__ import annotations

from pathlib import Path

from rfqinbox import reader
from rfqinbox.record import review_record


def process_email(path: Path) -> dict:
    raw = path.read_bytes()
    if not raw.strip():
        return review_record("email file is empty")
    packet = reader.read_email(path)
    return review_record(f"not processed: no model step yet ({_summary(packet)})")


def _summary(pk: reader.Packet) -> str:
    if not pk.attachments:
        return "body only"
    return "attachments: " + ", ".join(f"{a.filename} [{a.status}]" for a in pk.attachments)
