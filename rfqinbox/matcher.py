"""The optional matcher (MATCHER.md): line -> catalog part, "not in catalog", or "ambiguous".

No model. A line's description is read into the catalog's own attributes (product, size,
spec, material, ends, extra); the catalog is filtered by every attribute the customer
*stated*; exactly one part left is a match, none is "not in catalog", several is a question
for the customer. The nearest part is never offered: a wrong part is a wrong quote.

The same reader is used on the customer's text and on the catalog's own fields, so both
sides are compared in one vocabulary.
"""

from __future__ import annotations

import csv
import os
import re
from fractions import Fraction
from pathlib import Path

MAX_CANDIDATES = 10
MAX_REASON = 140


def default_catalog_path() -> Path:
    env = os.environ.get("RFQINBOX_CATALOG")
    return Path(env) if env else Path(__file__).resolve().parents[1] / "data" / "catalog.csv"


# --------------------------------------------------------------------------- text clean-up

_UNICODE_FRACTIONS = {"½": "1/2", "¼": "1/4", "¾": "3/4", "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8"}


def _clean(text: str) -> str:
    t = text or ""
    for ch in "”“″〃":
        t = t.replace(ch, '"')
    t = t.replace("''", '"').replace("’", "'").replace("′", "'").replace("×", "x")
    for ch, frac in _UNICODE_FRACTIONS.items():
        t = re.sub(r"(\d)\s*" + ch, r"\1 " + frac, t).replace(ch, frac)
    # glued flange codes: WNRF, RFWN, SORF, RFSO
    t = re.sub(r"\b(WN|SO|BL)(RF|FF|RTJ)\b", r"\1 \2", t, flags=re.I)
    t = re.sub(r"\b(RF|FF)(WN|SO)\b", r"\1 \2", t, flags=re.I)
    return t


def _take(pattern: str, text: str, flags=re.I) -> tuple[list[re.Match], str]:
    """All matches of pattern, and the text with them blanked out."""
    found = list(re.finditer(pattern, text, flags))
    return found, re.sub(pattern, " ", text, flags=flags)


# --------------------------------------------------------------------------- extras

_EXTRAS = [
    ("LOCKING", r"\block(?:ing|able)?\b"),
    ("FULL PORT", r"\bfull[\s-]*(?:port|bore)\b"),
    ("STD PORT", r"\b(?:std\.?|standard|regular)[\s-]*port\b|\breduced[\s-]*(?:port|bore)\b"),
    ("LR", r"\bLR\b|\blong[\s-]*rad\w*"),
    ("SR", r"\bSR\b|\bshort[\s-]*rad\w*"),
    ("13CR", r"\b13\s*%?\s*CR\b|\btrim\s*(?:#|no\.?)?\s*8\b"),
    ("WAFER", r"\bwafer\b"),
    ("LUG", r"\blug(?:ged)?\b"),
    ("INNER RING", r"\binner\s*ring\b|\bw/?\s*IR\b"),
]
_LENGTH = r"\b(\d+(?:\.\d+)?)\s*(?:ft\b\.?|feet\b|foot\b|')"


def _extras(text: str) -> tuple[set[str], str | None, str]:
    tags = set()
    for tag, pat in _EXTRAS:
        found, text = _take(pat, text)
        if found:
            tags.add(tag)
    found, text = _take(_LENGTH, text)
    length = f"{found[0].group(1)} FT" if found else None
    return tags, length, text


# --------------------------------------------------------------------------- spec

