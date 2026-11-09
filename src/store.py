# -*- coding: utf-8 -*-
"""项目存储：每期一个 projects/ep-NNN/ 目录，manifest.json 记录阶段状态。

目录内容：
    briefing.md      Grok 简报原文（人工粘贴，留档）
    briefing.json    结构化简报（ingest 输出）
    script.json      逐字稿 + 每段卡片字段（scriptgen 输出）
    hammer.json      锤稿检查结果（redline/lint 输出）
    timeline.json    时间轴（voice 后根据实际音频时长计算）
    review.json      审片状态与意见
    manifest.json    阶段状态机（断点续跑依据）
    audio/           逐段配音 wav
    cards/           逐段文字卡 png
    output/          final.mp4 / cover.jpg / qc_report.json / upload_info.txt

阶段：ingest → script → hammer → voice → render → qc
manifest.stages[stage] == "done" 即跳过；redo 使指定阶段及其后全部失效。
"""
import re
import time
from pathlib import Path

from src.jsonio import load_json, save_json

ROOT = Path(__file__).resolve().parent.parent

STAGES = ("ingest", "script", "hammer", "voice", "render", "qc")


class StoreError(RuntimeError):
    pass


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def projects_dir() -> Path:
    p = ROOT / "projects"
    p.mkdir(exist_ok=True)
    return p


def project_dir(pid: str) -> Path:
    pdir = projects_dir() / pid
    if not pdir.is_dir():
        raise StoreError(f"项目不存在: {pid}")
    return pdir


def new_project(briefing_md_path: Path, date: str) -> tuple[str, Path]:
    """从简报原文建新项目，返回 (pid, 项目目录)。"""
    nums = [int(m.group(1)) for d in projects_dir().iterdir()
            if (m := re.fullmatch(r"ep-(\d+)", d.name))]
    pid = f"ep-{max(nums, default=0) + 1:03d}"
    pdir = projects_dir() / pid
    for sub in ("audio", "cards", "output"):
        (pdir / sub).mkdir(parents=True, exist_ok=True)
    md = Path(briefing_md_path).read_text(encoding="utf-8")
    (pdir / "briefing.md").write_text(md, encoding="utf-8")
    save_json({"pid": pid, "date": date, "created_at": now(), "stages": {}},
              pdir / "manifest.json")
    return pid, pdir


def manifest(pid: str) -> dict:
    m = load_json(project_dir(pid) / "manifest.json")
    if not m:
        raise StoreError(f"manifest 缺失: {pid}")
    return m


def stage_done(pid: str, stage: str) -> bool:
    return manifest(pid)["stages"].get(stage) == "done"


def mark_stage(pid: str, stage: str, detail: str = "") -> None:
    m = manifest(pid)
    m["stages"][stage] = "done"
    if detail:
        m.setdefault("notes", {})[stage] = detail
    m["updated_at"] = now()
    save_json(m, project_dir(pid) / "manifest.json")


def redo_stage(pid: str, stage: str) -> None:
    """使指定阶段及其后全部失效（下游都基于上游产物，必须重跑）。"""
    if stage not in STAGES:
        raise StoreError(f"未知阶段: {stage}")
    m = manifest(pid)
    idx = STAGES.index(stage)
    for s in STAGES[idx:]:
        m["stages"].pop(s, None)
    m["updated_at"] = now()
    save_json(m, project_dir(pid) / "manifest.json")
