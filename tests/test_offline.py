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



# ---- 第三轮 P1-A：已投稿项目防重复放行/重复投稿 ---------------------------
def _publish_once(tmp_path, monkeypatch):
    """夹具：有效项目 → 放行 → 首次投稿成功（stub，不触网）。返回 (pdir, calls)。"""
    from src import review, uploader
    calls = _stub_sau(monkeypatch)
    pdir = _fake_release(tmp_path, monkeypatch)
    (pdir / "output" / "upload_info.txt").write_text(
        "标题: t\n简介:\n简介内容够长\n", encoding="utf-8")
    review.approve("ep-999", "首次放行")
    uploader.publish("ep-999")
    return pdir, calls


def test_published_cannot_reapprove(tmp_path, monkeypatch):
    """published 是终态：底层 approve 直接拒绝（重复放行=重复投稿风险）。"""
    import pytest
    from src import review
    _publish_once(tmp_path, monkeypatch)
    assert review.status("ep-999") == "published"
    with pytest.raises(RuntimeError, match="重复放行"):
        review.approve("ep-999", "再次放行")


def test_cmd_approve_rejects_published(tmp_path, monkeypatch):
    """CLI 层对已投稿项目的 approve 也要拦（双层防御）。"""
    import argparse
    import pytest
    import cli
    _publish_once(tmp_path, monkeypatch)
    with pytest.raises(SystemExit):
        cli.cmd_approve(argparse.Namespace(pid="ep-999", note="再放行"))


def test_published_cannot_republish_zero_uploads(tmp_path, monkeypatch):
    """重复 publish 必须拒绝，且不再产生任何上传调用。"""
    import pytest
    from src import uploader
    pdir, calls = _publish_once(tmp_path, monkeypatch)
    assert calls["upload"] == 1
    with pytest.raises(RuntimeError, match="已投稿"):
        uploader.publish("ep-999")
    assert calls["upload"] == 1            # 重投尝试：0 次上传


def test_publish_failure_leaves_no_success_record(tmp_path, monkeypatch):
    """上传抛错：审片状态保持 ready，绝不写入成功记录。"""
    import pytest
    import sys
    from src import review, uploader
    calls = _stub_sau(monkeypatch)
    pdir = _fake_release(tmp_path, monkeypatch)
    (pdir / "output" / "upload_info.txt").write_text(
        "标题: t\n简介:\n简介内容够长\n", encoding="utf-8")
    sys.modules["sau_bridge"].upload = _fail_upload
    review.approve("ep-999", "放行")
    with pytest.raises(RuntimeError, match="biliup"):
        uploader.publish("ep-999")
    assert review.status("ep-999") == "ready"
    assert not (pdir / "output" / "publish_result.json").exists()


def _fail_upload(**_kw):
    raise RuntimeError("biliup failed: cookie expired")


def test_publish_fingerprint_blocks_same_video_allows_new(tmp_path, monkeypatch):
    """持久化指纹闸门：同成片（即使状态被改回 draft）拒绝重投；
    成片变了（redo 重做的新片）→ 不因旧记录误拒，走正常流程。"""
    import pytest
    from src import review, uploader
    from src.jsonio import load_json
    pdir, calls = _publish_once(tmp_path, monkeypatch)
    rec = load_json(pdir / "output" / "publish_result.json")
    assert rec["video"]["sha256_16"]       # 指纹随投稿成功持久化
    review.reset("ep-999", "测试：状态回 draft，投稿记录仍在")
    with pytest.raises(RuntimeError, match="已投稿过"):
        uploader.publish("ep-999")         # 同指纹 → 拒
    assert calls["upload"] == 1
    final = pdir / "output" / "final.mp4"
    final.write_bytes(final.read_bytes() + b"redo-new-version")
    with pytest.raises(RuntimeError, match="approve"):
        uploader.publish("ep-999")         # 新成片 → 越过指纹闸，卡在未放行
    assert calls["upload"] == 1


# ---- 第三轮 P1-B：ffprobe OSError/超时也走降级 ---------------------------
def test_probe_video_ffprobe_oserror_falls_back(monkeypatch):
    import pytest
    from src import ffmpeg
    monkeypatch.setattr(ffmpeg, "ffprobe_exe", lambda: "ffprobe")

    def fake_run(cmd, **kw):
        if "ffprobe" in str(cmd[0]):
            raise OSError("ffprobe binary broken")
        return _FakeRet(stderr=_STDERR_OK)
    monkeypatch.setattr(ffmpeg, "run", fake_run)
    info = ffmpeg.probe_video("x.mp4")
    assert (info["width"], info["height"]) == (1920, 1080)


