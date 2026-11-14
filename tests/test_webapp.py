"""The optional web app: one email walked through the system, for a rep.

    python -m rfqinbox serve --emails <dir> --parsed parsed.json

It only reads: the emails (through the reader) and parsed.json. It never calls the model and
never changes parsed.json; a rep's accept / overturn goes to a separate review.json.
Everything here uses invented emails and an invented catalog.
"""

from __future__ import annotations

import json
import urllib.request

import pytest

import fixtures as fx
from conftest import make_eml
from rfqinbox import cli, webapp

BODY = """Hi team,

Please quote the following for the Tuesday shutdown:

10 ea 2" 300# RF weld neck flange, A105
4 ea 2" pressure gauge, 0-100 psi

Thanks,
Pat

On Mon, 5 Oct 2026, Ridgeline wrote:
> 99 ea 6" blind flange from the old thread
"""

CATALOG_CSV = (
    "sku,description,category,product,size,spec,material,ends,extra,uom\n"
    'T-002,"FLG WN 2"" 300# A105 RF",flange,weld neck flange,2,300#,A105,RF,,EA\n'
    'T-001,"FLG WN 2"" 150# A105 RF",flange,weld neck flange,2,150#,A105,RF,,EA\n'
)


def line(raw, description, source="body", **match):
    out = {"raw": raw, "description": description, "qty": 1, "uom": "EA", "source": source}
    out.update(match)
    return out


def record(cls="rfq", lines=(), nr=False, reason=None, dup=None):
    return {"classification": cls, "revises": None, "duplicate_of": dup, "needs_review": nr,
            "review_reason": reason, "line_items": list(lines)}


@pytest.fixture
def site(tmp_path):
    """An inbox of three emails, its parsed.json and a catalog; returns the App."""
    inbox = tmp_path / "inbox"
    make_eml(inbox / "A1.eml", BODY, subject="Shutdown flanges")
    sheet = fx.xlsx_bytes(lambda wb: [wb.active.append(r) for r in
                                      (["Item", "Qty", "Description"], [1, 6, "3 in gate valve class 800"])])
    make_eml(inbox / "A2.eml", "List attached.", subject="Valves",
             attachments=[("list.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", sheet),
                          ("tag.png", "image/png", fx.picture(900, 700, "MODEL ZX-90"))])
    make_eml(inbox / "A3.eml", "<script>alert('x')</script> Out of office until Monday.", subject="Auto: away")
    parsed = {
        "A1": record(lines=[
            line('10 ea 2" 300# RF weld neck flange, A105', '2" 300# RF weld neck flange, A105',
                 sku="T-002", match="matched", match_reason="FLG WN 2\" 300# A105 RF: one part fits", candidates=[]),
            line('4 ea 2" pressure gauge, 0-100 psi', '2" pressure gauge, 0-100 psi',
                 sku=None, match="not_in_catalog", match_reason="no stocked product recognised", candidates=[]),
        ]),
        "A2": record(lines=[line("1 | 6 | 3 in gate valve class 800", "3 in gate valve class 800", source="list.xlsx"),
                            line("MODEL ZX-90", "Pump model ZX-90", source="tag.png")],
                     nr=True, reason="could not read tag.png fully"),
        "A3": record("auto_reply"),
    }
    parsed_path = tmp_path / "parsed.json"
    parsed_path.write_text(json.dumps(parsed, indent=2), encoding="utf-8")
    catalog = tmp_path / "catalog.csv"
    catalog.write_text(CATALOG_CSV, encoding="utf-8")
    return webapp.App(inbox, parsed_path, review_path=tmp_path / "review.json", catalog_path=catalog)


def get(app, path):
    status, ctype, body = app.handle("GET", path)
    return status, ctype, body.decode("utf-8") if ctype.startswith(("text/", "application/json")) else body


def post(app, payload):
    status, _, body = app.handle("POST", "/decision", json.dumps(payload).encode("utf-8"))
    return status, json.loads(body.decode("utf-8"))


# ---------------------------------------------------------------- the view (no HTML)

