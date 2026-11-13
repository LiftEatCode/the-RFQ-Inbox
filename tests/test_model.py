"""The model layer: OpenAI client, response cache, cost ledger, failure handling.

No test here needs a key or the network. Two seams are faked:

- `OpenAIClient(opener=...)` - the HTTP call itself (stands in for urllib's urlopen)
- `model.make_client()`      - what the CLI calls to get a client (None = no key)

The properties under test are the brief's: replay from the cache with no key, no
new calls on a second run, one failed call never takes down the run, and the cost
of every email is known.
"""

from __future__ import annotations

import base64
import io
import json
import urllib.error

import pytest

import fixtures as fx
from conftest import make_eml
from rfqinbox import cli, model

KEY = "sk-test-NEVER-PRINT-THIS-0123456789"
ACTION = ("rfq", "rfq_revision", "purchase_order")


# ------------------------------------------------------------------ helpers

def answer(classification="rfq", lines=None, needs_review=False, reason=None) -> str:
    """A well-formed model reply, as the JSON text the API returns."""
    if lines is None and classification in ACTION:
        lines = [{"raw": '10 ea 2" 90 elbow', "description": '2" 90 elbow',
                  "qty": 10, "uom": "EA", "source": "body"}]
    return json.dumps({
        "analysis": "The new message asks for a price on the listed items.",
        "classification": classification,
        "needs_review": needs_review,
        "review_reason": reason,
        "line_items": lines or [],
    })


class FakeClient:
    """Stands in for OpenAIClient. Each reply is JSON text, or an exception to raise.
    The last reply repeats, so one FakeClient can serve a whole inbox."""

    model = "fake-model"

    def __init__(self, *replies, tokens=(1000, 200)):
        self.replies = list(replies) or [answer()]
        self.tokens = tokens
        self.calls = []

    def complete(self, messages, schema):
        self.calls.append(messages)
        r = self.replies[min(len(self.calls), len(self.replies)) - 1]
        if isinstance(r, BaseException):
            raise r
        return model.Completion(text=r, input_tokens=self.tokens[0], output_tokens=self.tokens[1])