def _spec(text: str) -> tuple[str | None, str | None, str]:
    """(schedule, rating, rest). Schedules and pressure ratings are different kinds of spec:
    a flange has a class and may also name a bore schedule the catalog does not record."""
    schedule = rating = None

    found, text = _take(r"\b(?:sch(?:edule)?\.?|s/)\s*-?\s*(\d{1,3})\s*(s)?\b", text)
    if found:
        schedule = f"SCH {int(found[0].group(1))}" + ("S" if found[0].group(2) else "")
    found, text = _take(r"\b(5|10|40|80)S\b", text, flags=0)
    if found and not schedule:
        schedule = f"SCH {found[0].group(1)}S"
    found, text = _take(r"\b(?:sch(?:edule)?\.?\s*)?(XXS|XXH|XS|XH|STD)\b|\bextra[\s-]*(?:heavy|strong)\b"
                        r"|\bstandard\s*(?:wall|weight|wt|bore)\b", text)
    if found and not schedule:
        word = (found[0].group(1) or found[0].group(0)).upper()
        schedule = "XXS" if word.startswith("XX") else "SCH 80" if word[0] in "XE" else "SCH 40"

    found, text = _take(r"\b(\d{2,5})\s*WOG\b", text)
    if found:
        rating = f"{int(found[0].group(1))} WOG"
    found, text = _take(r"\b(\d{1,2})\s*GA(?:UGE)?\b", text)
    if found and not rating:
        rating = f"{int(found[0].group(1))} GA"
    pats = [r"(?<![\d/])(\d{3,5})\s*#", r"#\s*(\d{3,5})\b", r"\b(\d{3,5})\s*(?:lbs?\b\.?|pound\w*|psi\w*)",
            r"\b(?:cl(?:ass)?\.?)\s*(\d{3,5})\b", r"\b(\d{3,5})\s*class\b"]
    for pat in pats:
        found, text = _take(pat, text)
        if found and not rating:
            rating = f"{int(found[0].group(1))}#"
    return schedule, rating, text


def _same_wall(a: str, b: str) -> bool:
    """SCH 10 and SCH 10S are the same wall in the stocked sizes."""
    return a.rstrip("S") == b.rstrip("S")


# --------------------------------------------------------------------------- material

_MATERIALS = [
    ("A53B", r"\bA-?\s?53[\s-]*(?:GR(?:ADE)?\.?\s*)?B\b"),
    ("A53", r"\bA-?\s?53(?:[\s-]*(?:GR(?:ADE)?\.?\s*)?B)?\b"),
    ("A106", r"\bA-?\s?106(?:[\s-]*(?:GR(?:ADE)?\.?\s*)?B)?\b"),
    ("A105", r"\bA-?\s?105N?\b"),
    ("A234", r"\bA-?\s?234\b|\bWPB\b"),
    ("WCB", r"\bWCB\b|\bA-?\s?216\b|\bcast\s*steel\b"),
    ("CI", r"\bcast\s*iron\b|\bC\.?I\.?\b|\bA-?\s?126\b"),
    ("DUCTILE", r"\bductile(?:\s*iron)?\b|\bD\.?I\.?\b"),
    # the ASTM number says which product form a stainless grade comes in; "F316L" implies it
    ("A182", r"\bA-?\s?182\b|\bF(?=3\d\dL?\b)"),
    ("A403", r"\bA-?\s?403\b|\bWP(?=3\d\dL?\b)"),
    ("A312", r"\bA-?\s?312\b|\bTP(?=3\d\dL?\b)"),
    ("316L", r"(?<![\d.])316L(?!\d)"),
    ("316", r"(?<![\d.])316(?!\d)"),
    ("304L", r"(?<![\d.])304L(?!\d)"),
    ("304", r"(?<![\d.])304(?!\d)"),
    ("SS", r"\bstainless(?:\s*steel)?\b|\bS\.?S\.?T?\b"),
    ("CS", r"\bcarbon(?:\s*steel)?\b|\bC\.?S\.?\b|\bCSTL\b"),
    ("SMLS", r"\bSMLS\b|\bseamless\b"),
    ("ERW", r"\bERW\b"),
    ("PRE-GALV", r"\bpre[\s-]*galv\w*"),
    ("GALV", r"\bgalv\w*|\bHDG\b|\bhot[\s-]*dip\w*"),
    ("BLACK", r"\bblack\b|\bBLK\b"),
    ("MI", r"\bmalleable(?:\s*iron)?\b|\bM\.?I\.?\b"),
    ("BRONZE", r"\bbronze\b|\bBRZ\b"),
    ("BRASS", r"\bbrass\b"),
    ("GRAPHITE", r"\bgraphite\b|\bgrafoil\b|\bFG\b"),
    ("B7M", r"\bB7M\b"),
    ("B7", r"\bB7\b"),
    ("B8M", r"\bB8M\b"),
    ("B8", r"\bB8\b"),
    ("8M", r"\b8M\b"),
    ("2H", r"\b2H\b"),
    ("GR5", r"\bGR(?:ADE)?\.?\s*5\b"),
    ("GR8", r"\bGR(?:ADE)?\.?\s*8\b"),
    ("GR2", r"\bGR(?:ADE)?\.?\s*2\b"),
    ("ZINC", r"\bzinc(?:[\s-]*plated)?\b|\bZP\b"),
    # materials nothing in a carbon / stainless / iron / brass catalog is made of
    ("LTCS", r"\bA-?\s?333\b|\bA-?\s?350\b|\bLF2\b|\bWPL6\b|\blow[\s-]*temp\w*"),
    ("CHROME", r"\bchrome(?:[\s-]*moly)?\b|\b(?:P|F|WP)(?:5|9|11|22|91)\b"),
    ("DUPLEX", r"\b(?:super\s*)?duplex\b|\b2205\b|\b2507\b"),
    ("NICKEL", r"\bmonel\b|\binconel\b|\bhastelloy\b|\balloy\s*\d+\b|\btitanium\b"),
    ("321", r"(?<![\d/.])(?:321|347|317L?|310)(?![\d/])"),
    ("PLASTIC", r"\bC?PVC\b|\bHDPE\b|\bFRP\b|\bPVDF\b|\bpolyprop\w*|\bplastic\b"),
    ("COPPER", r"\bcopper\b|\bcu[\s-]*ni\b"),
    ("ALUMINUM", r"\balumin\w*"),
    ("RUBBER", r"\brubber\b|\bEPDM\b|\bviton\b|\bneoprene\b|\bbuna\b|\bnitrile\b"),
    ("NON-METAL", r"\bnon[\s-]*asbestos\b|\bfib(?:er|re)\b|\bgarlock\b"),
]
_IMPLIES = {"A105": ["CS"], "A234": ["CS"], "A106": ["CS"], "A53": ["CS"], "A53B": ["A53", "CS"],
            "WCB": ["CS"], "316": ["SS"], "304": ["SS"], "316L": ["316", "SS"], "304L": ["304", "SS"], "B8M": ["SS"], "PRE-GALV": ["GALV"]}
