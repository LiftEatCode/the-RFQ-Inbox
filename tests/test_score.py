"""The local scorer: data/README.md's 'What we grade', implemented so every
change can be measured. Tests use small synthetic keys, plus one
self-consistency check on the shipped key.
"""

from __future__ import annotations

import copy
import json

import pytest

from conftest import ROOT
from rfqinbox import score


def key_line(raw, qty=1, uom="EA", source="body", mm=(), mnm=(), tol=0, lid="X-1"):
    return {
        "id": lid, "raw": raw, "qty": qty, "qty_tol": tol, "uom": uom, "source": source,
        "must_mention": list(mm), "must_not_mention": list(mnm),
    }


def key_email(cls="rfq", lines=(), nr=False, revises=None, dup=None):
    return {"classification": cls, "revises": revises, "duplicate_of": dup,
            "needs_review": nr, "line_items": list(lines)}


def pred_line(raw, qty=1, uom="EA", source="body", description=None):
    return {"raw": raw, "description": description or raw, "qty": qty, "uom": uom, "source": source}


def pred_email(cls="rfq", lines=(), nr=False, revises=None, dup=None):
    return {"classification": cls, "revises": revises, "duplicate_of": dup, "needs_review": nr,
            "review_reason": "x" if nr else None, "line_items": list(lines)}


def as_pred(key: dict) -> dict:
    """A 'perfect' prediction built from a key: description = raw + every must_mention option 1."""
    out = {}
    for eid, e in key.items():
        lines = []
        for ln in e["line_items"]:
            desc = " ".join([ln["raw"]] + [m.split("|")[0] for m in ln["must_mention"]])
            lines.append(pred_line(ln["raw"], ln["qty"], ln["uom"], ln["source"], desc))
        out[eid] = pred_email(e["classification"], lines, e["needs_review"], e["revises"], e["duplicate_of"])
    return out


# ---------------------------------------------------------------- headline numbers

def test_perfect_prediction_on_shipped_key_scores_perfect():
    key = json.loads((ROOT / "data/dev/answer_key.json").read_text(encoding="utf-8"))["emails"]
    r = score.score(as_pred(key), key)
    assert r["silent_losses"] == []
    assert r["hallucinated_lines"] == 0
    assert r["lost_requests"] == [] and r["phantom_requests"] == []
    assert r["classification_accuracy"] == 1.0
    assert r["line_recall"] == 1.0 and r["line_precision"] == 1.0
    assert r["qty_accuracy"] == 1.0 and r["uom_accuracy"] == 1.0
    assert r["source_accuracy"] == 1.0 and r["context_accuracy"] == 1.0


def test_action_email_with_no_lines_and_no_flag_is_a_silent_loss():
    key = {"E1": key_email(lines=[key_line("10 ea 2\" ell")])}
    r = score.score({"E1": pred_email(lines=[])}, key)
    assert r["silent_losses"] == ["E1"]


def test_flagging_prevents_a_silent_loss():
    key = {"E1": key_email(lines=[key_line("10 ea 2\" ell")])}
    r = score.score({"E1": pred_email(lines=[], nr=True)}, key)
    assert r["silent_losses"] == []


def test_needs_review_email_returned_unflagged_and_empty_is_a_silent_loss():
    key = {"E1": key_email(nr=True)}
    r = score.score({"E1": pred_email()}, key)
    assert r["silent_losses"] == ["E1"]


def test_missing_email_counts_as_silent_loss():
    key = {"E1": key_email(lines=[key_line("a")])}
    r = score.score({}, key)
    assert r["silent_losses"] == ["E1"]


def test_extra_line_is_hallucinated_and_lowers_precision():
    key = {"E1": key_email(lines=[key_line("10 ea 2\" 90 ell", qty=10)])}
    pred = {"E1": pred_email(lines=[pred_line("10 ea 2\" 90 ell", 10),
                                    pred_line("TOTAL QTY 35", 35)])}
    r = score.score(pred, key)
    assert r["hallucinated_lines"] == 1
    assert r["line_precision"] == 0.5
    assert r["line_recall"] == 1.0