class FakeHTTP:
    """Stands in for urllib.request.urlopen. Each step is a response dict, raw bytes,
    or an exception to raise. Records every request it was given."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append((request, timeout))
        step = self.steps[min(len(self.requests), len(self.steps)) - 1]
        if isinstance(step, BaseException):
            raise step
        body = step if isinstance(step, bytes) else json.dumps(step).encode("utf-8")
        return _Response(body)


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def api_reply(text=None, prompt_tokens=1200, completion_tokens=300) -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": text or answer()},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                  "total_tokens": prompt_tokens + completion_tokens},
    }


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://api.openai.com/v1/chat/completions", code,
                                  "simulated", {}, io.BytesIO(b'{"error": {"message": "simulated"}}'))


def make_openai(http, **kw):
    sleeps = []
    client = model.OpenAIClient(KEY, opener=http, sleep=sleeps.append, **kw)
    return client, sleeps


def make_engine(tmp_path, client, **kw):
    ledger = model.Ledger()
    engine = model.Engine(client=client, cache=model.Cache(tmp_path / "cache"), ledger=ledger, **kw)
    return engine, ledger


def run_parse(tmp_path, monkeypatch, client, inbox=None, out="parsed.json"):
    """Run the real CLI with `client` as the model (None = no API key)."""
    monkeypatch.setattr(model, "make_client", lambda: client)
    out_path = tmp_path / out
    rc = cli.main(["parse", "--emails", str(inbox or tmp_path / "inbox"),
                   "--out", str(out_path), "--cache", str(tmp_path / "cache")])
    return rc, json.loads(out_path.read_text(encoding="utf-8"))


def inbox_of(tmp_path, *stems):
    for stem in stems:
        make_eml(tmp_path / "inbox" / f"{stem}.eml", body=f"Please quote 10 ea 2\" 90 elbow. Ref {stem}")
    return tmp_path / "inbox"


MESSAGES = [{"role": "user", "content": "hello"}]


# ================================================================== OpenAI client (HTTP)

def test_request_is_chat_completions_with_strict_json_schema():
    http = FakeHTTP(api_reply())
    client, _ = make_openai(http, model="some-model", timeout=45)

    got = client.complete(MESSAGES, model.OUTPUT_SCHEMA)

    request, timeout = http.requests[0]
    assert request.full_url == "https://api.openai.com/v1/chat/completions"
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == f"Bearer {KEY}"
    assert request.get_header("Content-type") == "application/json"
    assert timeout == 45
    body = json.loads(request.data.decode("utf-8"))
    assert body["model"] == "some-model"
    assert body["messages"] == MESSAGES
    rf = body["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["schema"] == model.OUTPUT_SCHEMA
    assert (got.text, got.input_tokens, got.output_tokens) == (answer(), 1200, 300)


def test_output_schema_is_valid_for_strict_mode():
    """Strict mode requires every object to list all its properties as required and
    forbid extras; and the schema must only allow what the output contract allows."""
    from rfqinbox.record import CLASSES, UOMS

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False
                assert set(node["required"]) == set(node["properties"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(model.OUTPUT_SCHEMA)
    props = model.OUTPUT_SCHEMA["properties"]
    assert set(props["classification"]["enum"]) == set(CLASSES)
    item = props["line_items"]["items"]["properties"]
    assert {"raw", "description", "qty", "uom", "source"} <= set(item)
    assert set(item["uom"]["enum"]) == set(UOMS) | {None}


def test_images_are_sent_as_base64_data_urls_with_their_detail():
    png = fx.picture(40, 30, "x")
    jpg = fx.picture(40, 30, "y", fmt="JPEG")

    messages = model.build_messages("EMAIL TEXT", [("list.png", png, "high"), ("logo.jpg", jpg, "low")])

    assert messages[0]["role"] == "system" and messages[0]["content"].strip()
    parts = messages[-1]["content"]
    assert messages[-1]["role"] == "user"
    assert any(p["type"] == "text" and "EMAIL TEXT" in p["text"] for p in parts)
    images = [p["image_url"] for p in parts if p["type"] == "image_url"]
    assert [i["detail"] for i in images] == ["high", "low"]
    assert images[0]["url"] == "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    assert images[1]["url"].startswith("data:image/jpeg;base64,")
    # Each picture is introduced by its label so `source` can name the right file.
    text = " ".join(p["text"] for p in parts if p["type"] == "text")
    assert text.index("list.png") < text.index("logo.jpg")


def test_no_images_means_plain_text_request():
    messages = model.build_messages("EMAIL TEXT", [])
    assert "image_url" not in json.dumps(messages)
    assert "EMAIL TEXT" in json.dumps(messages)


@pytest.mark.parametrize("code", [429, 500, 502, 503])
def test_retries_rate_limits_and_server_errors_with_backoff(code):
    http = FakeHTTP(http_error(code), http_error(code), api_reply())
    client, sleeps = make_openai(http, max_retries=3)

    got = client.complete(MESSAGES, model.OUTPUT_SCHEMA)

    assert got.text == answer()
    assert len(http.requests) == 3
    assert len(sleeps) == 2 and 0 < sleeps[0] < sleeps[1]   # waited, and waited longer


@pytest.mark.parametrize("failure", [
    http_error(429),
    http_error(503),
    TimeoutError("timed out"),
    urllib.error.URLError("connection refused"),
    ConnectionResetError("reset by peer"),
], ids=["429", "503", "timeout", "network", "reset"])
def test_gives_up_after_the_retry_budget(failure):
    http = FakeHTTP(failure)
    client, sleeps = make_openai(http, max_retries=2)

    with pytest.raises(model.ModelError) as err:
        client.complete(MESSAGES, model.OUTPUT_SCHEMA)

    assert len(http.requests) == 3            # first try + 2 retries, then stop
    assert len(sleeps) == 2
    assert str(err.value)                     # a reason a rep can read


@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_client_errors_are_not_retried(code):
    http = FakeHTTP(http_error(code))
    client, sleeps = make_openai(http, max_retries=3)

    with pytest.raises(model.ModelError) as err:
        client.complete(MESSAGES, model.OUTPUT_SCHEMA)

    assert len(http.requests) == 1 and sleeps == []
    assert str(code) in str(err.value)


@pytest.mark.parametrize("body", [
    b"<html>502 Bad Gateway</html>",
    b"{}",
    json.dumps({"choices": []}).encode(),
    json.dumps({"choices": [{"message": {"content": None, "refusal": "I can't help with that"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 5}}).encode(),
], ids=["not-json", "empty-object", "no-choices", "refusal"])
def test_unusable_api_response_is_a_model_error(body):
    client, _ = make_openai(FakeHTTP(body), max_retries=0)
    with pytest.raises(model.ModelError):
        client.complete(MESSAGES, model.OUTPUT_SCHEMA)


@pytest.mark.parametrize("failure", [http_error(401), http_error(500), TimeoutError("timed out")],
                         ids=["401", "500", "timeout"])
def test_errors_never_contain_the_api_key(failure):
    client, _ = make_openai(FakeHTTP(failure), max_retries=0)
    with pytest.raises(model.ModelError) as err:
        client.complete(MESSAGES, model.OUTPUT_SCHEMA)
    assert KEY not in str(err.value) and KEY not in repr(err.value)
    assert KEY not in repr(client)


def test_make_client_reads_the_key_from_the_environment_only(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert model.make_client() is None
    monkeypatch.setenv("OPENAI_API_KEY", "   ")
    assert model.make_client() is None
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    client = model.make_client()
    assert isinstance(client, model.OpenAIClient)
    assert client.model == model.DEFAULT_MODEL


# ================================================================== cache

def key_for(**changes):
    base = dict(model="m1", prompt_version="v1", schema={"type": "object"},
                text="EMAIL TEXT", images=[b"img-one", b"img-two"])
    base.update(changes)
    return model.cache_key(**base)


def test_cache_key_is_stable_and_is_a_sha256():
    assert key_for() == key_for()
    assert len(key_for()) == 64 and int(key_for(), 16) >= 0


@pytest.mark.parametrize("change", [
    {"model": "m2"},
    {"prompt_version": "v2"},
    {"schema": {"type": "object", "x": 1}},
    {"text": "EMAIL TEXT."},
    {"images": [b"img-one", b"img-2"]},
    {"images": [b"img-one"]},
    {"images": [b"img-two", b"img-one"]},
    {"images": [b"img-oneimg-two"]},
], ids=["model", "prompt-version", "schema", "text", "image-bytes", "image-removed",
        "image-order", "image-boundary"])
def test_anything_the_model_would_see_differently_changes_the_key(change):
    assert key_for(**change) != key_for()


def test_cache_round_trip_one_json_file_per_key(tmp_path):
    cache = model.Cache(tmp_path / "cache")
    key = key_for()
    assert cache.get(key) is None

    cache.put(key, {"output": {"classification": "other"}, "note": "café ½\""})

    assert cache.get(key) == {"output": {"classification": "other"}, "note": "café ½\""}
    files = sorted(p.name for p in (tmp_path / "cache").iterdir())
    assert files == [f"{key}.json"]                      # and no temp file left behind
    # Committed to git and read on Windows: UTF-8, LF, byte-identical when rewritten.
    raw = (tmp_path / "cache" / f"{key}.json").read_bytes()
    assert b"\r" not in raw and "café".encode("utf-8") in raw
    cache.put(key, {"note": "café ½\"", "output": {"classification": "other"}})
    assert (tmp_path / "cache" / f"{key}.json").read_bytes() == raw


@pytest.mark.parametrize("content", [b"", b"{not json", b"[1, 2]", b"\xff\xfe\x00"],
                         ids=["empty", "truncated", "wrong-type", "binary"])
def test_a_corrupt_cache_file_is_a_miss_not_a_crash(tmp_path, content):
    cache = model.Cache(tmp_path / "cache")
    key = key_for()
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / f"{key}.json").write_bytes(content)
    assert cache.get(key) is None


# ================================================================== cost ledger

def test_cost_comes_from_the_price_table(monkeypatch):
    assert model.DEFAULT_MODEL in model.PRICES
    monkeypatch.setitem(model.PRICES, "fake-model", (2.0, 8.0))   # $ per 1M input / output tokens
    assert model.cost_usd("fake-model", 1_000_000, 0) == pytest.approx(2.0)
    assert model.cost_usd("fake-model", 1000, 200) == pytest.approx(0.002 + 0.0016)


def test_ledger_totals_add_up_and_separate_new_spend_from_replayed(monkeypatch):
    monkeypatch.setitem(model.PRICES, "fake-model", (2.0, 8.0))
    ledger = model.Ledger()
    ledger.add("E1", "fake-model", 1000, 200, cached=False)
    ledger.add("E1", "fake-model", 500, 100, cached=False)     # a repair retry
    ledger.add("E2", "fake-model", 3000, 400, cached=True)     # replayed from the cache
    ledger.touch("E3")                                         # never reached the model

    report = ledger.report()

    e1, e2, e3 = (report["emails"][k] for k in ("E1", "E2", "E3"))
    assert (e1["calls"], e1["new_calls"], e1["input_tokens"], e1["output_tokens"]) == (2, 2, 1500, 300)
    assert e1["cost_usd"] == e1["new_cost_usd"] == pytest.approx(0.003 + 0.0024)
    # A cache hit still reports what that answer cost when it was recorded, but nothing new.
    assert (e2["calls"], e2["new_calls"], e2["new_cost_usd"]) == (1, 0, 0)
    assert e2["cost_usd"] == pytest.approx(0.006 + 0.0032)
    assert (e3["calls"], e3["cost_usd"]) == (0, 0)
    totals = report["totals"]
    assert totals["emails"] == 3
    for field in ("calls", "new_calls", "input_tokens", "output_tokens"):
        assert totals[field] == sum(e[field] for e in report["emails"].values())
    for field in ("cost_usd", "new_cost_usd"):
        assert totals[field] == pytest.approx(sum(e[field] for e in report["emails"].values()))


# ================================================================== engine: cache + validation

def test_second_extract_of_the_same_email_makes_no_call(tmp_path):
    client = FakeClient()
    engine, ledger = make_engine(tmp_path, client)

    first = engine.extract("E1", "EMAIL TEXT", [])
    second = engine.extract("E1", "EMAIL TEXT", [])

    assert first == second == json.loads(answer())
    assert len(client.calls) == 1
    assert ledger.report()["emails"]["E1"]["new_calls"] == 1


def test_cache_survives_a_new_process_and_needs_no_client(tmp_path):
    engine, _ = make_engine(tmp_path, FakeClient())
    first = engine.extract("E1", "EMAIL TEXT", [b"scan"])

    replay, ledger = make_engine(tmp_path, client=None)      # the graders' second run: no key

    assert replay.extract("E1", "EMAIL TEXT", [b"scan"]) == first
    row = ledger.report()["emails"]["E1"]
    assert (row["calls"], row["new_calls"], row["new_cost_usd"]) == (1, 0, 0)
    assert (row["input_tokens"], row["output_tokens"]) == (1000, 200)


def test_changing_the_prompt_version_busts_the_cache(tmp_path):
    client = FakeClient()
    engine, _ = make_engine(tmp_path, client, prompt_version="v1")
    engine.extract("E1", "EMAIL TEXT", [])

    bumped, _ = make_engine(tmp_path, client, prompt_version="v2")
    bumped.extract("E1", "EMAIL TEXT", [])
    assert len(client.calls) == 2

    engine.extract("E1", "EMAIL TEXT", [])                   # v1 is still there
    assert len(client.calls) == 2


def test_a_different_model_does_not_reuse_another_models_answer(tmp_path):
    a, b = FakeClient(), FakeClient()
    b.model = "other-model"
    make_engine(tmp_path, a)[0].extract("E1", "EMAIL TEXT", [])
    make_engine(tmp_path, b)[0].extract("E1", "EMAIL TEXT", [])
    assert (len(a.calls), len(b.calls)) == (1, 1)


def test_no_key_and_nothing_cached_is_a_model_error_that_says_so(tmp_path):
    engine, _ = make_engine(tmp_path, client=None)
    with pytest.raises(model.ModelError) as err:
        engine.extract("E1", "EMAIL TEXT", [])
    assert "OPENAI_API_KEY" in str(err.value)


BAD_REPLIES = {
    "not-json": "Sure! Here are the items you asked for:",
    "truncated": answer()[:-25],
    "wrong-type": "[]",
    "missing-field": json.dumps({"classification": "rfq", "line_items": []}),
    "unknown-class": answer().replace('"rfq"', '"quote_request"'),
    "bad-uom": answer().replace('"EA"', '"EACH"'),
    "qty-not-a-number": answer().replace('"qty": 10', '"qty": "ten"'),
    "line-not-an-object": json.dumps({"classification": "rfq", "needs_review": False,
                                      "review_reason": None, "line_items": ["10 elbows"]}),
}


@pytest.mark.parametrize("bad", BAD_REPLIES.values(), ids=BAD_REPLIES.keys())
def test_a_malformed_reply_gets_one_repair_retry(tmp_path, bad):
    client = FakeClient(bad, answer("purchase_order"))
    engine, ledger = make_engine(tmp_path, client)

    out = engine.extract("E1", "EMAIL TEXT", [])

    assert out["classification"] == "purchase_order"
    assert len(client.calls) == 2
    # The retry tells the model what was wrong with its first reply.
    assert len(json.dumps(client.calls[1])) > len(json.dumps(client.calls[0]))
    # Both calls were paid for, and both are remembered with the cached answer.
    assert ledger.report()["emails"]["E1"]["calls"] == 2
    replay, ledger2 = make_engine(tmp_path, client=None)
    assert replay.extract("E1", "EMAIL TEXT", []) == out
    assert ledger2.report()["emails"]["E1"]["input_tokens"] == 2000


@pytest.mark.parametrize("bad", BAD_REPLIES.values(), ids=BAD_REPLIES.keys())
def test_two_malformed_replies_give_up_and_cache_nothing(tmp_path, bad):
    client = FakeClient(bad, bad, answer())
    engine, ledger = make_engine(tmp_path, client)

    with pytest.raises(model.ModelError):
        engine.extract("E1", "EMAIL TEXT", [])

    assert len(client.calls) == 2                        # one repair retry, not a loop
    assert not list((tmp_path / "cache").glob("*.json"))  # a bad answer is never replayed
    assert ledger.report()["emails"]["E1"]["calls"] == 2  # but it was still paid for
    assert engine.extract("E1", "EMAIL TEXT", [])["classification"] == "rfq"   # next run retries


def test_a_failed_call_is_not_cached_and_any_exception_becomes_a_model_error(tmp_path):
    client = FakeClient(model.ModelError("gave up after 3 retries: HTTP 503"),
                        RuntimeError("something nobody planned for"), answer())
    engine, _ = make_engine(tmp_path, client)

    with pytest.raises(model.ModelError, match="503"):
        engine.extract("E1", "EMAIL TEXT", [])
    with pytest.raises(model.ModelError, match="nobody planned"):
        engine.extract("E1", "EMAIL TEXT", [])
    assert not list((tmp_path / "cache").glob("*.json"))
    assert engine.extract("E1", "EMAIL TEXT", [])["classification"] == "rfq"


# ================================================================== through the CLI

def test_parse_uses_the_models_answer(tmp_path, monkeypatch, check_format):
    inbox_of(tmp_path, "E1")
    client = FakeClient(answer("purchase_order"))

    rc, data = run_parse(tmp_path, monkeypatch, client)

    assert rc == 0 and check_format.check(data) == []
    rec = data["E1"]
    assert rec["classification"] == "purchase_order"
    assert rec["needs_review"] is False and rec["review_reason"] is None
    assert rec["line_items"] == json.loads(answer())["line_items"]
    # The model was shown the email as the reader renders it.
    assert "Ref E1" in json.dumps(client.calls[0])


def test_images_reach_the_model(tmp_path, monkeypatch):
    photo = fx.picture(900, 700, "12 EA 2in tee")
    make_eml(tmp_path / "inbox" / "E1.eml", "List attached.", attachments=[("list.png", "image/png", photo)])
    client = FakeClient()

    run_parse(tmp_path, monkeypatch, client)

    sent = json.dumps(client.calls[0])
    assert "data:image/" in sent and "list.png" in sent


def test_second_run_makes_no_calls_and_matches_with_the_key_removed(tmp_path, monkeypatch):
    """How we are graded: once with the key, then again with the key removed."""
    inbox_of(tmp_path, "E1", "E2", "E3")
    client = FakeClient(answer(), answer("status_inquiry"), answer("purchase_order"))

    _, first = run_parse(tmp_path, monkeypatch, client, out="run1.json")
    assert len(client.calls) == 3
    _, second = run_parse(tmp_path, monkeypatch, client, out="run2.json")
    assert len(client.calls) == 3
    _, no_key = run_parse(tmp_path, monkeypatch, None, out="run3.json")

    assert first == second == no_key
    assert {r["classification"] for r in first.values()} == {"rfq", "status_inquiry", "purchase_order"}
    assert (tmp_path / "run1.json").read_bytes() == (tmp_path / "run3.json").read_bytes()


def test_no_key_and_no_cache_flags_everything_and_exits_cleanly(tmp_path, monkeypatch, check_format, capsys):
    inbox_of(tmp_path, "E1", "E2")

    rc, data = run_parse(tmp_path, monkeypatch, None)

    assert rc == 0 and check_format.check(data) == []
    for rec in data.values():
        assert rec["classification"] == "rfq" and rec["needs_review"] is True
        assert "OPENAI_API_KEY" in rec["review_reason"]
    assert "OPENAI_API_KEY" in capsys.readouterr().err      # said once, loudly, not only per record


FAILURES = {
    "timeout": model.ModelError("timed out after 60s (3 attempts)"),
    "rate-limit": model.ModelError("HTTP 429 after 3 retries"),
    "server-error": model.ModelError("HTTP 503 after 3 retries"),
    "malformed-json": "{ this is not json",
    "schema-invalid": json.dumps({"classification": "rfq"}),
    "unexpected": ValueError("something nobody planned for"),
}


@pytest.mark.parametrize("failure", FAILURES.values(), ids=FAILURES.keys())
def test_every_failure_mode_degrades_to_a_flagged_record_and_the_run_goes_on(
        tmp_path, monkeypatch, check_format, failure):
    inbox_of(tmp_path, "E1", "E2")

    class FailsOnE1(FakeClient):
        def complete(self, messages, schema):
            if "Ref E1" in json.dumps(messages):
                self.calls.append(messages)
                if isinstance(failure, BaseException):
                    raise failure
                return model.Completion(text=failure, input_tokens=10, output_tokens=10)
            return super().complete(messages, schema)

    rc, data = run_parse(tmp_path, monkeypatch, FailsOnE1(answer("purchase_order")))

    assert rc == 0 and check_format.check(data) == []
    bad, good = data["E1"], data["E2"]
    assert bad["classification"] == "rfq" and bad["needs_review"] is True   # never a silent loss
    assert bad["review_reason"] and "model" in bad["review_reason"].lower()
    assert good["classification"] == "purchase_order" and good["needs_review"] is False
    # A failure is not remembered: only the good email was cached, so the next run retries E1.
    assert len(list((tmp_path / "cache").glob("*.json"))) == 1


def test_an_action_email_with_no_lines_and_no_flag_is_flagged_by_code(tmp_path, monkeypatch):
    """The model may say 'rfq, nothing found, no review needed'. That is the silent
    loss the graders count first, so code does not let it through."""
    inbox_of(tmp_path, "E1")

    _, data = run_parse(tmp_path, monkeypatch, FakeClient(answer("rfq", lines=[])))

    assert data["E1"]["classification"] == "rfq"
    assert data["E1"]["needs_review"] is True and data["E1"]["review_reason"]


def test_a_no_action_email_is_not_flagged(tmp_path, monkeypatch):
    inbox_of(tmp_path, "E1")
    _, data = run_parse(tmp_path, monkeypatch, FakeClient(answer("auto_reply")))
    assert data["E1"] == {"classification": "auto_reply", "revises": None, "duplicate_of": None,
                          "needs_review": False, "review_reason": None, "line_items": []}


def test_cost_report_lists_every_email_and_adds_up(tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(model.PRICES, "fake-model", (2.0, 8.0))
    inbox = inbox_of(tmp_path, "E1", "E2")
    (inbox / "empty.eml").write_bytes(b"")                   # never reaches the model

    run_parse(tmp_path, monkeypatch, FakeClient(tokens=(1000, 200)))

    report = json.loads((tmp_path / "cost_report.json").read_text(encoding="utf-8"))   # next to --out
    assert set(report["emails"]) == {"E1", "E2", "empty"}
    assert report["emails"]["empty"]["calls"] == 0
    per_email = pytest.approx(0.002 + 0.0016)
    assert report["emails"]["E1"]["cost_usd"] == per_email
    assert report["totals"]["calls"] == report["totals"]["new_calls"] == 2
    assert report["totals"]["input_tokens"] == 2000 and report["totals"]["output_tokens"] == 400
    assert report["totals"]["cost_usd"] == pytest.approx(2 * (0.002 + 0.0016))
    assert report["model"] == "fake-model" and report["prompt_version"] == model.PROMPT_VERSION
    err = capsys.readouterr().err
    assert "2 model calls" in err and "$" in err             # the stderr summary

    # Replay: same cost per email on record, nothing newly spent.
    run_parse(tmp_path, monkeypatch, None)
    replay = json.loads((tmp_path / "cost_report.json").read_text(encoding="utf-8"))
    assert replay["totals"]["new_calls"] == 0 and replay["totals"]["new_cost_usd"] == 0
    assert replay["totals"]["cost_usd"] == pytest.approx(report["totals"]["cost_usd"])
    assert replay["emails"]["E1"]["input_tokens"] == 1000


def test_the_key_is_never_written_anywhere(tmp_path, monkeypatch, capsys):
    """Run with a real-looking key in the environment and a transport that fails with
    an error that echoes the request; then search every file and stream for the key."""
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    inbox_of(tmp_path, "E1", "E2")

    def opener(request, timeout=None):
        if b"Ref E1" in request.data:
            raise urllib.error.URLError(f"proxy rejected headers {dict(request.header_items())}")
        return _Response(json.dumps(api_reply()).encode("utf-8"))

    client = model.OpenAIClient(KEY, opener=opener, sleep=lambda s: None, max_retries=1)
    rc, data = run_parse(tmp_path, monkeypatch, client)

    assert rc == 0 and data["E1"]["needs_review"] is True and data["E2"]["needs_review"] is False
    streams = capsys.readouterr()
    assert KEY not in streams.out and KEY not in streams.err
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert KEY.encode() not in path.read_bytes(), f"API key written to {path.name}"


# ================================================================== .env convenience

def test_dotenv_in_the_current_folder_supplies_the_key(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(f"OPENAI_API_KEY={KEY}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RFQINBOX_NO_DOTENV")

    cli.load_env()

    assert isinstance(model.make_client(), model.OpenAIClient)


def test_the_real_environment_wins_over_dotenv(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("RFQINBOX_MODEL=from-dotenv\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RFQINBOX_NO_DOTENV")
    monkeypatch.setenv("RFQINBOX_MODEL", "from-environment")
    monkeypatch.setenv("OPENAI_API_KEY", KEY)

    cli.load_env()

    assert model.make_client().model == "from-environment"


def test_no_dotenv_file_is_fine_and_tests_never_load_one(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RFQINBOX_NO_DOTENV")
    cli.load_env()                                   # no file: nothing happens
    assert model.make_client() is None

    (tmp_path / ".env").write_text(f"OPENAI_API_KEY={KEY}\n", encoding="utf-8")
    monkeypatch.setenv("RFQINBOX_NO_DOTENV", "1")    # what conftest sets for every test
    cli.load_env()
    assert model.make_client() is None
