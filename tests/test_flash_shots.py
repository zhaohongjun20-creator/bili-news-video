# -*- coding: utf-8 -*-
"""线索包生成分镜清单、实拍剪入时间轴、以及不能靠删掉清单绕过许可门。"""
import subprocess

import pytest

from src.jsonio import load_json, save_json
from src.shotlist import ShotList

NE = ShotList.NE_URL
DVIDS = "https://www.dvidshub.net/video/1"
DVIDS_TERMS = "https://www.dvidshub.net/about/faq"
LIVE_LIC = f"DVIDS 公有领域 {DVIDS_TERMS}"
NEWS = "https://example.com/ungated-news"


def _pid(tmp_path, monkeypatch) -> str:
    from src import store
    monkeypatch.setattr(store, "ROOT", tmp_path)
    pdir = tmp_path / "projects" / "ep-001"
    for sub in ("audio", "cards", "output", "footage"):
        (pdir / sub).mkdir(parents=True)
    save_json({"pid": "ep-001", "date": "2026-11-20", "stages": {}},
              pdir / "manifest.json")
    return "ep-001"


def _brief(**over) -> dict:
    brief = {
        "source": "clue-v3.md",
        "标题": "塞尔维亚确认选举结果",
        "事实钩子": "11月20日塞尔维亚确认约140席。",
        "时间地点": "11月20日，塞尔维亚",
        "发生了什么": "11月20日塞尔维亚确认约140席。",
        "各方怎么说": "选举委员会：最终结果已经确认。",
        "信源署名": "选举委员会",
        "items": [{
            "title": "塞尔维亚确认选举结果【官方】",
            "summary": "11月20日塞尔维亚确认约140席。",
            "event_time": "11月20日",
            "chess": "面带微笑恐将引发颜色革命。",
            "risk": "不要把竞选写成已组阁。",
            "sources": [
                {"tier": "官方", "name": "选举委员会",
                 "claim": "最终结果已经确认。", "url": NEWS},
                {"tier": "主流媒体", "name": "某通讯社",
                 "claim": "尚未看到内阁名单。", "url": NEWS + "/wire"},
            ],
        }],
    }
    brief.update(over)
    return brief


def _hammer(tmp_path, status="ok"):
    save_json({"status": status, "items_left": 1},
              tmp_path / "projects" / "ep-001" / "hammer.json")


def test_generate_copies_package_fields_and_invents_nothing(tmp_path, monkeypatch):
    pid = _pid(tmp_path, monkeypatch)
    _hammer(tmp_path)
    from src import store
    save_json(_brief(), store.project_dir(pid) / "briefing.json")
    text = ShotList.generate(pid)
    assert ShotList.problems(text) == []

    for exact in ("塞尔维亚确认选举结果",
                  "11月20日塞尔维亚确认约140席。",
                  "11月20日，塞尔维亚",
                  "选举委员会：最终结果已经确认。",
                  "最终结果已经确认。",
                  "尚未看到内阁名单。",
                  "选举委员会",
                  "某通讯社"):
        assert exact in text
    for invented in ("面带微笑", "颜色革命", "不要把竞选写成已组阁",
                     NEWS, "画面类型: 官方实拍", "画面类型: 公有领域",
                     "画面类型: 明确许可", "双方对峙", "现场一片混乱"):
        assert invented not in text

    doc = ShotList.parse(text)
    assert doc["cover"]["是否指定素材静帧"] == "否"
    assert doc["cover"]["封面类型"] == "图形设计封面"
    assert "画面来源 URL" not in doc["cover"]
    hook = next(s for s in doc["shots"] if s["no"] == 1)
    assert hook["事实句"] == "11月20日塞尔维亚确认约140席。"
    assert hook["时码"] == "00:00.00–00:15.00"
    assert hook["画面类型"] == "地图卡"
    assert hook["来源 URL"] == NE
    assert "Natural Earth" in hook["许可"]
    assert hook["起止时间"] == "自制"
    claims = {s["事实句"]: s["出处"] for s in doc["shots"] if s["no"] != 1}
    assert claims == {"最终结果已经确认。": "选举委员会",
                      "尚未看到内阁名单。": "某通讯社"}
    assert "总规格:" in text and "锁定元素:" in text
    assert "按秒分镜:" in text and "禁止项:" in text
    locked = text.split("锁定元素:", 1)[1].split("按秒分镜:", 1)[0]
    for token in ("11月20日", "塞尔维亚", "140", "选举委员会"):
        assert token in locked
    assert "面带微笑" not in locked
    assert "红审状态：通过" in text


