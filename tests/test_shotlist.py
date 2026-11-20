# -*- coding: utf-8 -*-
"""分镜清单许可门：过门进渲染，缺来源/许可/时码或封面不合格则拦住。"""
from pathlib import Path

import pytest

from src.shotlist import ShotList

NE = "https://www.naturalearthdata.com/about/terms-of-use/"
DVIDS = "https://www.dvidshub.net/video/1"
DVIDS_TERMS = "https://www.dvidshub.net/about/faq"
LIVE_LIC = f"DVIDS 公有领域 {DVIDS_TERMS}"


def _map(**over) -> dict:
    shot = {
        "CUT": "01",
        "时码": "00:00.00–00:15.00",
        "镜类": "开头钩子",
        "事实句": "11月20日某地发生了某事。",
        "出处": "当事方公告",
        "画面类型": "地图卡",
        "来源 URL": NE,
        "许可": f"自制；Natural Earth 公有领域 {NE}",
        "起止时间": "自制",
        "字幕": "11月20日某地发生了某事。",
        "指定封面": "否",
    }
    shot.update(over)
    return shot


def _live(**over) -> dict:
    shot = {
        "CUT": "02",
        "时码": "00:15.00–00:25.00",
        "镜类": "正文",
        "事实句": "当事方公布了一段现场画面。",
        "出处": "DVIDS",
        "画面类型": "官方实拍",
        "来源 URL": DVIDS,
        "许可": LIVE_LIC,
        "起止时间": "00:12.00–00:20.00",
        "字幕": "当事方公布了一段现场画面。",
        "指定封面": "否",
    }
    shot.update(over)
    return shot


def _doc(shots, *, still="否", cover_type="纯文字封面", cover_lines=()) -> str:
    cover = [
        "## 1. 封面（必填，单独成栏）",
        f"- 是否指定素材静帧：{still}",
        f"- 封面类型：{cover_type}",
        *cover_lines,
        "- 主标题 / 事实副题：某事发生 / 11月20日某地",
    ]
    blocks = []
    for shot in shots:
        lines = [f"{key}: {shot[key]}" for key in shot]
        blocks.append("```\n" + "\n".join(lines) + "\n```")
    body = "# 线索包 → 分镜清单\n\n" + "\n".join(cover)
    body += "\n\n## 2. 分镜\n\n" + "\n\n".join(blocks) + "\n"
    return body


def _specified_cover_lines() -> list[str]:
    return [
        "- 对应 CUT：02",
        f"- 画面来源 URL：{DVIDS}",
        f"- 许可（名称 + 条款页）：{LIVE_LIC}",
        "- 精确时码（素材入点；精确到秒，能到帧更好）：00:12.00",
    ]


def test_map_card_zizhi_with_basemap_passes():
    assert ShotList.problems(_doc([_map()])) == []


def test_data_card_zizhi_without_basemap_passes():
    shot = _map(**{
        "画面类型": "数据卡",
        "来源 URL": "",
        "许可": "自制",
        "起止时间": "自制",
    })
    assert ShotList.problems(_doc([shot])) == []


def test_map_card_zizhi_without_basemap_fails():
    shot = _map(**{"来源 URL": "", "许可": "自制"})
    problems = ShotList.problems(_doc([shot]))
    assert any("来源 URL" in p for p in problems)
    assert any("条款页" in p for p in problems)


@pytest.mark.parametrize("kind", ["官方实拍", "公有领域", "明确许可"])
def test_live_shot_with_license_passes(kind):
    assert ShotList.problems(_doc([_map(), _live(**{"画面类型": kind})])) == []


@pytest.mark.parametrize("kind,field,value,token", [
    ("官方实拍", "来源 URL", "", "来源 URL"),
    ("公有领域", "许可", "", "许可"),
    ("公有领域", "许可", "DVIDS 公有领域", "条款页"),
    ("官方实拍", "许可", DVIDS_TERMS, "名称"),
    ("明确许可", "起止时间", "", "起止时间"),
    ("明确许可", "起止时间", "自制", "起止时间"),
])
def test_live_shot_missing_gate_field_fails(kind, field, value, token):
    problems = ShotList.problems(_doc([
        _map(), _live(**{"画面类型": kind, field: value})]))
    assert problems
    assert any("CUT 02" in p and token in p for p in problems)


def test_specified_cover_from_gated_shot_passes():
    text = _doc(
        [_map(), _live(**{"指定封面": "是"})],
        still="是",
        cover_lines=_specified_cover_lines(),
    )
    assert ShotList.problems(text) == []


def test_specified_cover_missing_timecode_fails():
    lines = [ln for ln in _specified_cover_lines() if "精确时码" not in ln]
    problems = ShotList.problems(_doc(
        [_map(), _live(**{"指定封面": "是"})],
        still="是", cover_lines=lines))
    assert any("精确时码" in p for p in problems)