def test_lines_on_a_no_action_email_are_hallucinated():
    key = {"V": key_email("vendor_quote")}
    pred = {"V": pred_email("vendor_quote", lines=[pred_line("50 2\" elbow $11.80", 50)])}
    assert score.score(pred, key)["hallucinated_lines"] == 1


def test_dropped_line_lowers_recall():
    key = {"E1": key_email(lines=[key_line("12 jts 2\" pipe", 12, lid="E1-1"),
                                  key_line("30 2\" coupling", 30, lid="E1-2")])}
    pred = {"E1": pred_email(lines=[pred_line("12 jts 2\" pipe", 12)])}
    r = score.score(pred, key)
    assert r["line_recall"] == 0.5
    assert r["missed_lines"] == ["E1-2"]


def test_lost_and_phantom_requests():
    key = {"R": key_email("rfq", [key_line("a")]),
           "Q": key_email("vendor_quote"),
           "S": key_email("status_inquiry")}
    pred = {"R": pred_email("status_inquiry"),
            "Q": pred_email("rfq", nr=True),
            "S": pred_email("status_inquiry")}
    r = score.score(pred, key)
    assert r["lost_requests"] == ["R"]
    assert r["phantom_requests"] == ["Q"]
    assert r["classification_accuracy"] == pytest.approx(1 / 3)


def test_rfq_vs_revision_is_a_misclassification_but_not_lost():
    key = {"R": key_email("rfq_revision", [key_line("a")], revises="R0")}
    pred = {"R": pred_email("rfq", [pred_line("a")])}
    r = score.score(pred, key)
    assert r["lost_requests"] == []
    assert r["classification_accuracy"] == 0.0


# ---------------------------------------------------------------- pairing

def test_pairing_tolerates_different_cell_separators():
    key = {"E": key_email(lines=[key_line("1 | 12 | EA | 6\" | 90 LR elbow", 12)])}
    pred = {"E": pred_email(lines=[pred_line("12 EA 6\" 90 LR elbow", 12)])}
    assert score.score(pred, key)["line_recall"] == 1.0


def test_pairing_keeps_sizes_apart():
    """Two lines that differ only in size must pair with the right partner."""
    key = {"E": key_email(lines=[key_line("4 EA 1-1/2\" Tee", 4, lid="E-1"),
                                 key_line("9 EA 1/2\" Tee", 9, lid="E-2")])}
    pred = {"E": pred_email(lines=[pred_line("9 EA 1/2\" Tee", 9),
                                   pred_line("4 EA 1-1/2\" Tee", 4)])}
    r = score.score(pred, key)
    assert r["line_recall"] == 1.0
    assert r["qty_accuracy"] == 1.0


def test_unrelated_text_does_not_pair():
    key = {"E": key_email(lines=[key_line("12 jts 2\" SCH 40 pipe", 12)])}
    pred = {"E": pred_email(lines=[pred_line("Spiral wound gasket 304", 12)])}
    r = score.score(pred, key)
    assert r["line_recall"] == 0.0
    assert r["hallucinated_lines"] == 1


# ---------------------------------------------------------------- paired-line fields

def test_qty_tolerance_exact_relative_and_unscored():
    key = {"E": key_email(lines=[
        key_line("aa bb cc", 10, tol=0, lid="E-1"),
        key_line("dd ee ff", 100, tol=0.1, lid="E-2"),
        key_line("gg hh ii", None, tol=None, lid="E-3"),
    ])}
    pred = {"E": pred_email(lines=[
        pred_line("aa bb cc", 11), pred_line("dd ee ff", 108), pred_line("gg hh ii", 999)])}
    r = score.score(pred, key)
    assert r["qty_accuracy"] == pytest.approx(1 / 2)  # 1 wrong, 1 within 10%, 1 unscored