def test_ungated_live_becomes_map_card_without_fake_license(tmp_path, monkeypatch):
    pid = _pid(tmp_path, monkeypatch)
    _hammer(tmp_path)
    from src import store
    brief = _brief()
    brief["items"][0]["footage"] = {
        "画面类型": "官方实拍",
        "来源 URL": NEWS,
        "许可": "挂在官网",
        "起止时间": "",
    }
    brief["items"][0]["sources"] = [
        {"name": "选举委员会", "claim": "", "url": NEWS}]
    brief["各方怎么说"] = ""
    save_json(brief, store.project_dir(pid) / "briefing.json")
    text = ShotList.generate(pid)
    assert ShotList.problems(text) == []
    assert "官方实拍" not in text
    assert NEWS not in text
    assert "挂在官网" not in text
    assert "CC BY" not in text
    for shot in ShotList.parse(text)["shots"]:
        assert shot["画面类型"] == "地图卡"
        assert shot["来源 URL"] == NE
        assert shot["起止时间"] == "自制"


def test_gated_live_fields_are_copied_not_rewritten(tmp_path, monkeypatch):
    pid = _pid(tmp_path, monkeypatch)
    _hammer(tmp_path)
    from src import store
    brief = _brief()
    brief["各方怎么说"] = ""
    brief["items"][0]["sources"] = [
        {"name": "选举委员会", "claim": "", "url": NEWS}]
    brief["items"][0]["footage"] = {
        "画面类型": "公有领域",
        "来源 URL": DVIDS,
        "许可": LIVE_LIC,
        "起止时间": "00:12.00–00:20.00",
        "时码": "00:15.00–00:23.00",
        "素材文件": "footage/clip.mp4",
        "精确时码": "00:12.00",
    }
    save_json(brief, store.project_dir(pid) / "briefing.json")
    text = ShotList.generate(pid)
    assert ShotList.problems(text) == []
    doc = ShotList.parse(text)
    live = next(s for s in doc["shots"] if s["画面类型"] == "公有领域")
    assert live["来源 URL"] == DVIDS
    assert live["许可"] == LIVE_LIC
    assert live["起止时间"] == "00:12.00–00:20.00"
    assert live["时码"] == "00:15.00–00:23.00"
    assert live["事实句"] == "11月20日塞尔维亚确认约140席。"
    assert live["指定封面"] == "是"
    assert "footage/clip.mp4" in text
    assert doc["cover"]["是否指定素材静帧"] == "是"
    assert doc["cover"]["对应 CUT"] == f"{live['no']:02d}"
    assert DVIDS in doc["cover"]["画面来源 URL"]
    assert LIVE_LIC in doc["cover"]["许可"]
    assert doc["cover"]["精确时码"].startswith("00:12.00")
    hook = next(s for s in doc["shots"] if s["no"] == 1)
    assert hook["画面类型"] == "地图卡"
    assert hook["时码"] == "00:00.00–00:15.00"
    assert "图形提示词: 无" in text


