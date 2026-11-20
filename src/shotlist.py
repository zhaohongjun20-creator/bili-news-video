# -*- coding: utf-8 -*-
"""分镜清单：从线索包映射，并在渲染前执行许可门。

规则原文：
    docs/线索包-分镜清单-标准模板.md
    docs/线索包-到-分镜清单-生成规则.md
    docs/合法画面来源规则.md

这里只核对字段、只抄写线索包里已经有的句子，不解释法律，也不抓取画面。
新闻地图卡的底图按规则默认 Natural Earth（公有领域条款页是底图，不是实拍许可）。

没有「分镜清单.md」时：纯卡面、项目里也没有外部实拍的成片仍可渲染。
项目里已有外部实拍文件，或线索包已标明实拍条目时，缺这份文件就不进渲染。
"""
import re
from pathlib import Path


class ShotList:
    """标准分镜清单的解析和许可门。检查都是静态方法。"""

    FILENAME = "分镜清单.md"
    LIVE = frozenset({"官方实拍", "公有领域", "明确许可"})
    CARD = frozenset({"地图卡", "数据卡"})
    COVER_TYPES = frozenset({"纯文字封面", "图形设计封面"})
    HOOK_S = 15.0
    HOOK_TC = "00:00.00–00:15.00"
    PASSED_REVIEW = frozenset({"ok", "fixed", "warned"})
    VIDEO_EXT = frozenset({".mp4", ".mov", ".mkv", ".webm", ".m4v"})
    PRODUCED_DIRS = frozenset({"output", "clips", "audio", "cards"})
    # 新闻地图卡的默认底图。这是图卡底图，不是实拍许可，不拿来补实拍缺项。
    NE_URL = "https://www.naturalearthdata.com/about/terms-of-use/"
    NE_LIC = "自制；Natural Earth 公有领域 " + NE_URL
    DUR_TOL = 0.05

    _URL = re.compile(r"https?://[^\s）)】>，,；;\"']+")
    _TC = r"(?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?"
    _RANGE = re.compile(rf"(?P<a>{_TC})\s*[–—\-－~]\s*(?P<b>{_TC})")
    _ONE = re.compile(rf"^{_TC}$")
    _FIELD = re.compile(r"^(?:[-*]\s*)?([^：:\n]{1,40})[：:]\s*(.*)$")
    _PAREN = re.compile(r"^[（(][^）)]*[）)]$")
    _YES = re.compile(r"^是([。]|(（[^）]*）))?$")
    _NO = re.compile(r"^否([。]|(（[^）]*）))?$")

    COVER_KEYS = frozenset({
        "是否指定素材静帧", "封面类型", "对应 CUT", "画面来源 URL",
        "许可", "精确时码", "若不指定",
    })
    SHOT_KEYS = frozenset({
        "CUT", "时码", "镜类", "事实句", "出处", "画面类型", "来源 URL",
        "许可", "起止时间", "字幕", "指定封面",
    })

    @staticmethod
    def problems(text: str) -> list[str]:
        """空列表表示过门。"""
        doc = ShotList.parse(text)
        problems: list[str] = []
        per_shot: dict[int, list[str]] = {}
        numbered: list[int] = []
        if not doc["shots"]:
            problems.append("分镜清单没有 CUT")
        for shot in doc["shots"]:
            label = ShotList._label(shot)
            own = ShotList._check_shot(shot, label)
            problems.extend(own)
            no = shot.get("no")
            if isinstance(no, int):
                numbered.append(no)
                per_shot.setdefault(no, []).extend(own)
        problems.extend(ShotList._check_hook(doc["shots"], numbered))
        problems.extend(ShotList._check_cover(doc["cover"], doc["shots"], per_shot))
        return problems

    @staticmethod
    def refusal(pid: str) -> str | None:
        """渲染前的拒绝理由。空表示可以开始建时间轴。

        有分镜清单：字段门不过，或已过门的实拍没有可剪的本地素材，都拒绝。
        没有分镜清单：仅当项目里没有外部实拍、线索包也没有实拍条目时放行。
        """
        from src import store
        path = store.project_dir(pid) / ShotList.FILENAME
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            found = ShotList.problems(text)
            if found:
                return "分镜清单未过许可门，不进渲染：" + "；".join(found)
            media = ShotList._cut_problems(pid, text)
            if media:
                return "实拍镜不能剪入时间轴，不进渲染：" + "；".join(media)
            return None
        if ShotList.external_live(pid):
            return ("缺少分镜清单.md：项目含外部实拍或已标明的实拍条目，不进渲染。"
                    "纯卡面且无外部素材的成片可以没有这份文件")
        return None

    @staticmethod
    def parse(text: str) -> dict:
        cover_src, _shot_src = ShotList._parts(text)
        shots = [fields for fields, _chunk in ShotList._iter_shots(text)]
        cover = ShotList._fields(cover_src, ShotList.COVER_KEYS)
        chosen = ShotList._cover_type(cover)
        if chosen in ShotList.COVER_TYPES:
            cover["封面类型"] = chosen
        return {"cover": cover, "shots": shots}

    @staticmethod
    def _iter_shots(text: str) -> list[tuple[dict, str]]:
        _cover_src, shot_src = ShotList._parts(text)
        out = []
        for chunk in re.split(r"(?m)^(?=CUT\s*[：:])", shot_src):
            if not chunk.strip().startswith("CUT"):
                continue
            fields = ShotList._fields(chunk, ShotList.SHOT_KEYS)
            fields["no"] = ShotList._cut_no(fields.get("CUT", ""))
            out.append((fields, chunk))
        return out

    @staticmethod
    def _parts(text: str) -> tuple[str, str]:
        body = text
        cut_at = []
        for pat in (r"^###\s*图形提示词写法", r"^##\s*3[\.、\s]"):
            if m := re.search(pat, body, re.M):
                cut_at.append(m.start())
        if cut_at:
            body = body[:min(cut_at)]
        m1 = re.search(r"^##\s*1[\.、\s]", body, re.M)
        m2 = re.search(r"^##\s*2[\.、\s]", body, re.M)
        if m1 and m2 and m1.start() < m2.start():
            return body[m1.end():m2.start()], body[m2.end():]
        if m2:
            return "", body[m2.end():]
        return "", body

    @staticmethod
    def _fields(text: str, keys: frozenset[str]) -> dict[str, str]:
        found: dict[str, str] = {}
        for raw in text.splitlines():
            m = ShotList._FIELD.match(raw.strip())
            if not m:
                continue
            key = ShotList._key(m.group(1))
            if key not in keys:
                continue
            val = m.group(2).strip()
            if key not in found or not ShotList._is_blank(val):
                found[key] = val
        return found

    @staticmethod
    def _key(raw: str) -> str:
        key = re.sub(r"（[^）]*）", "", raw)
        key = re.sub(r"\([^)]*\)", "", key)
        return key.strip()

    @staticmethod
    def _is_blank(value: str) -> bool:
        v = (value or "").strip()
        return (not v) or bool(ShotList._PAREN.fullmatch(v))

    @staticmethod
    def _cut_no(value: str) -> int | None:
        m = re.search(r"\d+", value or "")
        return int(m.group(0)) if m else None

    @staticmethod
    def _label(shot: dict) -> str:
        no = shot.get("no")
        return f"CUT {no:02d}" if isinstance(no, int) else "未编号镜头"

    @staticmethod
    def _seconds(token: str) -> float | None:
        m = ShotList._ONE.fullmatch(token.strip())
        if not m:
            return None
        parts = token.strip().replace(",", ".")
        frac = "0"
        if "." in parts:
            parts, frac = parts.split(".", 1)
        nums = [int(x) for x in parts.split(":")]
        if len(nums) == 3:
            h, mi, s = nums
        elif len(nums) == 2:
            h, mi, s = 0, nums[0], nums[1]
        else:
            return None
        scale = 10 ** len(frac)
        return h * 3600 + mi * 60 + s + int(frac) / scale

    @staticmethod
    def _range(value: str) -> tuple[float, float] | None:
        m = ShotList._RANGE.search(value or "")
        if not m:
            return None
        a, b = ShotList._seconds(m.group("a")), ShotList._seconds(m.group("b"))
        if a is None or b is None:
            return None
        return a, b

    @staticmethod
    def _one_tc(value: str) -> float | None:
        return ShotList._seconds(value or "")

    @staticmethod
    def _license_ok(value: str) -> str:
        """ok / missing / no-terms / no-name。名称和条款页都要有。"""
        if ShotList._is_blank(value):
            return "missing"
        urls = ShotList._URL.findall(value)
        name = ShotList._URL.sub(" ", value).replace("自制", " ")
        name = re.sub(r"[\s（）()；;，,、：:|+/「」]+", "", name)
        if not urls:
            return "no-terms"
        if not name:
            return "no-name"
        return "ok"

    @staticmethod
    def _uses_basemap(shot: dict) -> bool:
        kind = shot.get("画面类型", "").strip()
        if kind == "地图卡":
            return True
        if kind != "数据卡":
            return False
        return bool(ShotList._URL.search(shot.get("来源 URL", ""))
                    or ShotList._URL.search(shot.get("许可", "")))

    @staticmethod
    def _is_yes(value: str) -> bool:
        return bool(ShotList._YES.fullmatch((value or "").strip()))

    @staticmethod
    def _yes_no(value: str) -> bool | None:
        v = (value or "").strip()
        if ShotList._YES.fullmatch(v):
            return True
        if ShotList._NO.fullmatch(v):
            return False
        return None

    @staticmethod
    def _norm(value: str) -> str:
        return re.sub(r"\s+", "", value or "")

    @staticmethod
    def _check_shot(shot: dict, label: str) -> list[str]:
        kind = shot.get("画面类型", "").strip()
        if kind not in ShotList.LIVE and kind not in ShotList.CARD:
            return [f"{label} 画面类型须单选：官方实拍、公有领域、明确许可、地图卡、数据卡"]
        if kind in ShotList.LIVE:
            return ShotList._check_live(shot, label, kind)
        return ShotList._check_card(shot, label, kind)

    @staticmethod
    def _check_live(shot: dict, label: str, kind: str) -> list[str]:
        problems = []
        if not ShotList._URL.search(shot.get("来源 URL", "")):
            problems.append(f"{label} {kind}缺少来源 URL")
        lic = ShotList._license_ok(shot.get("许可", ""))
        if lic == "missing":
            problems.append(f"{label} {kind}缺少许可（须写名称和条款页）")
        elif lic == "no-terms":
            problems.append(f"{label} {kind}的许可缺少条款页")
        elif lic == "no-name":
            problems.append(f"{label} {kind}的许可缺少名称")
        span_raw = shot.get("起止时间", "")
        if ShotList._is_blank(span_raw):
            problems.append(f"{label} {kind}缺少起止时间")
        elif span_raw.strip() == "自制":
            problems.append(f"{label} {kind}的起止时间不能写「自制」，须写素材入点–出点")
        elif ShotList._range(span_raw) is None:
            problems.append(f"{label} {kind}的起止时间无法识别")
        return problems

    @staticmethod
    def _check_card(shot: dict, label: str, kind: str) -> list[str]:
        problems = []
        span_raw = shot.get("起止时间", "").strip()
        if ShotList._is_blank(span_raw):
            problems.append(f"{label} {kind}缺少起止时间（可写「自制」）")
        elif span_raw != "自制" and ShotList._range(span_raw) is None:
            problems.append(f"{label} {kind}的起止时间无法识别")
        if ShotList._uses_basemap(shot):
            if not ShotList._URL.search(shot.get("来源 URL", "")):
                problems.append(f"{label} {kind}使用了底图，但缺少来源 URL")
            if ShotList._license_ok(shot.get("许可", "")) != "ok":
                problems.append(f"{label} {kind}使用了底图，许可须写明底图名称和条款页")
        else:
            lic = shot.get("许可", "")
            if ShotList._is_blank(lic):
                problems.append(f"{label} {kind}缺少许可（可写「自制」）")
            elif lic.strip() != "自制" and ShotList._license_ok(lic) != "ok":
                problems.append(f"{label} {kind}的许可须写「自制」，或写明名称和条款页")
        return problems

    @staticmethod
    def _check_hook(shots: list[dict], numbered: list[int]) -> list[str]:
        ones = [s for s in shots if s.get("no") == 1]
        if len(ones) != 1:
            if numbered.count(1) > 1:
                return ["CUT 01 重复，无法确认前 15 秒事实钩子由哪一镜覆盖"]
            return ["缺少 CUT 01，快讯线须由 CUT 01 覆盖前 15 秒事实钩子"]
        span = ShotList._range(ones[0].get("时码", ""))
        if span is None or span[0] > 0.05 or span[1] < ShotList.HOOK_S:
            shown = ones[0].get("时码", "") or "（空）"
            return [f"CUT 01 时码 {shown} 未覆盖前 15 秒事实钩子"
                    "（须从 0 覆盖到至少 15 秒）"]
        return []

    @staticmethod
    def _selection_types(text: str) -> list[str]:
        """「封面类型：」后面点名的封面类型。

        「封面类型必须二选一，写明「纯文字封面」或「图形设计封面」」这种
        说明句没有冒号，两边都点到，不算已经选定。
        """
        found: list[str] = []
        for match in re.finditer(r"封面类型\s*[：:]\s*([^\n]*)", text or ""):
            value = match.group(1)
            for token in ("纯文字封面", "图形设计封面"):
                if token in value and token not in found:
                    found.append(token)
        return found

    @staticmethod
    def _cover_type(fields: dict) -> str:
        explicit = (fields.get("封面类型") or "").strip().strip("「」\"'“”")
        if explicit in ShotList.COVER_TYPES:
            explicit_choice: str | None = explicit
        elif explicit:
            named = [token for token in ("纯文字封面", "图形设计封面") if token in explicit]
            if len(named) == 1:
                explicit_choice = named[0]
            elif len(named) > 1:
                return ""
            else:
                return explicit
        else:
            explicit_choice = None
        nested = ShotList._selection_types(fields.get("若不指定", ""))
        nested_choice: str | None
        if len(nested) == 1:
            nested_choice = nested[0]
        elif len(nested) > 1:
            return ""
        else:
            nested_choice = None
        if explicit_choice and nested_choice and explicit_choice != nested_choice:
            return ""
        if explicit_choice:
            return explicit_choice
        if nested_choice:
            return nested_choice
        exact = []
        for val in fields.values():
            token = val.strip().strip("「」\"'“”")
            if token in ShotList.COVER_TYPES and token not in exact:
                exact.append(token)
        return exact[0] if len(exact) == 1 else ""

    @staticmethod
    def _check_cover(fields: dict, shots: list[dict],
                     per_shot: dict[int, list[str]]) -> list[str]:
        specified = ShotList._yes_no(fields.get("是否指定素材静帧", ""))
        if specified is None:
            return ["封面未写明是否指定素材静帧（须填「是」或「否」）"]
        if not specified:
            problems = []
            if ShotList._cover_type(fields) not in ShotList.COVER_TYPES:
                problems.append("未指定素材静帧时，封面类型必须是「纯文字封面」或「图形设计封面」")
            if ShotList._URL.search(fields.get("画面来源 URL", "")):
                problems.append("未指定素材静帧，不得另附画面来源 URL")
            return problems
        return ShotList._check_specified_cover(fields, shots, per_shot)

    @staticmethod
    def _check_specified_cover(fields: dict, shots: list[dict],
                               per_shot: dict[int, list[str]]) -> list[str]:
        problems = []
        url = fields.get("画面来源 URL", "")
        lic = fields.get("许可", "")
        tc = ShotList._one_tc(fields.get("精确时码", ""))
        no = ShotList._cut_no(fields.get("对应 CUT", ""))
        if not ShotList._URL.search(url):
            problems.append("封面指定了素材静帧，但缺少画面来源 URL")
        lic_state = ShotList._license_ok(lic)
        if lic_state != "ok":
            problems.append("封面指定了素材静帧，但许可须同时写名称和条款页")
        if tc is None:
            problems.append("封面指定了素材静帧，但缺少精确时码")
        if no is None:
            problems.append("封面指定了素材静帧，但缺少对应 CUT")
            return problems
        shot = next((s for s in shots if s.get("no") == no), None)
        if shot is None:
            problems.append(f"封面对应 CUT {no:02d} 不在分镜里")
            return problems
        if per_shot.get(no):
            problems.append(f"封面对应的 CUT {no:02d} 未过许可门")
        elif tc is not None and lic_state == "ok" and ShotList._URL.search(url):
            if ShotList._norm(url) != ShotList._norm(shot.get("来源 URL", "")):
                problems.append(f"封面画面来源 URL 与 CUT {no:02d} 不一致")
            if ShotList._norm(lic) != ShotList._norm(shot.get("许可", "")):
                problems.append(f"封面许可与 CUT {no:02d} 不一致")
            span = ShotList._range(shot.get("起止时间", ""))
            if span is None or abs(tc - span[0]) > 0.02:
                problems.append(f"封面精确时码与 CUT {no:02d} 的素材入点不一致")
        if not ShotList._is_yes(shot.get("指定封面", "")):
            problems.append(f"CUT {no:02d} 的指定封面须为「是」，并与封面栏一致")
        return problems

    # ---------------------------------------------------------------- 生成

    @staticmethod
    def generate(pid: str) -> str:
        """红审通过后，把线索包里已有的字段映射成分镜清单。不写盘。"""
        block = ShotList._red_review_block(pid)
        if block:
            raise RuntimeError(block)
        return ShotList._render_doc(pid, ShotList._package(pid))

    @staticmethod
    def write(pid: str) -> Path:
        """生成并写入项目目录。生成结果自己也要过字段门，否则不落盘。"""
        from src import store
        text = ShotList.generate(pid)
        found = ShotList.problems(text)
        if found:
            raise RuntimeError("生成的分镜清单未过许可门：" + "；".join(found))
        path = store.project_dir(pid) / ShotList.FILENAME
        path.write_text(text, encoding="utf-8")
        return path

    @staticmethod
    def _red_review_block(pid: str) -> str | None:
        """锤稿未通过，或线索包写明退回，都不生成。"""
        from src import store
        from src.jsonio import load_json
        pdir = store.project_dir(pid)
        md = ""
        md_path = pdir / "briefing.md"
        if md_path.is_file():
            md = md_path.read_text(encoding="utf-8")
        status = ShotList._labeled(md, "红审状态")
        if status.startswith("退回") or "不通过" in status:
            return "红审状态为退回，不生成分镜清单"
        hammer = load_json(pdir / "hammer.json") or {}
        if hammer.get("status") not in ShotList.PASSED_REVIEW:
            return "红审未通过，不生成分镜清单"
        return None

    @staticmethod
    def _package(pid: str) -> dict:
        """只读线索包里已经写明的字段。口播稿不拿来补事实，人工稿除外。"""
        from src import store
        from src.jsonio import load_json
        pdir = store.project_dir(pid)
        brief = load_json(pdir / "briefing.json") or {}
        script = load_json(pdir / "script.json") or {}
        md = ""
        if (pdir / "briefing.md").is_file():
            md = (pdir / "briefing.md").read_text(encoding="utf-8")
        intro = brief.get("简介") if isinstance(brief.get("简介"), dict) else {}
        header = {
            "title": (ShotList._labeled(md, "标题")
                      or str(brief.get("标题") or brief.get("title") or "")).strip(),
            "hook": (ShotList._labeled(md, "事实钩子")
                     or str(brief.get("事实钩子") or brief.get("hook") or "")).strip(),
            "time_place": (ShotList._labeled(md, "时间地点")
                           or str(intro.get("时间地点") or brief.get("时间地点") or "")).strip(),
            "what": (ShotList._labeled(md, "发生了什么")
                     or str(intro.get("发生了什么") or brief.get("发生了什么") or "")).strip(),
            "voices": (ShotList._labeled(md, "各方怎么说")
                       or str(intro.get("各方怎么说") or brief.get("各方怎么说") or "")).strip(),
            "attrib": (ShotList._labeled(md, "信源署名")
                       or str(intro.get("信源署名") or brief.get("信源署名") or "")).strip(),
            "version": str(brief.get("source") or "").strip(),
        }
        items = ShotList._items(brief, script)
        md_footage = ShotList._markdown_footage(md)
        if md_footage and items:
            ShotList._attach_markdown_footage(items, md_footage)
        elif md_footage and not items:
            items = [{"title": "", "summary": header["what"] or header["hook"],
                      "event_time": header["time_place"], "sources": [],
                      "footage": md_footage[0]}]
        return {"header": header, "items": items, "script": script}

    @staticmethod
    def _labeled(md: str, key: str) -> str:
        if not md:
            return ""
        pat = re.compile(
            rf"(?m)^\s*(?:[-*]\s*)?(?:\*\*)?{re.escape(key)}"
            rf"(?:（[^）]*）)?(?:\*\*)?\s*[:：]\s*(.*?)\s*$")
        m = pat.search(md)
        return m.group(1).strip() if m else ""

    @staticmethod
    def _items(brief: dict, script: dict) -> list[dict]:
        raw = [it for it in (brief.get("items") or []) if isinstance(it, dict)]
        if raw:
            refs = [s.get("item_ref") for s in script.get("segments") or []
                    if isinstance(s, dict) and s.get("kind") == "item"]
            keep = None
            if refs and all(isinstance(r, int) and not isinstance(r, bool) and r > 0
                            for r in refs):
                keep = set(refs)
            excluded = set(brief.get("excluded_refs") or [])
            out = []
            for i, it in enumerate(raw, 1):
                if i in excluded or (keep is not None and i not in keep):
                    continue
                sources = []
                for src in it.get("sources") or []:
                    if not isinstance(src, dict):
                        continue
                    name = str(src.get("name") or "").strip()
                    if name in {"见链接", "见原文"}:
                        name = ""
                    sources.append({
                        "name": name,
                        "claim": str(src.get("claim") or "").strip(),
                        "url": str(src.get("url") or "").strip(),
                    })
                out.append({
                    "title": ShotList._strip_badge(str(it.get("title") or "")),
                    "summary": str(it.get("summary") or "").strip(),
                    "event_time": str(it.get("event_time") or "").strip(),
                    "sources": sources,
                    "footage": ShotList._footage_of(it),
                })
            return out
        if (script.get("meta") or {}).get("mode") == "manual":
            out = []
            for seg in script.get("segments") or []:
                if not isinstance(seg, dict) or seg.get("kind") == "outro":
                    continue
                text = str(seg.get("narration") or "").strip()
                if text:
                    out.append({"title": "", "summary": text, "event_time": "",
                                "sources": [], "footage": None})
            if out and not any(it["title"] for it in out):
                title = str(script.get("title") or "").strip()
                if title:
                    out[0]["title"] = title
            return out
        return []

    @staticmethod
    def _strip_badge(title: str) -> str:
        return re.sub(r"【[^】]*】", "", title).strip()

    @staticmethod
    def _footage_of(item: dict) -> dict | None:
        raw = item.get("footage") if isinstance(item.get("footage"), dict) else item
        kind = str(raw.get("画面类型") or "").strip()
        if kind not in ShotList.LIVE and kind not in ShotList.CARD:
            return None
        keys = ("画面类型", "来源 URL", "许可", "起止时间", "时码",
                "素材文件", "指定封面", "精确时码", "对应事实")
        return {k: str(raw.get(k) or "").strip() for k in keys}

    @staticmethod
    def _markdown_footage(md: str) -> list[dict]:
        """briefing.md 里单独写明的已核对画面。不从散文里猜。"""
        if not md or "画面类型" not in md:
            return []
        blocks = re.split(r"(?m)^(?=\s*(?:[-*]\s*)?画面类型\s*[:：])", md)
        out = []
        keys = ("画面类型", "来源 URL", "许可", "起止时间", "时码",
                "素材文件", "指定封面", "精确时码", "对应事实")
        for block in blocks[1:]:
            # 只取这一块到空行或下一个标题，避免把后文句子吞进来
            lines = []
            for ln in block.splitlines():
                if lines and (not ln.strip() or ln.startswith("#")):
                    break
                lines.append(ln)
            fields = {k: ShotList._labeled("\n".join(lines), k) for k in keys}
            if fields["画面类型"] in ShotList.LIVE or fields["画面类型"] in ShotList.CARD:
                out.append(fields)
        return out

    @staticmethod
    def _attach_markdown_footage(items: list[dict], blocks: list[dict]) -> None:
        used = set()
        for block in blocks:
            fact = block.get("对应事实") or ""
            target = None
            if fact:
                for i, it in enumerate(items):
                    if i in used:
                        continue
                    blob = it["title"] + it["summary"]
                    if fact in blob or any(fact in s["claim"] for s in it["sources"]):
                        target = i
                        break
            if target is None:
                for i, it in enumerate(items):
                    if i not in used and not it.get("footage"):
                        target = i
                        break
            if target is None:
                continue
            used.add(target)
            if not items[target].get("footage"):
                items[target]["footage"] = block

    @staticmethod
    def _sentences(text: str) -> list[str]:
        text = (text or "").strip()
        if not text:
            return []
        parts = re.split(r"(?<=[。！？])", text)
        out = []
        for part in parts:
            sent = part.strip()
            if sent and re.sub(r"[。！？；，、\s]", "", sent):
                out.append(sent)
        return out or [text]

    @staticmethod
    def _named_sources(item: dict) -> str:
        names = []
        for src in item.get("sources") or []:
            name = src.get("name") or ""
            if name and name not in names:
                names.append(name)
        return "、".join(names)

    @staticmethod
    def _live_complete(footage: dict | None) -> bool:
        if not footage or footage.get("画面类型") not in ShotList.LIVE:
            return False
        if not ShotList._URL.search(footage.get("来源 URL", "")):
            return False
        if ShotList._license_ok(footage.get("许可", "")) != "ok":
            return False
        span_raw = footage.get("起止时间", "")
        if ShotList._is_blank(span_raw) or span_raw.strip() == "自制":
            return False
        return ShotList._range(span_raw) is not None

    @staticmethod
    def _card_picture(footage: dict | None) -> dict:
        """未过门的实拍改图卡。地图卡用 Natural Earth，不抄未核验的实拍 URL。"""
        kind = (footage or {}).get("画面类型", "")
        if kind == "数据卡" and not ShotList._live_complete(footage):
            url = (footage or {}).get("来源 URL", "")
            lic = (footage or {}).get("许可", "")
            if (ShotList._URL.search(url) and ShotList._license_ok(lic) == "ok"):
                span = (footage or {}).get("起止时间", "").strip()
                if span != "自制" and ShotList._range(span) is None:
                    span = "自制"
                return {"画面类型": "数据卡", "来源 URL": url.strip(),
                        "许可": lic.strip(), "起止时间": span or "自制"}
            return {"画面类型": "数据卡", "来源 URL": "", "许可": "自制",
                    "起止时间": "自制"}
        explicit_map = kind == "地图卡"
        if explicit_map:
            url = (footage or {}).get("来源 URL", "")
            lic = (footage or {}).get("许可", "")
            if ShotList._URL.search(url) and ShotList._license_ok(lic) == "ok":
                return {"画面类型": "地图卡", "来源 URL": url.strip(),
                        "许可": lic.strip(), "起止时间": "自制"}
        return {"画面类型": "地图卡", "来源 URL": ShotList.NE_URL,
                "许可": ShotList.NE_LIC, "起止时间": "自制"}

    @staticmethod
    def _picture(footage: dict | None) -> dict:
        if ShotList._live_complete(footage):
            return {"画面类型": footage["画面类型"],
                    "来源 URL": footage["来源 URL"].strip(),
                    "许可": footage["许可"].strip(),
                    "起止时间": footage["起止时间"].strip(),
                    "时码": footage.get("时码", "").strip()
                    if ShotList._range(footage.get("时码", "")) else "",
                    "素材文件": footage.get("素材文件", "").strip(),
                    "精确时码": footage.get("精确时码", "").strip()}
        pic = ShotList._card_picture(footage)
        pic["时码"] = ""
        pic["素材文件"] = ""
        pic["精确时码"] = ""
        return pic

    @staticmethod
    def _units(items: list[dict]) -> list[dict]:
        units = []
        for item in items:
            sents = ShotList._sentences(item.get("summary") or "")
            if not sents and item.get("title"):
                sents = [item["title"]]
            attrib = ShotList._named_sources(item)
            for sent in sents:
                units.append({"事实句": sent, "出处": attrib,
                              "footage": item.get("footage"),
                              "item": item})
            for src in item.get("sources") or []:
                claim = src.get("claim") or ""
                if not claim:
                    continue
                # 这句说法已经写在事实句里就不再拆一镜，也不另造一句引语。
                if any(claim == sent or claim in sent for sent in sents):
                    continue
                units.append({"事实句": claim, "出处": src.get("name") or "",
                              "footage": None, "item": item})
        return units

    @staticmethod
    def _footage_matches(unit: dict) -> bool:
        footage = unit.get("footage")
        if not footage:
            return False
        fact = footage.get("对应事实") or ""
        if not fact:
            return True
        return fact in unit["事实句"] or unit["事实句"] in fact

    @staticmethod
    def _take_footage(unit: dict) -> dict | None:
        """一条已核对画面只挂到第一句对得上的事实句上。"""
        footage = unit.get("footage")
        if not footage or footage.get("_used") or not ShotList._footage_matches(unit):
            return None
        footage["_used"] = True
        return footage

    @staticmethod
    def _build_shots(header: dict, items: list[dict]) -> list[dict]:
        units = ShotList._units(items)
        hook = header.get("hook") or (units[0]["事实句"] if units else "")
        if not hook:
            what = header.get("what") or ""
            sents = ShotList._sentences(what)
            if sents:
                hook = sents[0]
                if not units:
                    units = [{"事实句": s, "出处": header.get("attrib") or "",
                              "footage": None, "item": None} for s in sents]
        if not hook:
            raise RuntimeError("线索包没有事实钩子，也没有事实句，不生成分镜清单")
        shots: list[dict] = []
        first = units[0] if units else None
        hook_is_first = bool(first and first["事实句"] == hook)
        first_live = bool(
            hook_is_first and first and ShotList._live_complete(first.get("footage"))
            and ShotList._footage_matches(first))
        # CUT 01 固定是事实钩子图卡，盖住前 15 秒。已过门的实拍另成一镜再剪入，
        # 避免把短于 15 秒的素材硬写成钩子时码。
        hook_attrib = ""
        if hook_is_first and first:
            hook_attrib = first["出处"]
        elif header.get("attrib"):
            hook_attrib = header["attrib"]
        shots.append(ShotList._make_shot(hook, hook_attrib, None, "开头钩子"))
        rest = units[1:] if hook_is_first else list(units)
        if first_live and first is not None:
            rest = [first, *rest]
        for unit in rest:
            shots.append(ShotList._make_shot(
                unit["事实句"], unit["出处"], ShotList._take_footage(unit), "正文"))
        for i, shot in enumerate(shots, 1):
            shot["no"] = i
            if i == 1:
                shot["时码"] = ShotList.HOOK_TC
        return shots

    @staticmethod
    def _make_shot(fact: str, attrib: str, footage: dict | None, role: str) -> dict:
        pic = ShotList._picture(footage)
        return {"事实句": fact, "出处": attrib, "镜类": role,
                "字幕": fact, "指定封面": "否", **pic}

    @staticmethod
    def _fill_header(header: dict, items: list[dict]) -> dict:
        """缺的简介只拼接线索包里已有的句子，不补评论。"""
        out = dict(header)
        if not out["title"]:
            out["title"] = next((it["title"] for it in items if it.get("title")), "")
        if not out["time_place"]:
            times = [it["event_time"] for it in items if it.get("event_time")]
            out["time_place"] = "；".join(dict.fromkeys(times))
        if not out["what"]:
            summaries = [it["summary"] for it in items if it.get("summary")]
            out["what"] = "；".join(summaries)
        if not out["voices"]:
            bits = []
            for it in items:
                for src in it.get("sources") or []:
                    if src.get("claim"):
                        prefix = f"{src['name']}：" if src.get("name") else ""
                        bits.append(prefix + src["claim"])
            out["voices"] = "；".join(bits)
        if not out["attrib"]:
            names = []
            for it in items:
                for src in it.get("sources") or []:
                    if src.get("name") and src["name"] not in names:
                        names.append(src["name"])
            out["attrib"] = "、".join(names)
        return out

    @staticmethod
    def _cover_block(shots: list[dict], header: dict) -> tuple[list[str], list[dict]]:
        """默认图形设计封面。只有某一镜已经带齐过门静帧四项才指定。"""
        shots = [dict(s) for s in shots]
        chosen = None
        for shot in shots:
            if shot["画面类型"] not in ShotList.LIVE:
                continue
            tc = ShotList._one_tc(shot.get("精确时码", ""))
            span = ShotList._range(shot.get("起止时间", ""))
            if tc is None or span is None or abs(tc - span[0]) > 0.02:
                continue
            if ShotList._license_ok(shot.get("许可", "")) != "ok":
                continue
            if not ShotList._URL.search(shot.get("来源 URL", "")):
                continue
            chosen = shot
            break
        title = header.get("title") or ""
        sub = header.get("hook") or (shots[0]["事实句"] if shots else "")
        if chosen is None:
            for shot in shots:
                shot["指定封面"] = "否"
                shot["精确时码"] = ""
            lines = [
                "- 是否指定素材静帧：否",
                "- 封面类型：图形设计封面",
                f"- 主标题 / 事实副题：{title} / {sub}",
            ]
            return lines, shots
        chosen["指定封面"] = "是"
        lines = [
            "- 是否指定素材静帧：是",
            f"- 对应 CUT：{chosen['no']:02d}",
            f"- 画面来源 URL：{chosen['来源 URL']}",
            f"- 许可（名称 + 条款页）：{chosen['许可']}",
            f"- 精确时码（素材入点；精确到秒，能到帧更好）：{chosen['精确时码']}",
            f"- 主标题 / 事实副题：{title} / {sub}",
        ]
        return lines, shots

    @staticmethod
    def _locked_tokens(fact: str, source: str) -> str:
        from src.cards import ALIAS, CORE_ISO, GAZETTEER
        names = sorted(set(GAZETTEER) | set(ALIAS) | set(CORE_ISO.values()),
                       key=len, reverse=True)
        spans: list[tuple[int, str]] = []
        for rx in (re.compile(r"\d{4}年\d{1,2}月\d{1,2}日|\d{1,2}月\d{1,2}日|\d{4}-\d{2}-\d{2}"),
                   re.compile(r"\d+(?:\.\d+)?%?")):
            spans.extend((m.start(), m.group()) for m in rx.finditer(fact or ""))
        for name in names:
            start = 0
            while name and (i := (fact or "").find(name, start)) >= 0:
                spans.append((i, name))
                start = i + len(name)
        if source:
            idx = (fact or "").find(source)
            spans.append((idx if idx >= 0 else 10**9, source))
        spans.sort(key=lambda x: (x[0], -len(x[1])))
        out: list[str] = []
        for _pos, tok in spans:
            if tok and tok not in out:
                out.append(tok)
        return "、".join(out) if out else "无"

    @staticmethod
    def _prompt(shot: dict) -> str:
        if shot["画面类型"] in ShotList.LIVE:
            return "图形提示词: 无"
        window = ("0.0–15.0 出示锁定元素与出处" if shot["no"] == 1
                  else "出示锁定元素与出处")
        locked = ShotList._locked_tokens(shot["事实句"], shot.get("出处", ""))
        return "\n".join([
            "图形提示词:",
            "  总规格: 16:9，卡面或地图，信息图风格，无人物演绎",
            f"  锁定元素: {locked}",
            f"  按秒分镜: {window}",
            "  禁止项: 不生成冲突或灾难现场，不出现线索包没有的人物表情，"
            "不加预测性标题，不把库存空镜标成事发现场",
        ])

    @staticmethod
    def _render_doc(pid: str, pkg: dict) -> str:
        header = ShotList._fill_header(pkg["header"], pkg["items"])
        if not header["hook"]:
            header["hook"] = ""
        shots = ShotList._build_shots(header, pkg["items"])
        if shots and not header["hook"]:
            header["hook"] = shots[0]["事实句"]
        cover_lines, shots = ShotList._cover_block(shots, header)
        blocks = []
        for shot in shots:
            lines = [
                f"CUT: {shot['no']:02d}",
                f"时码: {shot['时码']}",
                f"镜类: {shot['镜类']}",
                f"事实句: {shot['事实句']}",
                f"出处: {shot['出处']}",
                f"画面类型: {shot['画面类型']}",
                f"来源 URL: {shot['来源 URL']}",
                f"许可: {shot['许可']}",
                f"起止时间: {shot['起止时间']}",
                f"字幕: {shot['字幕']}",
                f"指定封面: {shot['指定封面']}",
            ]
            if shot.get("素材文件"):
                lines.append(f"素材文件: {shot['素材文件']}")
            lines.append(ShotList._prompt(shot))
            lines.append("禁止: 不虚构现场；不添加线索包没有的情节或表情；"
                         "不用未授权的电视、通讯社或新闻网站成片；不站队、不预测")
            blocks.append("\n".join(lines))
        head = [
            "# 线索包 → 分镜清单",
            "",
            "## 0. 片子头",
            "",
            "- 产线：时政快讯",
            f"- 期号 / 工作名：{pid}",
            f"- 标题（只写发生了什么）：{header['title']}",
            f"- 事实钩子（前 15 秒口播，只讲发生了什么，不用栏目名或预判）：{header['hook']}",
            "- 简介：",
            f"  - 时间地点：{header['time_place']}",
            f"  - 发生了什么：{header['what']}",
            f"  - 各方怎么说：{header['voices']}",
            f"  - 信源署名：{header['attrib']}",
            f"- 线索包版本：{header['version']}",
            "- 红审状态：通过",
            "- 预估时长：",
            "",
            "## 1. 封面（必填，单独成栏）",
            "",
            *cover_lines,
            "",
            "## 2. 分镜（每一镜一张，缺一项不进渲染）",
            "",
            "\n\n".join(blocks),
            "",
        ]
        return "\n".join(head)

    # ---------------------------------------------------------------- 实拍剪入

    @staticmethod
    def external_live(pid: str) -> bool:
        """项目会不会带上外部实拍：footage 里有片子，或线索包写了实拍条目。"""
        from src import store
        from src.jsonio import load_json
        pdir = store.project_dir(pid)
        folder = pdir / "footage"
        if folder.is_dir() and any(
                p.is_file() and p.suffix.lower() in ShotList.VIDEO_EXT
                for p in folder.rglob("*")):
            return True
        if any(p.is_file() and p.suffix.lower() in ShotList.VIDEO_EXT
               for p in pdir.iterdir()):
            return True
        md_path = pdir / "briefing.md"
        if md_path.is_file():
            md = md_path.read_text(encoding="utf-8")
            if re.search(r"画面类型\s*[:：]\s*(官方实拍|公有领域|明确许可)", md):
                return True
            if re.search(r"(?m)^(?:[-*]\s*)?素材文件\s*[:：]\s*\S+", md):
                return True
        if ShotList._json_live(load_json(pdir / "briefing.json")):
            return True
        return False

    @staticmethod
    def _json_live(obj) -> bool:
        if isinstance(obj, dict):
            if str(obj.get("画面类型") or "").strip() in ShotList.LIVE:
                return True
            if str(obj.get("素材文件") or "").strip():
                return True
            return any(ShotList._json_live(v) for v in obj.values())
        if isinstance(obj, list):
            return any(ShotList._json_live(v) for v in obj)
        return False

    @staticmethod
    def _media_line(chunk: str) -> str:
        m = re.search(r"(?m)^(?:[-*]\s*)?素材文件\s*[:：]\s*(\S+)\s*$", chunk)
        return m.group(1).strip() if m else ""

    @staticmethod
    def _under_project(pdir: Path, path: Path) -> bool:
        try:
            path.resolve().relative_to(pdir.resolve())
        except ValueError:
            return False
        return True

    @staticmethod
    def _is_produced(pdir: Path, path: Path) -> bool:
        try:
            rel = path.resolve().relative_to(pdir.resolve())
        except ValueError:
            return False
        return bool(rel.parts) and rel.parts[0] in ShotList.PRODUCED_DIRS

    @staticmethod
    def _resolve_media(pid: str, no: int, chunk: str) -> tuple[Path | None, str]:
        """返回 (路径, 错误)。路径为空且错误为空表示这条不是实拍。"""
        from src import store
        pdir = store.project_dir(pid)
        rel = ShotList._media_line(chunk)
        if rel:
            path = (pdir / rel).resolve()
            label = f"CUT {no:02d}" if isinstance(no, int) else "未编号镜头"
            if not ShotList._under_project(pdir, path):
                return None, f"{label} 的素材文件不在项目目录内"
            if ShotList._is_produced(pdir, path):
                return None, (f"{label} 的素材指向成片或产出目录，"
                              "不能当作外部实拍剪入")
            if (not path.is_file() or path.suffix.lower() not in ShotList.VIDEO_EXT):
                return None, (f"{label} 已过许可门，但项目里没有可剪的本地素材"
                              "（不从成片或网络抓取）")
            return path, ""
        if not isinstance(no, int):
            return None, "未编号镜头已过许可门，但项目里没有可剪的本地素材"
        folder = pdir / "footage"
        if folder.is_dir():
            for path in sorted(folder.glob(f"CUT-{no:02d}.*")):
                if (path.is_file() and path.suffix.lower() in ShotList.VIDEO_EXT
                        and not ShotList._is_produced(pdir, path)):
                    return path.resolve(), ""
        label = f"CUT {no:02d}"
        return None, (f"{label} 已过许可门，但项目里没有可剪的本地素材"
                      "（不从成片或网络抓取）")

    @staticmethod
    def _collect_cuts(pid: str, text: str) -> tuple[list[dict], list[str]]:
        cuts = []
        problems = []
        for shot, chunk in ShotList._iter_shots(text):
            kind = shot.get("画面类型", "").strip()
            if kind not in ShotList.LIVE:
                continue
            no = shot.get("no")
            label = f"CUT {no:02d}" if isinstance(no, int) else "未编号镜头"
            program = ShotList._range(shot.get("时码", ""))
            source = ShotList._range(shot.get("起止时间", ""))
            if program is None:
                problems.append(f"{label} 缺少成片时码，不能剪入")
                continue
            if source is None:
                problems.append(f"{label} 缺少素材起止时间，不能剪入")
                continue
            if abs((program[1] - program[0]) - (source[1] - source[0])) > ShotList.DUR_TOL:
                problems.append(f"{label} 的成片时码长度与素材起止不一致，不能剪入")
                continue
            path, err = ShotList._resolve_media(pid, no if isinstance(no, int) else -1, chunk)
            if err or path is None:
                problems.append(err or f"{label} 已过许可门，但项目里没有可剪的本地素材")
                continue
            cuts.append({"no": no, "start": program[0], "end": program[1],
                         "src_in": source[0], "src_out": source[1],
                         "path": str(path)})
        cuts.sort(key=lambda c: c["start"])
        for prev, nxt in zip(cuts, cuts[1:]):
            if nxt["start"] < prev["end"] - ShotList.DUR_TOL:
                problems.append(
                    f"CUT {prev['no']:02d} 与 CUT {nxt['no']:02d} 的成片时码重叠")
        return cuts, problems

    @staticmethod
    def _cut_problems(pid: str, text: str) -> list[str]:
        _cuts, problems = ShotList._collect_cuts(pid, text)
        return problems

    @staticmethod
    def live_cuts(pid: str) -> list[dict]:
        """已过门、且能剪入的实拍。没有清单或字段未过门时为空，不在这里补画面。"""
        from src import store
        path = store.project_dir(pid) / ShotList.FILENAME
        if not path.is_file():
            return []
        text = path.read_text(encoding="utf-8")
        if ShotList.problems(text):
            return []
        cuts, problems = ShotList._collect_cuts(pid, text)
        if problems:
            return []
        return cuts

    @staticmethod
    def visual_pieces(tl: dict) -> list[dict]:
        """把已过门的实拍按成片时码嵌进卡片时间轴。没有实拍时一段卡片仍是一段。"""
        cuts = sorted(tl.get("live_cuts") or [], key=lambda c: c["start"])
        pieces = []
        for seg in tl.get("segments") or []:
            seg_s = float(seg["start"])
            seg_e = round(seg_s + float(seg["length"]), 3)
            cursor = seg_s
            for cut in cuts:
                if cut["end"] <= cursor + 1e-3 or cut["start"] >= seg_e - 1e-3:
                    continue
                a = round(max(cut["start"], cursor), 3)
                b = round(min(cut["end"], seg_e), 3)
                if a > cursor + 1e-3:
                    pieces.append({"kind": "card", "seg": seg, "start": round(cursor, 3),
                                   "length": round(a - cursor, 3)})
                pieces.append({
                    "kind": "live", "seg": seg, "no": cut["no"],
                    "start": a, "length": round(b - a, 3),
                    "src_in": round(cut["src_in"] + (a - cut["start"]), 3),
                    "path": cut["path"],
                })
                cursor = b
            if seg_e > cursor + 1e-3:
                pieces.append({"kind": "card", "seg": seg, "start": round(cursor, 3),
                               "length": round(seg_e - cursor, 3)})
        return pieces

    @staticmethod
    def placement_problems(tl: dict) -> list[str]:
        """实拍的成片时码必须整段落在节目时长里，不能只核字段不剪进去。"""
        total = float(tl.get("total_s") or 0)
        pieces = ShotList.visual_pieces(tl)
        problems = []
        for cut in tl.get("live_cuts") or []:
            no = cut["no"]
            label = f"CUT {no:02d}" if isinstance(no, int) else "未编号镜头"
            if cut["start"] < -0.02 or cut["end"] > total + ShotList.DUR_TOL:
                problems.append(f"{label} 的成片时码超出节目时长，不能剪入")
                continue
            covered = round(sum(p["length"] for p in pieces
                                if p["kind"] == "live" and p.get("no") == no), 3)
            need = round(cut["end"] - cut["start"], 3)
            if abs(covered - need) > ShotList.DUR_TOL:
                problems.append(f"{label} 未能按成片时码剪入时间轴")
        return problems
