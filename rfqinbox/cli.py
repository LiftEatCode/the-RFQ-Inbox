"""Command line: `python -m rfqinbox parse --emails <dir> --out parsed.json`."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from rfqinbox import pipeline
from rfqinbox.record import review_record


def parse_inbox(emails_dir: Path) -> dict[str, dict]:
    """Process every .eml in the folder. One bad email never stops the run."""
    results: dict[str, dict] = {}
    for path in sorted(emails_dir.glob("*.eml")):
        try:
            results[path.stem] = pipeline.process_email(path)
        except Exception as exc:  # noqa: BLE001 — isolation is the point
            results[path.stem] = review_record(
                f"could not process this email ({type(exc).__name__}: {exc})"
            )
    return results


def write_json_atomic(data: dict, out: Path) -> None:
    """Write to a temp file and rename, so a crash never leaves half a parsed.json."""
    out = out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=out.name + ".", suffix=".tmp", dir=out.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, out)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def cmd_parse(args: argparse.Namespace) -> int:
    emails_dir = Path(args.emails)
    if not emails_dir.is_dir():
        print(f"error: --emails {emails_dir} is not a directory", file=sys.stderr)
        return 2
    results = parse_inbox(emails_dir)
    write_json_atomic(results, Path(args.out))
    flagged = sum(1 for r in results.values() if r["needs_review"])
    print(f"{len(results)} emails -> {args.out} ({flagged} flagged for review)", file=sys.stderr)
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    from rfqinbox import score as scoring

    try:
        pred = json.loads(Path(args.parsed).read_text(encoding="utf-8"))
        key = scoring.load_key(Path(args.key))
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    report = scoring.score(pred, key)
    print(scoring.format_report(report, verbose=not args.quiet))
    if args.json:
        write_json_atomic(report, Path(args.json))
    if args.gate and report["silent_losses"]:
        print(f"GATE FAILED: {len(report['silent_losses'])} silent loss(es)", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="rfqinbox", description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("parse", help="read every .eml in a folder and write parsed.json")
    p.add_argument("--emails", required=True, help="folder of .eml files")
    p.add_argument("--out", required=True, help="output JSON path")
    p.set_defaults(func=cmd_parse)
    s = sub.add_parser("score", help="score a parsed.json against an answer key (README grading rules)")
    s.add_argument("parsed", help="parsed.json to score")
    s.add_argument("--key", default="data/dev/answer_key.json", help="answer key JSON")
    s.add_argument("--gate", action="store_true", help="exit 1 if there is any silent loss")
    s.add_argument("--json", help="also write the full report as JSON here")
    s.add_argument("--quiet", action="store_true", help="headline numbers only")
    s.set_defaults(func=cmd_score)
    args = ap.parse_args(argv)
    return args.func(args)
