"""Shared test helpers.

Unit tests build their own small synthetic emails. The dev inbox is used only
for shape checks here and for scoring in eval/, never for asserting specific
answers: asserting dev strings would fit the dev set, not the problem.
"""

from __future__ import annotations

import importlib.util
import sys
from email.message import EmailMessage
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEV_EMAILS = ROOT / "data" / "dev" / "emails"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_check_format():
    spec = importlib.util.spec_from_file_location("check_format", ROOT / "data" / "check_format.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def check_format():
    """The organisers' own shape validator, imported unchanged."""
    return _load_check_format()


@pytest.fixture(autouse=True)
def _no_key_no_shared_cache(monkeypatch, tmp_path):
    """No test may spend money or touch the committed cache: the key is removed from
    the environment and the default cache folder points into the test's temp dir."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("RFQINBOX_CACHE_DIR", str(tmp_path / "default-cache"))


def make_eml(
    path: Path,
    body: str = "Please quote 10 ea 2\" 90 elbow.",
    *,
    sender: str = "Pat Buyer <pat@customer.example>",
    subject: str = "Quote request",
    date: str = "Mon, 05 Oct 2026 09:00:00 -0500",
    attachments: list[tuple[str, str, bytes]] | None = None,
) -> Path:
    """Write a minimal RFC-822 email. attachments: (filename, mime type, bytes)."""
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = "rfq@ridgeline-supply.example"
    msg["Subject"] = subject
    msg["Date"] = date
    msg["Message-ID"] = f"<{path.stem}@test.example>"
    msg.set_content(body)
    for name, mime, data in attachments or []:
        maintype, subtype = mime.split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(msg.as_bytes())
    return path
