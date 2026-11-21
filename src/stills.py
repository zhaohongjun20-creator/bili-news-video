# -*- coding: utf-8 -*-
"""许可静帧：在已锁定的事实句上叠 2–3 张空镜，对不上就保持文字卡。

优先 Wikimedia Commons 上和锁定地点、场合都对得上、且该档许可完整的照片。
Pexels 只作退路，而且只能是空镜：不把库存图说成这一条新闻的现场。

一张静帧要同时有来源 URL、许可名称、条款页、画面署名，缺一项就不用。
画面署名先写该档自己的作品名和作者，再写许可。不把 Wikimedia Commons 或 Pexels 写成作者。
作品名只取文件元数据里的题名；没有作品名或作者，这张图就不用。Pexels 没有作品名，署名写摄影师和许可。
许可名称和条款页沿用分镜清单的许可门（ShotList._license_ok），不另开后门。
NC、ND、来源不在允许名单、作者不明，一律不用。画面上不画国界，不加海域名。
"""
import html
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from PIL import Image, ImageDraw

from src.jsonio import load_json, save_json


class Stills:
    """静帧的允许名单、许可门、检索和署名条。检查和绘制都是静态方法。"""

    WIKIMEDIA = "wikimedia"
    PEXELS = "pexels"
    ALLOWED = frozenset({WIKIMEDIA, PEXELS})
    ROLE = "空镜"
    BLANK = "无"
    PEXELS_NAME = "Pexels License"
    PEXELS_TERMS = "https://www.pexels.com/license/"
    LABEL = {WIKIMEDIA: "Wikimedia Commons", PEXELS: "Pexels"}
    COMMONS_API = "https://commons.wikimedia.org/w/api.php"
    PEXELS_SEARCH = "https://api.pexels.com/v1/search"
    PEXELS_PHOTO = "https://api.pexels.com/v1/photos/"
    UA = "bili-news-video/stills (flash-news establishing stills)"
    TIMEOUT = 25
    MAX_BYTES = 20_000_000
    IMAGE_HOSTS = frozenset({
        "upload.wikimedia.org", "thumb.wikimedia.org", "images.pexels.com",
    })
    MIME = frozenset({"image/jpeg", "image/png", "image/webp"})
    FIELDS = (
        "静帧用途", "静帧来源 URL", "静帧许可", "静帧条款页", "画面署名", "静帧对应",
    )
    PUBLIC = (
        "source", "source_url", "license_name", "terms_url", "title", "author", "credit",
        "role", "matched_place", "matched_occasion", "image_url",
    )

    _NC_ND = re.compile(
        r"(?i)(\bNC\b|\bND\b|non[-\s]?commercial|no[-\s]?deriv|非商业|禁止改作)")
    _WIKI_OK = re.compile(
        r"(?i)^(CC0|CC BY-SA|CC BY|Public domain|PDM|PD)(\b|[-\s\d.]).*$"
        r"|^(CC0|PD|PDM)$")
    _UNKNOWN = re.compile(
        r"(?i)^(unknown|anonymous|not known|n/?a|未知|不详|匿名|佚名)$")
    _MAPISH = re.compile(
        r"(?i)(\blocator map\b|\blocation map\b|\bblank map\b|\bmap of\b|"
        r"\bcartograph|\bborder map\b|国界|地图|"
        r"\bensign\b|\bflag\b|\bcoat of arms\b|\blogo\b|\blemblem\b|\bmap\b)")
    _EVENT = ("现场", "实拍", "官方实拍")

    # 检索用的固定英译，只服务允许名单里的 API，不上画面、不改事实句。
    PLACE_EN = {
        "乌斯季卢加": "Ust-Luga", "圣彼得堡": "Saint Petersburg", "芬兰湾": "Gulf of Finland",
        "波罗的海": "Baltic Sea", "立陶宛": "Lithuania", "拉脱维亚": "Latvia",
        "爱沙尼亚": "Estonia", "维尔纽斯": "Vilnius", "里加": "Riga",
        "霍尔木兹": "Strait of Hormuz", "阿曼湾": "Gulf of Oman", "波斯湾": "Persian Gulf",
        "哈伊马角": "Ras Al Khaimah", "阿联酋": "United Arab Emirates", "阿曼": "Oman",
        "伊朗": "Iran", "德黑兰": "Tehran", "以色列": "Israel", "特拉维夫": "Tel Aviv",
        "红海": "Red Sea", "苏伊士": "Suez", "巴林": "Bahrain", "卡塔尔": "Qatar",
        "伊斯坦布尔": "Istanbul", "爱德华兹": "Edwards", "黑海": "Black Sea",
        "乌克兰": "Ukraine", "基辅": "Kyiv", "敖德萨": "Odesa", "俄罗斯": "Russia",
        "莫斯科": "Moscow", "哈萨克斯坦": "Kazakhstan", "吉尔吉斯斯坦": "Kyrgyzstan",
        "塔吉克斯坦": "Tajikistan", "亚美尼亚": "Armenia", "土耳其": "Turkey",
        "安卡拉": "Ankara", "阿根廷": "Argentina", "布宜诺斯艾利斯": "Buenos Aires",
        "英国": "United Kingdom", "伦敦": "London", "米尔德霍尔": "Mildenhall",
        "德国": "Germany", "法国": "France", "北大西洋": "North Atlantic",
        "大西洋": "Atlantic Ocean", "塞尔维亚": "Serbia", "科索沃": "Kosovo",
        "波黑": "Bosnia", "黑山": "Montenegro", "北马其顿": "North Macedonia",
        "马其顿": "North Macedonia", "阿尔巴尼亚": "Albania", "贝尔格莱德": "Belgrade",
        "普里什蒂纳": "Pristina", "萨拉热窝": "Sarajevo", "波德戈里察": "Podgorica",
        "地拉那": "Tirana", "斯科普里": "Skopje",
    }
    OCCASION_EN = {
        "港口": "port", "机场": "airport", "码头": "dock", "议会": "parliament",
        "选举": "election", "军舰": "warship", "舰艇": "warship", "飞机": "aircraft",
        "战机": "fighter", "油田": "oil field", "炼厂": "refinery", "海峡": "strait",
        "基地": "base", "峰会": "summit", "车站": "station", "大桥": "bridge",
        "桥梁": "bridge", "广场": "square", "宫殿": "palace", "城堡": "castle",
        "大学": "university", "工厂": "factory", "铁路": "railway", "列车": "train",
        "坦克": "tank", "导弹": "missile", "卫星": "satellite", "火箭": "rocket",
        "航母": "aircraft carrier", "潜艇": "submarine", "巡逻": "patrol",
        "演习": "exercise", "边境": "border",
    }

    # ---------------------------------------------------------------- 许可门

    @staticmethod
    def blank_fields() -> dict:
        return {key: Stills.BLANK for key in Stills.FIELDS}

    @staticmethod
    def is_blank_shot(shot: dict) -> bool:
        for key in Stills.FIELDS:
            value = str((shot or {}).get(key) or "").strip()
            if value and value != Stills.BLANK:
                return False
        return True

    @staticmethod
    def shot_fields(record: dict) -> dict:
        tokens = [t for t in (record.get("matched_place"), record.get("matched_occasion")) if t]
        return {
            "静帧用途": Stills.ROLE,
            "静帧来源 URL": record.get("source_url") or "",
            "静帧许可": record.get("license_name") or "",
            "静帧条款页": record.get("terms_url") or "",
            "画面署名": record.get("credit") or "",
            "静帧对应": "、".join(tokens) if tokens else Stills.BLANK,
        }

    @staticmethod
    def from_shot(shot: dict) -> dict:
        tokens = Stills._split_tokens(str((shot or {}).get("静帧对应") or ""))
        place, occasion = "", ""
        for token in tokens:
            if token in Stills.OCCASION_EN and not occasion:
                occasion = token
            elif not place:
                place = token
        source = Stills.source_of(str(shot.get("静帧来源 URL") or ""))
        credit = str(shot.get("画面署名") or "").strip()
        parsed = Stills.split_credit(credit, source)
        return {
            "source": source,
            "source_url": str(shot.get("静帧来源 URL") or "").strip(),
            "license_name": str(shot.get("静帧许可") or "").strip(),
            "terms_url": str(shot.get("静帧条款页") or "").strip(),
            "title": parsed[0] if parsed else "",
            "credit": credit,
            "role": str(shot.get("静帧用途") or "").strip(),
            "matched_place": place,
            "matched_occasion": occasion,
            "author": parsed[1] if parsed else "",
            "image_url": "",
        }

    @staticmethod
    def accept(record: dict, locked_text: str) -> str | None:
        """可用则返回 None。否则返回拒绝原因，调用方不得使用这张图。"""
        from src.shotlist import ShotList
        rec = dict(record or {})
        source_url = str(rec.get("source_url") or "").strip()
        license_name = str(rec.get("license_name") or "").strip()
        terms = str(rec.get("terms_url") or "").strip()
        credit = str(rec.get("credit") or "").strip()
        role = str(rec.get("role") or "").strip()
        source = str(rec.get("source") or "").strip() or Stills.source_of(source_url)
        if source_url in ("", Stills.BLANK):
            return "静帧缺少来源 URL"
        if source not in Stills.ALLOWED:
            return "静帧来源不在允许名单（只许 Pexels 或 Wikimedia Commons）"
        if not Stills._page_ok(source, source_url):
            return "静帧来源 URL 不是允许的 Pexels 或 Wikimedia Commons 文件页"
        if license_name in ("", Stills.BLANK):
            return "静帧缺少许可名称"
        if terms in ("", Stills.BLANK):
            return "静帧缺少条款页"
        if credit in ("", Stills.BLANK):
            return "静帧缺少画面署名"
        if role != Stills.ROLE:
            return "静帧用途必须是空镜，不能标成现场或官方实拍"
        if Stills._NC_ND.search(license_name):
            return "静帧许可为 NC 或 ND，不能用"
        if ShotList._license_ok(f"{license_name} {terms}") != "ok":
            return "静帧许可须同时写名称和条款页"
        if source == Stills.PEXELS:
            if license_name != Stills.PEXELS_NAME:
                return "Pexels 静帧的许可名称必须是 Pexels License"
            if not Stills._pexels_terms(terms):
                return "Pexels 静帧的条款页必须是 https://www.pexels.com/license/"
        elif not Stills._WIKI_OK.match(license_name):
            return "Wikimedia 静帧的许可不在可用范围"
        parsed = Stills.split_credit(credit, source)
        if not parsed:
            if source == Stills.PEXELS:
                return "画面署名必须是作者 / 许可"
            return "画面署名必须是作品名 / 作者 / 许可"
        title, author, lic = parsed
        if Stills._house_name(author) or Stills._house_name(title):
            return "画面署名不能把来源站写成作者"
        if source == Stills.WIKIMEDIA and not title:
            return "画面署名缺少作品名"
        if lic != license_name:
            return "画面署名与作品名、作者、许可不一致"
        given = str(rec.get("author") or "").strip()
        if given and given != author:
            return "画面署名与作品名、作者、许可不一致"
        given_title = str(rec.get("title") or "").strip()
        if given_title and given_title != title:
            return "画面署名与作品名、作者、许可不一致"
        if Stills._UNKNOWN.match(author):
            return "静帧作者不明，不能用"
        if any(word in credit for word in Stills._EVENT):
            return "画面署名不能把空镜写成现场"
        tokens = [t for t in (rec.get("matched_place"), rec.get("matched_occasion")) if t]
        if not tokens:
            return "静帧没有对应到锁定事实里的地点或场合"
        if any(t not in (locked_text or "") for t in tokens):
            return "静帧对应的地点或场合不在事实句里"
        return None

    @staticmethod
    def split_credit(credit: str, source: str = "") -> tuple[str, str, str] | None:
        """返回 (作品名, 作者, 许可)。Pexels 没有作品名，第一项为空。"""
        parts = [p.strip() for p in (credit or "").split(" / ")]
        if not parts or any(not p for p in parts):
            return None
        if source == Stills.PEXELS:
            if len(parts) != 2:
                return None
            return "", parts[0], parts[1]
        if len(parts) < 3:
            return None
        author = " / ".join(parts[1:-1]).strip()
        if not author:
            return None
        return parts[0], author, parts[-1]

    @staticmethod
    def _house_name(value: str) -> bool:
        text = re.sub(r"\s+", " ", (value or "").strip()).casefold()
        return text in {name.casefold() for name in Stills.LABEL.values()}

    @staticmethod
    def work_title(meta: dict) -> str:
        """作品名只取该档自己的题名。没有就不编，也不拿描述或来源站顶上。

        署名里的斜体如果整段都在 ObjectName 里，用这段斜体（该档自己标出的题名）。
        否则用 ObjectName。两边都空，作品名就空着。
        """
        object_name = Stills._plain(Stills._meta_value(meta, "ObjectName"))
        raw = Stills._meta_value(meta, "Attribution")
        italic = ""
        matched = re.search(r"<i\b[^>]*>(.*?)</i>", raw or "", flags=re.I | re.S)
        if matched:
            italic = Stills._plain(matched.group(1))
        if italic and object_name and italic in object_name:
            return italic
        if object_name:
            return object_name
        if italic:
            return italic
        return ""

    @staticmethod
    def compose_credit(source: str, title: str, author: str, license_name: str) -> str:
        """拼画面署名。缺作品名、缺作者，或作者是来源站，就返回空串。"""
        title = Stills._plain(title)
        author = Stills._plain(author)
        license_name = (license_name or "").strip()
        if not author or not license_name:
            return ""
        if Stills._house_name(author) or Stills._UNKNOWN.match(author):
            return ""
        if source == Stills.PEXELS:
            if " / " in author:
                return ""
            return f"{author} / {license_name}"
        if source != Stills.WIKIMEDIA:
            return ""
        if not title or Stills._house_name(title) or " / " in title:
            return ""
        return f"{title} / {author} / {license_name}"

    @staticmethod
    def source_of(url: str) -> str:
        host = (urlparse(url or "").hostname or "").lower()
        if host == "commons.wikimedia.org":
            return Stills.WIKIMEDIA
        if host in {"www.pexels.com", "pexels.com"}:
            return Stills.PEXELS
        return ""

    @staticmethod
    def overlay(record: dict) -> dict:
        """烧进画面的署名数据。只有许可门已经通过的记录才该拿去画。"""
        parsed = Stills.split_credit(
            str(record.get("credit") or ""), str(record.get("source") or ""))
        author = parsed[1] if parsed else str(record.get("author") or "")
        return {
            "source": record.get("source") or "",
            "source_url": record.get("source_url") or "",
            "license_name": record.get("license_name") or "",
            "terms_url": record.get("terms_url") or "",
            "author": author,
            "credit": record.get("credit") or "",
            "role": Stills.ROLE,
            "matched_place": record.get("matched_place") or "",
            "matched_occasion": record.get("matched_occasion") or "",
        }

    # ---------------------------------------------------------------- 检索

    @staticmethod
    def query(text: str) -> dict:
        """地点和场合只从已锁定的原文里摘，不另写搜索词。"""
        from src.cards import ALIAS, CORE_ISO, GAZETTEER, _KIND_RANK
        blob = text or ""
        names = list(GAZETTEER) + [n for n in ALIAS if n not in GAZETTEER]
        names += [n for n in CORE_ISO.values() if n not in names]
        found = [name for name in names if name and name in blob]

        def rank(name: str) -> tuple:
            if name in GAZETTEER:
                kind = GAZETTEER[name][3]
            else:
                kind = "country"
            return (-len(name), _KIND_RANK.get(kind, 9))

        place = sorted(found, key=rank)[0] if found else ""
        occasions = [word for word in Stills.OCCASION_EN if word in blob]
        occasion = sorted(occasions, key=lambda w: (-len(w), w))[0] if occasions else ""
        place_en = Stills.PLACE_EN.get(place, "")
        if place and not place_en and place.isascii():
            place_en = place
        return {
            "place": place,
            "place_en": place_en,
            "occasion": occasion,
            "occasion_en": Stills.OCCASION_EN.get(occasion, ""),
        }

    @staticmethod
    def locked_text(seg: dict | None, item: dict | None) -> str:
        parts: list[str] = []
        seg = seg or {}
        card = seg.get("card") or {}
        parts.append(str(seg.get("narration") or ""))
        parts.append(str(card.get("headline") or ""))
        parts.append(str(card.get("sub") or ""))
        parts.extend(str(ln) for ln in (card.get("lines") or []) if ln)
        if item:
            parts.append(str(item.get("title") or ""))
            parts.append(str(item.get("summary") or ""))
            parts.append(str(item.get("event_time") or ""))
            for src in item.get("sources") or []:
                if isinstance(src, dict):
                    parts.append(str(src.get("claim") or ""))
        return "\n".join(p for p in parts if p)

    @staticmethod
    def item_for(seg: dict, items: list) -> dict | None:
        ref = seg.get("item_ref")
        if isinstance(ref, bool) or not isinstance(ref, int):
            return None
        if ref < 1 or ref > len(items or []):
            return None
        item = items[ref - 1]
        return item if isinstance(item, dict) else None

    @staticmethod
    def matches(meta: str, query: dict) -> tuple[str, str] | None:
        place, occasion = query.get("place") or "", query.get("occasion") or ""
        if not place and not occasion:
            return None
        blob = meta or ""
        place_ok = Stills._token_in(blob, place, query.get("place_en") or "")
        occasion_ok = Stills._token_in(blob, occasion, query.get("occasion_en") or "")
        if place and occasion:
            if place_ok and occasion_ok:
                return place, occasion
            return None
        if place and place_ok:
            return place, ""
        if occasion and occasion_ok:
            return "", occasion
        return None

    @staticmethod
    def choose(locked_text: str, wiki: list[dict], pexels: list[dict]) -> dict | None:
        """先 Commons，再 Pexels 空镜。没有完整且对得上的记录就返回 None。"""
        return Stills.choose_query(locked_text, Stills.query(locked_text), wiki, pexels)

    @staticmethod
    def choose_query(locked_text: str, query: dict, wiki: list[dict],
                     pexels: list[dict]) -> dict | None:
        return next(Stills.iter_records(locked_text, query, wiki, pexels), None)

    @staticmethod
    def iter_records(locked_text: str, query: dict, wiki: list[dict],
                     pexels: list[dict]):
        """按 Commons、再 Pexels 的顺序给出每一张过门的空镜。"""
        if not (query or {}).get("place") and not (query or {}).get("occasion"):
            return
        pools = ((Stills.WIKIMEDIA, wiki), (Stills.PEXELS, pexels))
        for source, pool in pools:
            for cand in pool or []:
                rec = Stills._from_candidate(cand, query, locked_text, source)
                if rec and Stills.accept(rec, locked_text) is None:
                    yield rec

    @staticmethod
    def assign(segments: list, items: list, searcher, limit: int = 3) -> list[dict]:
        """给条目段选静帧。searcher 返回 (commons 候选, pexels 候选)。选不中的段不在结果里。"""
        chosen = []
        used: set[str] = set()
        for seg in segments or []:
            if len(chosen) >= limit:
                break
            if not isinstance(seg, dict) or seg.get("kind") != "item":
                continue
            if (seg.get("card") or {}).get("phases"):
                continue
            item = Stills.item_for(seg, items or [])
            query = Stills._segment_query(seg, item)
            if not query["place"] and not query["occasion"]:
                continue
            wiki, pexels = searcher(query)
            hit = Stills.choose_query(Stills.locked_text(seg, None), query,
                                      wiki or [], pexels or [])
            if not hit or hit.get("source_url") in used:
                continue
            used.add(hit["source_url"])
            chosen.append({**hit, "segment_id": seg.get("id") or ""})
        return chosen

    @staticmethod
    def parse_commons(payload: dict) -> list[dict]:
        pages = (payload or {}).get("query", {}).get("pages") or {}
        if isinstance(pages, dict):
            pages = list(pages.values())
        out = []
        for page in pages:
            if not isinstance(page, dict):
                continue
            infos = page.get("imageinfo") or []
            if not infos or not isinstance(infos[0], dict):
                continue
            info = infos[0]
            mime = str(info.get("mime") or "").split(";")[0].strip().lower()
            if mime not in Stills.MIME:
                continue
            meta = info.get("extmetadata") or {}
            desc = Stills._plain(Stills._meta_value(meta, "ImageDescription"))
            cats = []
            for cat in page.get("categories") or []:
                if isinstance(cat, dict):
                    cats.append(str(cat.get("title") or ""))
                elif isinstance(cat, str):
                    cats.append(cat)
            blob = " ".join([str(page.get("title") or ""), desc, *cats])
            if Stills._MAPISH.search(blob):
                continue
            out.append({
                "source": Stills.WIKIMEDIA,
                "source_url": str(info.get("descriptionurl") or "").strip(),
                "license_name": Stills._plain(Stills._meta_value(meta, "LicenseShortName")),
                "terms_url": Stills._meta_value(meta, "LicenseUrl").strip(),
                "title": Stills.work_title(meta),
                "author": Stills._plain(Stills._meta_value(meta, "Artist")),
                "image_url": str(info.get("thumburl") or info.get("url") or "").strip(),
                "meta": blob,
            })
        return out

    @staticmethod
    def parse_pexels(payload: dict) -> list[dict]:
        """Pexels 接口不按张给许可。能用的只有官网声明的 Pexels License，不写成 CC，也不写成现场。"""
        out = []
        for photo in (payload or {}).get("photos") or []:
            if not isinstance(photo, dict):
                continue
            src = photo.get("src") or {}
            image = src.get("large") or src.get("large2x") or src.get("original") or ""
            out.append({
                "source": Stills.PEXELS,
                "source_url": str(photo.get("url") or "").strip(),
                "license_name": Stills.PEXELS_NAME,
                "terms_url": Stills.PEXELS_TERMS,
                "author": Stills._plain(str(photo.get("photographer") or "")),
                "image_url": str(image or "").strip(),
                "meta": str(photo.get("alt") or ""),
            })
        return out

    # ---------------------------------------------------------------- 落盘

    @staticmethod
    def attach(pid: str) -> dict:
        """渲染前准备静帧。有分镜清单时只兑现清单里已经写全的空镜，不改清单。

        没有清单时才按锁定口播去检索。检索失败、许可不全、对不上，该段保持文字卡。
        """
        from src import store
        from src.config import load_config
        from src.shotlist import ShotList
        cfg = (load_config().get("stills") or {})
        limit = int(cfg.get("max_per_episode") or 3)
        script = load_json(store.project_dir(pid) / "script.json") or {}
        segments = script.get("segments") or []
        brief = load_json(store.project_dir(pid) / "briefing.json") or {}
        items = [it for it in (brief.get("items") or []) if isinstance(it, dict)]
        path = store.project_dir(pid) / ShotList.FILENAME
        gaps: list[str] = []
        if path.is_file():
            records = Stills._from_shotlist(pid, path.read_text(encoding="utf-8"),
                                            segments, items)
            gaps = records["gaps"]
            chosen = records["stills"]
        elif os.environ.get("NEWS_OFFLINE") == "1" or cfg.get("enable", True) is False:
            chosen = []
        else:
            chosen = Stills._search_episode(pid, segments, items, limit)
            if brief:
                # 条目 dict 已就地写入 still。有清单时不改线索包，避免动已锁定的一期。
                save_json(brief, store.project_dir(pid) / "briefing.json")
        save_json({"stills": chosen, "gaps": gaps},
                  store.project_dir(pid) / "stills.json")
        return {"stills": chosen, "gaps": gaps}

    @staticmethod
    def gaps(pid: str) -> list[str]:
        from src import store
        data = load_json(store.project_dir(pid) / "stills.json") or {}
        return list(data.get("gaps") or [])

    @staticmethod
    def load(pid: str) -> dict[str, dict]:
        from src import store
        data = load_json(store.project_dir(pid) / "stills.json") or {}
        out = {}
        for rec in data.get("stills") or []:
            seg_id = str(rec.get("segment_id") or "")
            if seg_id:
                out[seg_id] = rec
        return out

    @staticmethod
    def search(query: dict) -> tuple[list[dict], list[dict]]:
        from src.config import api_keys
        english = " ".join(p for p in (query.get("place_en"), query.get("occasion_en")) if p)
        chinese = " ".join(p for p in (query.get("place"), query.get("occasion")) if p)
        # 同一个地点、场合可以换写法去查，不另造词。intitle 只是让标题里真有这些词的文件靠前。
        queries = []
        if english:
            queries.append(english)
            words = [w for w in english.split() if w]
            if len(words) >= 2:
                queries.append(" ".join(f"intitle:{w}" for w in words))
        if chinese:
            queries.append(chinese)
        wiki: list[dict] = []
        for text in queries:
            payload = Stills._get_json(Stills.COMMONS_API, {
                "action": "query", "format": "json", "generator": "search",
                "gsrsearch": text, "gsrnamespace": "6", "gsrlimit": "15",
                "prop": "imageinfo|categories",
                "iiprop": "url|extmetadata|mime", "iiurlwidth": "1600",
                "cllimit": "30",
            })
            wiki.extend(Stills.parse_commons(payload))
            # 标题碰巧带上地点、但许可残缺的文件不算找到。换一种同样的词再查。
            probe = " ".join(t for t in (query.get("place"), query.get("occasion")) if t)
            if Stills.choose_query(probe, query, wiki, []) is not None:
                break
        pexels: list[dict] = []
        key = (api_keys().get("pexels") or "").strip()
        if key and english:
            payload = Stills._get_json(
                Stills.PEXELS_SEARCH, {"query": english, "per_page": "10"},
                {"Authorization": key, "User-Agent": Stills.UA})
            pexels = Stills.parse_pexels(payload)
        return wiki, pexels

    # ---------------------------------------------------------------- 画面

    @staticmethod
    def _credit_origin() -> tuple[int, int]:
        """署名起点 x，以及它右边能用的宽度。和 paint 用同一条边。"""
        from src.cards import W, _font
        probe = ImageDraw.Draw(Image.new("RGB", (16, 16)))
        role_w = probe.textlength(Stills.ROLE, font=_font(28, True))
        text_x = int(40 + role_w + 36 + 28)
        return text_x, max(240, W - text_x - 48)

    @staticmethod
    def credit_layout(draw: ImageDraw.ImageDraw, credit: str,
                      max_w: int = 1500) -> tuple[list[str], int] | None:
        from src.cards import _font
        text = (credit or "").strip()
        if not text:
            return None
        for size in range(28, 21, -2):
            font = _font(size, False)
            if draw.textlength(text, font=font) <= max_w:
                return [text], size
            parts = [p.strip() for p in text.split(" / ")]
            if len(parts) >= 2 and all(p and draw.textlength(p, font=font) <= max_w
                                       for p in parts):
                return parts, size
        return None

    @staticmethod
    def credit_lines(draw: ImageDraw.ImageDraw, credit: str,
                     max_w: int = 1500) -> list[str] | None:
        layout = Stills.credit_layout(draw, credit, max_w)
        return None if layout is None else layout[0]

    @staticmethod
    def credit_fits(credit: str) -> bool:
        _text_x, max_w = Stills._credit_origin()
        probe = Image.new("RGB", (16, 16))
        return Stills.credit_layout(ImageDraw.Draw(probe), credit, max_w) is not None

    @staticmethod
    def paint(photo: Image.Image, record: dict) -> Image.Image | None:
        """新闻条幅加空镜署名。不写事实标题，不画国界，不加海域名。

        署名留在顶栏。标题卡 zoompan 会裁掉顶上约 40px，字幕在底边，两边都不盖署名。
        """
        from src import cards
        credit = str(record.get("credit") or "")
        canvas = Image.new("RGB", (cards.W, cards.H), cards.BG)
        draw = ImageDraw.Draw(canvas)
        text_x, max_w = Stills._credit_origin()
        layout = Stills.credit_layout(draw, credit, max_w)
        if not layout:
            return None
        lines, size = layout
        text_font = cards._font(size, False)
        line_h = max(size + 8, 36)
        text_top = 52
        text_bottom = text_top + line_h * len(lines)
        bar_bottom = max(132, text_bottom + 20)
        draw.rectangle([0, 0, cards.W, 12], fill=cards.ACCENT)
        draw.rectangle([0, 12, cards.W, bar_bottom], fill=(8, 12, 18))
        role_font = cards._font(28, True)
        pill_h = 48
        pill_y = 46 if bar_bottom <= 132 else max(46, (12 + bar_bottom - pill_h) // 2)
        pill = [40, pill_y, text_x - 28, pill_y + pill_h]
        draw.rounded_rectangle(pill, 10, fill=cards.ACCENT)
        draw.text((58, pill_y + 8), Stills.ROLE, font=role_font, fill=cards.INK)
        y = text_top
        for line in lines:
            draw.text((text_x, y), line, font=text_font, fill=cards.INK)
            y += line_h
        Stills._paste_contain(canvas, photo.convert("RGB"),
                              (48, bar_bottom + 24, cards.W - 48, cards.H - 48))
        return canvas

    @staticmethod
    def paint_segment(seg: dict, record: dict) -> Image.Image | None:
        path = Path(str(record.get("path") or ""))
        if not path.is_file():
            return None
        if Stills.accept(record, Stills.locked_text(seg, None)) is not None:
            return None
        try:
            photo = Image.open(path)
            photo.load()
        except OSError:
            return None
        return Stills.paint(photo, record)

    # ---------------------------------------------------------------- 内部

    @staticmethod
    def _search_episode(pid: str, segments: list, items: list, limit: int) -> list[dict]:
        saved = []
        used: set[str] = set()
        for seg in segments or []:
            if seg.get("kind") != "item" or (seg.get("card") or {}).get("phases"):
                continue
            item = Stills.item_for(seg, items)
            seg_text = Stills.locked_text(seg, None)
            kept = Stills._reuse_still(pid, seg, item, seg_text)
            if kept and kept.get("source_url") not in used and len(saved) < limit:
                saved.append(kept)
                used.add(kept["source_url"])
                continue
            if len(saved) >= limit:
                continue
            query = Stills._segment_query(seg, item)
            if not query["place"] and not query["occasion"]:
                if (item and isinstance(item.get("still"), dict)
                        and Stills.accept(item["still"], seg_text) is not None):
                    item.pop("still", None)
                continue
            wiki, pexels = Stills.search(query)
            placed = False
            for hit in Stills.iter_records(seg_text, query, wiki, pexels):
                if hit.get("source_url") in used:
                    continue
                path = Stills._download(pid, seg.get("id") or "still",
                                        hit.get("image_url") or "",
                                        hit.get("source_url") or "")
                if path is None or not Stills.credit_fits(hit.get("credit") or ""):
                    continue
                hit = {**hit, "path": str(path), "segment_id": seg.get("id") or ""}
                saved.append(hit)
                used.add(hit["source_url"])
                if item is not None:
                    item["still"] = {key: hit.get(key) or "" for key in Stills.PUBLIC}
                placed = True
                break
            if not placed and item and isinstance(item.get("still"), dict):
                if Stills.accept(item["still"], seg_text) is not None:
                    item.pop("still", None)
        return saved

    @staticmethod
    def _reuse_still(pid: str, seg: dict, item: dict | None, seg_text: str) -> dict | None:
        existing = item.get("still") if item and isinstance(item.get("still"), dict) else None
        if not existing or Stills.accept(existing, seg_text) is not None:
            return None
        image = str(existing.get("image_url") or "")
        path = Stills._download(pid, seg.get("id") or "still", image,
                                str(existing.get("source_url") or ""))
        if path is None or not Stills.credit_fits(existing.get("credit") or ""):
            return None
        return {**existing, "path": str(path), "segment_id": seg.get("id") or ""}

    @staticmethod
    def _segment_query(seg: dict, item: dict | None) -> dict:
        """地点和场合可以来自简报，但必须已经写在这一段口播或卡面上。"""
        seg_text = Stills.locked_text(seg, None)
        query = Stills.query(Stills.locked_text(seg, item))
        if query["place"] and query["place"] not in seg_text:
            query["place"] = ""
            query["place_en"] = ""
        if query["occasion"] and query["occasion"] not in seg_text:
            query["occasion"] = ""
            query["occasion_en"] = ""
        return query

    @staticmethod
    def _from_shotlist(pid: str, text: str, segments: list, items: list) -> dict:
        from src.shotlist import ShotList
        if ShotList.problems(text):
            return {"stills": [], "gaps": []}
        stills = []
        gaps = []
        for shot in ShotList.parse(text)["shots"]:
            if Stills.is_blank_shot(shot):
                continue
            label = ShotList._label(shot)
            rec = Stills.from_shot(shot)
            reason = Stills.accept(rec, shot.get("事实句") or "")
            if reason:
                gaps.append(f"{label} {reason}")
                continue
            seg = Stills._segment_for(shot, segments)
            if seg is None:
                gaps.append(f"{label} 的静帧对不上口播段落")
                continue
            image = Stills._image_for_declared(rec, items)
            if not image:
                gaps.append(f"{label} 的静帧无法核对图像文件")
                continue
            path = Stills._download(pid, seg.get("id") or label, image,
                                    rec.get("source_url") or "")
            if path is None or not Stills.credit_fits(rec.get("credit") or ""):
                gaps.append(f"{label} 的静帧无法核对图像文件")
                continue
            filled = {**rec, "image_url": image, "path": str(path),
                      "segment_id": seg.get("id") or ""}
            if Stills.accept(filled, shot.get("事实句") or "") is not None:
                gaps.append(f"{label} 的静帧未过许可门")
                continue
            stills.append(filled)
        return {"stills": stills, "gaps": gaps}

    @staticmethod
    def _segment_for(shot: dict, segments: list) -> dict | None:
        fact = shot.get("事实句") or ""
        tokens = [t for t in (Stills.from_shot(shot).get("matched_place"),
                              Stills.from_shot(shot).get("matched_occasion")) if t]
        ranked = [s for s in segments if s.get("kind") == "item"]
        ranked += [s for s in segments if s.get("kind") != "item"]
        for seg in ranked:
            blob = Stills.locked_text(seg, None)
            if fact and fact in blob:
                return seg
            if tokens and all(t in blob for t in tokens):
                return seg
        return None

    @staticmethod
    def _image_for_declared(record: dict, items: list) -> str:
        """图像地址只用来取文件。许可对不上声明的，宁可不取。"""
        for item in items:
            still = item.get("still") if isinstance(item, dict) else None
            if not isinstance(still, dict):
                continue
            if str(still.get("source_url") or "") != record.get("source_url"):
                continue
            if str(still.get("credit") or "") != record.get("credit"):
                continue
            if str(still.get("license_name") or "") != record.get("license_name"):
                continue
            image = str(still.get("image_url") or "")
            if Stills._image_host_ok(image):
                return image
        if record.get("source") == Stills.WIKIMEDIA:
            return Stills._commons_image(record)
        return ""

    @staticmethod
    def _commons_image(record: dict) -> str:
        title = Stills._file_title(record.get("source_url") or "")
        if not title:
            return ""
        payload = Stills._get_json(Stills.COMMONS_API, {
            "action": "query", "format": "json", "titles": title,
            "prop": "imageinfo|categories",
            "iiprop": "url|extmetadata|mime", "iiurlwidth": "1600",
            "cllimit": "30",
        })
        for cand in Stills.parse_commons(payload):
            if not Stills._same_license(cand, record):
                continue
            if Stills._image_host_ok(cand.get("image_url") or ""):
                return cand["image_url"]
        return ""

    @staticmethod
    def _same_license(cand: dict, record: dict) -> bool:
        if cand.get("license_name") != record.get("license_name"):
            return False
        if Stills._norm_url(cand.get("terms_url") or "") != Stills._norm_url(
                record.get("terms_url") or ""):
            return False
        parsed = Stills.split_credit(
            record.get("credit") or "", record.get("source") or "")
        if not parsed:
            return False
        title, author, _lic = parsed
        if (cand.get("author") or "") != author:
            return False
        if (cand.get("title") or "") != title:
            return False
        return True

    @staticmethod
    def _download(pid: str, seg_id: str, image_url: str,
                  source_url: str = "") -> Path | None:
        from src import store
        image_url = Stills._bounded_image(source_url, image_url)
        if not Stills._image_host_ok(image_url):
            return None
        safe = re.sub(r"[^A-Za-z0-9_-]+", "-", seg_id).strip("-") or "still"
        dest = store.project_dir(pid) / "stills" / f"{safe}.img"
        dest.parent.mkdir(exist_ok=True)
        try:
            response = requests.get(image_url, headers={"User-Agent": Stills.UA},
                                    timeout=Stills.TIMEOUT, stream=True)
        except requests.RequestException:
            return None
        if response.status_code != 200:
            return None
        ctype = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
        if ctype not in Stills.MIME:
            return None
        buf = bytearray()
        try:
            for chunk in response.iter_content(65536):
                if not chunk:
                    continue
                buf.extend(chunk)
                if len(buf) > Stills.MAX_BYTES:
                    return None
        except requests.RequestException:
            return None
        if not buf:
            return None
        dest.write_bytes(buf)
        try:
            with Image.open(dest) as photo:
                photo.load()
        except OSError:
            dest.unlink(missing_ok=True)
            return None
        return dest

    @staticmethod
    def _from_candidate(cand: dict, query: dict, locked_text: str, source: str) -> dict | None:
        if (cand or {}).get("source") != source:
            return None
        if Stills._MAPISH.search(cand.get("meta") or ""):
            return None
        hit = Stills.matches(cand.get("meta") or "", query)
        if not hit:
            return None
        title = Stills._plain(str(cand.get("title") or ""))
        author = Stills._plain(str(cand.get("author") or ""))
        license_name = str(cand.get("license_name") or "").strip()
        credit = Stills.compose_credit(source, title, author, license_name)
        if not credit:
            return None
        record = {
            "source": source,
            "source_url": str(cand.get("source_url") or "").strip(),
            "license_name": license_name,
            "terms_url": str(cand.get("terms_url") or "").strip(),
            "title": title if source == Stills.WIKIMEDIA else "",
            "author": author,
            "credit": credit,
            "role": Stills.ROLE,
            "matched_place": hit[0],
            "matched_occasion": hit[1],
            "image_url": str(cand.get("image_url") or "").strip(),
        }
        if Stills.accept(record, locked_text) is not None:
            return None
        if not Stills._image_host_ok(record["image_url"]):
            return None
        return record

    @staticmethod
    def _paste_contain(canvas: Image.Image, photo: Image.Image, box: tuple) -> None:
        x0, y0, x1, y1 = box
        bw, bh = x1 - x0, y1 - y0
        pw, ph = photo.size
        if pw < 1 or ph < 1 or bw < 1 or bh < 1:
            return
        scale = min(bw / pw, bh / ph)
        size = (max(1, int(pw * scale)), max(1, int(ph * scale)))
        fitted = photo.resize(size, Image.Resampling.LANCZOS)
        ox = x0 + (bw - size[0]) // 2
        oy = y0 + (bh - size[1]) // 2
        canvas.paste(fitted, (ox, oy))

    @staticmethod
    def _get_json(url: str, params: dict, headers: dict | None = None) -> dict:
        head = {"User-Agent": Stills.UA}
        if headers:
            head.update(headers)
        try:
            response = requests.get(url, params=params, headers=head,
                                    timeout=Stills.TIMEOUT)
        except requests.RequestException:
            return {}
        if response.status_code != 200:
            return {}
        try:
            data = response.json()
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _page_ok(source: str, url: str) -> bool:
        parsed = urlparse(url or "")
        if parsed.scheme != "https":
            return False
        path = unquote(parsed.path or "")
        if source == Stills.WIKIMEDIA:
            return parsed.hostname == "commons.wikimedia.org" and "/wiki/File:" in path
        if source == Stills.PEXELS:
            return parsed.hostname in {"www.pexels.com", "pexels.com"} and "/photo/" in path
        return False

    @staticmethod
    def _pexels_terms(url: str) -> bool:
        parsed = urlparse(url or "")
        if parsed.scheme != "https" or parsed.hostname not in {"www.pexels.com", "pexels.com"}:
            return False
        return parsed.path.rstrip("/") == "/license"

    @staticmethod
    def _image_host_ok(url: str) -> bool:
        parsed = urlparse(url or "")
        host = (parsed.hostname or "").lower()
        if parsed.scheme == "https" and host in Stills.IMAGE_HOSTS:
            return True
        # 缩小后的同一张 Commons 文件，避免去拉原图。
        return (parsed.scheme == "https" and host == "commons.wikimedia.org"
                and parsed.path.startswith("/wiki/Special:FilePath/"))

    @staticmethod
    def _bounded_image(source_url: str, image_url: str) -> str:
        from urllib.parse import quote
        title = Stills._file_title(source_url)
        if title.startswith("File:"):
            name = quote(title[len("File:"):], safe="")
            return ("https://commons.wikimedia.org/wiki/Special:FilePath/"
                    f"{name}?width=1600")
        return image_url

    @staticmethod
    def _file_title(url: str) -> str:
        path = unquote(urlparse(url or "").path or "")
        mark = "/wiki/"
        if mark not in path:
            return ""
        title = path.split(mark, 1)[1]
        return title if title.startswith("File:") else ""

    @staticmethod
    def _norm_url(url: str) -> str:
        parsed = urlparse((url or "").strip())
        return f"{parsed.scheme}://{parsed.hostname or ''}{parsed.path.rstrip('/')}"

    @staticmethod
    def _token_in(blob: str, zh: str, en: str) -> bool:
        if zh and zh in blob:
            return True
        return bool(en and en.lower() in blob.lower())

    @staticmethod
    def _split_tokens(value: str) -> list[str]:
        if not value or value.strip() == Stills.BLANK:
            return []
        return [p.strip() for p in re.split(r"[、,，]", value) if p.strip()
                and p.strip() != Stills.BLANK]

    @staticmethod
    def _plain(value: str) -> str:
        text = re.sub(r"<[^>]+>", " ", value or "")
        text = html.unescape(text)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _meta_value(meta: dict, key: str) -> str:
        raw = (meta or {}).get(key) or ""
        if isinstance(raw, dict):
            raw = raw.get("value") or ""
        return str(raw)