# ASTM numbers that only say which product form a grade comes in
_FORM_SPECS = r"\bA-?\s?(?:193|194|307|197|153|36)\b|\bASTM\b|\bASME\b|\bB16\.\d+\b|\bAPI\s*\d*[A-Z]?\b"


def _materials(text: str) -> tuple[set[str], list[str], str]:
    """(tags with what they imply, tags as stated, rest)."""
    stated = []
    for tag, pat in _MATERIALS:
        found, text = _take(pat, text)
        if found:
            stated.append(tag)
    _, text = _take(_FORM_SPECS, text)
    tags = set(stated)
    for tag in stated:
        tags.update(_IMPLIES.get(tag, []))
    if tags & {"A53", "A106"} and "GALV" not in tags:
        tags.add("BLACK")           # carbon pipe that is not galvanised is "black" pipe
    return tags, stated, text


# --------------------------------------------------------------------------- ends

_FACES = {"RF", "FF", "RTJ"}
_ENDS = [  # (label, catalog values it can mean, pattern, case-sensitive)
    ("TBE", {"TBE"}, r"\bTBE\b|\bthr?(?:ea)?d(?:ed)?\.?\s*both\s*ends\b", False),
    ("TOE", {"TOE"}, r"\bTOE\b|\bthr?(?:ea)?d(?:ed)?\.?\s*one\s*end\b", False),
    ("T&C", {"T&C"}, r"\bT\s*&\s*C\b|\bthr?(?:ea)?d(?:ed)?\.?\s*(?:and|&)\s*c(?:ou)?pl\w*", False),
    ("RF", {"RF"}, r"\bRF\b|\braised[\s-]*face\b", False),
    ("FF", {"FF"}, r"\bFF\b|\bflat[\s-]*face\b|\bfull[\s-]*face\b", False),
    ("RTJ", {"RTJ"}, r"\bRTJ\b|\bring[\s-]*(?:type[\s-]*)?joint\b", False),
    ("flanged", set(_FACES), r"\bfl(?:an)?gd\b|\bflanged\b", False),
    ("SW", {"SW"}, r"\bSW\b|\bsocket[\s-]*weld(?:ed|ing)?\b", False),
    ("BW", {"BW", "BE"}, r"\bBW\b|\bbutt[\s-]*weld(?:ed|ing)?\b", False),
    ("BE", {"BE", "BW"}, r"\bBE\b|\bBBE\b", True),
    ("BE", {"BE", "BW"}, r"\bbevel+(?:ed)?(?:\s*(?:both\s*)?ends?)?\b|\bbev\b\.?", False),
    ("PE", {"PE"}, r"\bPE\b|\bPBE\b", True),
    ("PE", {"PE"}, r"\bplain[\s-]*ends?\b", False),
    # ways of joining that nothing in the catalog has: stating one rules every part out
    ("MJ", {"MJ"}, r"\bMJ\b|\bmech(?:anical)?\.?[\s-]*joint\b", False),
    ("grooved", {"GROOVED"}, r"\bgrooved?\b|\bvictaulic\b|\bvic\b", False),
    ("push-on", {"PUSH"}, r"\bpush[\s-]*(?:on|fit|to[\s-]*connect)\b|\bcompression\b|\bflared?\b", False),
    ("solder", {"SOLDER"}, r"\bsolder(?:ed)?\b|\bsweat\b|\bbrazed?\b|\bpress[\s-]*fit\b", False),
    ("sanitary", {"SANITARY"}, r"\btri[\s-]*clamp\b|\bsanitary\b", False),
    ("THD", {"THD", "TBE", "TOE", "T&C"},
     r"\bthr?d\b\.?|\bthreaded\b|\bF?M?NPT\b|\bscrewed\b|\bscr'?d\b|\b[FM]PT\b|\b[FM]IP\b", False),
]