def test_probe_video_ffprobe_timeout_falls_back(monkeypatch):
    import subprocess
    from src import ffmpeg
    monkeypatch.setattr(ffmpeg, "ffprobe_exe", lambda: "ffprobe")

    def fake_run(cmd, **kw):
        if "ffprobe" in str(cmd[0]):
            raise subprocess.TimeoutExpired(cmd="ffprobe", timeout=60)
        return _FakeRet(stderr=_STDERR_OK)
    monkeypatch.setattr(ffmpeg, "run", fake_run)
    info = ffmpeg.probe_video("x.mp4")
    assert info["height"] == 1080


def test_probe_duration_ffprobe_crash_falls_back(monkeypatch):
    import pytest
    from src import ffmpeg
    monkeypatch.setattr(ffmpeg, "ffprobe_exe", lambda: "ffprobe")

    def fake_run(cmd, **kw):
        if "ffprobe" in str(cmd[0]):
            raise OSError("no exec")
        return _FakeRet(stderr=_STDERR_OK)
    monkeypatch.setattr(ffmpeg, "run", fake_run)
    assert ffmpeg.probe_duration("x.mp4") == pytest.approx(90.04)


def test_probe_video_garbage_file_raises_for_real(tmp_path):
    """真实损坏文件（不 mock）：ffprobe 与 ffmpeg 两路都失败 → 明确报错。"""
    import pytest
    from src import ffmpeg
    bad = tmp_path / "garbage.mp4"
    bad.write_bytes(b"\x00\x01\x02not a video at all" * 64)
    with pytest.raises(RuntimeError):
        ffmpeg.probe_video(bad)


# ---- 第三轮 P2-A：逐字稿结构校验加固 ------------------------------------
def test_validate_item_ref_must_be_int_not_bool():
    """{True}=={1} 的 Python 陷阱：布尔 item_ref 必须显式拒绝；字符串同样拒。"""
    from src import scriptgen
    refs = {1, 2}
    s = _script_with([1, 2])
    s["segments"][1]["item_ref"] = True
    assert not scriptgen._validate(s, refs)
    s2 = _script_with([1, 2])
    s2["segments"][1]["item_ref"] = "1"
    assert not scriptgen._validate(s2, refs)
    assert scriptgen._validate(_script_with([1, 2]), refs)   # 正常整数仍通过


def test_validate_hook_outro_exactly_once():
    """hook/outro 各恰好一次（中间混入即拒）。"""
    from src import scriptgen
    refs = {1, 2}
    s = _script_with([1, 2])
    s["segments"].insert(2, {"kind": "hook",
                             "narration": "中间又插了一个钩子段", "card": {}})
    assert not scriptgen._validate(s, refs)
    s2 = _script_with([1, 2])
    s2["segments"].insert(2, {"kind": "outro",
                              "narration": "中间又插了一个收尾段", "card": {}})
    assert not scriptgen._validate(s2, refs)


def test_validate_rejects_malformed_segments():
    """缺 narration、非 dict 段落都要拒（旧实现对后者会直接崩）。"""
    from src import scriptgen
    refs = {1, 2}
    s = _script_with([1, 2])
    del s["segments"][1]["narration"]
    assert not scriptgen._validate(s, refs)
    s2 = _script_with([1, 2])
    s2["segments"][1] = "not-a-dict"
    assert not scriptgen._validate(s2, refs)


# ---- 第三轮 P2-B：俄罗斯触发词收紧（单字「俄」误触发） -------------------
def test_actor_russia_triggers_precise():
    from src import cards
    assert cards.external_actors("俄罗斯政府表示不接受该安排。") == ["俄罗斯"]
    assert cards.external_actors("俄方回应称报道不实。") == ["俄罗斯"]
    assert cards.external_actors("俄军在边境地区展开演习。") == ["俄罗斯"]
    assert cards.external_actors("一份俄语资料显示了不同的数字。") == []
    assert cards.external_actors("今天没有任何外围动向。") == []


