# -*- coding: utf-8 -*-
"""许可静帧：允许名单、残缺许可、画面署名，以及对不上就保持文字卡。"""
from PIL import Image, ImageDraw

from src.jsonio import save_json
from src.shotlist import ShotList
from src.stills import Stills

NE = "https://www.naturalearthdata.com/about/terms-of-use/"
FACT = "11月20日伦敦港口有船停泊。"
WIKI_PAGE = "https://commons.wikimedia.org/wiki/File:Port_of_London.jpg"
WIKI_TERMS = "https://creativecommons.org/licenses/by/4.0"
WIKI_FILE = "https://upload.wikimedia.org/wikipedia/commons/a/a/Port_of_London.jpg"
PEXELS_PAGE = "https://www.pexels.com/photo/london-port-1842/"
PEXELS_FILE = "https://images.pexels.com/photos/1842/london.jpeg"


def _wiki(**over) -> dict:
    record = {
        "source": "wikimedia",
        "source_url": WIKI_PAGE,
        "license_name": "CC BY 4.0",
        "terms_url": WIKI_TERMS,
        "title": "Port of London",
        "author": "Ada Lovelace",
        "role": "空镜",
        "matched_place": "伦敦",
        "matched_occasion": "港口",
        "image_url": WIKI_FILE,
    }
    record.update(over)
    record["credit"] = over.get(
        "credit",
        f"{record['title']} / {record['author']} / {record['license_name']}")
    return record


def _pexels(**over) -> dict:
    record = {
        "source": "pexels",
        "source_url": PEXELS_PAGE,
        "license_name": "Pexels License",
        "terms_url": "https://www.pexels.com/license/",
        "title": "",
        "author": "Ada Lovelace",
        "role": "空镜",
        "matched_place": "伦敦",
        "matched_occasion": "港口",
        "image_url": PEXELS_FILE,
    }
    record.update(over)
    record["title"] = ""
    record["credit"] = over.get(
        "credit", f"{record['author']} / {record['license_name']}")
    return record


def _cand(source: str, meta: str, **over) -> dict:
    base = _wiki() if source == "wikimedia" else _pexels()
    base.update(over)
    base["meta"] = meta
    base["source"] = source
    return base


def _doc(extra: str = "") -> str:
    return f"""
## 1. 封面（必填，单独成栏）
- 是否指定素材静帧：否
- 封面类型：纯文字封面
- 主标题 / 事实副题：伦敦港口 / {FACT}

## 2. 分镜
CUT: 01
时码: 00:00.00–00:15.00
镜类: 开头钩子
事实句: {FACT}
出处: 港务局
画面类型: 地图卡
来源 URL: {NE}
许可: 自制；Natural Earth 公有领域 {NE}
起止时间: 自制
字幕: {FACT}
指定封面: 否
{extra}
"""


def _still_lines(record: dict) -> str:
    fields = Stills.shot_fields(record)
    return "\n".join(f"{key}: {fields[key]}" for key in Stills.FIELDS)


def test_source_allowlist_rejects_unknown_nc_and_event_role():
    assert Stills.accept(_wiki(), FACT) is None
    assert Stills.accept(_pexels(), FACT) is None

    unknown = _wiki(source="example", source_url="https://example.com/photo.jpg")
    assert "允许名单" in Stills.accept(unknown, FACT)

    offsite = _wiki(source_url="https://upload.wikimedia.org/wikipedia/commons/a.jpg")
    assert "文件页" in Stills.accept(offsite, FACT)

    nc = _wiki(license_name="CC BY-NC-SA 4.0")
    assert "NC" in Stills.accept(nc, FACT)
    nd = _wiki(license_name="CC BY-ND 2.0")
    assert "ND" in Stills.accept(nd, FACT)

    event = _pexels(role="现场")
    assert "空镜" in Stills.accept(event, FACT)
    official = _pexels(role="官方实拍")
    assert "空镜" in Stills.accept(official, FACT)

    caption = _pexels(credit="Ada Lovelace / 现场")
    assert Stills.accept(caption, FACT) is not None
    assert "现场" not in (Stills.accept(_pexels(), FACT) or "")


