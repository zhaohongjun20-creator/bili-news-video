# -*- coding: utf-8 -*-
"""新闻事实一致性核验：确定性规则比对（不是 AI 给自己打分）。

三条铁律：
1. 口播里的数字/日期必须能在简报原文里找到——找不到 = WARN（人工裁量），
   因为可能有合法换算；连续多来源报道以简报为准。
2. 含「单方声称待核实」信源的条目，口播必须有对冲表述
   （待核实/尚待核实/单方面说法…）——没有 = BLOCK。
3. 只比对，不改稿：修正永远经过人（锤稿重写或人工改稿）。
"""
import re

_NUM = re.compile(r"\d+(?:\.\d+)?")
_DATE = re.compile(r"\d{1,2}月\d{1,2}日|\d{4}年\d{1,2}月")
_HEDGE = ("待核实", "尚待核实", "未经证实", "单方面说法", "单方说法", "据称",
          "宣称", "无法交叉验证")


def _norm_dates(text: str) -> str:
    """「11 月 11 日」→「11月11日」：简报排版常带空格，统一后再比对。"""
    text = re.sub(r"(\d+)\s*月\s*(\d+)\s*日", r"\1月\2日", text)
    return re.sub(r"(\d{4})\s*年\s*(\d{1,2})\s*月", r"\1年\2月", text)


def fact_sets(brief: dict) -> tuple[set[str], set[str]]:
    """简报事实集：全部条目（标题+概述+棋盘）里的数字与日期。"""
    nums: set[str] = set()
    dates: set[str] = set()
    for it in brief.get("items", []):
        blob = _norm_dates(str(it.get("title", "")) + str(it.get("summary", ""))
                           + str(it.get("chess", "")))
        nums |= set(_NUM.findall(blob))
        dates |= set(_DATE.findall(blob))
    return nums, dates


def check_script(brief: dict, script: dict) -> list[dict]:
    """比对简报与逐字稿。只查 item/china/mainline（hook 的日期、条目序数豁免）。"""
    nums, dates = fact_sets(brief)
    items = {i + 1: it for i, it in enumerate(brief.get("items", []))}
    issues: list[dict] = []
    for seg in script.get("segments", []):
        if seg.get("kind") not in ("item", "china", "mainline"):
            continue
        text = _norm_dates(seg.get("narration", ""))
        sid = seg.get("id", "")
        for n in set(_NUM.findall(text)):
            if n in nums or re.fullmatch(r"\d{4}", n) or f"第{n}条" in text:
                continue                      # 年份 / 条目序数豁免
            issues.append({"rule": "FC-NUM", "level": "warn", "seg": sid,
                           "hit": f"数字 {n} 未见于简报（人工核对是否合法换算）"})
        for d in sorted(set(_DATE.findall(text)) - dates):
            issues.append({"rule": "FC-DATE", "level": "warn", "seg": sid,
                           "hit": f"日期 {d} 未见于简报（注意报道时间≠事件时间）"})
        if seg.get("kind") == "item":
            it = items.get(seg.get("item_ref") or 0, {})
            tiers = [str(s.get("tier", "")) for s in it.get("sources", [])]
            if "单方声称待核实" in tiers:
                # 徽标【单方声称待核实】本身含「待核实」字样——剥掉徽标再查对冲
                bare = re.sub(r"【[^】]*】", "", text)
                if not any(h in bare for h in _HEDGE):
                    issues.append({"rule": "FC-HEDGE", "level": "block", "seg": sid,
                                   "hit": "该条含待核实信源，口播缺少对冲表述"})
    return issues


# ---- 声明保真与实体（确定性比对，不是 AI 自评） ---------------------------
_ATTR_VERBS = ("称", "表示", "宣布", "指出", "声称", "强调", "援引", "透露", "报道")
_CLAIM = re.compile(r"([\u4e00-\u9fa5A-Za-z0-9·]{2,14})"
                    r"(称|表示|宣布|指出|声称|强调|透露)([^。；]{6,40})")
_ENTITY_PAT = (re.compile(r"「([^」]{2,14})」"),
               re.compile(r"\b([A-Z][A-Za-z]{2,}(?:\s[A-Z][A-Za-z]{2,})?)\b"),
               re.compile(r"([\u4e00-\u9fa5]{2,8})"
                          r"(?:州|海峡|共和国|组织|舰队|基地|炼厂|港口|机场|电视台)"))


