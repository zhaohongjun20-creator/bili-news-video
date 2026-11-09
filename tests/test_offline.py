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


def test_validate_rejects_unknown_ref():
    """引用不存在的条目：3 条却引用 ref=4（越界）→ 打回。"""
    assert not scriptgen._validate(_script_with([1, 2, 4]), refs={1, 2, 3})
    # ref=0（非条目段的占位值）出现在 item 段同样是无效引用
    assert not scriptgen._validate(_script_with([0, 1, 2]), refs={1, 2, 3})


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


# ---- 环境兼容：probe_video 三路降级（不允许 0x0 当探测成功） ------------
_STDERR_OK = (
    "Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'final.mp4':\n"
    "  Duration: 00:01:30.04, start: 0.000000, bitrate: 1512 kb/s\n"
    "    Stream #0:0(und): Video: h264 (High) (avc1 / 0x31637661), "
    "yuv420p(tv, bt709), 1920x1080 [SAR 1:1 DAR 16:9], 1349 kb/s, "
    "30 fps, 30 tbr, 30k tbn (default)\n"
    "    Stream #0:1(und): Audio: aac (LC), 44100 Hz, stereo, fltp, "
    "128 kb/s (default)\n")
_FFPROBE_OK = "width=1920\nheight=1080\nr_frame_rate=30/1\nduration=10.0\n"


class _FakeRet:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def test_probe_video_ffprobe_ok(monkeypatch):
    import pytest
    from src import ffmpeg
    monkeypatch.setattr(ffmpeg, "ffprobe_exe", lambda: "ffprobe")
    monkeypatch.setattr(ffmpeg, "run",
                        lambda cmd, **kw: _FakeRet(stdout=_FFPROBE_OK))
    info = ffmpeg.probe_video("x.mp4")
    assert (info["width"], info["height"], info["fps"]) == (1920, 1080, 30.0)
    assert info["duration"] == pytest.approx(10.0)


def test_probe_video_no_ffprobe_falls_back_to_stderr(monkeypatch):
    import pytest
    from src import ffmpeg
    monkeypatch.setattr(ffmpeg, "ffprobe_exe", lambda: None)
    monkeypatch.setattr(ffmpeg, "run", lambda cmd, **kw: _FakeRet(stderr=_STDERR_OK))
    info = ffmpeg.probe_video("x.mp4")
    assert info["width"] == 1920 and info["height"] == 1080
    assert info["fps"] == pytest.approx(30.0)
    assert info["duration"] == pytest.approx(90.04)


def test_probe_video_ffprobe_fails_falls_back(monkeypatch):
    """ffprobe 存在但执行失败/输出为空 → 掉到 ffmpeg -i stderr 降级，不用 0x0。"""
    from src import ffmpeg
    monkeypatch.setattr(ffmpeg, "ffprobe_exe", lambda: "ffprobe")

    def fake_run(cmd, **kw):
        if "ffprobe" in str(cmd[0]):
            return _FakeRet(returncode=1, stdout="", stderr="moov atom not found")
        return _FakeRet(stderr=_STDERR_OK)

    monkeypatch.setattr(ffmpeg, "run", fake_run)
    info = ffmpeg.probe_video("x.mp4")
    assert info["width"] == 1920 and info["height"] == 1080


def test_probe_video_zero_size_never_success(monkeypatch):
    """宽高为 0 绝不允许当探测成功返回：降级也解析不出 → 报错。"""
    import pytest
    from src import ffmpeg
    monkeypatch.setattr(ffmpeg, "ffprobe_exe", lambda: "ffprobe")
    # ffprobe 输出空；ffmpeg -i 只有 Duration、没有视频流行
    monkeypatch.setattr(
        ffmpeg, "run",
        lambda cmd, **kw: _FakeRet(stderr="  Duration: 00:00:10.00, start: 0.000000\n"))
    with pytest.raises(RuntimeError, match="0x0"):
        ffmpeg.probe_video("broken.mp4")


def test_probe_video_corrupt_raises(monkeypatch):
    """损坏文件（两路都解析不出）→ 明确报错而不是静默返回全 0。"""
    import pytest
    from src import ffmpeg
    monkeypatch.setattr(ffmpeg, "ffprobe_exe", lambda: None)
    monkeypatch.setattr(ffmpeg, "run", lambda cmd, **kw: _FakeRet(stderr="Invalid data"))
    with pytest.raises(RuntimeError):
        ffmpeg.probe_video("corrupt.mp4")