def _ends(text: str) -> tuple[set[str], list[str], str]:
    allowed, labels = set(), []
    for label, values, pat, cased in _ENDS:
        found, text = _take(pat, text, flags=0 if cased else re.I)
        if found:
            allowed |= values
            if label not in labels:
                labels.append(label)
    return allowed, labels, text


# --------------------------------------------------------------------------- product

_ALL_FLANGES = ("weld neck flange", "slip-on flange", "blind flange")
_NOT_STOCKED = (r"\w*olets?\b|\bcross(?:es)?\b|\blaterals?\b|\bswages?\b|\bstub[\s-]*ends?\b|\bexpansion\b"
                r"|\bgau?ges?\b|\bhoses?\b|\btub(?:e|ing)\b|\bconduit\b|\bu[\s-]*bolts?\b|\binsulation\b"
                r"|\bregulators?\b|\btraps?\b|\bactuators?\b|\btransmitters?\b|\bthermo\w+|\bsight\b"
                r"|\bspectacle\b|\bspacers?\b|\borifice\b|\breturns?\b|\bbends?\b|\bgrooved\b|\bwashers?\b")
_PRODUCTS = [  # first rule that fires wins; () = recognised, and we do not stock it
    (r"\bclevis\b", ("clevis hanger",)),
    (_NOT_STOCKED, ()),
    (r"\bspiral[\s-]*w(?:ou)?nd\b|\bSPW\b|\bSWG\b", ("spiral wound gasket",)),
    (r"\bgaskets?\b|\bgskts?\b", ()),
    (r"\bstuds?\b", ("stud bolt",)),
    (r"\b(?:spring|channel|strut)\s*nuts?\b", ("channel spring nut",)),
    (r"\b(?:heavy|hvy)\s*hex(?:\s*nuts?)?\b|\bHH\s*nuts?\b", ("heavy hex nut",)),
    (r"\bhex\s*nuts?\b", ("hex nut",)),
    (r"\bcap\s*screws?\b|\bHCS\b|\bhex(?:\s*head)?\s*bolts?\b", ("hex cap screw",)),
    (r"\bthreaded\s*rod\b|\ball[\s-]*thread\b|\bATR\b", ("threaded rod",)),
    (r"\bnuts?\b", ("hex nut", "heavy hex nut")),
    (r"\b(?:uni)?strut\b", ("strut channel",)),
    (r"\bclamps?\b", ("pipe clamp",)),
    (r"\bdope\b|\bthread\s*seal(?:ant|er)\b|\bpipe\s*compound\b", ("pipe thread dope",)),
    (r"\b(?:ptfe|teflon|thread(?:\s*seal)?)\s*tape\b", ("ptfe thread tape",)),
    (r"\b(?:y|wye)[\s-]*strainers?\b|\bstrainers?\b", ("y-strainer",)),
    (r"\bbutterfly\b|\bBFLY\b|\bBFV\b", ("butterfly valve",)),
    (r"\bswing\b", ("swing check valve",)),
    (r"\bcheck\b|\bCHK\b", ("check valve", "swing check valve")),
    (r"\bball\b", ("ball valve",)),
    (r"\bgate\b", ("gate valve",)),
    (r"\bglobe\b", ("globe valve",)),
    (r"\bvalves?\b|\bVLVS?\b", ()),
    (r"\bweld[\s-]*neck\b|\bweldneck\b|\bW\.?N\.?\b", ("weld neck flange",)),
    (r"\bslip[\s-]*ons?\b|\bslipon\b", ("slip-on flange",)),
    (r"\bblinds?\b|\bBLD\b", ("blind flange",)),
    (r"\bnipples?\b|\bNIP\b", ("nipple",)),
    (r"\bbush(?:ing)?s?\b", ("hex bushing",)),
    (r"\bhalf[\s-]*c(?:ou)?pl\w*", ("half coupling",)),
    (r"\bcouplings?\b|\bCPLGS?\b", ("coupling",)),
    (r"\bunions?\b", ("union",)),
    (r"\bstreet\b|\bST\.?\s*ELL?S?\b", ("street elbow",)),
    (r"\bell?s?\b|\belbows?\b", ("90 elbow", "45 elbow")),
    (r"\btees?\b", ("tee",)),
    (r"\becc\w*", ("eccentric reducer",)),
    (r"\bconc\w*", ("concentric reducer",)),
    (r"\bred(?:ucers?)?\b\.?", ("concentric reducer", "eccentric reducer")),
    (r"\bcaps?\b", ("cap",)),
    (r"\bplugs?\b", ("plug",)),
    (r"\bpipes?\b", ("pipe",)),
]
_FLANGE = r"\bfl(?:an)?ges?\b|\bFLGS?\b"
_OTHER_FLANGE = r"\blap[\s-]*joint\b|\bLJ\b|\bthr?(?:ea)?d(?:ed)?\b|\bNPT\b|\bsocket\b|\bSW\b|\breducing\b|\bcompanion\b"
_ANGLE = r"\b(90|45)\b(?!\s*(?:\"|#|/))\s*(?:°|deg\w*\.?)?"


