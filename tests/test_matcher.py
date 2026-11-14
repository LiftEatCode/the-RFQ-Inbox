"""The optional matcher (MATCHER.md): each line becomes one catalog part, a decision that
we do not stock it, or a question for the customer.

Every test uses a small invented catalog with invented SKUs. Nothing here asserts an answer
for a dev line or a row of data/catalog.csv: the tests state the rule, not the data.
"""

from __future__ import annotations

import copy

import pytest

from rfqinbox import cli, matcher


def part(sku, product, size, spec="", material="", ends="", extra="", uom="EA"):
    return {"sku": sku, "description": f"{product} {size} {spec} {material} {ends} {extra}".upper(),
            "category": "test", "product": product, "size": size, "spec": spec,
            "material": material, "ends": ends, "extra": extra, "uom": uom}


CATALOG = matcher.Catalog([
    part("T-001", "weld neck flange", "2", "150#", "A105", "RF"),
    part("T-002", "weld neck flange", "2", "300#", "A105", "RF"),
    part("T-003", "weld neck flange", "2", "150#", "A182 F316L", "RF"),
    part("T-004", "weld neck flange", "2", "150#", "A105", "FF"),
    part("T-010", "pipe", "2", "SCH 40", "A53B ERW", "PE", uom="FT"),
    part("T-011", "pipe", "2", "SCH 80", "A106B SMLS", "BE", uom="FT"),
    part("T-012", "pipe", "2", "SCH 40", "A53 GALV", "TBE", uom="FT"),
    part("T-013", "pipe", "2", "SCH 10S", "A312 TP316L", "PE", uom="FT"),
    part("T-020", "90 elbow", "1", "3000#", "A105", "THD"),
    part("T-021", "90 elbow", "1", "3000#", "A105", "SW"),
    part("T-022", "90 elbow", "4", "SCH 40", "A234 WPB", "BW", "LR"),
    part("T-030", "concentric reducer", "4 x 2", "SCH 40", "A234 WPB", "BW"),
    part("T-040", "ball valve", "1", "600 WOG", "316 SS", "THD", "full port"),
    part("T-041", "ball valve", "1", "600 WOG", "316 SS", "THD", "std port"),
    part("T-050", "stud bolt", "5/8 x 3-1/2", "", "B7/2H"),
    part("T-060", "spiral wound gasket", "3", "150#", "316/GRAPHITE"),
    part("T-070", "gate valve", "1-1/2", "800#", "A105", "SW", "13CR"),
])
SKUS = {"T-001", "T-002", "T-003", "T-004", "T-010", "T-011", "T-012", "T-013", "T-020", "T-021",
        "T-022", "T-030", "T-040", "T-041", "T-050", "T-060", "T-070"}


def match(description):
    return matcher.match_line({"raw": description, "description": description}, CATALOG)


# ---------------------------------------------------------------- matched

def test_one_part_fits_everything_the_customer_stated():
    m = match('2" 300# RF weld neck flange, A105')
    assert (m["match"], m["sku"]) == ("matched", "T-002")


@pytest.mark.parametrize("description", [
    "FLG WN 2 in CL300 RF A105",
    "2 inch 300 lb weldneck flange, raised face, A105",
    'Flange, WN, 2", class 300, RF, ASTM A105',
])
def test_abbreviations_and_word_order_do_not_matter(description):
    assert match(description)["sku"] == "T-002"


@pytest.mark.parametrize("description, sku", [
    ("4 x 2 concentric reducer", "T-030"),             # only one such part: nothing to ask
    ('3" spiral wound gasket, 150#', "T-060"),
    ('1-1/2" gate valve 800# socket weld', "T-070"),
])
def test_an_unstated_attribute_that_every_candidate_shares_is_not_a_question(description, sku):
    m = match(description)
    assert (m["match"], m["sku"]) == ("matched", sku)


@pytest.mark.parametrize("description, sku", [
    ('2" 150# RF weld neck flange, carbon steel', "T-001"),
    ('2" 150# RF weld neck flange, 316 stainless', "T-003"),
    ('2" SCH 40 galvanized pipe, threaded both ends', "T-012"),
    ('2" SCH 80 seamless pipe, bevelled ends', "T-011"),
])
def test_a_material_family_matches_the_stocked_grade_in_that_family(description, sku):
    assert match(description)["sku"] == sku


@pytest.mark.parametrize("description, sku", [
    ('2" STD wall A53B ERW pipe, plain end', "T-010"),      # STD = SCH 40 in this size
    ('2" SCH 10 316L pipe, PE', "T-013"),                   # stainless SCH 10 = SCH 10S
])
def test_equivalent_wall_names_are_the_same_spec(description, sku):
    assert match(description)["sku"] == sku


