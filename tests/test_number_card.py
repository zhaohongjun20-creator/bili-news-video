# -*- coding: utf-8 -*-
"""数字对照卡：左右布局，来源和自称在底部；线索包对不上就不画、不造数。"""
from PIL import Image, ImageDraw

from src.cards import ACCENT, BG2, NumberCard, W, H, render_cards
from src.jsonio import load_json, save_json

PAIR = "伊方自称击中4艘，美方称确认2艘。"
MISMATCH = "伊方自称击中4艘，美方称确认90分钟。"
WIKI_PAGE = "https://commons.wikimedia.org/wiki/File:Port_of_London.jpg"
WIKI_TERMS = "https://creativecommons.org/licenses/by/4.0"


def _fact(text: str, source: str = "", role: str = "body") -> dict:
    return {"text": text, "source": source, "role": role}


def _episode(tmp_path, monkeypatch, narration: str, card: dict, summary: str = ""):
    from src import store
    monkeypatch.setattr(store, "ROOT", tmp_path)
    pid = "ep-001"
    pdir = tmp_path / "projects" / pid
    for sub in ("audio", "cards", "output"):
        (pdir / sub).mkdir(parents=True)
    save_json({"pid": pid, "date": "2026-11-21", "stages": {}},
              pdir / "manifest.json")
    save_json({
        "date": "2026-11-21",
        "source": "演示样本",
        "items": [{
            "title": "演示样本·勿发布",
            "summary": summary or narration,
            "sources": [
                {"name": "伊方", "claim": "伊方自称击中4艘。"},
                {"name": "美方", "claim": "美方称确认2艘。"},
            ],
        }],
    }, pdir / "briefing.json")
    save_json({
        "title": "演示样本·勿发布",
        "meta": {"date": "2026-11-21"},
        "segments": [{
            "id": "seg01",
            "kind": "item",
            "narration": narration,
            "card": card,
        }],
    }, pdir / "script.json")
    return pid, pdir


def _painted(fn):
    drawn = []
    original = ImageDraw.ImageDraw.text

    def capture(self, xy, text, *args, **kwargs):
        drawn.append((xy, text))
        return original(self, xy, text, *args, **kwargs)

    ImageDraw.ImageDraw.text = capture
    try:
        fn()
    finally:
        ImageDraw.ImageDraw.text = original
    return drawn


def _at(drawn, text):
    return next(xy for xy, item in drawn if item == text)


def test_layout_is_left_right_with_source_and_self_claim_at_the_bottom():
    spec = NumberCard.pair([_fact(PAIR)])
    assert spec is not None
    assert spec["left"] == {"value": "4", "unit": "艘"}
    assert spec["right"] == {"value": "2", "unit": "艘"}
    assert spec["source"] == "美方"
    assert spec["self_actor"] == "伊方"

    lay = NumberCard.layout(spec)
    assert lay["left"]["x1"] <= 960 <= lay["right"]["x0"]
    assert lay["left"]["y"] == lay["right"]["y"]
    assert lay["source"]["y"] > lay["left"]["y"]
    assert lay["self_claim"]["y"] > lay["source"]["y"]
    assert lay["source"]["y"] > H * 0.75
    assert "来源：美方" == lay["source"]["text"]
    assert lay["self_claim"]["text"].startswith("自称：")
    assert "伊方" in lay["self_claim"]["text"]

    # 口播把两边写反，也按原文顺序左右排，不把大数固定放左边。
    flipped = NumberCard.pair([_fact("美方称确认2艘，伊方自称击中4艘。")])
    assert (flipped["left"]["value"], flipped["right"]["value"]) == ("2", "4")
    assert flipped["source"] == "美方" and flipped["self_actor"] == "伊方"

    dated = NumberCard.pair([_fact("11月20日伊方自称击中4艘，美方称确认2艘。")])
    assert dated["self_actor"] == "伊方"
    assert "日" not in dated["self_actor"]


def test_skips_when_the_clue_package_has_no_matching_pair():
    assert NumberCard.pair([_fact(MISMATCH)]) is None
    assert NumberCard.pair([_fact("伊方自称击中4艘。")]) is None
    assert NumberCard.pair([_fact("伊方称击中4艘，美方称确认2艘。")]) is None
    assert NumberCard.pair([_fact("伊方自称击中4艘，美方自称确认2艘。")]) is None
    assert NumberCard.pair([_fact("伊方自称击中4艘，美方称确认4艘。")]) is None
    assert NumberCard.pair([_fact("击中4艘，美方称确认2艘。")]) is None
    assert NumberCard.pair([_fact(
        "伊方自称击中4艘，美方称确认2艘，另有机构称发现8艘。")]) is None


def test_refuses_to_invent_numbers_or_attributions(tmp_path, monkeypatch):
    spec = NumberCard.pair([_fact(PAIR)])
    blob = f"{spec['left']['value']} {spec['right']['value']} {spec['source']} {spec['self_actor']}"
    assert "999" not in blob and "6" not in blob
    assert "路透" not in blob
    for token in ("4", "2", "艘", "美方", "伊方"):
        assert token in PAIR

    pid, _pdir = _episode(
        tmp_path, monkeypatch,
        narration=PAIR + "另外还有999艘。",
        card={"type": "headline", "headline": PAIR},
        summary=PAIR)
    kept = NumberCard.for_segment(pid, {
        "narration": PAIR + "另外还有999艘。",
        "card": {"type": "headline"},
    })
    assert kept is not None
    assert kept["left"]["value"] == "4" and kept["right"]["value"] == "2"
    assert "999" not in kept["left"]["value"] + kept["right"]["value"]

    spoken_only = NumberCard.for_segment(pid, {
        "narration": "伊方自称击中999艘，美方称确认1艘。",
    })
    assert spoken_only is None

    from src import store
    brief = load_json(store.ROOT / "projects" / pid / "briefing.json")
    brief["excluded_refs"] = [1]
    save_json(brief, store.ROOT / "projects" / pid / "briefing.json")
    assert NumberCard.for_segment(pid, {"narration": PAIR}) is None