def test_generate_requires_passed_red_review(tmp_path, monkeypatch):
    pid = _pid(tmp_path, monkeypatch)
    from src import store
    save_json(_brief(), store.project_dir(pid) / "briefing.json")
    with pytest.raises(RuntimeError, match="红审未通过"):
        ShotList.write(pid)
    assert not (store.project_dir(pid) / ShotList.FILENAME).exists()

    _hammer(tmp_path, "rejected")
    with pytest.raises(RuntimeError, match="红审未通过"):
        ShotList.generate(pid)

    _hammer(tmp_path, "ok")
    (store.project_dir(pid) / "briefing.md").write_text(
        "红审状态：退回\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="退回"):
        ShotList.generate(pid)
    assert not (store.project_dir(pid) / ShotList.FILENAME).exists()


def test_dropped_item_is_not_brought_back(tmp_path, monkeypatch):
    pid = _pid(tmp_path, monkeypatch)
    _hammer(tmp_path)
    from src import store
    brief = _brief()
    brief["items"].append({
        "title": "另一条",
        "summary": "这句被红审剔除的事实不该进清单。",
        "sources": [],
    })
    save_json(brief, store.project_dir(pid) / "briefing.json")
    save_json({"title": "t", "segments": [
        {"kind": "item", "item_ref": 1, "narration": "口播改写了事实，不该覆盖线索包。"}]},
        store.project_dir(pid) / "script.json")
    text = ShotList.generate(pid)
    assert "不该进清单" not in text
    assert "口播改写了事实" not in text


def test_missing_shotlist_blocks_only_when_live_footage_is_in_play(tmp_path, monkeypatch):
    pid = _pid(tmp_path, monkeypatch)
    from src import store
    pdir = store.project_dir(pid)
    assert ShotList.refusal(pid) is None
    assert ShotList.external_live(pid) is False

    (pdir / "footage" / "raw.mp4").write_bytes(b"video")
    msg = ShotList.refusal(pid)
    assert msg and "缺少分镜清单.md" in msg
    (pdir / "footage" / "raw.mp4").unlink()
    assert ShotList.refusal(pid) is None

    (pdir / "briefing.md").write_text(
        "画面类型：官方实拍\n来源 URL：https://example.com/a\n",
        encoding="utf-8")
    assert "缺少分镜清单.md" in ShotList.refusal(pid)
    (pdir / "briefing.md").unlink()

    save_json({"items": [{"footage": {"画面类型": "明确许可"}}]},
              pdir / "briefing.json")
    assert "缺少分镜清单.md" in ShotList.refusal(pid)


def test_live_cut_lands_on_program_timecode(tmp_path, monkeypatch):
    pid = _pid(tmp_path, monkeypatch)
    from src import store
    pdir = store.project_dir(pid)
    media = pdir / "footage" / "clip.mp4"
    media.write_bytes(b"video")
    text = _passing_live_doc(media_line="footage/clip.mp4")
    (pdir / ShotList.FILENAME).write_text(text, encoding="utf-8")
    assert ShotList.problems(text) == []
    assert ShotList.refusal(pid) is None

    _voice_script(pdir, hook_s=30.0, outro_s=5.0)
    from src.timeline import build_timeline
    tl = build_timeline(pid)
    assert len(tl["live_cuts"]) == 1
    cut = tl["live_cuts"][0]
    assert cut["start"] == 15.0 and cut["end"] == 23.0
    assert cut["src_in"] == 12.0 and cut["src_out"] == 20.0
    assert cut["path"].endswith("clip.mp4")

    pieces = ShotList.visual_pieces(tl)
    live = [p for p in pieces if p["kind"] == "live"]
    assert len(live) == 1
    assert live[0]["start"] == 15.0
    assert live[0]["length"] == 8.0
    assert live[0]["src_in"] == 12.0
    cards = [p for p in pieces if p["kind"] == "card" and p["seg"]["id"] == "seg01"]
    assert cards[0]["start"] == 0.0 and abs(cards[0]["length"] - 15.0) < 0.02
    assert abs(cards[1]["start"] - 23.0) < 0.02
    covered = sum(p["length"] for p in pieces if p["seg"]["id"] == "seg01")
    assert abs(covered - tl["segments"][0]["length"]) < 0.02
    assert ShotList.placement_problems(tl) == []

    from src.renderer import WH_PROMO_H, WH_PROMO_REF_H, WH_PROMO_Y, live_clip_command
    cmd = live_clip_command(cut["path"], live[0]["src_in"], live[0]["length"],
                            pdir / "clips" / "live.mp4", 30)
    assert "-ss" in cmd and "12.000" in cmd
    assert "-an" in cmd
    joined = " ".join(cmd)
    assert "fade" not in joined and "xfade" not in joined
    assert f"ih*{WH_PROMO_Y}/{WH_PROMO_REF_H}" in joined
    assert f"ih*{WH_PROMO_H}/{WH_PROMO_REF_H}" in joined
    assert "force_original_aspect_ratio=decrease" in joined


def test_live_without_local_file_or_from_finished_video_does_not_render(
        tmp_path, monkeypatch):
    pid = _pid(tmp_path, monkeypatch)
    from src import store
    pdir = store.project_dir(pid)
    (pdir / ShotList.FILENAME).write_text(
        _passing_live_doc(media_line="footage/missing.mp4"), encoding="utf-8")
    msg = ShotList.refusal(pid)
    assert msg and "没有可剪的本地素材" in msg

    finished = pdir / "output" / "final.mp4"
    finished.write_bytes(b"done")
    (pdir / ShotList.FILENAME).write_text(
        _passing_live_doc(media_line="output/final.mp4"), encoding="utf-8")
    msg = ShotList.refusal(pid)
    assert msg and "成片或产出目录" in msg

    outside = tmp_path / "secret.mp4"
    outside.write_bytes(b"x")
    (pdir / ShotList.FILENAME).write_text(
        _passing_live_doc(media_line="../secret.mp4"), encoding="utf-8")
    msg = ShotList.refusal(pid)
    assert msg and "不在项目目录内" in msg


def test_render_trims_gated_shot_and_does_not_grab_cover(tmp_path, monkeypatch):
    pid = _pid(tmp_path, monkeypatch)
    from src import renderer, store
    pdir = store.project_dir(pid)
    media = pdir / "footage" / "clip.mp4"
    media.write_bytes(b"video")
    (pdir / ShotList.FILENAME).write_text(
        _passing_live_doc(media_line="footage/clip.mp4"), encoding="utf-8")
    _voice_script(pdir, hook_s=30.0, outro_s=5.0)
    for name in ("seg01", "seg02"):
        (pdir / "cards" / f"{name}.png").write_bytes(b"png")
    save_json({"cards": [
        {"id": "seg01", "png": str(pdir / "cards" / "seg01.png")},
        {"id": "seg02", "png": str(pdir / "cards" / "seg02.png")},
    ]}, pdir / "cards.json")

    cmds = []

    def fake_run(cmd, timeout=1800, cwd=None):
        cmds.append([str(c) for c in cmd])
        out = __import__("pathlib").Path(cmd[-1])
        if not out.is_absolute():
            out = tmp_path / out.name
        if out.suffix == ".mp4":
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"mp4")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(renderer.ffmpeg, "run", fake_run)
    monkeypatch.setattr(renderer.ffmpeg, "probe_video",
                        lambda _p: {"duration": 36.0, "width": 1920,
                                    "height": 1080, "fps": 30.0})

    def fake_cover(_pid):
        dest = store.project_dir(_pid) / "output" / "cover.jpg"
        dest.write_bytes(b"cover")
        return dest

    import src.cards as cards_mod
    monkeypatch.setattr(cards_mod, "make_cover", fake_cover)

    renderer.render(pid)
    live_cmds = [c for c in cmds if "-ss" in c and str(media) in c]
    assert len(live_cmds) == 1
    assert "fade" not in " ".join(live_cmds[0])
    assert "-an" in live_cmds[0]
    # 封面不是从成片或实拍抽的帧
    for c in cmds:
        if "-ss" in c:
            assert "final.mp4" not in " ".join(c)
    assert (pdir / "output" / "cover.jpg").read_bytes() == b"cover"
    assert renderer.ASS_MARGIN_RATIO == 0.04