def _product(text: str, full: str) -> tuple[tuple[str, ...], str]:
    """(stocked products this could be, rest). An empty tuple: nothing we stock."""
    if re.search(_FLANGE, text, re.I) and not re.search(r"\bgaskets?\b|\bgskts?\b|\bstuds?\b", text, re.I):
        _, rest = _take(_FLANGE, text)
        for pat, product in ((r"\bS\.?O\.?\b", "slip-on flange"), (r"\bBL\b", "blind flange")):
            if re.search(pat, rest):                 # two-letter codes, upper case, beside "flange"
                return (product,), _take(pat, rest, flags=0)[1]
        for pat, products in _PRODUCTS:
            if products and products[0] in _ALL_FLANGES and re.search(pat, rest, re.I):
                return products, _take(pat, rest)[1]
        if re.search(_OTHER_FLANGE + "|" + _NOT_STOCKED, full, re.I):
            return (), rest
        return _ALL_FLANGES, rest
    for pat, products in _PRODUCTS:
        if re.search(pat, text, re.I):
            _, rest = _take(pat, text)
            if "90 elbow" in products:
                angle, rest = _take(_ANGLE, rest)
                if angle:
                    products = (f"{angle[0].group(1)} elbow",)
            return products, rest
    return (), text


# --------------------------------------------------------------------------- size