def test_view_has_the_email_the_lines_and_where_each_line_came_from(site):
    v = site.view("A1")
    assert v["subject"] == "Shutdown flanges" and "pat@customer.example" in v["sender"]
    assert v["classification"] == "rfq"
    first, second = v["lines"]
    assert first["description"] == '2" 300# RF weld neck flange, A105'
    # each line points at the place in the email it was read from
    assert first["found"]["where"] == "body"
    assert "weld neck flange" in v["body"][first["found"]["line"]]["text"]
    assert v["body"][second["found"]["line"]]["text"].startswith("4 ea")
    assert first["found"]["line"] != second["found"]["line"]


def test_quoted_history_is_shown_apart_from_the_new_text(site):
    v = site.view("A1")
    assert not any("old thread" in ln["text"] for ln in v["body"])
    assert any("old thread" in ln["text"] for q in v["quoted"] for ln in q["lines"])


def test_a_line_from_an_attachment_points_into_that_attachment(site):
    v = site.view("A2")
    names = [a["filename"] for a in v["attachments"]]
    assert names == ["list.xlsx", "tag.png"]
    sheet_line, tag_line = v["lines"]
    assert sheet_line["found"]["where"] == "list.xlsx"
    att = v["attachments"][0]
    assert "gate valve" in att["lines"][sheet_line["found"]["line"]]["text"]
    # a line read from a picture can only point at the picture
    assert tag_line["found"] == {"where": "tag.png", "line": None}
    assert v["attachments"][1]["images"] >= 1
    assert v["needs_review"] is True and "tag.png" in v["review_reason"]


def test_a_line_we_cannot_place_says_so_instead_of_guessing(tmp_path, site):
    parsed = json.loads(site.parsed_path.read_text(encoding="utf-8"))
    parsed["A1"]["line_items"].append(line("12 ea something never written", "something never written"))
    site.parsed_path.write_text(json.dumps(parsed), encoding="utf-8")
    assert site.view("A1")["lines"][2]["found"] is None


def test_the_view_carries_the_catalog_decision(site):
    first, second = site.view("A1")["lines"]
    assert (first["match"], first["sku"]) == ("matched", "T-002")
    assert first["part"] == 'FLG WN 2" 300# A105 RF'          # the catalog's description of that sku
    assert (second["match"], second["sku"]) == ("not_in_catalog", None)
    assert first["decision"] is None                            # nobody has reviewed it yet
    assert site.view("A2")["lines"][0]["match"] is None         # parsed without the matcher: still shown


# ---------------------------------------------------------------- pages

def test_inbox_page_lists_every_email_with_its_class(site):
    status, ctype, html = get(site, "/")
    assert status == 200 and ctype.startswith("text/html")
    for eid in ("A1", "A2", "A3"):
        assert f"/email/{eid}" in html
    assert "auto_reply" in html and "needs review" in html.lower()


def test_email_page_shows_email_lines_and_match(site):
    status, _, html = get(site, "/email/A1")
    assert status == 200
    assert "Shutdown flanges" in html
    assert "weld neck flange" in html and "T-002" in html
    assert "not in catalog" in html.lower()
    assert "old thread" in html


def test_email_content_is_escaped_never_run(site):
    _, _, html = get(site, "/email/A3")
    assert "<script>alert" not in html
    assert "&lt;script&gt;alert" in html


def test_unknown_pages_and_ids_are_404_not_a_crash(site):
    for path in ("/email/NOPE", "/email/../../etc/passwd", "/nothing", "/image/A1/9/9", "/email/"):
        assert get(site, path)[0] == 404


def test_an_email_file_that_cannot_be_read_still_gets_a_page(site):
    (site.emails_dir / "A1.eml").unlink()
    status, _, html = get(site, "/email/A1")
    assert status == 200
    assert "weld neck flange" in html              # the extracted lines are still shown
    assert "could not read" in html.lower()


def test_attachment_pictures_are_served(site):
    status, ctype, body = site.handle("GET", "/image/A2/1/0")
    assert status == 200 and ctype in ("image/png", "image/jpeg") and len(body) > 100