def test_null_qty_must_match_null():
    key = {"E": key_email(lines=[key_line("a couple caps", None, uom=None, tol=0)])}
    pred = {"E": pred_email(lines=[pred_line("a couple caps", 2, None)])}
    assert score.score(pred, key)["qty_accuracy"] == 0.0


def test_uom_null_reads_as_ea():
    key = {"E": key_email(lines=[key_line("aa bb", 1, uom="EA")])}
    pred = {"E": pred_email(lines=[pred_line("aa bb", 1, None)])}
    assert score.score(pred, key)["uom_accuracy"] == 1.0


def test_source_must_match():
    key = {"E": key_email(lines=[key_line("aa bb", source="list.xlsx")])}
    pred = {"E": pred_email(lines=[pred_line("aa bb", source="body")])}
    assert score.score(pred, key)["source_accuracy"] == 0.0


@pytest.mark.parametrize("desc, phrase, ok", [
    ("2\" pipe, Schedule 40, A53B", "sch 40|schedule 40", True),
    ("2\" pipe, SCH40", "sch 40", True),
    ("ell, malleable iron, Class 150", "150#|150 lb|class 150", True),
    ("ell, 150 lb", "150#", True),
    ("90 ell, butt weld", "bw|butt weld", True),
    ("90 ell, BW", "butt weld", True),
    ("coupling, NPT", "threaded", True),
    ("pipe seamless", "smls", True),
    ("nipple galvanized", "galv", True),
    ("90 ELL", "elbow", True),
    ("2\" gate VLV", "valve", True),
    ("ell, malleable iron", "malleable", True),
    ("2\" pipe sch 80", "sch 40", False),
    ("2\" tee", "1/2", False),
])
def test_must_mention_matching(desc, phrase, ok):
    assert score.mentions(desc, phrase) is ok


def test_context_requires_all_must_mention_and_no_must_not():
    key = {"E": key_email(lines=[
        key_line("4) 12 ea - 2\" 90 ell", 12, mm=["malleable", "150#"], mnm=["sch 40"], lid="E-1"),
        key_line("1) 20 jts - 2\"", 20, mm=["pipe", "sch 40"], mnm=["malleable"], lid="E-2"),
    ])}
    pred = {"E": pred_email(lines=[
        pred_line("4) 12 ea - 2\" 90 ell", 12, description="2\" 90 ell, malleable iron, 150 lb"),
        pred_line("1) 20 jts - 2\"", 20, description="2\" pipe, SCH 40, malleable iron fittings"),
    ])}
    r = score.score(pred, key)
    assert r["context_accuracy"] == 0.5
    assert [f["id"] for f in r["context_failures"]] == ["E-2"]


# ---------------------------------------------------------------- links and review

def test_duplicate_and_revision_links():
    key = {"A": key_email("rfq", [key_line("a")]),
           "B": key_email("rfq", dup="A"),
           "C": key_email("rfq_revision", [key_line("a")], revises="A")}
    pred = {"A": pred_email("rfq", [pred_line("a")]),
            "B": pred_email("rfq", dup="A"),
            "C": pred_email("rfq_revision", [pred_line("a")], revises=None)}
    r = score.score(pred, key)
    assert r["link_accuracy"] == 0.5


def test_needs_review_precision_and_recall():
    key = {"A": key_email(nr=True), "B": key_email(nr=True),
           "C": key_email(lines=[key_line("a")]), "D": key_email(lines=[key_line("b")])}
    pred = {"A": pred_email(nr=True), "B": pred_email(lines=[pred_line("zz")]),
            "C": pred_email(nr=True, lines=[pred_line("a")]), "D": pred_email(lines=[pred_line("b")])}
    r = score.score(pred, key)
    assert r["needs_review_recall"] == 0.5
    assert r["needs_review_precision"] == 0.5


# ---------------------------------------------------------------- report + gate

