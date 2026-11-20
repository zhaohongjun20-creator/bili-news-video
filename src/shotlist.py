# -*- coding: utf-8 -*-
"""分镜清单许可门。规则原文在 docs/线索包-分镜清单-标准模板.md
与 docs/合法画面来源规则.md。这里只核对字段，不解释法律，也不抓取画面。

项目目录里有「分镜清单.md」时，渲染前必须过门；没有这份文件时不拦截
（现有纯卡面路径不摄入外部实拍）。
"""
import re


class ShotList:
    """标准分镜清单的解析和许可门。检查都是静态方法。"""

    FILENAME = "分镜清单.md"
    LIVE = frozenset({"官方实拍", "公有领域", "明确许可"})
    CARD = frozenset({"地图卡", "数据卡"})
    COVER_TYPES = frozenset({"纯文字封面", "图形设计封面"})
    HOOK_S = 15.0

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
        """项目里有分镜清单且未过门时，返回拒绝渲染的原因。"""
        from src import store
        path = store.project_dir(pid) / ShotList.FILENAME
        if not path.is_file():
            return None
        found = ShotList.problems(path.read_text(encoding="utf-8"))
        if not found:
            return None
        return "分镜清单未过许可门，不进渲染：" + "；".join(found)

    @staticmethod
    def parse(text: str) -> dict:
        cover_src, shot_src = ShotList._parts(text)
        shots = []
        for chunk in re.split(r"(?m)^(?=CUT\s*[：:])", shot_src):
            if not chunk.strip().startswith("CUT"):
                continue
            fields = ShotList._fields(chunk, ShotList.SHOT_KEYS)
            fields["no"] = ShotList._cut_no(fields.get("CUT", ""))
            shots.append(fields)
        return {"cover": ShotList._fields(cover_src, ShotList.COVER_KEYS),
                "shots": shots}

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
    def _cover_type(fields: dict) -> str:
        raw = fields.get("封面类型", "").strip().strip("「」\"'“”")
        if raw:
            return raw
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