_NUM = r"(?:\d+[\s-]\d+/\d+|\d+/\d+|\d*\.\d+|\d+)"
_MARK = r"(?:\s*(?:\"|in\b\.?|inch(?:es)?\b))"
_THREAD_PITCH = re.compile(r"(\d+/\d+\"?|\d+\")\s*-\s*\d{1,2}(?:\s*UN[CF])?(?=\s*(?:x|by)\b)", re.I)
_LONG = re.compile(rf"({_NUM}){_MARK}?\s*(?:long\b|lg\b\.?|length\b|OAL\b)", re.I)
_PAIR = re.compile(rf"({_NUM}){_MARK}?\s*(?:x|by)\s*(?:({_NUM}){_MARK}?|(close)\b)", re.I)
_MARKED = re.compile(rf"(?<![\d/.])({_NUM}){_MARK}", re.I)
_BARE = re.compile(rf"(?<![\d/.#-])({_NUM})(?![\d/.#-])")
_DECIMALS = {Fraction(1, 8), Fraction(1, 4), Fraction(3, 8), Fraction(1, 2), Fraction(5, 8),
             Fraction(3, 4), Fraction(7, 8)}
_NOMINAL = {Fraction(n, d) for n, d in [(1, 8), (1, 4), (3, 8), (1, 2), (3, 4), (5, 4), (3, 2), (5, 2), (7, 2),
                                        (5, 8), (7, 8), (9, 8), (13, 8)]} | \
           {Fraction(n) for n in (1, 2, 3, 4, 5, 6, 8, 10, 12, 14, 16, 18, 20, 24, 30, 36)}
_KEEP_ORDER = ("stud bolt", "hex cap screw", "nipple", "ptfe thread tape", "threaded rod")


def _value(num: str) -> Fraction | None:
    num = num.strip()
    try:
        m = re.fullmatch(r"(\d+)[\s-](\d+)/(\d+)", num)
        if m:
            return int(m.group(1)) + Fraction(int(m.group(2)), int(m.group(3)))
        m = re.fullmatch(r"(\d+)/(\d+)", num)
        if m:
            return Fraction(int(m.group(1)), int(m.group(2)))
        return Fraction(num).limit_denominator(64)
    except (ValueError, ZeroDivisionError):
        return None


def _fmt(v: Fraction) -> str:
    whole, frac = divmod(v, 1)
    if not frac:
        return str(whole)
    if frac.denominator not in (2, 4, 8, 16):
        return f"{float(v):g}"
    return f"{whole}-{frac}" if whole else str(frac)


def _size(text: str) -> tuple[tuple[Fraction | str, ...], str]:
    """Size as a tuple of values (one, or two for 'A x B'), and the rest."""
    _, text = _take(r"\b(?:w/|with)\s*\(?\d+\)?(?=\s)|\b\d[\s-]*(?:pc|pcs|piece)s?\b", text)
    text = _THREAD_PITCH.sub(r"\1", text)            # 1/2"-13 x 2": the 13 is the thread, not a size
    long = _LONG.search(text)                         # 3/4" stud, 4-1/2" long
    if long and not _PAIR.search(text):
        rest = text[:long.start()] + " " + text[long.end():]
        (dia, rest2), length = _single(rest), _value(long.group(1))
        if dia and length is not None:
            return (dia[0], length), rest2
    close = re.search(r"\bclose\b", text, re.I)      # a close nipple: the length is "close"
    if close and not _PAIR.search(text):
        dia, rest = _single(text[:close.start()] + " " + text[close.end():])
        if dia:
            return (dia[0], "close"), rest
    m = _PAIR.search(text)
    if m:
        a = _value(m.group(1))
        b = "close" if m.group(3) else _value(m.group(2))
        if a is not None and b is not None:
            return (a, b), text[:m.start()] + " " + text[m.end():]
    return _single(text)


def _single(text: str) -> tuple[tuple, str]:
    m = _MARKED.search(text)
    if m and _value(m.group(1)) is not None:
        return (_value(m.group(1)),), text[:m.start()] + " " + text[m.end():]
    for m in _BARE.finditer(text):
        v = _value(m.group(1))
        if v in _NOMINAL:
            return (v,), text[:m.start()] + " " + text[m.end():]
    return (), text