def test_incomplete_license_is_rejected_and_blocks_the_shot_list():
    assert ShotList.problems(_doc()) == []
    assert ShotList.problems(_doc(_still_lines(_wiki()))) == []

    for field, token in (
        ("source_url", "来源 URL"),
        ("license_name", "许可名称"),
        ("terms_url", "条款页"),
        ("credit", "画面署名"),
    ):
        broken = _wiki(**{field: ""})
        assert token in Stills.accept(broken, FACT)
        problems = ShotList.problems(_doc(_still_lines(broken)))
        assert problems
        assert any(token in p for p in problems)

    nameless = _wiki(license_name="https://creativecommons.org/licenses/by/4.0")
    assert "名称" in Stills.accept(nameless, FACT)
    assert "作者不明" in Stills.accept(_wiki(author="Unknown"), FACT)
    drifted = _wiki(matched_place="巴黎")
    assert "不在事实句" in Stills.accept(drifted, FACT)

    live = _doc(_still_lines(_wiki())).replace("画面类型: 地图卡", "画面类型: 官方实拍", 1)
    live = live.replace("起止时间: 自制", "起止时间: 00:00.00–00:15.00", 1)
    live = live.replace(
        f"许可: 自制；Natural Earth 公有领域 {NE}",
        "许可: DVIDS 公有领域 https://www.dvidshub.net/about/faq", 1)
    live = live.replace(f"来源 URL: {NE}", "来源 URL: https://www.dvidshub.net/video/1", 1)
    problems = ShotList.problems(live)
    assert any("库存静帧" in p for p in problems)


def test_credit_overlay_is_the_real_attribution_and_not_a_caption():
    record = _wiki()
    overlay = Stills.overlay(record)
    assert overlay["credit"] == "Port of London / Ada Lovelace / CC BY 4.0"
    assert overlay["author"] == "Ada Lovelace"
    assert "Wikimedia Commons" not in overlay["credit"]
    assert overlay["role"] == "空镜"
    assert overlay["source_url"] == WIKI_PAGE
    assert overlay["license_name"] == "CC BY 4.0"
    assert overlay["terms_url"] == WIKI_TERMS
    assert FACT not in overlay["credit"]
    assert "现场" not in overlay["credit"]

    photo = Image.new("RGB", (640, 360), (20, 140, 90))
    drawn = []
    polygons = []
    original_text = ImageDraw.ImageDraw.text
    original_polygon = ImageDraw.ImageDraw.polygon

    def capture_text(self, xy, text, *args, **kwargs):
        drawn.append(text)
        return original_text(self, xy, text, *args, **kwargs)

    def capture_polygon(self, xy, *args, **kwargs):
        polygons.append(xy)
        return original_polygon(self, xy, *args, **kwargs)

    ImageDraw.ImageDraw.text = capture_text
    ImageDraw.ImageDraw.polygon = capture_polygon
    try:
        frame = Stills.paint(photo, record)
    finally:
        ImageDraw.ImageDraw.text = original_text
        ImageDraw.ImageDraw.polygon = original_polygon

    assert frame is not None
    assert frame.size == (1920, 1080)
    assert overlay["credit"] in drawn
    assert "Wikimedia Commons" not in drawn
    assert "空镜" in drawn
    assert FACT not in "".join(drawn)
    for sea in ("东海", "南海", "波罗的海", "黑海", "红海"):
        assert sea not in "".join(drawn)
    assert polygons == []
    assert frame.getpixel((4, 4)) == (217, 4, 41)
    assert frame.getpixel((80, 30)) == (8, 12, 18)
    assert frame.getpixel((960, 700)) == (20, 140, 90)


def test_no_match_keeps_the_text_card():
    segment = {"id": "seg02", "kind": "item", "item_ref": 1,
               "narration": FACT,
               "card": {"headline": "伦敦港口", "type": "headline"}}
    scenic = _cand("pexels", "beautiful sunset over the beach",
                   source_url="https://www.pexels.com/photo/beach-9/")
    calls = []

    def searcher(query):
        calls.append(query)
        return [], [scenic]

    chosen = Stills.assign([segment], [], searcher)
    assert chosen == []
    assert calls and calls[0]["place"] == "伦敦"
    assert calls[0]["occasion"] == "港口"
    assert "beautiful" not in calls[0]["place_en"]

    plain = {"id": "seg03", "kind": "item", "narration": "今天没有新的动态。",
             "card": {"headline": "无事"}}

    def fail_if_called(_query):
        raise AssertionError("没有地点或场合时不该去找图")

    assert Stills.assign([plain], [], fail_if_called) == []
    assert Stills.choose(FACT, [], [scenic]) is None