# ---------------------------------------------------------------- accept / overturn

def test_accept_is_saved_to_review_json_and_shown(site):
    status, reply = post(site, {"email": "A1", "line": 0, "action": "accept"})
    assert status == 200 and reply["ok"] is True
    saved = json.loads(site.review_path.read_text(encoding="utf-8"))
    assert saved["A1"]["0"]["action"] == "accept" and saved["A1"]["0"]["sku"] == "T-002"
    assert site.view("A1")["lines"][0]["decision"]["action"] == "accept"
    assert "accepted" in get(site, "/email/A1")[2].lower()


def test_overturn_to_another_part_or_to_not_stocked(site):
    assert post(site, {"email": "A1", "line": 0, "action": "overturn", "sku": "T-001"})[0] == 200
    assert post(site, {"email": "A1", "line": 1, "action": "overturn", "sku": None})[0] == 200
    lines = site.view("A1")["lines"]
    assert lines[0]["decision"] == {"action": "overturn", "sku": "T-001", "was": "T-002"}
    assert lines[1]["decision"]["sku"] is None
    # the system's own answer is still what is shown as the system's answer
    assert lines[0]["sku"] == "T-002"


def test_a_decision_never_changes_parsed_json(site):
    before = site.parsed_path.read_bytes()
    post(site, {"email": "A1", "line": 0, "action": "overturn", "sku": "T-001"})
    post(site, {"email": "A1", "line": 1, "action": "accept"})
    assert site.parsed_path.read_bytes() == before


@pytest.mark.parametrize("payload", [
    {"email": "NOPE", "line": 0, "action": "accept"},
    {"email": "A1", "line": 7, "action": "accept"},
    {"email": "A1", "line": 0, "action": "delete"},
    {"email": "A1", "line": 0, "action": "overturn", "sku": "NOT-A-SKU"},     # only catalog parts
    {"email": "A1", "line": "0; drop", "action": "accept"},
    ["not", "an", "object"],
])
def test_a_bad_decision_is_refused_and_nothing_is_saved(site, payload):
    status, reply = post(site, payload)
    assert status == 400 and reply["ok"] is False
    assert not site.review_path.exists()


def test_garbage_post_body_is_refused(site):
    status, _, _ = site.handle("POST", "/decision", b"\xff\xfe not json")
    assert status == 400


def test_decisions_survive_a_restart(site):
    post(site, {"email": "A1", "line": 0, "action": "accept"})
    again = webapp.App(site.emails_dir, site.parsed_path, review_path=site.review_path,
                       catalog_path=site.catalog_path)
    assert again.view("A1")["lines"][0]["decision"]["action"] == "accept"


# ---------------------------------------------------------------- the server and the command

def test_the_server_listens_on_this_machine_only_and_serves_the_inbox(site):
    server = webapp.make_server(site, port=0)
    try:
        host, port = server.server_address[:2]
        assert host == "127.0.0.1"
        import threading
        threading.Thread(target=server.serve_forever, daemon=True).start()
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as r:
            assert r.status == 200 and "/email/A1" in r.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()


def test_serve_command_needs_a_real_inbox_and_parsed_file(tmp_path, capsys):
    assert cli.main(["serve", "--emails", str(tmp_path / "none"), "--parsed", str(tmp_path / "p.json")]) == 2
    (tmp_path / "inbox").mkdir()
    assert cli.main(["serve", "--emails", str(tmp_path / "inbox"), "--parsed", str(tmp_path / "p.json")]) == 2
    assert "error" in capsys.readouterr().err.lower()


def test_the_app_never_builds_a_model_client(site, monkeypatch):
    from rfqinbox import model
    monkeypatch.setattr(model, "make_client", lambda *a, **k: pytest.fail("the web app called the model"))
    monkeypatch.setattr(model.OpenAIClient, "complete", lambda *a, **k: pytest.fail("model call"), raising=False)
    get(site, "/")
    get(site, "/email/A2")