# ---- 人工稿通道：markdown 解析 ------------------------------------------
_MINI_SCRIPT = """# 测试稿｜2026-11-10

**主标题**：测试标题在这里

## 4. 逐字稿

**【00:00–00:15｜开场钩子】**

【画面提示】黑场起，大字幕：「测试」。
这一段是画面提示的续行，不应进口播。

11 月 9 日，测试开场白，只讲事实。

**【00:15–00:40｜各方怎么说】**

【画面提示】信息卡。

美军官员向媒体确认防护加严了，信源写作保留原样。官方没有具名通稿说明原因，
华尔街日报援引匿名信源，这不是国防部声明。

**【00:40–01:00｜收尾】**

不站队，不预测。下期再见。
"""


def test_manual_script_parse():
    import tempfile
    from pathlib import Path as _P
    from src import manual
    with tempfile.TemporaryDirectory() as td:
        f = _P(td) / "s.md"
        f.write_text(_MINI_SCRIPT, encoding="utf-8")
        s = manual.parse_script(f)
    assert s["meta"]["mode"] == "manual"
    assert s["meta"]["date"] == "2026-11-10"
    assert s["title"] == "测试标题在这里"
    kinds = [x["kind"] for x in s["segments"]]
    assert kinds == ["hook", "item", "outro"]
    hook = s["segments"][0]["narration"]
    assert "测试开场白" in hook and "画面提示" not in hook and "续行" not in hook
    item = s["segments"][1]
    assert item["card"]["headline"]          # 卡面标题非空
    assert "匿名信源" in item["narration"]


def test_manual_script_rejects_wrong_format():
    import tempfile
    from pathlib import Path as _P
    from src import manual
    with tempfile.TemporaryDirectory() as td:
        f = _P(td) / "bad.md"
        f.write_text("# 没有逐字稿块的文档\n正文而已\n", encoding="utf-8")
        try:
            manual.parse_script(f)
            assert False, "应当报错"
        except RuntimeError:
            pass


def test_manual_parse_stops_at_md_headers():
    """解析器必须在 md 标题行/分隔线处终止块——后文的信源表不能吞进口播。"""
    import tempfile
    from pathlib import Path as _P
    from src import manual
    md = _MINI_SCRIPT.replace("不站队，不预测。下期再见。\n", """
不站队，不预测。下期再见。

---

## 5. 关键信息与信源

- 信源A：https://example.com
- 信源B：https://example.org
""")
    with tempfile.TemporaryDirectory() as td:
        f = _P(td) / "s.md"
        f.write_text(md, encoding="utf-8")
        s = manual.parse_script(f)
    outro = s["segments"][-1]["narration"]
    assert "下期再见" in outro
    assert "信源A" not in outro and "example.com" not in outro
    assert s["meta"]["expected_s"] == 60.0          # 末段时间轴 00:40–01:00


def test_map_applicable_region_gate():
    """地图卡地域门控：巴尔干条目适用底图，波罗的海/中亚/中东条目不适用。"""
    from src import cards
    assert cards.map_applicable("塞尔维亚「学生名单」大选定局")
    assert cards.map_applicable("匈塞铁路铺轨进入新阶段")
    assert cards.map_applicable("科索沃北部市镇改选")
    assert not cards.map_applicable("乌斯季卢加港区起火")        # 波罗的海
    assert not cards.map_applicable("集安组织暂停亚美尼亚表决权")  # 中亚
    assert not cards.map_applicable("拉斐尔发布超级冰巡航导弹")    # 以色列


# ---- A批修复:双标点 / GLM失败留痕 / 解释器守卫 / hook条数 ----------------
def test_narration_lines_no_double_punct():
    import re
    from src import scriptgen
    t = ("11月12日，英国海事贸易行动中心与联合海事信息中心在更新中记录了四起油轮事件。"
         "伊朗革命卫队海军称两艘油轮发生剧烈爆炸。。信源级别【官方】。")
    lines = scriptgen.narration_lines(t)
    for ln in lines:
        assert not re.search(r"[。！？，；]{2,}", ln), ln
        core = re.sub(r"[。！？；：，、,.]+", "", ln).strip()
        assert len(core) > 1, ln
    assert lines[-1].endswith("信源级别【官方】。")


def test_hook_count_fix():
    from src import redlines
    fixed, note = redlines.fix_hook_count("今天五条快讯，俄军舰遇袭。", 6)
    assert "六条快讯" in fixed and note and "6" in note
    assert redlines.fix_hook_count("今天六条快讯。", 6)[1] is None
    fixed2, note2 = redlines.fix_hook_count("本期共4条动态。", 6)
    assert "六条" in fixed2 and note2
    assert redlines.fix_hook_count("今天带你看最新动向。", 6)[1] is None
    fixed3, _ = redlines.fix_hook_count("今天十一条快讯。", 11)
    assert "十一条" in fixed3


