# -*- coding: utf-8 -*-
"""离线单元测试：红线规则、降级解析、模板稿、字幕切行、时间轴。

全离线：不联网、不调 GLM、不出声、不渲染。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["NEWS_OFFLINE"] = "1"

from src import redlines, scriptgen                      # noqa: E402
from src.ingest import _rule_parse                        # noqa: E402
from src.hammer import _check_segment                     # noqa: E402
from src.config import load_config                        # noqa: E402


# ---- 红线规则 --------------------------------------------------------
def test_block_patterns():
    for txt in ("巴黎爆发大规模抗议", "警方清场", "镇压示威者", "尸横遍野",
                "侵略者的下场", "中国必须如何"):
        assert redlines.check_text(txt)[0]["level"] == "block", txt


def test_warn_patterns():
    for txt in ("此举必将引发反弹", "震惊全球", "21英里的海峡"):
        assert redlines.check_text(txt)[0]["level"] == "warn", txt


def test_clean_text_passes():
    assert redlines.check_text("据EIA约2000万桶，约合每日300万吨。") == []


def test_badge_and_china_anchor():
    assert redlines.check_badge("信源级别【官方】显示…")
    assert redlines.check_badge("信源级别为官方的消息称…")       # 口播化写法
    assert redlines.check_badge("信源：区域专家分析认为…")
    assert not redlines.check_badge("无徽标的口播")
    assert not redlines.check_badge("据相关人士说法，事情有进展")
    assert redlines.check_china_anchor("中国外交部此前表示…")
    assert not redlines.check_china_anchor("这对中国影响很大")


# ---- 降级解析 --------------------------------------------------------
def test_rule_parse():
    md = """巴尔干快讯 2026-11-09

1. 塞美签矿产备忘录【官方】
   塞尔维亚政府与美国签署备忘录，规模约10亿美元。
   棋盘：西方落子。

主线：塞科对话无新进展。"""
    b = _rule_parse(md)
    assert b["date"] == "2026-11-09"
    assert len(b["items"]) == 1
    assert b["items"][0]["sources"][0]["tier"] == "官方"
    assert "备忘录" in b["items"][0]["summary"]


def test_rule_parse_nothing():
    b = _rule_parse("今日无事。主线无进展。")
    assert b["nothing_to_report"] and b["items"] == []


# ---- 模板稿 ----------------------------------------------------------
def test_template_script_structure():
    cfg = load_config()
    brief = {"date": "2026-11-09", "region": "巴尔干",
             "items": [{"title": "测试条目", "summary": "发生了某事，约100人参与。",
                        "sources": [{"tier": "官方", "name": "政府公告"}],
                        "chess": "棋盘上意味着X", "china_link": "中企参建铁路",
                        "risk": ""}],
             "mainlines": ["塞科对话"]}
    s = scriptgen._template_script(brief, cfg)
    kinds = [seg["kind"] for seg in s["segments"]]
    assert kinds[0] == "hook" and kinds[-1] == "outro"
    assert "item" in kinds and "china" in kinds and "mainline" in kinds
    item = next(seg for seg in s["segments"] if seg["kind"] == "item")
    assert "【官方】" in item["narration"]
    china = next(seg for seg in s["segments"] if seg["kind"] == "china")
    assert "中国外交部" in china["narration"]   # 模板自带官方口径锚点


# ---- 锤稿检查 --------------------------------------------------------
def test_validate_rejects_degenerate():
    """GLM 退化稿（3 条动态却没写 item 段）必须打回。"""
    bad = {"title": "t", "segments": [
        {"kind": "hook", "narration": "开场钩子，今天三件事。", "card": {}},
        {"kind": "china", "narration": "塞中项目的外溢影响需要关注。", "card": {}},
        {"kind": "outro", "narration": "不站队不预测，下期再见。", "card": {}}]}
    assert not scriptgen._validate(bad, n_items=3)
    good = {"title": "t", "segments": [
        {"kind": "hook", "narration": "开场钩子，今天一件事。", "card": {}},
        {"kind": "item", "narration": "第一条动态内容，官方口径如下。", "card": {}},
        {"kind": "outro", "narration": "不站队不预测，下期再见。", "card": {}}]}
    assert scriptgen._validate(good, n_items=1)


def test_check_segment_requires_badge():
    seg = {"kind": "item", "item_ref": 1, "narration": "发生了某事。"}
    issues = _check_segment(seg, {1: "官方"})
    assert any(i["rule"] == "RL-SRC" for i in issues)


def test_check_segment_china_needs_anchor():
    seg = {"kind": "china", "narration": "中国承建了铁路。"}
    issues = _check_segment(seg, {})
    assert any(i["rule"] == "RL-CHINA" for i in issues)


def test_check_segment_ok():
    seg = {"kind": "item", "item_ref": 1,
           "narration": "约200公里铁路铺轨。信源级别【主流媒体】。"}
    assert _check_segment(seg, {1: "主流媒体"}) == []


# ---- 字幕切行 --------------------------------------------------------
def test_narration_lines():
    lines = scriptgen.narration_lines("第一句，比较长一点的句子。第二句！"
                                      "第三句更长一些，中间还有逗号，继续说。")
    assert all(len(l) <= 16 for l in lines)
    assert "".join(lines).startswith("第一句")