def test_wikimedia_is_preferred_and_pexels_stays_broll():
    wiki = _cand("wikimedia", "Port of London warehouse")
    pexels = _cand("pexels", "London port cranes at dawn")
    chosen = Stills.choose(FACT, [wiki], [pexels])
    assert chosen["source"] == "wikimedia"
    assert chosen["role"] == "空镜"
    assert chosen["title"] == "Port of London"
    assert chosen["credit"] == "Port of London / Ada Lovelace / CC BY 4.0"
    assert not chosen["credit"].startswith("Wikimedia Commons")
    assert FACT not in chosen["credit"]

    nc = _cand("wikimedia", "Port of London warehouse", license_name="CC BY-NC 4.0",
               author="Ada Lovelace")
    fallback = Stills.choose(FACT, [nc], [pexels])
    assert fallback["source"] == "pexels"
    assert fallback["role"] == "空镜"
    assert fallback["license_name"] == "Pexels License"
    assert fallback["terms_url"] == "https://www.pexels.com/license/"
    assert fallback["credit"] == "Ada Lovelace / Pexels License"
    assert fallback["author"] == "Ada Lovelace"
    assert not fallback["credit"].startswith("Pexels /")
    assert "现场" not in fallback["credit"]


def test_commons_parser_drops_nc_and_missing_terms():
    def page(title, lic, terms, artist="Ada Lovelace", object_name="Port of London"):
        return {
            "title": title,
            "imageinfo": [{
                "mime": "image/jpeg",
                "descriptionurl": WIKI_PAGE,
                "thumburl": WIKI_FILE,
                "extmetadata": {
                    "ObjectName": {"value": object_name},
                    "LicenseShortName": {"value": lic},
                    "LicenseUrl": {"value": terms},
                    "Artist": {"value": f"<a href='https://example.invalid'>{artist}</a>"},
                    "ImageDescription": {"value": title},
                    "Credit": {"value": "Wikimedia Commons"},
                },
            }],
        }

    good = page("Port of London", "CC BY-SA 4.0",
                "https://creativecommons.org/licenses/by-sa/4.0")
    missing = page("Port of London", "Public domain", "")
    nc = page("Port of London", "CC BY-NC 4.0",
              "https://creativecommons.org/licenses/by-nc/4.0")
    mapped = page("Location map of London port", "CC BY 4.0", WIKI_TERMS)
    payload = {"query": {"pages": {"1": good, "2": missing, "3": nc, "4": mapped}}}
    picked = Stills.choose(FACT, Stills.parse_commons(payload), [])
    assert picked is not None
    assert picked["license_name"] == "CC BY-SA 4.0"
    assert picked["title"] == "Port of London"
    assert picked["author"] == "Ada Lovelace"
    assert picked["credit"] == "Port of London / Ada Lovelace / CC BY-SA 4.0"
    assert "Wikimedia Commons" not in picked["credit"]
    assert picked["terms_url"].startswith("https://creativecommons.org/")
    assert "Location map" not in picked["source_url"]


def test_shot_list_copies_a_complete_still_and_drops_a_broken_one(tmp_path, monkeypatch):
    from src import store
    monkeypatch.setattr(store, "ROOT", tmp_path)
    pdir = tmp_path / "projects" / "ep-009"
    for sub in ("audio", "cards", "output"):
        (pdir / sub).mkdir(parents=True)
    save_json({"pid": "ep-009", "date": "2026-11-20", "stages": {}},
              pdir / "manifest.json")
    save_json({"status": "ok"}, pdir / "hammer.json")
    brief = {
        "source": "fixture",
        "标题": "伦敦港口停泊",
        "事实钩子": FACT,
        "时间地点": "11月20日，伦敦",
        "发生了什么": FACT,
        "各方怎么说": "",
        "信源署名": "港务局",
        "items": [{
            "title": "伦敦港口停泊",
            "summary": FACT,
            "event_time": "11月20日",
            "sources": [{"name": "港务局", "claim": "", "url": ""}],
            "still": _wiki(),
        }, {
            "title": "另一条没有对上的图",
            "summary": "另有一条动态。",
            "sources": [{"name": "港务局", "claim": "另有一条动态。", "url": ""}],
            "still": {"license_name": "挂在官网", "source_url": "https://example.com/a.jpg",
                      "credit": "随便写的署名"},
        }],
    }
    save_json(brief, pdir / "briefing.json")
    text = ShotList.generate("ep-009")
    assert ShotList.problems(text) == []
    assert "挂在官网" not in text
    assert "example.com" not in text
    assert "画面类型: 官方实拍" not in text
    assert "画面类型: 明确许可" not in text
    assert "Port of London / Ada Lovelace / CC BY 4.0" in text
    assert "Wikimedia Commons / Ada Lovelace" not in text
    assert WIKI_TERMS in text
    doc = ShotList.parse(text)
    assert doc["cover"]["是否指定素材静帧"] == "否"
    host = next(s for s in doc["shots"] if "伦敦" in s["事实句"] and "港口" in s["事实句"])
    assert host["画面类型"] == "地图卡"
    assert host["静帧用途"] == "空镜"
    assert host["静帧来源 URL"] == WIKI_PAGE
    assert host["静帧许可"] == "CC BY 4.0"
    assert host["静帧条款页"] == WIKI_TERMS
    assert host["画面署名"] == "Port of London / Ada Lovelace / CC BY 4.0"
    assert "伦敦" in host["静帧对应"] and "港口" in host["静帧对应"]
    others = [s for s in doc["shots"] if s is not host]
    assert others
    assert all(s["静帧用途"] == "无" for s in others)