def test_ensure_interpreter_guard(monkeypatch):
    import pytest
    import cli
    monkeypatch.setattr(
        sys, "executable",
        r"C:\Program Files\LibreOffice\program\python-core-3.13.17\python.exe")
    with pytest.raises(SystemExit):
        cli.ensure_interpreter()
    monkeypatch.setattr(
        sys, "executable",
        r"C:\Users\15804\AppData\Local\Programs\Python\Python314\python.exe")
    cli.ensure_interpreter()


def test_build_script_records_glm_failure(tmp_path, monkeypatch):
    """GLM 两次都失败 → 模板稿，但失败原因必须留在 warnings，且重试了一次。"""
    from src import scriptgen, store
    from src.jsonio import save_json
    from src import store
    monkeypatch.setattr(store, "ROOT", tmp_path)
    pdir = tmp_path / "projects" / "ep-998"
    pdir.mkdir(parents=True)
    save_json({"pid": "ep-998", "stages": {}}, pdir / "manifest.json")
    save_json({"date": "2026-11-13", "region": "测试",
               "items": [{"title": f"条目{i}", "summary": f"第{i}条测试内容。",
                          "sources": [{"tier": "官方", "name": "测试"}],
                          "chess": "", "china_link": "", "risk": ""} for i in (1, 2)],
               "mainlines": [], "excluded_refs": []},
              pdir / "briefing.json")
    calls = {"n": 0}

    def fake_chat(key, prompt, **kw):
        calls["n"] += 1
        return None, "GLM boom"

    monkeypatch.setattr(scriptgen, "chat_json_ex", fake_chat)
    monkeypatch.setattr(scriptgen, "api_keys", lambda: {"zhipu": "k"})
    s = scriptgen.build_script("ep-998")
    assert s["meta"]["mode"] == "template_fallback"
    assert calls["n"] == 2
    assert any("GLM boom" in w for w in s["warnings"])


# ---- 全球自动定位地图卡与地球仪 ------------------------------------------
def test_resolve_place_regions():
    from src import cards
    p = cards.resolve_place("乌克兰无人机打击乌斯季卢加港区", "")
    assert p and p["name"] == "乌斯季卢加" and abs(p["lat"] - 59.66) < 0.01
    p2 = cards.resolve_place("霍尔木兹海峡油轮事件", "")
    assert p2 and abs(p2["lat"] - 26.6) < 0.01
    p3 = cards.resolve_place("", "集安组织峰会在莫斯科举行")
    assert p3 and p3["name"] == "莫斯科"
    assert cards.resolve_place("普通条目没有任何地名信息", "") is None


def test_globe_projection_math():
    from src import cards
    x, y, c = cards._globe_project((0, 0), 0, 0, 100, 500, 500)
    assert abs(x - 500) < 1e-6 and abs(y - 500) < 1e-6 and c >= 1
    x, y, _ = cards._globe_project((90, 0), 0, 0, 100, 500, 500)
    assert abs(x - 600) < 1e-6 and abs(y - 500) < 1e-6
    x, y, _ = cards._globe_project((0, 90), 0, 0, 100, 500, 500)
    assert abs(x - 500) < 1e-6 and abs(y - 400) < 1e-6
    _, _, c = cards._globe_project((180, 0), 0, 0, 100, 500, 500)
    assert c < 0


def test_subtitle_events_weighted_by_chars():
    from src.renderer import subtitle_events
    narr = {"seg01": "短句。这一行有十二个字以上所以更长一些。"}
    tl = [{"id": "seg01", "start": 0.0, "audio_in": 0.3, "audio_duration": 6.0}]
    ev = subtitle_events(narr, tl)
    assert len(ev) == 2
    assert abs(ev[0][0] - 0.3) < 1e-6
    assert abs(ev[-1][1] - 6.3) < 1e-6
    assert (ev[1][1] - ev[1][0]) > (ev[0][1] - ev[0][0])   # 长行多占时