def test_text_card_renders_the_comparison_in_product_chrome(tmp_path, monkeypatch):
    pid, pdir = _episode(
        tmp_path, monkeypatch, PAIR,
        {"type": "headline", "headline": PAIR, "full": [PAIR]})

    def run():
        render_cards(pid)

    drawn = _painted(run)
    img = Image.open(pdir / "cards" / "seg01.png")
    assert img.size == (W, H)
    assert img.getpixel((4, 4)) == ACCENT
    assert img.getpixel((960, 500)) == ACCENT
    assert img.getpixel((200, 220)) == BG2
    assert img.getpixel((200, 220)) != (255, 255, 255)

    left, right = _at(drawn, "4"), _at(drawn, "2")
    assert left[1] == right[1] == NumberCard.NUM_Y
    assert left[0] < 960 < right[0]
    source, claim = _at(drawn, "来源：美方"), _at(drawn, "自称：伊方")
    assert source[1] > left[1] and claim[1] > source[1]
    assert source[1] > H * 0.75
    assert "巴尔干快讯" in [text for _, text in drawn]
    joined = "".join(text for _, text in drawn)
    assert "999" not in joined and "6艘" not in joined


def test_unmatched_figures_keep_the_text_card(tmp_path, monkeypatch):
    pid, pdir = _episode(
        tmp_path, monkeypatch, MISMATCH,
        {"type": "headline", "headline": MISMATCH, "full": [MISMATCH]},
        summary=MISMATCH)

    def run():
        render_cards(pid)

    drawn = _painted(run)
    texts = [text for _, text in drawn]
    assert not any(text.startswith("来源：") or text.startswith("自称：") for text in texts)
    assert "4" not in texts and "2" not in texts and "90" not in texts
    joined = "".join(texts)
    assert MISMATCH in joined
    assert "999" not in joined
    img = Image.open(pdir / "cards" / "seg01.png")
    assert img.getpixel((4, 4)) == ACCENT
    assert img.getpixel((960, 500)) != ACCENT


def test_map_still_and_quote_stay_when_a_pair_exists(tmp_path, monkeypatch):
    pair = "伊方自称在塞尔维亚附近击中4艘，美方称确认2艘。"
    pid, pdir = _episode(
        tmp_path, monkeypatch, pair,
        {"type": "map", "headline": "塞尔维亚", "sub": "", "lines": []},
        summary=pair)

    def run_map():
        render_cards(pid)

    drawn = _painted(run_map)
    assert not any(text.startswith("来源：") or text.startswith("自称：")
                   for _, text in drawn)
    img = Image.open(pdir / "cards" / "seg01.png")
    land = 0
    px = img.load()
    for y in range(400, 900, 8):
        for x in range(200, 1000, 8):
            if px[x, y][:3] == (36, 52, 71):
                land += 1
    assert land > 20

    quote = "伊方自称击中4艘，美方称确认2艘。"
    save_json({
        "title": "演示样本·勿发布",
        "meta": {"date": "2026-11-21"},
        "segments": [{
            "id": "seg01", "kind": "item", "narration": quote,
            "card": {"type": "quote", "headline": quote},
        }],
    }, pdir / "script.json")

    def run_quote():
        render_cards(pid)

    quoted = _painted(run_quote)
    qtexts = [text for _, text in quoted]
    assert "单方说法 · 尚待核实" in qtexts
    assert not any(text.startswith("来源：") or text.startswith("自称：") for text in qtexts)

    still_line = "伊方自称在伦敦港口击中4艘，美方称确认2艘。"
    photo = pdir / "london.png"
    Image.new("RGB", (640, 360), (20, 140, 90)).save(photo)
    save_json({"stills": [{
        "segment_id": "seg01",
        "path": str(photo),
        "source": "wikimedia",
        "source_url": WIKI_PAGE,
        "license_name": "CC BY 4.0",
        "terms_url": WIKI_TERMS,
        "title": "Port of London",
        "author": "Ada Lovelace",
        "role": "空镜",
        "matched_place": "伦敦",
        "matched_occasion": "港口",
        "credit": "Port of London / Ada Lovelace / CC BY 4.0",
    }]}, pdir / "stills.json")
    save_json({
        "title": "演示样本·勿发布",
        "meta": {"date": "2026-11-21"},
        "segments": [{
            "id": "seg01", "kind": "item", "narration": still_line,
            "card": {"type": "headline", "headline": still_line, "full": [still_line]},
        }],
    }, pdir / "script.json")
    save_json({
        "date": "2026-11-21",
        "items": [{"title": "演示", "summary": still_line, "sources": [
            {"name": "伊方", "claim": "伊方自称在伦敦港口击中4艘。"},
            {"name": "美方", "claim": "美方称确认2艘。"},
        ]}],
    }, pdir / "briefing.json")

    def run_still():
        render_cards(pid)

    stilled = _painted(run_still)
    assert "Port of London / Ada Lovelace / CC BY 4.0" in [text for _, text in stilled]
    assert not any(text.startswith("来源：") or text.startswith("自称：")
                   for _, text in stilled)
    frame = Image.open(pdir / "cards" / "seg01.png")
    assert frame.getpixel((80, 30)) == (8, 12, 18)
    assert frame.getpixel((960, 700)) == (20, 140, 90)
