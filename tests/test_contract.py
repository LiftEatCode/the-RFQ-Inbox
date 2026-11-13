"""The run contract from data/README.md and the brief's required properties.

    parse --emails <dir> --out parsed.json

- every .eml in <dir> appears, keyed by filename stem, and passes check_format
- one bad email never takes down the run (brief, property 3)
- nothing is ever silently lost: an email we could not handle comes back
  flagged for review, never as "nothing to do"
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from conftest import DEV_EMAILS, ROOT, make_eml
from rfqinbox import cli, pipeline


def run_parse(emails, out):
    return cli.main(["parse", "--emails", str(emails), "--out", str(out)])


def test_every_email_appears_and_shape_is_valid(tmp_path, check_format):
    inbox = tmp_path / "inbox"
    for stem in ("A1", "A2", "B7"):
        make_eml(inbox / f"{stem}.eml")
    out = tmp_path / "parsed.json"

    assert run_parse(inbox, out) == 0

    data = json.loads(out.read_text(encoding="utf-8"))
    assert set(data) == {"A1", "A2", "B7"}
    assert check_format.check(data) == []


def test_non_eml_files_are_ignored(tmp_path):
    inbox = tmp_path / "inbox"
    make_eml(inbox / "A1.eml")
    (inbox / "notes.txt").write_text("not an email", encoding="utf-8")
    out = tmp_path / "parsed.json"

    run_parse(inbox, out)

    assert set(json.loads(out.read_text(encoding="utf-8"))) == {"A1"}


def test_empty_and_garbage_files_are_reported_not_fatal(tmp_path, check_format):
    inbox = tmp_path / "inbox"
    make_eml(inbox / "good.eml")
    (inbox / "empty.eml").write_bytes(b"")
    (inbox / "garbage.eml").write_bytes(bytes(range(256)) * 40)
    out = tmp_path / "parsed.json"

    assert run_parse(inbox, out) == 0

    data = json.loads(out.read_text(encoding="utf-8"))
    assert set(data) == {"good", "empty", "garbage"}
    assert check_format.check(data) == []


def test_a_crash_inside_one_email_is_isolated(tmp_path, monkeypatch, check_format):
    inbox = tmp_path / "inbox"
    for stem in ("ok1", "boom", "ok2"):
        make_eml(inbox / f"{stem}.eml")
    real = pipeline.process_email

    def flaky(path, *args, **kwargs):
        if path.stem == "boom":
            raise RuntimeError("simulated failure deep in an attachment reader")
        return real(path, *args, **kwargs)

    monkeypatch.setattr(pipeline, "process_email", flaky)
    out = tmp_path / "parsed.json"

    assert run_parse(inbox, out) == 0

    data = json.loads(out.read_text(encoding="utf-8"))
    assert set(data) == {"ok1", "boom", "ok2"}
    assert check_format.check(data) == []
    boom = data["boom"]
    assert boom["needs_review"] is True
    assert "simulated failure" in boom["review_reason"]
    # Flagged as a request so a human sees it; never dropped as "other".
    assert boom["classification"] in ("rfq", "rfq_revision", "purchase_order")


def test_nothing_is_silently_lost(tmp_path):
    """Every email either has lines, is flagged, or is confidently a no-action kind."""
    inbox = tmp_path / "inbox"
    for stem in ("x1", "x2"):
        make_eml(inbox / f"{stem}.eml")
    out = tmp_path / "parsed.json"

    run_parse(inbox, out)

    action = {"rfq", "rfq_revision", "purchase_order"}
    for eid, rec in json.loads(out.read_text(encoding="utf-8")).items():
        if rec["classification"] in action:
            assert rec["line_items"] or rec["needs_review"], f"{eid} silently lost"


def test_output_is_deterministic(tmp_path):
    inbox = tmp_path / "inbox"
    for stem in ("b", "a", "c"):
        make_eml(inbox / f"{stem}.eml")
    out1, out2 = tmp_path / "p1.json", tmp_path / "p2.json"

    run_parse(inbox, out1)
    run_parse(inbox, out2)

    assert out1.read_bytes() == out2.read_bytes()
    assert list(json.loads(out1.read_text(encoding="utf-8"))) == ["a", "b", "c"]


def test_missing_inbox_dir_is_a_clean_error(tmp_path, capsys):
    rc = run_parse(tmp_path / "nope", tmp_path / "parsed.json")
    assert rc != 0
    assert "nope" in capsys.readouterr().err


def test_module_entry_point_on_dev_inbox(tmp_path, check_format):
    """The exact command the graders run, as a subprocess, on the dev inbox (shape only)."""
    out = tmp_path / "parsed.json"
    proc = subprocess.run(
        [sys.executable, "-m", "rfqinbox", "parse", "--emails", str(DEV_EMAILS), "--out", str(out)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    assert set(data) == {p.stem for p in DEV_EMAILS.glob("*.eml")}
    assert check_format.check(data) == []