def test_a_pressure_rating_is_not_read_as_the_size():
    assert match('ball valve 1" 600 WOG 316 SS threaded, full port')["sku"] == "T-040"


# ---------------------------------------------------------------- not in catalog

@pytest.mark.parametrize("description, said", [
    ('2" 600# RF weld neck flange, A105', "600#"),                 # rating
    ('2" SCH 160 A106B seamless pipe, BE', "SCH 160"),             # schedule
    ('2" 300# RF weld neck flange, 316L', "316"),                  # material
    ('3" 300# RF weld neck flange, A105', '3'),                    # size
    ('1" 3000# A105 90 elbow, butt weld', "BW"),                   # ends
    ('2" 300# RTJ weld neck flange, A105', "RTJ"),                 # facing
])
def test_one_attribute_off_is_not_in_catalog_and_the_reason_says_which(description, said):
    m = match(description)
    assert m["match"] == "not_in_catalog"
    assert m["sku"] is None
    assert said.lower() in m["match_reason"].lower()


@pytest.mark.parametrize("description", [
    '2" pressure gauge, 0-100 psi, bottom mount',
    "safety glasses, clear lens",
    '2" 150# expansion joint, rubber',
])
def test_a_product_we_do_not_sell_is_not_in_catalog(description):
    m = match(description)
    assert (m["match"], m["sku"]) == ("not_in_catalog", None)


def test_the_nearest_part_is_never_offered_as_the_match():
    for description in ('2" 600# RF weld neck flange, A105', '1" 6000# 90 elbow A105 threaded'):
        assert match(description)["sku"] is None


# ---------------------------------------------------------------- ambiguous

@pytest.mark.parametrize("description, candidates", [
    ('1" 3000# 90 elbow, A105', {"T-020", "T-021"}),                      # ends not given
    ('2" 150# weld neck flange, A105', {"T-001", "T-004"}),               # facing not given
    ('2" 150# RF weld neck flange', {"T-001", "T-003"}),                  # material not given
    ('1" ball valve 600 WOG 316 SS threaded', {"T-040", "T-041"}),        # port not given
])
def test_a_missing_attribute_that_changes_the_part_is_a_question(description, candidates):
    m = match(description)
    assert (m["match"], m["sku"]) == ("ambiguous", None)
    assert set(m["candidates"]) == candidates


def test_a_description_with_nothing_to_go_on_is_never_matched():
    for description in ("", "as per attached", "same as last time", "item 4"):
        assert match(description)["sku"] is None


# ---------------------------------------------------------------- normalising

@pytest.mark.parametrize("text", ['1 1/2"', '1.5"', "1-1/2 in", "1½\"", "1-1/2 inch", "1 1/2”"])
def test_one_size_however_it_is_written(text):
    assert matcher.read_attrs(f"{text} gate valve 800#")["size"] == "1-1/2"


@pytest.mark.parametrize("text", ['4" x 2"', "4x2", '2" x 4"', "4 X 2 in", '4" by 2"'])
def test_reducing_sizes_are_ordered_large_by_small(text):
    assert matcher.read_attrs(f"{text} concentric reducer SCH 40")["size"] == "4 x 2"


def test_bolting_is_diameter_by_length():
    assert matcher.read_attrs('stud bolt 5/8" x 3 1/2" B7 with 2H nuts')["size"] == "5/8 x 3-1/2"
    assert match('5/8" x 3-1/2" stud bolt, B7 w/ 2H nuts')["sku"] == "T-050"
    assert match('5/8" x 4" stud bolt, B7 w/ 2H nuts')["match"] == "not_in_catalog"


@pytest.mark.parametrize("text, spec", [
    ("SCH40", "SCH 40"), ("sch. 80", "SCH 80"), ("S/40", "SCH 40"), ("schedule 160", "SCH 160"),
    ("CL150", "150#"), ("150 lb", "150#"), ("class 300", "300#"), ("3000 PSI", "3000#"),
    ("600 WOG", "600 WOG"),
])
def test_one_spec_however_it_is_written(text, spec):
    assert matcher.read_attrs(f'2" tee {text}')["spec"] == spec


# ---------------------------------------------------------------- output contract

ALL_KINDS = ['2" 300# RF weld neck flange, A105', '2" 600# RF weld neck flange, A105',
             '1" 3000# 90 elbow, A105', "", '2" pressure gauge']


def test_every_answer_has_the_readme_shape(check_format):
    lines = []
    for d in ALL_KINDS:
        ln = {"raw": d or "x", "description": d or "x", "qty": 1, "uom": "EA", "source": "body"}
        ln.update(matcher.match_line(ln, CATALOG))
        lines.append(ln)
    record = {"classification": "rfq", "revises": None, "duplicate_of": None,
              "needs_review": False, "review_reason": None, "line_items": lines}
    assert check_format.check({"A1": record}) == []