def _order(size: tuple, products: tuple[str, ...]) -> tuple:
    if len(size) == 2 and "close" not in size and not any(p in _KEEP_ORDER for p in products):
        return tuple(sorted(size, reverse=True))
    return size


def _size_text(size: tuple) -> str | None:
    return " x ".join(s if isinstance(s, str) else _fmt(s) for s in size) or None


# --------------------------------------------------------------------------- reading a line

def _read(text: str) -> dict:
    full = _clean(text)
    extras, length, rest = _extras(full)
    schedule, rating, rest = _spec(rest)
    tags, stated, rest = _materials(rest)
    products, rest = _product(rest, full)
    ends, end_labels, rest = _ends(rest)
    size, rest = _size(rest)
    size = _order(size, products)
    return {"products": products, "size_values": size, "schedule": schedule, "rating": rating,
            "material_tags": tags, "material_stated": stated, "ends_allowed": ends,
            "ends_stated": end_labels, "extras": extras, "length": length}


def read_attrs(text: str) -> dict:
    """What a description states, in the catalog's vocabulary. None = not stated."""
    a = _read(text)
    return {
        "product": " / ".join(a["products"]) or None,
        "size": _size_text(a["size_values"]),
        "spec": a["rating"] or a["schedule"],
        "schedule": a["schedule"], "rating": a["rating"],
        "material": sorted(a["material_stated"]) or None,
        "ends": a["ends_stated"] or None,
        "extra": sorted(a["extras"]) + ([a["length"]] if a["length"] else []) or None,
    }


# --------------------------------------------------------------------------- catalog

class Catalog:
    """Catalog rows, each read once into the same attributes a customer line is read into."""

    def __init__(self, rows: list[dict]):
        self.rows = [dict(r) for r in rows]
        self.by_product: dict[str, list[dict]] = {}
        for r in self.rows:
            r["_size"] = _order(_size(_clean((r.get("size") or "") + ('"' if r.get("size") else "")))[0],
                                (r.get("product") or "",))
            r["_schedule"], r["_rating"], _ = _spec(r.get("spec") or "")
            r["_tags"] = _materials(_clean(r.get("material") or ""))[0]
            r["_extras"], r["_length"], _ = _extras(r.get("extra") or "")
            self.by_product.setdefault((r.get("product") or "").strip().lower(), []).append(r)

    @classmethod
    def load(cls, path: Path) -> "Catalog":
        with Path(path).open(encoding="utf-8-sig", newline="") as f:
            return cls([{k: (v or "").strip() for k, v in row.items() if k} for row in csv.DictReader(f)])


# --------------------------------------------------------------------------- deciding

def _result(match: str, reason: str, sku: str | None = None, candidates: list[str] | None = None) -> dict:
    reason = " ".join(reason.split())
    if len(reason) > MAX_REASON:
        reason = reason[:MAX_REASON - 3].rstrip() + "..."
    return {"sku": sku, "match": match, "match_reason": reason,
            "candidates": sorted(candidates or [])[:MAX_CANDIDATES]}


def _listed(values) -> str:
    values = sorted({v for v in values if v})
    return ", ".join(values[:6]) + (", ..." if len(values) > 6 else "")


def _size_fits(stated: tuple, row: tuple) -> bool:
    if len(stated) == 1 and len(row) == 2:      # diameter only: any length / any reduction
        return stated[0] == row[0]
    return stated == row


def _ends_fit(a: dict, row: dict) -> bool:
    e = (row.get("ends") or "").strip().upper()
    if not e or not a["ends_allowed"]:
        return True
    if "flange" in (row.get("product") or ""):   # a flange's facing; how it is welded on is not recorded
        faces = a["ends_allowed"] & _FACES
        return not faces or e in faces
    return e in a["ends_allowed"]


