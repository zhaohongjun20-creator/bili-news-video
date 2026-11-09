# -*- coding: utf-8 -*-
"""简报接入：Grok 任务D/任务E 的中文简报原文 → 结构化 briefing.json。

主路：GLM 结构化（保持条目原文语义，只做格式转换）。
降级：规则解析（按序号/徽标正则切块），离线可跑通全链。
「今日无事」直接产出 nothing_to_report 简报，不硬凑。
"""
import re

from src import store
from src.config import api_keys, load_config
from src.glm_client import chat_json_ex
from src.jsonio import load_json, save_json

REQUIRED = ("date", "items")

_PROMPT = """你是新闻简报结构化器。把下面这份地缘快讯简报转成 JSON，不要改写事实、
不要添加原文没有的信息、不要删条目。

要求输出 JSON：
{{
  "date": "简报日期，YYYY-MM-DD，原文没有就用今天",
  "region": "地区名",
  "items": [
    {{"title": "一句话标题",
      "summary": "事件概述，保留原文的数字与信源表述",
      "sources": [{{"tier": "官方|主流媒体|区域专家|单方声称待核实", "name": "信源名"}}],
      "chess": "棋盘角度一句话（原文没有就留空串）",
      "china_link": "对华关联一句话（没有就留空串）",
      "risk": "风险标记（没有就留空串）"}}
  ],
  "mainlines": ["主线追踪要点，没有就空数组"]
}}

简报原文：
---
{brief}
---

只输出 JSON。若简报说「今日无事」，items 输出空数组。"""


def _rule_parse(md: str) -> dict:
    """无 GLM 降级：按编号/标题行切块，徽标正则提取信源分级。"""
    lines = [l.rstrip() for l in md.splitlines() if l.strip()]
    date = ""
    region = ""
    items: list[dict] = []
    mainlines: list[str] = []
    cur: dict | None = None
    for ln in lines:
        if m := re.search(r"(\d{4}[-/年]\d{1,2}[-/月]\d{1,2})", ln):
            date = re.sub(r"[年月]", "-", m.group(1)).replace("日", "")
        if m := re.match(r"^#+\s*(\w{2,6})快讯|地区[：:]\s*(\w{2,8})", ln):
            region = region or (m.group(1) or m.group(2) or "")
        badge = re.search(r"【(官方|主流媒体|区域专家|单方声称待核实)】", ln)
        is_head = bool(re.match(r"^(#{1,4}\s|\d+[.、]\s|[-*]\s\*\*)", ln))
        if is_head:
            cur = {"title": re.sub(r"^[#\d.、\-*\s]+", "", ln)[:60],
                   "summary": "", "sources": [], "chess": "",
                   "china_link": "", "risk": ""}
            items.append(cur)
            if badge:
                cur["sources"].append({"tier": badge.group(1), "name": ln.strip()})
        elif cur is not None:
            cur["summary"] = (cur["summary"] + " " + ln.strip()).strip()
            if badge and not any(s["tier"] == badge.group(1) for s in cur["sources"]):
                cur["sources"].append({"tier": badge.group(1), "name": "见原文"})
        if "主线" in ln and ("：" in ln or ":" in ln):
            mainlines.append(ln.split("：")[-1].split(":")[-1].strip()[:80])
    nothing = ("今日无事" in md) or ("无事可报" in md)
    if not date:
        date = store.now()[:10]
    return {"date": date, "region": region or "巴尔干",
            "items": [] if nothing else items,
            "mainlines": mainlines,
            "nothing_to_report": nothing and not items}


def _normalize_tiers(briefing: dict) -> dict:
    """简报方 tier 写法各异（官方声明/OSINT分析/需交叉验证…），归一到四级：
    官方 | 主流媒体 | 区域专家 | 单方声称待核实。匹配不到的从严归「待核实」。"""
    rules = (("单方声称待核实", ("需交叉验证", "未经证实", "传言", "待核实", "线索", "建议补核")),
             ("区域专家", ("区域专家", "专家", "OSINT", "智库", "分析")),
             ("主流媒体", ("主流媒体", "媒体", "通讯社", "报纸", "电视")),
             ("官方", ("官方", "政府", "欧委会", "声明", "公告")))
    for it in briefing.get("items", []):
        for s in it.get("sources", []):
            raw = str(s.get("tier", ""))
            tier = ""
            for canonical, keys in rules:
                if any(k.lower() in raw.lower() for k in keys):
                    tier = canonical
                    break
            s["tier"] = tier or "单方声称待核实"      # 不认识的从严处理
    return briefing


def ingest(briefing_md_path, pid_hint_date: str = "") -> tuple[str, dict]:
    """读取简报原文 → 建项目 → 写 briefing.json。返回 (pid, briefing)。"""
    md_path = __import__("pathlib").Path(briefing_md_path)
    raw = md_path.read_text(encoding="utf-8")
    cfg = load_config()

    briefing = None
    key = api_keys()["zhipu"]
    if key:
        obj, _ = chat_json_ex(
            key, _PROMPT.format(brief=raw[:20000]),
            model=cfg["glm"]["model"], temperature=0.1,
            max_tokens=max(6000, cfg["glm"]["max_tokens"]),
            timeout=cfg["glm"]["timeout_s"],
            required_keys=REQUIRED)
        if obj is not None:
            obj.setdefault("region", "巴尔干")
            obj.setdefault("mainlines", [])
            obj["nothing_to_report"] = not obj["items"]
            briefing = obj
    mode = "glm"
    if briefing is None:
        briefing = _rule_parse(raw)
        mode = "rule_fallback"
    briefing = _normalize_tiers(briefing)

    if pid_hint_date:
        briefing["date"] = pid_hint_date
    pid, pdir = store.new_project(md_path, briefing["date"])
    briefing["source"] = md_path.name
    briefing["ingest_mode"] = mode
    save_json(briefing, pdir / "briefing.json")
    store.mark_stage(pid, "ingest",
                     f"{mode} / {len(briefing['items'])} 条 / "
                     f"{'无事' if briefing.get('nothing_to_report') else '有料'}")
    return pid, briefing


def load_briefing(pid: str) -> dict:
    b = load_json(store.project_dir(pid) / "briefing.json")
    if not b:
        raise RuntimeError(f"briefing.json 缺失: {pid}")
    return b
