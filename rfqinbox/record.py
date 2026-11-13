"""The per-email output record defined in data/README.md."""

from __future__ import annotations

CLASSES = (
    "rfq",
    "rfq_revision",
    "purchase_order",
    "vendor_quote",
    "status_inquiry",
    "auto_reply",
    "other",
)
ACTION_CLASSES = ("rfq", "rfq_revision", "purchase_order")
UOMS = ("EA", "FT", "M", "IN", "BX", "PK", "PR", "DZ", "RL", "LB", "SET", "GAL", "BAG", "CS")


def make_record(
    classification: str,
    line_items: list[dict] | None = None,
    *,
    revises: str | None = None,
    duplicate_of: str | None = None,
    needs_review: bool = False,
    review_reason: str | None = None,
) -> dict:
    if classification not in CLASSES:
        raise ValueError(f"unknown classification {classification!r}")
    return {
        "classification": classification,
        "revises": revises,
        "duplicate_of": duplicate_of,
        "needs_review": needs_review,
        "review_reason": review_reason if needs_review else None,
        "line_items": list(line_items or []),
    }


def review_record(reason: str, line_items: list[dict] | None = None) -> dict:
    """The safe default when we cannot decide: a human looks at it.

    The most expensive failure is a silent loss (a request that comes back with
    no lines and no flag), so "unknown" is always reported as a request that
    needs review — never as "other" with nothing to do.
    """
    return make_record("rfq", line_items, needs_review=True, review_reason=reason)