def match_line(line: dict, catalog: Catalog) -> dict:
    """{"sku", "match", "match_reason", "candidates"} for one extracted line."""
    text = (line.get("description") or line.get("raw") or "").strip()
    a = _read(text)
    if not a["products"]:
        return _result("not_in_catalog", "no stocked product recognised in the description")
    name = " / ".join(a["products"])
    rows = [r for p in a["products"] for r in catalog.by_product.get(p, [])]
    if not rows:
        return _result("not_in_catalog", f"{name}: not a stocked product")

    size = _size_text(a["size_values"])
    if a["size_values"]:
        kept = [r for r in rows if _size_fits(a["size_values"], r["_size"])]
        if not kept:
            return _result("not_in_catalog", f"{name}: asked size {size}, stocked "
                                             f"{_listed(r.get('size') for r in rows)}")
        rows = kept
    elif any(not r["_size"] for r in rows):     # no size asked: the part that has none
        rows = [r for r in rows if not r["_size"]]
    what = f"{name} {size}" if size else name

    steps = [
        # a part sold by schedule is not the pressure-class part, unless the schedule was given too
        (a["rating"], "spec", lambda r: r["_rating"] == a["rating"] if r["_rating"]
            else not r["_schedule"] or bool(a["schedule"])),
        (a["schedule"], "spec", lambda r: not r["_schedule"] or _same_wall(r["_schedule"], a["schedule"])),
        (", ".join(a["material_stated"]), "material",
         lambda r: not r["_tags"] or a["material_tags"] <= r["_tags"] or set(a["material_stated"]) <= r["_tags"]),
        (", ".join(a["ends_stated"]), "ends", lambda r: _ends_fit(a, r)),
        (", ".join(sorted(a["extras"])), "extra", lambda r: a["extras"] <= r["_extras"]),
        (a["length"], "extra", lambda r: not r["_length"] or r["_length"] == a["length"]),
    ]
    for stated, field, fits in steps:
        if not stated:
            continue
        kept = [r for r in rows if fits(r)]
        if not kept:
            return _result("not_in_catalog", f"{what}: asked {stated}, stocked "
                                             f"{_listed(r.get(field) for r in rows) or 'without it'}")
        rows = kept

    # A part that is exactly what was written beats one that is that and something more:
    # "316 SS" is the 316 SS part, not also the A182 F316L one; no handle asked, no handle.
    if a["material_tags"] and any(r["_tags"] == a["material_tags"] for r in rows):
        rows = [r for r in rows if r["_tags"] == a["material_tags"]]
    if any(r["_extras"] == a["extras"] for r in rows):
        rows = [r for r in rows if r["_extras"] == a["extras"]]

    confirmed = any((a["rating"], a["schedule"], a["material_stated"], a["ends_stated"],
                     a["extras"], a["length"]))
    if len(rows) == 1 and not confirmed and any(
            (rows[0].get(f) or "").strip() for f in ("spec", "material", "ends", "extra")):
        # Only a product and a size were read. Being the only one on the shelf does not make
        # it the part they meant: whatever else they wrote was not understood.
        return _result("ambiguous", f"{what}: only product and size read; stocked as "
                                    f"{rows[0].get('description') or rows[0]['sku']} - confirm",
                       candidates=[rows[0]["sku"]])
    if len(rows) == 1:
        return _result("matched", f"{rows[0].get('description') or what}: one part fits", sku=rows[0]["sku"])
    open_fields = [f for f in ("product", "size", "spec", "material", "ends", "extra")
                   if len({(r.get(f) or "").strip() for r in rows}) > 1]
    field = open_fields[0] if open_fields else "part"
    choices = " or ".join(sorted({(r.get(field) or "").strip() or "plain" for r in rows})[:5])
    return _result("ambiguous", f"{what}: {field} not given ({choices})", candidates=[r["sku"] for r in rows])


def add_matches(results: dict[str, dict], catalog: Catalog) -> dict[str, dict]:
    """Add sku / match / match_reason / candidates to every line. Nothing else is touched,
    and a line the matcher fails on is left exactly as it was."""
    for record in results.values():
        for line in record.get("line_items") or []:
            try:
                answer = match_line(line, catalog)
            except Exception:  # noqa: BLE001 — the matcher is optional; never lose a line to it
                for k in ("sku", "match", "match_reason", "candidates"):
                    line.pop(k, None)
                continue
            line.update(answer)
    return results
