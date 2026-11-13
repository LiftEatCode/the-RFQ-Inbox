"""Turns one .eml file into one output record.

    reader (deterministic) -> model (decides class and lines) -> code checks (rfqinbox.checks)

If the model step fails for any reason the record is the safe default: a request
flagged for review, with the reason. Cross-email links (revises, duplicate_of)
are set afterwards by the CLI, once every email has a record.
"""

from __future__ import annotations

from pathlib import Path

from rfqinbox import checks, model, reader
from rfqinbox.record import ACTION_CLASSES, make_record, review_record


def default_engine() -> model.Engine:
    return model.Engine(model.make_client(), model.Cache(model.default_cache_dir()), model.Ledger())


def process_email(path: Path, engine: model.Engine | None = None) -> dict:
    engine = engine or default_engine()
    engine.ledger.touch(path.stem)
    raw = path.read_bytes()
    if not raw.strip():
        return review_record("email file is empty")
    packet = reader.read_email(path)
    try:
        answer = engine.extract(path.stem, reader.render(packet), reader.images_for_model(packet),
                                image_keys=reader.image_keys(packet))
    except model.ModelError as exc:
        return review_record(f"model step failed: {exc} ({_summary(packet)})")
    record = to_record(answer)
    try:
        return checks.check_record(packet, record)
    except Exception as exc:  # noqa: BLE001 — a bug in a check must not cost the model's answer
        if record["classification"] in ACTION_CLASSES:
            own = f"{record['review_reason']}; " if record["needs_review"] else ""
            record["needs_review"] = True
            record["review_reason"] = f"{own}code checks failed ({type(exc).__name__}: {exc})"
        return record


def to_record(answer: dict) -> dict:
    """The model's answer, held to the output contract's rules."""
    classification = answer["classification"]
    if classification not in ACTION_CLASSES:
        return make_record(classification)   # no lines and no review flag for these kinds
    lines = answer["line_items"]
    needs_review = bool(answer["needs_review"])
    reason = (answer["review_reason"] or "").strip()
    if not lines and not needs_review:
        # "A request, nothing found, nobody needs to look" is the silent loss. Never let it out.
        needs_review, reason = True, "the model classified this as a request but found no line items"
    if needs_review and not reason:
        reason = "the model flagged this email for review without giving a reason"
    return make_record(classification, lines, needs_review=needs_review, review_reason=reason)


def _summary(pk: reader.Packet) -> str:
    if not pk.attachments:
        return "body only"
    return "attachments: " + ", ".join(f"{a.filename} [{a.status}]" for a in pk.attachments)
