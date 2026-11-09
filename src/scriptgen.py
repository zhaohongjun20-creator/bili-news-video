# -*- coding: utf-8 -*-
"""逐字稿生成：briefing.json → script.json（口播文本 + 每段卡片字段）。

主路：GLM 一次生成全稿（含卡片字段）。降级：确定性模板拼稿——新闻快讯
结构固定（开场→逐条→涉华→主线→收尾），模板稿可用，只是不如 GLM 灵动。
口播语速按 4.5 字/秒估算段时长，配音后以实测音频时长为准。
"""
import datetime as _dt
import re

from src import ingest, redlines, store
from src.config import api_keys, load_config
from src.glm_client import chat_json_ex
from src.jsonio import load_json, save_json

SEC_PER_CHAR = 1 / 4.5

_PROMPT = """你是中文军事地缘快讯栏目的主编。栏目「{show}」，只讲"发生了什么"和
"各方怎么说"，不站队、不评论、不预测。语速约 4.5 字/秒，全片目标 {target_s} 秒左右。

红线（违反即废稿）：
1. 不出现：抗议/游行/示威/罢工/骚乱/镇压/警力部署等社会运动叙事；伤亡画面化描写。
2. 不做预测（"将会引发/必将/恐怕会"一律改成"各方关注/有待观察"）。
3. 不站队定性；涉华内容必须以官方口径锚定（"中方表示/中国外交部"句式）。
4. 每条动态口播里必须出现信源徽标【官方】/【主流媒体】/【区域专家】/【单方声称待核实】；
   待核实信源口播必须说"据某方单方面说法，尚待核实"。
5. 数字加"约"或注明机构；英里/海里必须换算成"约合X公里"。

结构要求（依次，段落数量必须对齐）：
- hook：开场钩子（今天几条、最有钩子的一条一句话预告），恰好 1 段
- 简报里每一条动态单独一段（kind=item）：3 条动态 = 3 个 item 段，一条都不能丢、
  不能合并。每段：发生了什么(2句) + 信源分级念出来 + 各方说法/棋盘含义(2句)
- 若任一条的 china_link 非空：恰好 1 段涉华关联（kind=china，官方口径锚定）
- 若 mainlines 非空：恰好 1 段主线追踪（kind=mainline，多条主线并成一句）
- outro：收尾（"不站队不预测"+下期见），恰好 1 段

卡片字段：item 段的 card.headline 必须是本条标题的压缩（≤18字）；
map 卡用于普通条目、quote 卡仅用于「待核实」条目。

item 段口播示范（信源分级必须念出来，每段 60-100 字）：
"第一条，塞尔维亚与美国签署关键矿产合作备忘录。据塞尔
维亚政府公告，协议涉及锂矿勘探许可框架。信源级别为官方。棋盘上看，西方
在俄罗斯传统势力范围再落一子，贝尔格莱德继续左右逢源。"

只输出 JSON：
{{
  "title": "本期标题（含日期，格式：{show} YYYY年M月D日：<主线钩子>）",
  "segments": [
    {{"kind": "hook|item|china|mainline|outro",
      "narration": "口播文本，口语化短句，不要书面长句",
      "item_ref": 对应简报条目序号(1起)，非条目段为0,
      "card": {{"type": "hook|headline|quote|map|china|mainline|outro",
                "headline": "卡面大字（≤18字）",
                "sub": "卡面副题（≤40字，可为空串）",
                "badge": "【官方】等徽标，非条目段为空串",
                "lines": ["要点/大数字，最多3条，可为空数组"]}}}}
  ]
}}

简报（JSON）：
{brief}"""


def _estimate_s(text: str) -> float:
    return round(len(text) * SEC_PER_CHAR, 2)


def _card(kind: str, it: dict | None) -> dict:
    """模板稿的卡片字段。"""
    if kind == "hook":
        return {"type": "hook", "headline": "", "sub": "", "badge": "", "lines": []}
    if it is None:
        return {"type": {"china": "china", "mainline": "mainline",
                         "outro": "outro"}.get(kind, "headline"),
                "headline": "", "sub": "", "badge": "", "lines": []}
    tier = (it.get("sources") or [{}])[0].get("tier", "主流媒体")
    return {"type": "map" if tier != "单方声称待核实" else "quote",
            "headline": it.get("title", "")[:18],
            "sub": (it.get("summary", "") or "")[:40],
            "badge": f"【{tier}】",
            "lines": ([it.get("chess", "")[:30]] if it.get("chess") else [])}