# ---- 地图卡：外围行为者按口播提及门控 -----------------------------------
def test_external_actors_gate():
    from src import cards
    assert cards.external_actors("欧盟宣布新一轮对塞援助计划。") == ["西方/欧盟"]
    assert cards.external_actors("北约秘书长称将继续关注局势。") == ["西方/欧盟"]
    assert cards.external_actors("俄罗斯外交部回应称毫无根据。") == ["俄罗斯"]
    assert cards.external_actors("土耳其外长访问贝尔格莱德。") == ["土耳其"]
    # 多方同时提及：按 EXTERNAL 固定顺序返回
    assert cards.external_actors("西方与俄罗斯在安理会交锋，土耳其居中斡旋。") == \
        ["西方/欧盟", "俄罗斯", "土耳其"]
    # 完全未提及 → 不画 chip、不画连线
    assert cards.external_actors("塞科对话本轮无实质进展。") == []


# ---- QC：音轨检查与字幕时间越界（纯函数部分） ---------------------------
def test_stderr_has_audio():
    from src import ffmpeg
    assert ffmpeg.stderr_has_audio(
        "Stream #0:1(und): Audio: aac (LC), 44100 Hz, stereo, fltp, 128 kb/s")
    assert not ffmpeg.stderr_has_audio(
        "Stream #0:0(und): Video: h264 (High), yuv420p, 1920x1080, 30 fps")


def test_ass_dialogue_span():
    from src import qc
    ass = ("[Script Info]\n"
           "[Events]\n"
           "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
           "Dialogue: 0,0:00:00.50,0:00:03.20,News,,0,0,0,,第一行\n"
           "Dialogue: 0,0:00:03.80,0:00:07.00,News,,0,0,0,,第二行\n"
           "Dialogue: 0,0:00:06.90,0:00:08.35,News,,0,0,0,,第三行\n")
    first, last = qc.ass_dialogue_span(ass)
    assert first == 0.5 and last == 8.35
    assert qc.ass_dialogue_span("[Script Info]\n没有 Dialogue 行") is None


# ---- ingest：tier 归一化的「非」前缀 -------------------------------------
def test_normalize_tiers_negation_prefix():
    from src import ingest
    b = ingest._normalize_tiers({"items": [{"sources": [
        {"tier": "非官方声明"}, {"tier": "官方声明"},
        {"tier": "非官方渠道消息"}, {"tier": "需交叉验证"}]}]})
    tiers = [s["tier"] for s in b["items"][0]["sources"]]
    # 「非官方声明」若不先处理「非」前缀，会被「声明」子串误归「官方」
    assert tiers == ["单方声称待核实", "官方", "单方声称待核实", "单方声称待核实"]


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


# ---- 放行/投稿统一闸门：QC 必须对应当前成片 ------------------------------
def _fake_release(tmp_path, monkeypatch, *, final_exists=True, qc_ok=True,
                  qc_pid="ep-999", duration=100.0):
    """闸门测试夹具：全阶段 done + render.json + 成片文件 + qc_report.json。"""
    _fake_project(tmp_path, monkeypatch)
    from src import store
    from src.jsonio import save_json
    pdir = tmp_path / "projects" / "ep-999"
    final = pdir / "output" / "final.mp4"
    if final_exists:
        final.write_bytes(b"\x00" * 16)
    save_json({"final": str(final), "cover": str(pdir / "output" / "cover.jpg"),
               "duration": duration, "width": 1920, "height": 1080, "fps": 30.0},
              pdir / "output" / "render.json")
    save_json({"pid": qc_pid, "checked_at": store.now(), "duration": duration,
               "mean_volume_db": -20.0, "problems": [] if qc_ok else ["x"],
               "ok": qc_ok},
              pdir / "output" / "qc_report.json")
    return pdir


def test_gate_all_valid_passes(tmp_path, monkeypatch):
    """当前成片和 QC 都有效 → 闸门放行。"""
    from src import review
    _fake_release(tmp_path, monkeypatch)
    assert review.gate("ep-999") == []


def test_gate_blocks_stale_qc_after_redo(tmp_path, monkeypatch):
    """旧 QC PASS 文件 + redo render → 阶段已失效，approve 必须被拒。"""
    import argparse
    import pytest
    from src import review, store
    _fake_release(tmp_path, monkeypatch)
    store.redo_stage("ep-999", "render")
    problems = review.gate("ep-999")
    assert any("render" in p for p in problems)
    from cli import cmd_approve
    with pytest.raises(SystemExit):                # cli approve 同样拒绝
        cmd_approve(argparse.Namespace(pid="ep-999", note=""))


def test_gate_blocks_qc_stage_not_done(tmp_path, monkeypatch):
    """QC 阶段未完成 → 不允许 approve。"""
    from src import review, store
    from src.jsonio import save_json
    _fake_release(tmp_path, monkeypatch)
    m = store.manifest("ep-999")
    m["stages"].pop("qc")
    save_json(m, tmp_path / "projects" / "ep-999" / "manifest.json")
    assert any("qc" in p for p in review.gate("ep-999"))