def test_live_past_episode_end_is_not_silently_dropped(tmp_path, monkeypatch):
    pid = _pid(tmp_path, monkeypatch)
    from src import renderer, store
    pdir = store.project_dir(pid)
    (pdir / "footage" / "clip.mp4").write_bytes(b"video")
    (pdir / ShotList.FILENAME).write_text(
        _passing_live_doc(media_line="footage/clip.mp4"), encoding="utf-8")
    _voice_script(pdir, hook_s=4.0, outro_s=2.0)
    with pytest.raises(RuntimeError, match="超出节目时长"):
        renderer.render(pid)


def test_duration_mismatch_does_not_enter_render(tmp_path, monkeypatch):
    pid = _pid(tmp_path, monkeypatch)
    from src import store
    pdir = store.project_dir(pid)
    (pdir / "footage" / "clip.mp4").write_bytes(b"video")
    text = _passing_live_doc(media_line="footage/clip.mp4",
                             program="00:15.00–00:30.00")
    (pdir / ShotList.FILENAME).write_text(text, encoding="utf-8")
    assert ShotList.problems(text) == []
    msg = ShotList.refusal(pid)
    assert msg and "长度与素材起止不一致" in msg


def test_promo_band_is_covered_without_stretching(tmp_path):
    """1280×720 上第 590–679 行的宣传条被盖住；条上、条下的画面还在，人脸不变形。"""
    from PIL import Image

    from src import ffmpeg
    from src.renderer import WH_PROMO_H, WH_PROMO_REF_H, WH_PROMO_Y, live_picture_filter

    assert (WH_PROMO_Y, WH_PROMO_H, WH_PROMO_REF_H) == (590, 90, 720)
    src = tmp_path / "src.png"
    out = tmp_path / "out.png"
    im = Image.new("RGB", (1280, 720), (10, 20, 40))
    px = im.load()
    for y in range(180, 221):
        for x in range(600, 681):
            px[x, y] = (255, 0, 0)
    for y in range(WH_PROMO_Y, WH_PROMO_Y + WH_PROMO_H):
        for x in range(1280):
            px[x, y] = (250, 250, 250)
    for y in range(620, 661):
        for x in range(1180, 1241):
            px[x, y] = (0, 0, 0)
    for y in range(690, 720):
        for x in range(600, 681):
            px[x, y] = (0, 255, 0)
    im.save(src)

    cmd = [ffmpeg.ffmpeg_exe(), "-y", "-i", str(src),
           "-vf", live_picture_filter(), "-frames:v", "1", str(out)]
    r = ffmpeg.run(cmd, timeout=60)
    assert r.returncode == 0, r.stderr[-400:]
    got = Image.open(out)
    assert got.size == (1920, 1080)
    g = got.load()

    def at(sx, sy):
        return g[round(sx * 1920 / 1280), round(sy * 1080 / 720)]

    assert at(640, 200)[0] > 200 and at(640, 200)[1] < 40
    assert at(400, 640) == (0, 0, 0)
    assert at(1210, 640) == (0, 0, 0)
    assert at(640, 700)[1] > 200 and at(640, 700)[0] < 40
    # 16:9 进、16:9 出，条下的画面仍在底边，没有被裁掉后再拉高
    assert at(640, 710)[1] > 200


