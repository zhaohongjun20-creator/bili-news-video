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
def _item_seg(ref: int, headline: str = "条目标题") -> dict:
    return {"kind": "item", "item_ref": ref,
            "narration": f"第{ref}条动态内容，官方口径如下。",
            "card": {"headline": headline}}


def _script_with(refs: list[int]) -> dict:
    """构造恰好覆盖给定 ref 的稿子（hook + item×n + outro）。"""
    segs = [{"kind": "hook", "narration": "开场钩子，今天三件事。", "card": {}}]
    segs += [_item_seg(r) for r in refs]
    segs.append({"kind": "outro", "narration": "不站队不预测，下期再见。", "card": {}})
    return {"title": "t", "segments": segs}


def test_validate_rejects_degenerate():
    """GLM 退化稿（3 条动态却没写 item 段）必须打回。"""
    bad = {"title": "t", "segments": [
        {"kind": "hook", "narration": "开场钩子，今天三件事。", "card": {}},
        {"kind": "china", "narration": "塞中项目的外溢影响需要关注。", "card": {}},
        {"kind": "outro", "narration": "不站队不预测，下期再见。", "card": {}}]}
    assert not scriptgen._validate(bad, refs={1, 2, 3})
    good = {"title": "t", "segments": [
        {"kind": "hook", "narration": "开场钩子，今天一件事。", "card": {}},
        _item_seg(1),
        {"kind": "outro", "narration": "不站队不预测，下期再见。", "card": {}}]}
    assert scriptgen._validate(good, refs={1})


def test_validate_exact_coverage():
    """ref 乱序但恰好全覆盖 → 通过。"""
    assert scriptgen._validate(_script_with([2, 1, 3]), refs={1, 2, 3})


def test_validate_rejects_missing_ref():
    """少一条：3 个有效条目只写了 2 段 → 打回模板降级。"""
    assert not scriptgen._validate(_script_with([1, 2]), refs={1, 2, 3})


def test_validate_rejects_duplicate_ref():
    """重复 ref：段数凑够但 ref 重了、漏了另一条 → 打回。"""
    assert not scriptgen._validate(_script_with([1, 2, 2]), refs={1, 2, 3})
    # 段数、ref 集合都恰好，但内部有重复（漏一条重一条）也要打回
    assert not scriptgen._validate(_script_with([1, 2, 2]), refs={1, 2})


def test_validate_rejects_empty_headline():
    """item 段 card.headline 为空 → 打回模板降级。"""
    s = _script_with([1, 2, 3])
    s["segments"][2]["card"]["headline"] = "   "
    assert not scriptgen._validate(s, refs={1, 2, 3})
    s["segments"][2].pop("card")                      # 卡片字段缺失同样打回
    assert not scriptgen._validate(s, refs={1, 2, 3})


def test_validate_refs_exclude_excluded():
    """excluded_refs 剔除后的有效 ref 才算数：写了被剔除的条目反而打回。"""
    assert not scriptgen._validate(_script_with([1, 2, 3]), refs={2, 3})
    assert scriptgen._validate(_script_with([2, 3]), refs={2, 3})


def test_valid_refs_and_template_alignment():
    """valid_refs 与模板稿对齐：item_ref 用简报原始 ref，不因剔除重排。"""
    brief = {"date": "2026-11-09", "region": "巴尔干", "excluded_refs": [1],
             "items": [{"title": f"条目{i}", "summary": "发生了某事。",
                        "sources": [{"tier": "官方", "name": "公告"}]}
                       for i in (1, 2, 3)],
             "mainlines": []}
    refs = scriptgen.valid_refs(brief)
    assert refs == {2, 3}
    s = scriptgen._template_script(brief, load_config())
    got = [seg["item_ref"] for seg in s["segments"] if seg["kind"] == "item"]
    assert set(got) == refs and len(got) == len(refs)
    assert scriptgen._validate(s, refs)               # 模板稿自身必须过精确覆盖


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


# ---- 环境兼容：ffmpeg -i stderr 降级解析（无 ffprobe 路径） -------------
def test_parse_video_spec_from_stderr():
    import pytest
    from src import ffmpeg
    err = (
        "Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'final.mp4':\n"
        "  Duration: 00:01:30.04, start: 0.000000, bitrate: 1512 kb/s\n"
        "    Stream #0:0(und): Video: h264 (High) (avc1 / 0x31637661), "
        "yuv420p(tv, bt709), 1920x1080 [SAR 1:1 DAR 16:9], 1349 kb/s, "
        "30 fps, 30 tbr, 30k tbn (default)\n"
        "    Stream #0:1(und): Audio: aac (LC), 44100 Hz, stereo, fltp, "
        "128 kb/s (default)\n")
    spec = ffmpeg.parse_video_spec(err)
    assert spec["width"] == 1920 and spec["height"] == 1080
    assert spec["fps"] == pytest.approx(30.0)
    assert ffmpeg.parse_duration(err) == pytest.approx(90.04)


def test_parse_video_spec_garbage_and_edge():
    from src import ffmpeg
    assert ffmpeg.parse_video_spec("没有视频流的输出") == \
        {"width": 0, "height": 0, "fps": 0.0}
    # 音频流行（44100 Hz）不产生伪分辨率；无 fps 字样保持零值
    err = "Stream #0:1: Audio: aac, 44100 Hz, stereo\n"
    assert ffmpeg.parse_video_spec(err) == {"width": 0, "height": 0, "fps": 0.0}
    assert ffmpeg.parse_duration("nothing useful") is None


# ---- 发布安全：redo 作废旧审片 ----------------------------------------
def _fake_project(tmp_path, monkeypatch, status="ready"):
    """造一个隔离的 ep-999 项目（不碰真实 projects/）。"""
    from src import store
    from src.jsonio import save_json
    monkeypatch.setattr(store, "ROOT", tmp_path)
    pdir = tmp_path / "projects" / "ep-999"
    for sub in ("audio", "cards", "output"):
        (pdir / sub).mkdir(parents=True)
    save_json({"pid": "ep-999", "date": "2026-11-09",
               "stages": {s: "done" for s in store.STAGES}},
              pdir / "manifest.json")
    save_json({"status": status, "note": "", "history": []},
              pdir / "review.json")


def test_redo_render_resets_review(tmp_path, monkeypatch):
    from src import review, store
    _fake_project(tmp_path, monkeypatch, status="ready")
    store.redo_stage("ep-999", "render")
    assert review.status("ep-999") == "draft"
    # 下游阶段确实失效
    m = store.manifest("ep-999")
    assert "render" not in m["stages"] and "qc" not in m["stages"]
    assert m["stages"]["voice"] == "done"          # 上游保留


def test_redo_voice_also_resets_review(tmp_path, monkeypatch):
    """redo voice 也会连带重做 render/qc——审片同样必须作废。"""
    from src import review, store
    _fake_project(tmp_path, monkeypatch, status="ready")
    store.redo_stage("ep-999", "voice")
    assert review.status("ep-999") == "draft"


def test_redo_keeps_history(tmp_path, monkeypatch):
    from src import review, store
    from src.jsonio import load_json
    _fake_project(tmp_path, monkeypatch, status="ready")
    review.approve("ep-999", "看过，放行")           # history 现有 1 条
    store.redo_stage("ep-999", "qc")
    r = load_json(tmp_path / "projects" / "ep-999" / "review.json")
    assert r["status"] == "draft"
    assert len(r["history"]) == 2                  # 作废动作留痕，可审计

