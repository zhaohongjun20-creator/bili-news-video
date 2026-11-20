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


_LOCKED = """
## 1. 封面（必填，单独成栏）
- 是否指定素材静帧：否
- 封面类型：图形设计封面
- 主标题 / 事实副题：美澳印日四国领导人在马尼拉举行四方安全对话峰会 / 11月17日发表联合新闻稿

## 2. 分镜

CUT: 01
时码: 00:00.00–00:15.00
镜类: 开头钩子
画面类型: 数据卡
来源 URL: 自制
许可: 自制
起止时间: 自制
字幕:
  00:00.00–00:06.00  11月17日，美澳印日四国领导人
  00:06.00–00:12.00  在马尼拉举行四方安全对话峰会
  00:12.00–00:15.00  并发表联合新闻稿
指定封面: 否

CUT: 02
时码: 00:15.00–00:25.00
镜类: 正文
画面类型: 数据卡
来源 URL: 自制
许可: 自制
起止时间: 自制
字幕:
  00:15.00–00:20.00  日方官方摘要写明
  00:20.00–00:25.00  会谈当地时间 18:45 开始，约 90 分钟
锁定元素：日期 2026年11月17日；当地时间 18:45（日本时间 19:45）；约 90 分钟；署名「日本首相官邸官方摘要」；可出现高市早苗当时在马尼拉出席东盟相关峰会，不添加其他行程
指定封面: 否

CUT: 04
时码: 00:37.00–00:53.00
镜类: 正文
画面类型: 数据卡
来源 URL: 自制
许可: 自制
起止时间: 自制
字幕:
  00:37.00–00:45.00  联合新闻稿写明，强烈反对以武力或胁迫改变现状
  00:45.00–00:53.00  并对经济胁迫表示严重关切；此段未点名国家或海域
锁定元素：只出示联合新闻稿原句要点：改变现状、武力或胁迫、经济胁迫、任意出口限制；画面或字幕须保留「未点名特定国家或海域」；署名联合新闻稿
指定封面: 否

CUT: 05
时码: 00:53.00–01:09.00
镜类: 正文
画面类型: 数据卡
来源 URL: 自制
许可: 自制
起止时间: 自制
字幕:
  00:53.00–00:59.00  日本首相官邸官方摘要写明
  00:59.00–01:05.00  会上谈到印太局势，包括东海和南海
  01:05.00–01:09.00  联合新闻稿未点名海域
锁定元素：必须署名「日本首相官邸官方摘要」；可出现「东海和南海」，并必须同时写明「联合新闻稿未点名海域」；其余只用摘要中的改变现状、武力或胁迫、经济胁迫、关键供应链
指定封面: 否

CUT: 06
时码: 01:09.00–01:23.00
镜类: 正文
画面类型: 数据卡
来源 URL: 自制
许可: 自制
起止时间: 自制
字幕:
  01:09.00–01:16.00  稿件写明，首届工商领袖论坛定于 2027 年初举行
  01:16.00–01:23.00  并重申 Super Intelligence Accelerator
指定封面: 否

CUT: 07
时码: 01:23.00–01:39.00
镜类: 正文
画面类型: 数据卡
来源 URL: 自制
许可: 自制
起止时间: 自制
字幕:
  01:23.00–01:31.00  联合新闻稿欢迎印太海上监视合作
  01:31.00–01:39.00  稿件写明，2027 年定于首次举行巡逻机海上演习
锁定元素：印太范围示意；「印太海上监视合作」；P-8、P-3C；2027 年；「稿件写明定于」；首次在四方框架下进行海上演习；署名联合新闻稿
指定封面: 否

CUT: 10
时码: 02:07.00–02:23.00
镜类: 正文
画面类型: 数据卡
来源 URL: 自制
许可: 自制
起止时间: 自制
字幕:
  02:07.00–02:15.00  日方官方摘要写明，高市早苗谈到海上安全、经济安全与关键技术
  02:15.00–02:23.00  并提到 POWERR Asia 和 POWERR Gulf 倡议
锁定元素：必须署名「日本首相官邸官方摘要」；海上安全、经济安全与能源、关键和新兴技术；POWERR Asia；POWERR Gulf
指定封面: 否
"""


def _shot(text, no):
    return next(s for s in ShotList.timed_shots(text) if s["no"] == no)