def test_card_only_timeline_has_no_live_cuts(tmp_path, monkeypatch):
    pid = _pid(tmp_path, monkeypatch)
    from src import store
    from src.timeline import build_timeline
    pdir = store.project_dir(pid)
    _voice_script(pdir, hook_s=8.0, outro_s=3.0)
    tl = build_timeline(pid)
    assert tl["live_cuts"] == []
    pieces = ShotList.visual_pieces(tl)
    assert [p["kind"] for p in pieces] == ["card", "card"]
    assert abs(pieces[0]["length"] - tl["segments"][0]["length"]) < 0.001


def _voice_script(pdir, hook_s, outro_s):
    save_json({
        "title": "塞尔维亚确认选举结果",
        "meta": {"date": "2026-11-20", "show_label": "时政快讯"},
        "segments": [
            {"id": "seg01", "kind": "hook",
             "narration": "11月20日塞尔维亚确认约140席。",
             "card": {"type": "hook"}},
            {"id": "seg02", "kind": "outro", "narration": "下期见。",
             "card": {"type": "outro"}},
        ],
    }, pdir / "script.json")
    save_json({"segments": [
        {"id": "seg01", "duration": hook_s, "wav": "a.wav"},
        {"id": "seg02", "duration": outro_s, "wav": "b.wav"},
    ]}, pdir / "voice.json")


def _passing_live_doc(media_line: str, program: str = "00:15.00–00:23.00") -> str:
    hook = "\n".join([
        "CUT: 01",
        "时码: 00:00.00–00:15.00",
        "镜类: 开头钩子",
        "事实句: 11月20日塞尔维亚确认约140席。",
        "出处: 选举委员会",
        "画面类型: 地图卡",
        f"来源 URL: {NE}",
        f"许可: {ShotList.NE_LIC}",
        "起止时间: 自制",
        "字幕: 11月20日塞尔维亚确认约140席。",
        "指定封面: 否",
    ])
    live = "\n".join([
        "CUT: 02",
        f"时码: {program}",
        "镜类: 正文",
        "事实句: 11月20日塞尔维亚确认约140席。",
        "出处: 选举委员会",
        "画面类型: 公有领域",
        f"来源 URL: {DVIDS}",
        f"许可: {LIVE_LIC}",
        "起止时间: 00:12.00–00:20.00",
        "字幕: 11月20日塞尔维亚确认约140席。",
        "指定封面: 否",
        f"素材文件: {media_line}",
        "图形提示词: 无",
    ])
    return "\n".join([
        "# 线索包 → 分镜清单",
        "## 1. 封面（必填，单独成栏）",
        "- 是否指定素材静帧：否",
        "- 封面类型：图形设计封面",
        "## 2. 分镜",
        hook,
        "",
        live,
        "",
    ])