# ---- 第四轮审查:P0 信源追溯/事实核验/QC规格 + P1 投稿intent/地图置信度 ----
def test_check_spec_dimensions():
    """QC 规格检查：宽、高、帧率全查，不只查高度。"""
    from src.qc import check_spec
    cfg = {"width": 1920, "height": 1080, "fps": 30}
    assert check_spec({"width": 1280, "height": 1080, "fps": 30}, cfg)
    assert not check_spec({"width": 1920, "height": 1080, "fps": 29.97}, cfg)
    assert check_spec({"width": 1920, "height": 1080, "fps": 25}, cfg)


def test_rule_parse_extracts_urls():
    """规则降级也要抓信源链接（可追溯不依赖 GLM）。"""
    from src.ingest import _rule_parse
    md = """雷达 2026-11-13

1. 测试条目【官方】
   详见 https://example.com/a 和 https://example.com/b。
"""
    b = _rule_parse(md)
    urls = [s.get("url") for it in b["items"] for s in it.get("sources", [])]
    assert "https://example.com/a" in urls and "https://example.com/b" in urls


def test_factcheck_rules():
    from src import factcheck
    brief = {"items": [
        {"title": "乌斯季卢加港起火", "event_time": "11月11日凌晨",
         "summary": "11月11日凌晨遇袭，约5座储罐受损。",
         "sources": [{"tier": "单方声称待核实", "name": "SBU"}], "chess": ""},
        {"title": "霍尔木兹油轮", "summary": "11月12日一艘油轮遭不明投射物。",
         "sources": [{"tier": "官方", "name": "UKMTO"}], "chess": ""}]}
    script = {"segments": [
        {"id": "seg02", "kind": "item", "item_ref": 1,
         "narration": "乌斯季卢加港11月11日凌晨遇袭，约5座储罐受损，"
                      "另有999架无人机。信源级别【单方声称待核实】。"},
        {"id": "seg03", "kind": "item", "item_ref": 2,
         "narration": "11月12日油轮遭不明投射物。信源级别【官方】。"}]}
    issues = factcheck.check_script(brief, script)
    assert any(i["rule"] == "FC-HEDGE" and i["level"] == "block" for i in issues)
    assert any(i["rule"] == "FC-NUM" and "999" in i["hit"] for i in issues)
    assert not any(i["hit"] == "5" for i in issues)      # 简报内数字不告警
    script["segments"][0]["narration"] = (
        "乌斯季卢加港11月11日凌晨遇袭，据单方面说法约5座储罐受损，"
        "尚待核实。信源级别【单方声称待核实】。")
    issues2 = factcheck.check_script(brief, script)
    assert not any(i["rule"] == "FC-HEDGE" for i in issues2)


def test_resolve_place_ambiguity():
    from src import cards
    p = cards.resolve_place("乌斯季卢加与霍尔木兹同时出事", "")
    assert p["name"] in ("乌斯季卢加", "霍尔木兹")
    assert p["alternatives"]                              # 相距>15° → 人工确认
    single = cards.resolve_place("霍尔木兹海峡油轮事件", "")
    assert single and not single.get("alternatives")


def test_manual_kinds_china_mainline():
    import tempfile
    from pathlib import Path as _P
    from src import manual
    md = """# 测试稿｜2026-11-13

**主标题**：测试标题

**【00:00–00:10｜开场】**

开场白内容测试测试测试。

**【00:10–00:20｜对华关联】**

中国外交部此前表示相关立场。官方锚点句子在这里。

**【00:20–00:30｜主线追踪】**

塞科对话是长期主线之一，需要持续关注走向。

**【00:30–00:40｜收尾】**

不站队不预测，下期再见。
"""
    with tempfile.TemporaryDirectory() as td:
        f = _P(td) / "s.md"
        f.write_text(md, encoding="utf-8")
        s = manual.parse_script(f)
    kinds = [x["kind"] for x in s["segments"]]
    assert kinds == ["hook", "china", "mainline", "outro"]