def test_a_sku_can_only_come_from_the_catalog():
    for d in ALL_KINDS:
        m = match(d)
        assert m["sku"] is None or m["sku"] in SKUS
        assert set(m.get("candidates") or []) <= SKUS
        assert (m["sku"] is not None) == (m["match"] == "matched")


def test_the_reason_is_one_short_line_a_rep_can_check():
    for d in ALL_KINDS:
        reason = match(d)["match_reason"]
        assert reason and "\n" not in reason and len(reason) <= 140


def test_a_long_candidate_list_is_capped():
    many = matcher.Catalog([part(f"T-9{i:02d}", "tee", "2", "150#", f"GRADE{i}", "THD")
                            for i in range(30)])
    m = matcher.match_line({"raw": '2" tee', "description": '2" tee 150# threaded'}, many)
    assert m["match"] == "ambiguous" and 0 < len(m["candidates"]) <= 10


# ---------------------------------------------------------------- wiring: only ever adds

def results():
    ln = lambda d: {"raw": d, "description": d, "qty": 2, "uom": "EA", "source": "body"}
    rec = lambda cls, lines: {"classification": cls, "revises": None, "duplicate_of": None,
                              "needs_review": False, "review_reason": None, "line_items": lines}
    return {
        "A1": rec("rfq", [ln('2" 300# RF weld neck flange, A105'), ln('2" pressure gauge')]),
        "A2": rec("vendor_quote", []),
        "A3": rec("po", [ln('1" 3000# 90 elbow, A105')]),
    }


EXTRACTED = ("raw", "description", "qty", "uom", "source")


def test_matching_adds_fields_and_changes_nothing_else():
    before = results()
    after = matcher.add_matches(copy.deepcopy(before), CATALOG)
    assert set(after) == set(before)
    for eid, rec in before.items():
        assert {k: v for k, v in after[eid].items() if k != "line_items"} == \
               {k: v for k, v in rec.items() if k != "line_items"}
        assert len(after[eid]["line_items"]) == len(rec["line_items"])
        for old, new in zip(rec["line_items"], after[eid]["line_items"]):
            assert {k: new[k] for k in EXTRACTED} == {k: old[k] for k in EXTRACTED}
            assert new["match"] in ("matched", "not_in_catalog", "ambiguous")
    assert after["A1"]["line_items"][0]["sku"] == "T-002"


def test_a_line_the_matcher_chokes_on_is_left_without_a_match(monkeypatch, check_format):
    real = matcher.match_line

    def flaky(line, catalog):
        if "gauge" in line["description"]:
            raise RuntimeError("boom")
        return real(line, catalog)

    monkeypatch.setattr(matcher, "match_line", flaky)
    after = matcher.add_matches(results(), CATALOG)
    broken, fine = after["A1"]["line_items"][1], after["A1"]["line_items"][0]
    assert "match" not in broken and "sku" not in broken
    assert fine["sku"] == "T-002"
    assert check_format.check(after) == []


def test_no_catalog_file_means_no_match_fields_and_no_crash(tmp_path):
    before = results()
    after = cli.match_inbox(copy.deepcopy(before), tmp_path / "nothing-here.csv")
    assert after == before


def test_the_catalog_is_read_from_a_csv_with_the_readme_columns(tmp_path):
    path = tmp_path / "catalog.csv"
    path.write_text(
        "sku,description,category,product,size,spec,material,ends,extra,uom\n"
        'T-500,"FLG WN 2"" 300# A105 RF",flange,weld neck flange,2,300#,A105,RF,,EA\n',
        encoding="utf-8")
    after = cli.match_inbox(results(), path)
    assert after["A1"]["line_items"][0]["sku"] == "T-500"


def test_the_shipped_catalog_loads_and_every_part_matches_its_own_fields():
    """A self-consistency check on the catalog we ship, not on any email: a request written
    with a part's own structured fields must come back as that part."""
    cat = matcher.Catalog.load(matcher.default_catalog_path())
    assert len(cat.rows) > 500
    wrong = []
    for r in cat.rows:
        d = " ".join(x for x in (r["size"] + '"' if r["size"] else "", r["spec"], r["product"],
                                 r["material"], r["ends"], r["extra"]) if x)
        m = matcher.match_line({"raw": d, "description": d}, cat)
        if m["sku"] != r["sku"]:
            wrong.append((r["sku"], d, m["match"], m["match_reason"]))
    assert not wrong, wrong[:10]
