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