def test_publish_intent_blocks_unknown_outcome(tmp_path, monkeypatch):
    """上传中断 → publishing.json 拦住重投；人工确认删除后才能重试。"""
    import pytest
    import sys
    from src import review, uploader
    calls = _stub_sau(monkeypatch)
    pdir = _fake_release(tmp_path, monkeypatch)
    (pdir / "output" / "upload_info.txt").write_text(
        "标题: t\n简介:\n简介内容够长\n", encoding="utf-8")
    review.approve("ep-999", "放行")
    stub = sys.modules["sau_bridge"]

    def _boom(**kw):
        calls["upload"] += 1
        raise RuntimeError("biliup failed: cookie expired")

    stub.upload = _boom
    with pytest.raises(RuntimeError, match="biliup"):
        uploader.publish("ep-999")
    assert calls["upload"] == 1
    assert (pdir / "output" / "publishing.json").exists()
    with pytest.raises(RuntimeError, match="未完结的投稿"):
        uploader.publish("ep-999")                        # 结果未知 → 拦
    assert calls["upload"] == 1
    (pdir / "output" / "publishing.json").unlink()        # 人工确认未发出

    def _ok(**kw):
        calls["upload"] += 1
        return "BV1RETRY0000"

    stub.upload = _ok
    r = uploader.publish("ep-999")
    assert r["bvid"] == "BV1RETRY0000" and calls["upload"] == 2
    assert not (pdir / "output" / "publishing.json").exists()


# ---- 第五轮 P0:声明保真/人工稿来源/map-confirm/状态机/生产报告 -----------
def test_factcheck_attribution_preserved():
    from src import factcheck
    brief = {"items": [{"title": "t", "summary": "雷扎伊表示，在美方回应前不会重开海峡。",
                        "sources": [], "chess": ""}]}
    # 逐字照抄声明内容但删掉归属动词 → BLOCK（确定性能力边界：改写归人工）
    script = {"segments": [
        {"id": "seg02", "kind": "item", "item_ref": 1,
         "narration": "在美方回应前不会重开海峡。信源级别【官方】。"},
        {"id": "seg03", "kind": "item", "item_ref": 1,
         "narration": "雷扎伊表示，在美方回应前德黑兰不会重开海峡。信源级别【官方】。"}]}
    issues = factcheck.check_attribution(brief, script)
    assert any(i["rule"] == "FC-ATTR" and i["seg"] == "seg02" for i in issues)
    assert not any(i["seg"] == "seg03" for i in issues)   # 保留归属动词 → 通过


def test_hammer_manual_no_fact_baseline_flood(tmp_path, monkeypatch):
    """人工稿无简报基线：数字/日期不得误报 FC-NUM/FC-DATE（实测 bug 回归）。"""
    from src import store
    from src.jsonio import save_json
    monkeypatch.setattr(store, "ROOT", tmp_path)
    pdir = tmp_path / "projects" / "ep-997"
    pdir.mkdir(parents=True)
    save_json({"pid": "ep-997", "stages": {}}, pdir / "manifest.json")
    save_json({"title": "人工稿", "meta": {"mode": "manual", "date": "2026-11-13"},
               "segments": [
                   {"id": "seg01", "kind": "hook", "narration": "11月13日，军事快讯开场。",
                    "card": {}, "item_ref": 0},
                   {"id": "seg02", "kind": "item", "narration":
                    "据美军官员向媒体确认，11月11日凌晨有250架无人机参与行动，约5000万人关注。",
                    "card": {"headline": "x"}, "item_ref": 0}],
               "warnings": []}, pdir / "script.json")
    from src import hammer
    report = hammer.hammer("ep-997")
    fc = [i for i in report["issues"] if i["rule"].startswith("FC-N") or
          i["rule"].startswith("FC-D")]
    assert fc == []                                   # 无基线不误报
    assert not any(i["rule"] == "RL-SRC-M" for i in report["issues"])  # 有来源交代


def test_hammer_manual_blocks_unsourced(tmp_path, monkeypatch):
    """人工稿段落完全没有来源交代 → RL-SRC-M BLOCK。"""
    from src import store
    from src.jsonio import save_json
    monkeypatch.setattr(store, "ROOT", tmp_path)
    pdir = tmp_path / "projects" / "ep-996"
    pdir.mkdir(parents=True)
    save_json({"pid": "ep-996", "stages": {}}, pdir / "manifest.json")
    save_json({"title": "人工稿", "meta": {"mode": "manual", "date": "2026-11-13"},
               "segments": [
                   {"id": "seg01", "kind": "hook", "narration": "开场白内容足够长。",
                    "card": {}, "item_ref": 0},
                   {"id": "seg02", "kind": "item",
                    "narration": "港口起了大火，事态非常严重，情况仍在继续发展变化。",
                    "card": {"headline": "x"}, "item_ref": 0}],
               "warnings": []}, pdir / "script.json")
    from src import hammer
    report = hammer.hammer("ep-996")
    assert any(i["rule"] == "RL-SRC-M" and i["level"] == "block"
               for i in report["issues"])