def test_specified_cover_mismatched_source_fails():
    lines = _specified_cover_lines()
    lines[1] = "- 画面来源 URL：https://example.com/other"
    problems = ShotList.problems(_doc(
        [_map(), _live(**{"指定封面": "是"})],
        still="是", cover_lines=lines))
    assert any("不一致" in p for p in problems)


def test_specified_cover_rejects_ungated_shot():
    problems = ShotList.problems(_doc(
        [_map(), _live(**{"指定封面": "是", "来源 URL": ""})],
        still="是", cover_lines=_specified_cover_lines()))
    assert any("未过许可门" in p for p in problems)


@pytest.mark.parametrize("cover_type", ["纯文字封面", "图形设计封面"])
def test_unspecified_cover_types_pass(cover_type):
    assert ShotList.problems(_doc([_map()], cover_type=cover_type)) == []


def test_unspecified_cover_rejects_other_label():
    problems = ShotList.problems(_doc([_map()], cover_type="新闻截图"))
    assert any("纯文字封面" in p and "图形设计封面" in p for p in problems)


def test_unspecified_cover_rejects_extra_url():
    problems = ShotList.problems(_doc(
        [_map()],
        cover_lines=["- 画面来源 URL：https://example.com/still.jpg"]))
    assert any("不得另附" in p for p in problems)


def test_cut01_must_cover_first_15_seconds():
    short = ShotList.problems(_doc([_map(**{"时码": "00:00.00–00:12.00"})]))
    assert any("15" in p for p in short)
    late = ShotList.problems(_doc([_map(**{"时码": "00:02.00–00:20.00"})]))
    assert any("15" in p for p in late)
    missing = ShotList.problems(_doc([_map(**{"CUT": "02"})]))
    assert any("缺少 CUT 01" in p for p in missing)


def test_prompt_example_is_not_a_shot():
    text = _doc([_map()]) + """
### 图形提示词写法（占位示例，不可用于成片）

```
总规格：16:9，卡面或地图
CUT: 99
画面类型: 官方实拍
```
"""
    assert ShotList.problems(text) == []


def test_blank_template_does_not_pass():
    root = Path(__file__).resolve().parent.parent
    text = (root / "docs" / "线索包-分镜清单-标准模板.md").read_text(encoding="utf-8")
    problems = ShotList.problems(text)
    assert any("缺少 CUT 01" in p for p in problems)
    assert any("是否指定素材静帧" in p for p in problems)


def test_render_blocks_failed_shotlist_before_timeline(tmp_path, monkeypatch):
    from src import renderer, store
    monkeypatch.setattr(store, "ROOT", tmp_path)
    pdir = tmp_path / "projects" / "ep-999"
    pdir.mkdir(parents=True)
    (pdir / ShotList.FILENAME).write_text(
        _doc([_live(**{"CUT": "01", "时码": "00:00.00–00:15.00",
                       "来源 URL": ""})]),
        encoding="utf-8")

    def _no(*_a, **_k):
        raise AssertionError("timeline should not run")

    monkeypatch.setattr(renderer.timeline, "build_timeline", _no)
    with pytest.raises(RuntimeError, match="不进渲染"):
        renderer.render("ep-999")


def test_render_without_shotlist_reaches_timeline(tmp_path, monkeypatch):
    from src import renderer, store
    monkeypatch.setattr(store, "ROOT", tmp_path)
    (tmp_path / "projects" / "ep-999").mkdir(parents=True)

    def _reached(*_a, **_k):
        raise RuntimeError("reached-timeline")

    monkeypatch.setattr(renderer.timeline, "build_timeline", _reached)
    with pytest.raises(RuntimeError, match="reached-timeline"):
        renderer.render("ep-999")


def test_make_blocks_failed_shotlist_before_cards(tmp_path, monkeypatch):
    from src import pipeline, store
    from src.jsonio import save_json
    monkeypatch.setattr(store, "ROOT", tmp_path)
    pdir = tmp_path / "projects" / "ep-999"
    pdir.mkdir(parents=True)
    save_json({"pid": "ep-999", "stages": {
        "script": "done", "hammer": "done", "voice": "done"}},
        pdir / "manifest.json")
    (pdir / ShotList.FILENAME).write_text(
        _doc([_map(**{"来源 URL": "", "许可": "自制"})]),
        encoding="utf-8")

    def _no(*_a, **_k):
        raise AssertionError("cards should not render")

    monkeypatch.setattr(pipeline.cards, "render_cards", _no)
    with pytest.raises(pipeline.PipelineError, match="不进渲染"):
        pipeline.make("ep-999")