def test_cli_score_prints_report_and_gates_on_silent_losses(tmp_path, capsys):
    from rfqinbox import cli
    key_path = tmp_path / "key.json"
    key_path.write_text(json.dumps({"version": 1, "emails": {
        "E1": key_email(lines=[key_line("10 ea ell", 10)])}}), encoding="utf-8")
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"E1": pred_email(lines=[pred_line("10 ea ell", 10)])}), encoding="utf-8")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"E1": pred_email()}), encoding="utf-8")

    assert cli.main(["score", str(good), "--key", str(key_path), "--gate"]) == 0
    assert "line recall" in capsys.readouterr().out.lower()
    assert cli.main(["score", str(bad), "--key", str(key_path), "--gate"]) != 0


# ---------------------------------------------------------------- the optional matcher

def matched_key(raw, sku=None, match="matched", lid="X-1"):
    ln = key_line(raw, lid=lid)
    ln.update({"sku": sku, "match": match, "candidates": []})
    return ln


def matched_pred(raw, sku=None, match="matched"):
    ln = pred_line(raw)
    ln.update({"sku": sku, "match": match, "match_reason": "because"})
    return ln


RAWS = ["2 in weld neck flange 300 class", "4 in gate valve 150 class", "six inch blind flange",
        "one inch ball valve brass", "3 in pipe schedule 80 seamless"]


def matcher_case(pairs):
    """pairs: [((key sku, key match), (pred sku, pred match) or None)]."""
    k_lines, p_lines = [], []
    for i, (k, p) in enumerate(pairs):
        k_lines.append(matched_key(RAWS[i], k[0], k[1], lid=f"A-{i + 1}"))
        p_lines.append(pred_line(RAWS[i]) if p is None else matched_pred(RAWS[i], p[0], p[1]))
    return score.score({"A": pred_email(lines=p_lines)}, {"A": key_email(lines=k_lines)})


def test_no_matcher_section_when_no_line_carries_a_match():
    r = matcher_case([(("RL-1", "matched"), None)])
    assert r["matcher"] is None
    assert "MATCHER" not in score.format_report(r)


def test_matcher_counts_right_wrong_and_wrong_sku():
    r = matcher_case([
        (("RL-1", "matched"), ("RL-1", "matched")),                 # right
        (("RL-2", "matched"), ("RL-9", "matched")),                 # wrong part quoted
        ((None, "not_in_catalog"), ("RL-3", "matched")),            # quoted something we lack
        ((None, "not_in_catalog"), (None, "not_in_catalog")),       # right
        (("RL-5", "matched"), (None, "ambiguous")),                 # too cautious, not a wrong quote
    ])["matcher"]
    assert r["lines"] == 5
    assert r["correct"] == 2 and r["accuracy"] == pytest.approx(0.4)
    assert r["wrong_sku"] == ["A-2", "A-3"]
    assert r["confusion"]["matched"]["ambiguous"] == 1
    assert r["confusion"]["not_in_catalog"]["matched"] == 1
    assert r["not_in_catalog_precision"] == 1.0
    assert r["not_in_catalog_recall"] == 0.5


def test_a_paired_line_we_did_not_match_counts_against_accuracy_but_is_not_a_wrong_sku():
    r = matcher_case([
        (("RL-1", "matched"), ("RL-1", "matched")),
        (("RL-2", "matched"), None),
    ])["matcher"]
    assert r["lines"] == 2 and r["correct"] == 1
    assert r["wrong_sku"] == []
    assert r["confusion"]["matched"]["none"] == 1


def test_matcher_report_puts_wrong_skus_first():
    r = matcher_case([(("RL-2", "matched"), ("RL-9", "matched"))])
    text = score.format_report(r)
    assert "MATCHER" in text and "wrong sku" in text.lower() and "A-1" in text


def test_matcher_numbers_do_not_change_the_extraction_numbers():
    with_m = matcher_case([(("RL-2", "matched"), ("RL-9", "matched"))])
    without = matcher_case([(("RL-2", "matched"), None)])
    for k in with_m:
        if k != "matcher":
            assert with_m[k] == without[k]