def test_gate_blocks_foreign_or_failed_qc(tmp_path, monkeypatch):
    from src import review
    from src.jsonio import load_json, save_json
    pdir = _fake_release(tmp_path, monkeypatch, qc_pid="ep-001")  # 别的项目的 QC
    assert any("pid" in p for p in review.gate("ep-999"))
    qc = load_json(pdir / "output" / "qc_report.json")
    qc["pid"] = "ep-999"
    qc["ok"] = False                                              # QC 未过
    save_json(qc, pdir / "output" / "qc_report.json")
    assert any("QC 未通过" in p for p in review.gate("ep-999"))


def test_gate_blocks_missing_final(tmp_path, monkeypatch):
    """render.json 指向的成片不存在 → 拒绝。"""
    from src import review
    _fake_release(tmp_path, monkeypatch, final_exists=False)
    assert any("成片" in p for p in review.gate("ep-999"))


def test_gate_blocks_stale_qc_file(tmp_path, monkeypatch):
    """QC 报告早于当前成片 mtime（旧 QC 残留）→ 拒绝。"""
    import os
    from src import review
    pdir = _fake_release(tmp_path, monkeypatch)
    final = pdir / "output" / "final.mp4"
    st = final.stat()
    os.utime(final, (st.st_atime + 10, st.st_mtime + 10))    # 成片比 QC 新
    assert any("旧 QC" in p for p in review.gate("ep-999"))


def test_gate_blocks_duration_mismatch(tmp_path, monkeypatch):
    """QC 报告时长与当前成片不一致（对错了片）→ 拒绝。"""
    from src import review
    from src.jsonio import load_json, save_json
    pdir = _fake_release(tmp_path, monkeypatch, duration=100.0)
    qc = load_json(pdir / "output" / "qc_report.json")
    qc["duration"] = 150.0
    save_json(qc, pdir / "output" / "qc_report.json")
    assert any("时长不一致" in p for p in review.gate("ep-999"))


def _stub_sau(monkeypatch):
    """stub 掉 sau_bridge（biliup 桥），publish 测试绝不触网/真上传。"""
    import sys
    import types
    calls = {"upload": 0}
    stub = sys.modules.get("sau_bridge")
    if stub is None or not getattr(stub, "_is_stub", False):
        stub = types.ModuleType("sau_bridge")
        stub._is_stub = True
        monkeypatch.setitem(sys.modules, "sau_bridge", stub)
    stub.check_account = lambda: True
    stub.login_interactive = lambda: None

    def _upload(**kw):
        calls["upload"] += 1
        return "BV1FAKE00000"

    stub.upload = _upload
    import src.uploader as uploader
    monkeypatch.setattr(uploader, "sau_bridge", stub)   # 统一改绑当前 stub
    return calls


def test_publish_cannot_bypass_approve_and_gate(tmp_path, monkeypatch):
    """publish 不得绕过 approve，也不得绕过闸门（旧 QC 残留场景）。"""
    import pytest
    from src import review, store, uploader
    calls = _stub_sau(monkeypatch)
    _fake_release(tmp_path, monkeypatch)
    review.reset("ep-999", "测试：回到 draft")     # 夹具默认 ready，先退回
    # ① 未 approve（draft）→ 拒绝，绝不上传
    with pytest.raises(RuntimeError, match="approve"):
        uploader.publish("ep-999")
    assert calls["upload"] == 0
    # ② redo render（成片+QC 均失效，旧 QC 文件留在磁盘）后，即使有人绕过
    #    cli 闸门直接把审片状态改成 ready，publish 的二次校验仍必须拦截
    store.redo_stage("ep-999", "render")
    review.approve("ep-999", "误操作：没重跑 make 就放行")
    with pytest.raises(RuntimeError, match="投稿前置检查未过"):
        uploader.publish("ep-999")
    assert calls["upload"] == 0


def test_publish_happy_path_through_gate(tmp_path, monkeypatch):
    """有效成片 + QC + ready → publish 走通（stub 上传，不触网）。"""
    from src import review, uploader
    calls = _stub_sau(monkeypatch)
    pdir = _fake_release(tmp_path, monkeypatch)
    (pdir / "output" / "upload_info.txt").write_text(
        "标题: t\n简介:\n测试简介\n", encoding="utf-8")
    review.approve("ep-999", "看过")
    r = uploader.publish("ep-999")
    assert r["bvid"] == "BV1FAKE00000"
    assert calls["upload"] == 1