LONDON_META = {
    "ObjectName": {"value": "'MSC Altamira' at London Gateway Port - geograph.org.uk - 6850795"},
    "ImageDescription": {"value": "A ship alongside the berth, not the title."},
    "Artist": {"value": "<a href='https://www.geograph.org.uk/profile/9905'>Robin Webster</a>"},
    "Credit": {"value": "<a href='https://www.geograph.org.uk/photo/6850795'>Geograph Britain and Ireland</a>"},
    "Attribution": {"value": "<i>'MSC Altamira' at London Gateway Port</i> by Robin Webster"},
    "LicenseShortName": {"value": "CC BY-SA 2.0"},
    "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/2.0"},
}
LONDON_CREDIT = "'MSC Altamira' at London Gateway Port / Robin Webster / CC BY-SA 2.0"
BELGRADE_META = {
    "ObjectName": {"value": "Bg 0375 Zvezna-Skupščina"},
    "ImageDescription": {"value": "View of the Parliament or Federal Assembly building in Belgrade"},
    "Artist": {"value": "Stebunik"},
    "Credit": {"value": "Own work"},
    "LicenseShortName": {"value": "CC0"},
    "LicenseUrl": {"value": "http://creativecommons.org/publicdomain/zero/1.0/deed.en"},
}
BELGRADE_FACT = "贝尔格莱德议会大楼对外关闭。"


def _commons_page(meta: dict, description_url: str, categories: list[str]) -> dict:
    return {
        "title": "File:Example.jpg",
        "categories": [{"title": name} for name in categories],
        "imageinfo": [{
            "mime": "image/jpeg",
            "descriptionurl": description_url,
            "thumburl": WIKI_FILE,
            "extmetadata": meta,
        }],
    }