def test_locked_beats_keep_wording_and_cover_copy():
    shots = ShotList.timed_shots(_LOCKED)
    assert [s["no"] for s in shots] == [1, 2, 4, 5, 6, 7, 10]
    hook = shots[0]["cues"]
    assert [(c["start"], c["end"], c["text"]) for c in hook] == [
        (0.0, 6.0, "11月17日，美澳印日四国领导人"),
        (6.0, 12.0, "在马尼拉举行四方安全对话峰会"),
        (12.0, 15.0, "并发表联合新闻稿"),
    ]
    assert ShotList.cover_copy(_LOCKED) == (
        "美澳印日四国领导人在马尼拉举行四方安全对话峰会",
        "11月17日发表联合新闻稿",
    )
    built = ShotList.script_from_shots(
        {"title": "旧标题", "meta": {"mode": "manual", "date": "2026-11-17"},
         "segments": []},
        shots, *ShotList.cover_copy(_LOCKED))
    assert built["title"] == "美澳印日四国领导人在马尼拉举行四方安全对话峰会"
    assert "会谈起止" not in built["title"]
    assert "东海" not in built["title"] and "南海" not in built["title"]
    assert built["meta"]["cover_sub"] == "11月17日发表联合新闻稿"
    assert built["segments"][0]["narration"] == (
        "11月17日，美澳印日四国领导人"
        "在马尼拉举行四方安全对话峰会"
        "并发表联合新闻稿")
    assert "美国、澳大利亚" not in built["segments"][0]["narration"]

    card2 = ShotList.card_lines(_shot(_LOCKED, 2)["cues"], _shot(_LOCKED, 2)["locked"])
    assert "会谈当地时间 18:45 开始，约 90 分钟" in card2
    assert "当地时间 18:45（日本时间 19:45）" in card2
    assert "会谈起止" not in "".join(card2)

    card4 = "".join(ShotList.card_lines(
        _shot(_LOCKED, 4)["cues"], _shot(_LOCKED, 4)["locked"]))
    assert "东海" not in card4 and "南海" not in card4
    assert "未点名" in card4

    card5 = "".join(ShotList.card_lines(
        _shot(_LOCKED, 5)["cues"], _shot(_LOCKED, 5)["locked"]))
    assert "日本首相官邸官方摘要" in card5
    assert "联合新闻稿未点名海域" in card5
    assert "东海和南海" in card5

    for no in (6, 7):
        spoken = "".join(c["text"] for c in _shot(_LOCKED, no)["cues"])
        assert "稿件写明" in spoken and "定于" in spoken

    spoken10 = [c["text"] for c in _shot(_LOCKED, 10)["cues"]]
    assert spoken10 == [
        "日方官方摘要写明，高市早苗谈到海上安全、经济安全与关键技术",
        "并提到 POWERR Asia 和 POWERR Gulf 倡议",
    ]
    card10 = "".join(ShotList.card_lines(
        _shot(_LOCKED, 10)["cues"], _shot(_LOCKED, 10)["locked"]))
    for banned in ("朝鲜", "绑架", "中东", "伊朗"):
        assert banned not in card10


def test_untimed_subtitle_does_not_become_locked_beats():
    assert ShotList.timed_shots(_passing_live_doc("footage/clip.mp4")) == []


def test_locked_program_times_skip_audio_padding(tmp_path, monkeypatch):
    pid = _pid(tmp_path, monkeypatch)
    from src import store
    from src.timeline import build_timeline
    pdir = store.project_dir(pid)
    ranges = [(0, 15), (15, 25), (25, 37), (37, 53), (53, 69),
              (69, 83), (83, 99), (99, 113), (113, 127), (127, 143)]
    segments = []
    voice = []
    for i, (a, b) in enumerate(ranges, 1):
        sid = f"seg{i:02d}"
        segments.append({"id": sid, "kind": "hook" if i == 1 else "item",
                         "narration": "口播", "program_start": float(a),
                         "program_end": float(b),
                         "card": {"type": "headline"}})
        voice.append({"id": sid, "duration": 4.0, "wav": "a.wav"})
    save_json({"title": "t", "meta": {"date": "2026-11-17"},
               "segments": segments}, pdir / "script.json")
    save_json({"segments": voice}, pdir / "voice.json")
    tl = build_timeline(pid)
    assert [(s["start"], s["length"]) for s in tl["segments"]] == [
        (float(a), float(b - a)) for a, b in ranges]
    assert all(s["audio_in"] == 0 for s in tl["segments"])
    assert tl["total_s"] == 143


def test_locked_subtitle_events_use_cue_times():
    from src.renderer import subtitle_events
    cues = {"seg01": [
        {"start": 0.0, "end": 6.0, "text": "11月17日，美澳印日四国领导人"},
        {"start": 6.0, "end": 12.0, "text": "在马尼拉举行四方安全对话峰会"},
        {"start": 12.0, "end": 15.0, "text": "并发表联合新闻稿"},
    ]}
    tl = [{"id": "seg01", "start": 0.0, "audio_in": 0.3, "audio_duration": 9.0}]
    ev = subtitle_events(
        {"seg01": "11月17日，美国、澳大利亚、印度和日本四国领导人在马尼拉举行。"},
        tl, cues)
    assert ev == [
        (0.0, 6.0, "11月17日，美澳印日四国领导人"),
        (6.0, 12.0, "在马尼拉举行四方安全对话峰会"),
        (12.0, 15.0, "并发表联合新闻稿"),
    ]