def _attributed_claims(brief: dict) -> list[dict]:
    """简报里的有主声明：sources[].claim + 摘要中「X称Y」句。"""
    claims: list[dict] = []
    for i, it in enumerate(brief.get("items", []), 1):
        for s in it.get("sources", []):
            c = str(s.get("claim", "")).strip()
            if len(c) >= 6:
                claims.append({"ref": i, "actor": str(s.get("name", "")), "text": c})
        for m in _CLAIM.finditer(_norm_dates(str(it.get("summary", "")))):
            claims.append({"ref": i, "actor": m.group(1), "text": m.group(3)})
    return claims


def check_attribution(brief: dict, script: dict) -> list[dict]:
    """声明保真：简报「X称Y」的 Y 出现在口播时，同句必须保留归属动词；
    否则单方声明被写成既定事实 → BLOCK。逐句比对（剥离引号/逗号干扰）。"""
    claims = _attributed_claims(brief)
    if not claims:
        return []
    issues: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for seg in script.get("segments", []):
        if seg.get("kind") not in ("item", "china", "mainline"):
            continue
        text = _norm_dates(seg.get("narration", ""))
        for sent in re.split(r"(?<=[。！？])", text):
            bare = re.sub(r"[，、「」（）()\s]", "", sent)
            for c in claims:
                frag = re.sub(r"[，、「」（）()\s]", "", c["text"])[:10]
                if len(frag) < 6 or frag not in bare:
                    continue
                if any(v in sent for v in _ATTR_VERBS):
                    continue
                key = (seg.get("id", ""), frag)
                if key in seen:
                    continue
                seen.add(key)
                issues.append({"rule": "FC-ATTR", "level": "block",
                               "seg": seg.get("id", ""),
                               "hit": f"声明「{c['actor']}…{c['text'][:16]}」在口播中"
                                      "失去归属动词——单方说法不得写成既定事实"})
    return issues


def _entities(blob: str) -> set[str]:
    ents: set[str] = set()
    for pat in _ENTITY_PAT:
        ents |= set(pat.findall(blob))
    return {e.strip() for e in ents if len(e.strip()) >= 2}


def check_entities(brief: dict, script: dict) -> list[dict]:
    """新实体检查：口播出现的专名（引号名/拉丁名/机构地名）必须见于简报 → WARN。"""
    ents = _entities("".join(str(it.get(k, "")) for it in brief.get("items", [])
                             for k in ("title", "summary", "chess")))
    if not ents:
        return []
    issues: list[dict] = []
    for seg in script.get("segments", []):
        if seg.get("kind") not in ("item", "china", "mainline"):
            continue
        for e in sorted(_entities(seg.get("narration", "")) - ents):
            issues.append({"rule": "FC-ENTITY", "level": "warn",
                           "seg": seg.get("id", ""),
                           "hit": f"专名「{e}」未见于简报（人工核对是否新增事实）"})
    return issues


# ---- 人工稿来源可追溯（不强制徽标，但必须有来源交代） ----------------------
# 精确标记：不用单字宽泛词（「部」会误匹配「部分地区」）；「据」排除「部分/据说」
_MANUAL_SRC_RES = (re.compile(r"据(?![分此说闻])"),
                   re.compile(r"报道|宣布|透露|援引|表示|确认|声称|声明"),
                   re.compile(r"官方|媒体|通讯社|消息来源|发言人|外交部|国防部|参谋部"))


def check_manual_sources(script: dict) -> list[dict]:
    """人工稿每条 item/china/mainline 段必须有来源交代；没有 → BLOCK。
    人工稿不走 AI 稿徽标格式；本检查是「可追溯性」初筛，不是事实核验本身。"""
    issues: list[dict] = []
    for seg in script.get("segments", []):
        if seg.get("kind") not in ("item", "china", "mainline"):
            continue
        text = seg.get("narration", "")
        if not any(p.search(text) for p in _MANUAL_SRC_RES):
            issues.append({"rule": "RL-SRC-M", "level": "block",
                           "seg": seg.get("id", ""),
                           "hit": "人工稿段落没有任何来源交代（据X报道/称/官方…），"
                                  "无法追溯——补来源或删段"})
    return issues
