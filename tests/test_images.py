"""Large page images are sent in full-resolution bands.

The provider's "high detail" mode first shrinks every image so its shorter side is
768 px. A phone scan of a full page of small table text comes out about 8 px tall
per character, and digits get misread. A band no taller than 768 px is not shrunk
at all, so a tall page is sent as one reduced overview (for layout) plus overlapping
full-resolution bands (for reading).

Geometry only - no model is called. Whether it helps is measured by `rfqinbox score`.
"""

from __future__ import annotations

import base64
import io
import json

from PIL import Image

import fixtures as fx
from rfqinbox import model
from test_model import FakeClient, make_engine


def ruler(width: int, height: int) -> bytes:
    """An image whose every row says which row it is (lossless), so a test can tell
    exactly which rows of the page each band carries."""
    im = Image.new("RGB", (width, height))
    px = im.load()
    for y in range(height):
        for x in range(width):
            px[x, y] = (y % 256, y // 256, 200)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def rows_in(im: Image.Image) -> list[int]:
    px = im.convert("RGB").load()
    return [px[0, y][0] + 256 * px[0, y][1] for y in range(im.height)]


def sent(messages) -> tuple[list[str], list[tuple[Image.Image, str]]]:
    """(text parts, [(decoded image, detail)]) of the user message, in order."""
    texts, images = [], []
    for part in messages[-1]["content"]:
        if part["type"] == "text":
            texts.append(part["text"])
        else:
            data = base64.b64decode(part["image_url"]["url"].split(",", 1)[1])
            images.append((Image.open(io.BytesIO(data)), part["image_url"]["detail"]))
    return texts, images


PAGE = (1280, 1600)          # a phone scan of a letter page, as the reader renders it


def test_an_image_the_provider_will_not_shrink_is_sent_once_untouched():
    for size in [(700, 500), (768, 2000), (2000, 768), (900, 700)]:
        data = fx.picture(*size, "small")
        messages = model.build_messages("EMAIL", [("photo.png", data, "high")])
        url = [p for p in messages[-1]["content"] if p["type"] == "image_url"]
        assert len(url) == 1, size
        assert url[0]["image_url"]["url"].endswith(base64.b64encode(data).decode("ascii")), size


def test_a_full_page_scan_is_sent_as_an_overview_plus_full_resolution_bands():
    messages = model.build_messages("EMAIL", [("scan.pdf (page 1)", ruler(*PAGE), "high")])
    _, images = sent(messages)

    overview, bands = images[0][0], [im for im, _ in images[1:]]
    assert all(detail == "high" for _, detail in images)
    # The overview is the whole page, already at the size the provider would make it.
    assert min(overview.size) <= 768 and abs(overview.width / overview.height - PAGE[0] / PAGE[1]) < 0.01
    # Each band is the page's full width and short enough that nothing is shrunk.
    assert len(bands) >= 2
    assert all(b.width == PAGE[0] and b.height <= 768 for b in bands)


def test_bands_cover_every_row_of_the_page_in_order_and_overlap():
    messages = model.build_messages("EMAIL", [("scan.pdf", ruler(*PAGE), "high")])
    bands = [rows_in(im) for im, _ in sent(messages)[1][1:]]

    assert all(rows == list(range(rows[0], rows[0] + len(rows))) for rows in bands)   # unscaled, contiguous
    assert bands[0][0] == 0 and bands[-1][-1] == PAGE[1] - 1
    assert set().union(*bands) == set(range(PAGE[1]))                                 # no row lost
    for above, below in zip(bands, bands[1:]):
        shared = above[-1] - below[0] + 1
        assert 40 <= shared <= 200       # a text row cut by one band's edge is whole in the next


def test_a_landscape_page_is_banded_too():
    wide, tall = 2000, 1500
    bands = [im for im, _ in sent(model.build_messages("E", [("p.png", ruler(wide, tall), "high")]))[1][1:]]
    assert bands and all(b.width == wide and b.height <= 768 for b in bands)
    assert set().union(*(rows_in(b) for b in bands)) == set(range(tall))


def test_each_part_is_labelled_so_the_model_knows_what_it_is_looking_at():
    messages = model.build_messages("EMAIL", [("scan.pdf (page 2)", ruler(*PAGE), "high")])
    texts, images = sent(messages)
    labels = [t for t in texts if "scan.pdf (page 2)" in t]
    n = len(images) - 1

    assert len(labels) == len(images)                       # one label before each picture
    assert "whole" in labels[0].lower()
    for k, label in enumerate(labels[1:], 1):
        assert f"part {k} of {n}" in label
    # Overlapping bands show some rows twice; the model is told not to list them twice.
    assert "overlap" in " ".join(texts).lower()


def test_logos_and_low_detail_images_are_never_split():
    data = fx.picture(*PAGE, "big but marked low detail")
    messages = model.build_messages("EMAIL", [("logo.png", data, "low")])
    _, images = sent(messages)
    assert len(images) == 1 and images[0][1] == "low"


def test_several_images_keep_their_order_and_their_own_bands():
    messages = model.build_messages("EMAIL", [("a.png", fx.picture(600, 400, "a"), "high"),
                                              ("b.pdf", ruler(*PAGE), "high"),
                                              ("c.png", fx.picture(600, 400, "c"), "high")])
    text = " ".join(sent(messages)[0])
    assert text.index("a.png") < text.index("b.pdf") < text.index("c.png")
    assert text.count("b.pdf") >= 3 and text.count("a.png") == 1 and text.count("c.png") == 1


def test_an_image_that_cannot_be_opened_is_sent_as_it_is(tmp_path):
    """Never crash on a bad picture: let the provider have the bytes the reader produced."""
    messages = model.build_messages("EMAIL", [("odd.png", b"\x89PNG not really a png", "high")])
    assert len([p for p in messages[-1]["content"] if p["type"] == "image_url"]) == 1


def test_how_a_page_is_split_is_part_of_the_cache_key(tmp_path, monkeypatch):
    """An answer read from a shrunk page must not be replayed for the banded page -
    while emails with no large image keep their cached answers."""
    client = FakeClient()
    page, small = ruler(*PAGE), fx.picture(600, 400, "small")
    engine = make_engine(tmp_path, client)[0]
    engine.extract("big", "EMAIL A", [("scan.pdf", page, "high")])
    engine.extract("small", "EMAIL B", [("photo.png", small, "high")])
    assert len(client.calls) == 2

    monkeypatch.setattr(model, "BAND_OVERLAP", model.BAND_OVERLAP + 40)
    engine = make_engine(tmp_path, client)[0]
    engine.extract("small", "EMAIL B", [("photo.png", small, "high")])
    assert len(client.calls) == 2                      # untouched: still cached
    engine.extract("big", "EMAIL A", [("scan.pdf", page, "high")])
    assert len(client.calls) == 3                      # split differently: asked again
    assert json.dumps(client.calls[2]).count("image_url") > 2