def test_credit_leads_with_work_title_then_author_then_license():
    assert Stills.work_title(LONDON_META) == "'MSC Altamira' at London Gateway Port"
    assert "not the title" not in Stills.work_title(LONDON_META)
    assert Stills.work_title(BELGRADE_META) == "Bg 0375 Zvezna-Skupščina"
    assert "Parliament" not in Stills.work_title(BELGRADE_META)
    assert Stills.work_title({"ImageDescription": {"value": "Port of London"}}) == ""
    assert Stills.work_title({
        "ObjectName": {"value": "Port of London catalog"},
        "Attribution": {"value": "<i>Some Other Title</i>"},
        "ImageDescription": {"value": "A long description that is not the title"},
    }) == "Port of London catalog"

    london = Stills.compose_credit(
        "wikimedia", Stills.work_title(LONDON_META), "Robin Webster", "CC BY-SA 2.0")
    belgrade = Stills.compose_credit(
        "wikimedia", Stills.work_title(BELGRADE_META), "Stebunik", "CC0")
    assert london == LONDON_CREDIT
    assert belgrade == "Bg 0375 Zvezna-Skupščina / Stebunik / CC0"
    assert Stills.compose_credit("wikimedia", "", "Robin Webster", "CC BY-SA 2.0") == ""
    assert Stills.compose_credit(
        "wikimedia", "Wikimedia Commons", "Robin Webster", "CC BY-SA 2.0") == ""
    assert Stills.compose_credit(
        "wikimedia", "'MSC Altamira' at London Gateway Port",
        "Wikimedia Commons", "CC BY-SA 2.0") == ""
    assert Stills.compose_credit("pexels", "Pretty Harbor", "Ada Lovelace", "Pexels License") == (
        "Ada Lovelace / Pexels License")
    assert Stills.compose_credit("pexels", "", "Pexels", "Pexels License") == ""

    old = _wiki(credit="Wikimedia Commons / Ada Lovelace / CC BY 4.0", title="")
    assert "来源站" in Stills.accept(old, FACT)
    missing_title = _wiki(credit="Ada Lovelace / CC BY 4.0", title="")
    assert "作品名" in Stills.accept(missing_title, FACT)
    house_author = _wiki(credit="Port of London / Wikimedia Commons / CC BY 4.0",
                         author="Wikimedia Commons")
    assert "来源站" in Stills.accept(house_author, FACT)
    pexels_house = _pexels(credit="Pexels / Ada Lovelace / Pexels License")
    assert Stills.accept(pexels_house, FACT) is not None
    assert "Pexels /" not in (_pexels()["credit"])

    london_page = _commons_page(
        LONDON_META,
        "https://commons.wikimedia.org/wiki/File:%27MSC_Altamira%27_at_London_Gateway_Port.jpg",
        ["Category:London Gateway", "Category:Ports and harbours"])
    no_title = _commons_page(
        {"ImageDescription": {"value": "Port of London"},
         "Artist": {"value": "Robin Webster"},
         "LicenseShortName": {"value": "CC BY-SA 2.0"},
         "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/2.0"},
         "Credit": {"value": "Wikimedia Commons"}},
        WIKI_PAGE, ["Category:Port of London"])
    house = _commons_page(
        {**LONDON_META, "Artist": {"value": "Wikimedia Commons"}},
        WIKI_PAGE, ["Category:London Gateway"])
    picked = Stills.choose(FACT, Stills.parse_commons(
        {"query": {"pages": {"1": london_page}}}), [])
    assert picked is not None
    assert picked["credit"] == LONDON_CREDIT
    assert picked["title"] == "'MSC Altamira' at London Gateway Port"
    assert picked["author"] == "Robin Webster"
    assert Stills.credit_fits(picked["credit"])
    assert Stills.choose(FACT, Stills.parse_commons(
        {"query": {"pages": {"1": no_title, "2": house}}}), []) is None

    belgrade_page = _commons_page(
        BELGRADE_META,
        "https://commons.wikimedia.org/wiki/File:Bg_0375_Zvezna-Skup%C5%A1%C4%8Dina.jpg",
        ["Category:National Assembly of Serbia", "Category:Belgrade"])
    parliament = Stills.choose(BELGRADE_FACT, Stills.parse_commons(
        {"query": {"pages": {"1": belgrade_page}}}), [])
    assert parliament is not None
    assert parliament["credit"] == "Bg 0375 Zvezna-Skupščina / Stebunik / CC0"
    assert parliament["author"] == "Stebunik"
    assert "Wikimedia Commons" not in parliament["credit"]

    cand = {
        "license_name": "CC BY-SA 2.0",
        "terms_url": "https://creativecommons.org/licenses/by-sa/2.0",
        "author": "Robin Webster",
        "title": "'MSC Altamira' at London Gateway Port",
    }
    record = {**cand, "source": "wikimedia", "credit": LONDON_CREDIT}
    assert Stills._same_license(cand, record)
    invented = {**record, "title": "Some Other Title",
                "credit": "Some Other Title / Robin Webster / CC BY-SA 2.0"}
    house_credit = {**record, "title": "Wikimedia Commons",
                    "credit": "Wikimedia Commons / Robin Webster / CC BY-SA 2.0"}
    assert not Stills._same_license(cand, invented)
    assert not Stills._same_license(cand, house_credit)
    assert not Stills._same_license(cand, old)

    photo = Image.new("RGB", (640, 360), (20, 140, 90))
    drawn = []
    original_text = ImageDraw.ImageDraw.text

    def capture_text(self, xy, text, *args, **kwargs):
        drawn.append((xy[1], text))
        return original_text(self, xy, text, *args, **kwargs)

    ImageDraw.ImageDraw.text = capture_text
    try:
        frame = Stills.paint(photo, picked)
    finally:
        ImageDraw.ImageDraw.text = original_text
    assert frame is not None
    credit_lines = [text for y, text in drawn if text != "空镜"]
    assert " / ".join(credit_lines) == LONDON_CREDIT
    assert all(y >= 52 for y, text in drawn if text != "空镜")
    assert "Wikimedia Commons" not in " ".join(credit_lines)
    assert frame.getpixel((4, 4)) == (217, 4, 41)