def test_map_confirm_gate(tmp_path, monkeypatch):
    """PENDING 地图 → gate 拦截；CONFIRMED 后放行。"""
    from src import review
    from src.jsonio import save_json
    _fake_release(tmp_path, monkeypatch)
    pdir = tmp_path / "projects" / "ep-999"
    save_json({"seg02": {"place": "乌斯季卢加", "via": "标题",
                         "alternatives": ["芬兰湾"], "status": "PENDING"}},
              pdir / "map_confirm.json")
    problems = review.gate("ep-999")
    assert any("地图定位待人工确认" in p for p in problems)
    save_json({"seg02": {"place": "乌斯季卢加", "status": "CONFIRMED",
                         "chosen": "乌斯季卢加", "confirmed_at": "t"}},
              pdir / "map_confirm.json")
    assert not [p for p in review.gate("ep-999") if "地图" in p]


def test_production_report_verdict(tmp_path, monkeypatch):
    """报告结论：无阻断 + ready → 可发布；PENDING 地图 → 不可发布并点名阻断项。"""
    from src import production_report, store
    from src.jsonio import save_json
    _fake_release(tmp_path, monkeypatch)
    pdir = tmp_path / "projects" / "ep-999"
    rep = production_report.build("ep-999")
    assert rep["verdict"] == "可发布"
    assert len(rep["checks"]) >= 5
    save_json({"seg02": {"place": "x", "status": "PENDING",
                         "alternatives": ["y"]}}, pdir / "map_confirm.json")
    rep2 = production_report.build("ep-999")
    assert rep2["verdict"] == "不可发布" and "地图定位" in rep2["blockers"]
    assert (pdir / "production_report.md").exists()


def test_publish_intent_state_unknown(tmp_path, monkeypatch):
    """上传抛错 → intent 标 unknown（禁止自动重试的持久依据）。"""
    import sys
    from src import review, uploader
    from src.jsonio import load_json
    _publish_once(tmp_path, monkeypatch) if False else None
    calls = _stub_sau(monkeypatch)
    pdir = _fake_release(tmp_path, monkeypatch)
    (pdir / "output" / "upload_info.txt").write_text(
        "标题: t\n简介:\n简介内容够长\n", encoding="utf-8")
    review.approve("ep-999", "放行")
    stub = sys.modules["sau_bridge"]

    def _boom(**kw):
        raise RuntimeError("boom")

    stub.upload = _boom
    import pytest
    with pytest.raises(RuntimeError, match="boom"):
        uploader.publish("ep-999")
    intent = load_json(pdir / "output" / "publishing.json")
    assert intent["state"] == "unknown" and "boom" in intent["error"]
    assert calls["upload"] == 0


# ---- 第六轮:地图确认进入绘制 / 人工稿来源精度 / 检测器解析 / 报告口径 -----
def test_confirmed_place_overrides_auto(tmp_path, monkeypatch):
    """自动定位 A、人工确认 B → 绘制输入必须解析为 B。"""
    from src import cards
    from src.jsonio import save_json
    from src import store
    monkeypatch.setattr(store, "ROOT", tmp_path)
    pdir = tmp_path / "projects" / "ep-995"
    pdir.mkdir(parents=True)
    save_json({"seg02": {"place": "乌斯季卢加", "status": "CONFIRMED",
                         "chosen": "霍尔木兹", "confirmed_at": "2026-11-14T00:00"}},
              pdir / "map_confirm.json")
    place, rec = cards._confirmed_place("ep-995", "seg02")
    assert place and place["name"] == "霍尔木兹" and abs(place["lat"] - 26.6) < 0.01
    assert rec["status"] == "CONFIRMED"


def test_confirmed_place_unresolvable_returns_none(tmp_path, monkeypatch):
    """chosen 无法解析 → (None, rec)：调用方退大字卡，不静默用自动定位。"""
    from src import cards
    from src.jsonio import save_json
    from src import store
    monkeypatch.setattr(store, "ROOT", tmp_path)
    pdir = tmp_path / "projects" / "ep-995"
    pdir.mkdir(parents=True)
    save_json({"seg02": {"place": "乌斯季卢加", "status": "CONFIRMED",
                         "chosen": "不存在的地名XYZ", "confirmed_at": "t"}},
              pdir / "map_confirm.json")
    place, rec = cards._confirmed_place("ep-995", "seg02")
    assert place is None and rec["chosen"] == "不存在的地名XYZ"