def _template_script(brief: dict, cfg: dict) -> dict:
    """无 GLM 降级：确定性拼稿。句子模板本身就按红线设计。"""
    show = cfg["show"]["name"]
    d = _dt.date.fromisoformat(brief["date"])
    excluded = set(brief.get("excluded_refs", []))   # 简报编辑判断：只上动态/不适合成片的条目
    items = [it for i, it in enumerate(brief["items"], 1) if i not in excluded]
    n = len(items)
    segs: list[dict] = []
    hook = (f"{d.month}月{d.day}日，{show}，本期{n}条动态。今天带你看"
            + (items[0].get("title", "最新动态") if n else "主线动向")
            + "。只讲事实和各方说法。")
    segs.append({"kind": "hook", "narration": hook, "item_ref": 0,
                 "card": _card("hook", None)})
    for i, it in enumerate(items, 1):
        tier = (it.get("sources") or [{}])[0].get("tier", "主流媒体")
        title = re.sub(r"【[^】]*】", "", it.get("title", "")).strip()
        parts = [f"第{i}条，{title}。"]
        if tier == "单方声称待核实":
            parts.append(f"据单方面说法：{it.get('summary', '')}，尚待核实。")
        else:
            parts.append(f"{it.get('summary', '')}。信源级别【{tier}】。")
        if it.get("chess"):
            parts.append(f"棋盘上看，{it.get('chess')}")
        segs.append({"kind": "item", "narration": "".join(parts), "item_ref": i,
                     "card": _card("item", it)})
    if brief.get("china_link") or any(it.get("china_link") for it in brief["items"]):
        cl = next((it.get("china_link") for it in brief["items"] if it.get("china_link")),
                  brief.get("china_link", ""))
        segs.append({"kind": "china",
                     "narration": f"对华关联方面，{cl}。以上以中国外交部及官方渠道"
                                  "最终表述为准。",
                     "item_ref": 0, "card": _card("china", None)})
    if brief.get("mainlines"):
        ml = "；".join(brief["mainlines"])
        segs.append({"kind": "mainline",
                     "narration": f"主线追踪：{ml}。这几条线的后续，我们持续盯。",
                     "item_ref": 0, "card": _card("mainline", None)})
        segs[-1]["card"]["lines"] = [m[:30] for m in brief["mainlines"][:4]]
    segs.append({"kind": "outro",
                 "narration": ("以上是本期" + show + "。只讲发生了什么、各方怎么说；"
                               "不站队，不预测。数据口径以信源原文为准，我们下期见。"),
                 "item_ref": 0, "card": _card("outro", None)})
    title = f"{show} {d.year}年{d.month}月{d.day}日"
    return {"title": title, "segments": segs,
            "warnings": ["模板降级稿：文案为确定性拼接，可直接用但较平"]}


def _validate(obj: dict, n_items: int) -> bool:
    """结构校验：hook 开场、outro 收尾、动态必须逐条成段——GLM 退化稿
    （漏写 item 段、把内容塞进别的段）一律打回模板降级。"""
    segs = obj.get("segments")
    if not isinstance(segs, list) or not segs:
        return False
    kinds = [s.get("kind") for s in segs]
    if kinds[0] != "hook" or kinds[-1] != "outro":
        return False
    unknown = set(kinds) - {"hook", "item", "china", "mainline", "outro"}
    if unknown:
        return False
    n_items_segs = kinds.count("item")
    if n_items > 0 and n_items_segs < max(1, min(n_items, 2)):
        return False
    if n_items == 0 and n_items_segs > 0:
        return False
    return all(isinstance(s.get("narration"), str) and len(s["narration"].strip()) >= 8
               for s in segs) \
        and all(isinstance(s.get("card"), dict) for s in segs)


def build_script(pid: str) -> dict:
    brief = ingest.load_briefing(pid)
    excluded = set(brief.get("excluded_refs", []))
    active_items = [it for i, it in enumerate(brief["items"], 1) if i not in excluded]
    cfg = load_config()
    target_s = max(60, min(200, int(len(active_items) * 32 + 24)))

    script = None
    key = api_keys()["zhipu"]
    if key and active_items:
        obj, _ = chat_json_ex(
            key, _PROMPT.format(show=cfg["show"]["name"], target_s=target_s,
                                brief=_brief_digest(brief)),
            model=cfg["glm"]["model"], temperature=cfg["glm"]["temperature"],
            max_tokens=cfg["glm"]["max_tokens"], timeout=cfg["glm"]["timeout_s"],
            required_keys=("title", "segments"))
        if obj is not None and _validate(obj, len(active_items)):
            script = obj
    mode = "glm"
    if script is None:
        script = _template_script(brief, cfg)
        mode = "template_fallback"

    script["meta"] = {"pid": pid, "date": brief["date"],
                      "show": cfg["show"]["name"],
                      "target_s": target_s, "mode": mode,
                      "n_items": sum(1 for s in script["segments"]
                                     if s["kind"] == "item"),
                      "est_duration_s": round(sum(_estimate_s(s["narration"])
                                                  for s in script["segments"]), 1)}
    for i, s in enumerate(script["segments"], 1):
        s.setdefault("card", {})
        s["card"].setdefault("type", {"hook": "hook", "outro": "outro"}
                             .get(s["kind"], "headline"))
        s["id"] = f"seg{i:02d}"
        s["est_s"] = _estimate_s(s["narration"])
    save_json(script, store.project_dir(pid) / "script.json")
    store.mark_stage(pid, "script", f"{mode} / {len(script['segments'])} 段")
    return script


def _brief_digest(brief: dict) -> str:
    import json as _j
    excluded = set(brief.get("excluded_refs", []))
    slim = {"date": brief["date"], "region": brief.get("region", ""),
            "items": [{k: it.get(k, "") for k in
                       ("title", "summary", "chess", "china_link", "risk")}
                      | {"sources": it.get("sources", [])}
                      for i, it in enumerate(brief["items"], 1) if i not in excluded],
            "mainlines": brief.get("mainlines", [])}
    return _j.dumps(slim, ensure_ascii=False)


def load_script(pid: str) -> dict:
    s = load_json(store.project_dir(pid) / "script.json")
    if not s:
        raise RuntimeError(f"script.json 缺失: {pid}")
    return s


# 锤稿通过后供渲染使用的小工具
def narration_lines(narration: str, width: int = 16) -> list[str]:
    """口播按 ≤width 字切字幕行（标点优先断行）。"""
    import re as _re
    parts = [p for p in _re.split(r"(?<=[。！？；：,.])\s*", narration) if p]
    lines: list[str] = []
    for p in parts:
        while len(p) > width:
            cut = width
            for j in range(min(width, len(p) - 1), int(width * 0.6), -1):
                if p[j - 1] in "，。！？；：、,":
                    cut = j
                    break
            lines.append(p[:cut].strip())
            p = p[cut:]
        if p.strip():
            lines.append(p.strip())
    return lines or [narration]
