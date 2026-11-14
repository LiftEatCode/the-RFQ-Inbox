"""Command line: `python -m rfqinbox parse --emails <dir> --out parsed.json`."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from rfqinbox import checks, matcher, model, pipeline, reader
from rfqinbox.record import review_record


def load_env() -> None:
    """Load a .env file from the current folder (or a parent) into the environment.

    A convenience for local runs: variables already set in the environment win, and a
    missing file or missing python-dotenv is not an error. Tests set RFQINBOX_NO_DOTENV
    so that a developer's real key can never be picked up by a test run.
    """
    if os.environ.get("RFQINBOX_NO_DOTENV"):
        return
    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:
        return
    load_dotenv(find_dotenv(usecwd=True))


def parse_inbox(emails_dir: Path, engine: model.Engine | None = None) -> dict[str, dict]:
    """Process every .eml in the folder. One bad email never stops the run."""
    engine = engine or pipeline.default_engine()
    results: dict[str, dict] = {}
    for path in sorted(emails_dir.glob("*.eml")):
        engine.ledger.touch(path.stem)
        try:
            results[path.stem] = pipeline.process_email(path, engine)
        except Exception as exc:  # noqa: BLE001 — isolation is the point
            results[path.stem] = review_record(
                f"could not process this email ({type(exc).__name__}: {exc})"
            )
    return link_inbox(emails_dir, results)


def link_inbox(emails_dir: Path, results: dict[str, dict]) -> dict[str, dict]:
    """Duplicates and revisions need the whole inbox. If this step fails, the
    per-email records are returned as they were."""
    try:
        headers = {}
        for path in sorted(emails_dir.glob("*.eml")):
            try:
                headers[path.stem] = reader.read_headers(path)
            except Exception:  # noqa: BLE001 — an unreadable email is simply not linked
                continue
        return checks.link_records(headers, results,
                                   load=lambda i: reader.read_email(emails_dir / f"{i}.eml"))
    except Exception as exc:  # noqa: BLE001
        print(f"warning: could not link duplicates and revisions ({type(exc).__name__}: {exc})",
              file=sys.stderr)
        return results


def match_inbox(results: dict[str, dict], catalog_path: Path | None = None) -> dict[str, dict]:
    """The optional matcher: add sku / match to every line from the catalog. No catalog
    file, or any failure, leaves the records exactly as extracted."""
    path = Path(catalog_path) if catalog_path else matcher.default_catalog_path()
    if not path.is_file():
        return results
    try:
        return matcher.add_matches(results, matcher.Catalog.load(path))
    except Exception as exc:  # noqa: BLE001
        print(f"warning: could not match lines to the catalog ({type(exc).__name__}: {exc})",
              file=sys.stderr)
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
    client = model.make_client()
    if client is None:
        print("warning: OPENAI_API_KEY is not set - replaying from the cache only; "
              "emails with no cached answer are flagged for review", file=sys.stderr)
    cache_dir = Path(args.cache) if args.cache else model.default_cache_dir()
    engine = model.Engine(client, model.Cache(cache_dir), model.Ledger())
    results = parse_inbox(emails_dir, engine)
    if not args.no_match:
        results = match_inbox(results, Path(args.catalog) if args.catalog else None)
    out = Path(args.out)
    write_json_atomic(results, out)
    flagged = sum(1 for r in results.values() if r["needs_review"])
    print(f"{len(results)} emails -> {args.out} ({flagged} flagged for review)", file=sys.stderr)
    cost_path = Path(args.cost_report) if args.cost_report else out.resolve().parent / "cost_report.json"
    try:
        engine.ledger.write(cost_path)
    except OSError as exc:
        print(f"warning: could not write {cost_path}: {exc}", file=sys.stderr)
    t = engine.ledger.report()["totals"]
    print(f"{t['new_calls']} model calls this run, {t['calls'] - t['new_calls']} replayed from cache; "
          f"{t['input_tokens']:,} input / {t['output_tokens']:,} output tokens; "
          f"${t['new_cost_usd']:.4f} spent now, ${t['cost_usd']:.4f} total as recorded "
          f"({engine.model}) -> {cost_path.name}", file=sys.stderr)
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


def cmd_inspect(args: argparse.Namespace) -> int:
    from rfqinbox import reader

    path = Path(args.eml)
    if not path.is_file():
        print(f"error: {path} is not a file", file=sys.stderr)
        return 2
    pk = reader.read_email(path)
    print(reader.render(pk))
    imgs = reader.images_for_model(pk)
    if imgs:
        print("\n=== IMAGES SENT TO THE MODEL ===")
        for label, data, detail in imgs:
            print(f"- {label}: {len(data):,} bytes, detail={detail}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from rfqinbox import webapp

    emails_dir, parsed = Path(args.emails), Path(args.parsed)
    if not emails_dir.is_dir():
        print(f"error: --emails {emails_dir} is not a directory", file=sys.stderr)
        return 2
    if not parsed.is_file():
        print(f"error: --parsed {parsed} not found; run `parse` first", file=sys.stderr)
        return 2
    app = webapp.App(emails_dir, parsed, review_path=args.review, catalog_path=args.catalog)
    try:
        server = webapp.make_server(app, port=args.port)
    except OSError as exc:
        print(f"error: could not listen on port {args.port}: {exc}", file=sys.stderr)
        return 2
    print(f"RFQ inbox viewer: http://127.0.0.1:{server.server_address[1]}/  (Ctrl+C to stop)", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
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
    p.add_argument("--cache", help="model response cache folder (default: cache/ in the repo)")
    p.add_argument("--cost-report", help="where to write calls/tokens/$ per email "
                                         "(default: cost_report.json next to --out)")
    p.add_argument("--catalog", help="catalog CSV for the matcher (default: data/catalog.csv in the repo)")
    p.add_argument("--no-match", action="store_true", help="skip the catalog matcher (no sku / match fields)")
    p.set_defaults(func=cmd_parse)
    s = sub.add_parser("score", help="score a parsed.json against an answer key (README grading rules)")
    s.add_argument("parsed", help="parsed.json to score")
    s.add_argument("--key", default="data/dev/answer_key.json", help="answer key JSON")
    s.add_argument("--gate", action="store_true", help="exit 1 if there is any silent loss")
    s.add_argument("--json", help="also write the full report as JSON here")
    s.add_argument("--quiet", action="store_true", help="headline numbers only")
    s.set_defaults(func=cmd_score)
    i = sub.add_parser("inspect", help="print what the model will see for one email")
    i.add_argument("eml", help="path to one .eml file")
    i.set_defaults(func=cmd_inspect)
    w = sub.add_parser("serve", help="local web page: one email, its lines and catalog decisions (no model calls)")
    w.add_argument("--emails", required=True, help="folder of .eml files")
    w.add_argument("--parsed", default="parsed.json", help="parsed.json written by `parse`")
    w.add_argument("--port", type=int, default=8000)
    w.add_argument("--review", help="where a rep's accept / overturn is saved (default: review.json next to --parsed)")
    w.add_argument("--catalog", help="catalog CSV (default: data/catalog.csv in the repo)")
    w.set_defaults(func=cmd_serve)
    args = ap.parse_args(argv)
    load_env()
    return args.func(args)