def test_update_map_confirm_never_overwrites_confirmed(tmp_path, monkeypatch):
    """自动定位与人工确认不一致时，不得覆盖 CONFIRMED。"""
    from src import cards
    from src.jsonio import load_json, save_json
    from src import store
    monkeypatch.setattr(store, "ROOT", tmp_path)
    pdir = tmp_path / "projects" / "ep-995"
    pdir.mkdir(parents=True)
    save_json({"seg02": {"place": "霍尔木兹", "status": "CONFIRMED",
                         "chosen": "霍尔木兹", "confirmed_at": "t"}},
              pdir / "map_confirm.json")
    script = {"segments": [{"id": "seg02", "kind": "item", "narration": "n",
                            "card": {"type": "map", "headline": "乌斯季卢加"}}]}
    cards._update_map_confirm("ep-995", script)   # 自动会解析为乌斯季卢加
    mc = load_json(pdir / "map_confirm.json")
    assert mc["seg02"]["place"] == "霍尔木兹" and mc["seg02"]["chosen_resolved"] is True


def test_map_gate_stale_render_and_unresolved(tmp_path, monkeypatch):
    """确认后未重渲 → 拦；chosen 无法解析 → 拦。"""
    import os
    from src import review
    from src.jsonio import save_json
    _fake_release(tmp_path, monkeypatch)
    pdir = tmp_path / "projects" / "ep-999"
    final = pdir / "output" / "final.mp4"
    save_json({"seg02": {"place": "霍尔木兹", "status": "CONFIRMED",
                         "chosen": "霍尔木兹", "chosen_resolved": True,
                         "confirmed_at": "2026-11-14T00:00:00"}},
              pdir / "map_confirm.json")
    os.utime(final, (1_000_000_000, 1_000_000_000))   # 成片早于确认时间
    problems = review.gate("ep-999")
    assert any("未重新渲染成片" in p for p in problems)
    save_json({"seg02": {"place": "不存在地名", "status": "CONFIRMED",
                         "chosen": "不存在地名XYZ", "chosen_resolved": False,
                         "confirmed_at": "2026-11-14T00:00:00"}},
              pdir / "map_confirm.json")
    problems = review.gate("ep-999")
    assert any("无法解析" in p for p in problems)


def test_manual_sources_precision():
    """「部分地区」不得因「部」误判有来源；「据某通讯社报道」应通过。"""
    from src import factcheck
    script = {"segments": [
        {"id": "seg02", "kind": "item",
         "narration": "部分地区发生变化，事态仍在发展。"},
        {"id": "seg03", "kind": "item",
         "narration": "据某通讯社报道，当地情况正在恢复。"},
        {"id": "seg04", "kind": "item",
         "narration": "港口恢复运转，情况持续好转。"}]}
    issues = factcheck.check_manual_sources(script)
    blocked = {i["seg"] for i in issues if i["rule"] == "RL-SRC-M"}
    assert blocked == {"seg02", "seg04"}              # seg03 有「据…报道」通过


def test_detector_parsers():
    """黑屏/冻结/静音解析：以真实 ffmpeg 输出格式为样本。"""
    from src import ffmpeg
    assert ffmpeg.parse_blackdetect(
        "black_start:0 black_end:4.96 black_duration:4.96") == [(0.0, 4.96)]
    assert ffmpeg.parse_freezedetect(
        "lavfi.freezedetect.freeze_start: 0\n"
        "lavfi.freezedetect.freeze_duration: 4.9") == [(0.0, 4.9)]
    assert ffmpeg.parse_silencedetect(
        "silence_start: 0\nsilence_end: 8 | silence_duration: 8") == [(0.0, 8.0)]
    assert ffmpeg.parse_blackdetect("no events") == []


def test_map_label_rect_bounds():
    """标记名牌：贴右缘翻左侧、靠上夹紧、常规居右。"""
    from src import cards
    lx, ly, lw, lh = cards._label_rect(1800, 300, 200, 1920, 1080)
    assert lx + lw <= 1920 - 8 and lx < 1800        # 翻到标记点左侧
    lx2, ly2, _, _ = cards._label_rect(500, 10, 200, 1920, 1080)
    assert ly2 >= 6 and ly2 <= 1080 - 54
    lx3, _, _, _ = cards._label_rect(500, 540, 200, 1920, 1080)
    assert lx3 == 512