def test_cover_lines_do_not_use_the_item_headline():
    from src.cards import cover_lines
    script = {
        "title": "美澳印日四国领导人在马尼拉举行四方安全对话峰会",
        "meta": {"cover_title": "美澳印日四国领导人在马尼拉举行四方安全对话峰会",
                 "cover_sub": "11月17日发表联合新闻稿"},
        "segments": [{"kind": "item", "card": {"headline": "会谈起止"}}],
    }
    assert cover_lines(script) == (
        "美澳印日四国领导人在马尼拉举行四方安全对话峰会",
        "11月17日发表联合新闻稿",
    )


def test_wrap_all_keeps_every_character():
    from src.cards import _wrap_all

    class _Draw:
        def textlength(self, text, font=None):
            return len(text) * 10

    text = "会谈当地时间 18:45 开始，约 90 分钟" * 3
    lines = _wrap_all(text, None, _Draw(), 80)
    assert "".join(lines) == text
    assert all(len(ln) <= 8 for ln in lines)


def test_bind_refuses_a_shot_list_that_fails_the_gate(tmp_path, monkeypatch):
    pid = _pid(tmp_path, monkeypatch)
    from src import store
    pdir = store.project_dir(pid)
    (pdir / ShotList.FILENAME).write_text(
        "CUT: 01\n时码: 00:00.00–00:15.00\n字幕:\n  00:00.00–00:06.00  只有半句\n",
        encoding="utf-8")
    save_json({"title": "保持不动", "meta": {"date": "2026-11-17", "mode": "manual"},
               "segments": [{"id": "seg01", "kind": "hook", "narration": "旧口播"}]},
              pdir / "script.json")
    assert ShotList.bind_episode(pid) is False
    assert load_json(pdir / "script.json")["segments"][0]["narration"] == "旧口播"


def test_bind_replaces_narration_and_drops_old_voice(tmp_path, monkeypatch):
    pid = _pid(tmp_path, monkeypatch)
    from src import store
    pdir = store.project_dir(pid)
    text = "\n".join([
        "## 1. 封面（必填，单独成栏）",
        "- 是否指定素材静帧：否",
        "- 封面类型：图形设计封面",
        "- 主标题 / 事实副题：美澳印日四国领导人在马尼拉举行四方安全对话峰会 / 11月17日发表联合新闻稿",
        "## 2. 分镜",
        "CUT: 01",
        "时码: 00:00.00–00:15.00",
        "镜类: 开头钩子",
        "画面类型: 数据卡",
        "来源 URL: 自制",
        "许可: 自制",
        "起止时间: 自制",
        "字幕:",
        "  00:00.00–00:06.00  11月17日，美澳印日四国领导人",
        "  00:06.00–00:12.00  在马尼拉举行四方安全对话峰会",
        "  00:12.00–00:15.00  并发表联合新闻稿",
        "指定封面: 否",
    ])
    assert ShotList.problems(text) == []
    (pdir / ShotList.FILENAME).write_text(text, encoding="utf-8")
    save_json({"title": "旧标题", "meta": {"date": "2026-11-17", "mode": "manual",
                                         "show_label": "时政快讯"},
               "segments": [{"id": "seg01", "kind": "hook",
                             "narration": "11月17日，美国、澳大利亚、印度和日本。",
                             "card": {"headline": "会谈起止"}}]},
              pdir / "script.json")
    (pdir / "audio").mkdir(exist_ok=True)
    (pdir / "audio" / "old.wav").write_bytes(b"not-audio")
    (pdir / "voice.json").write_text("{}", encoding="utf-8")
    save_json({"pid": pid, "stages": {"script": "done", "hammer": "done",
                                      "voice": "done"}},
              pdir / "manifest.json")
    assert ShotList.bind_episode(pid) is True
    script = load_json(pdir / "script.json")
    assert script["segments"][0]["narration"].startswith("11月17日，美澳印日四国领导人")
    assert "美国、澳大利亚" not in script["segments"][0]["narration"]
    assert script["meta"]["cover_sub"] == "11月17日发表联合新闻稿"
    assert script["segments"][0]["card"]["headline"] != "会谈起止"
    assert not (pdir / "audio" / "old.wav").exists()
    assert not (pdir / "voice.json").exists()
    assert store.stage_done(pid, "hammer") is False
    assert ShotList.bind_episode(pid) is False
