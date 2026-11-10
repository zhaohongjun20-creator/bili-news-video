# -*- coding: utf-8 -*-
"""人工稿通道：已成稿的口播逐字稿（markdown）→ script.json（mode="manual"）。

跳过 briefing/scriptgen 的 AI 写稿环节，但 hammer（硬红线）/voice/cards/render/qc
全链照走——人写稿，机器仍守红线。约定稿式（与 Grok 出稿模板一致）：

    **【00:00–00:18｜开场钩子】**
    （空行）
    【画面提示】……（段落跳过，到空行为止）
    （空行）
    口播正文行……（硬换行的散文，直接拼接）

红线：本模块只做格式解析，不做任何内容改写；解析不出段落的稿子直接报错。
"""
import re
from pathlib import Path

from src import store
from src.jsonio import save_json

_HEADER = re.compile(r"\*\*【([^】]+)】\*\*")
_MAIN_TITLE = re.compile(r"\*\*主标题\*\*[：:]\s*(.+)")


def _parse_blocks(md: str) -> list[dict]:
    """按 【时间｜标题】 头切块；块内跳过画面提示段落（到空行），其余为口播。
    md 标题行（#）或分隔线（---）终止当前块——稿子的第 5-8 节（信源表、
    红线清单等）绝不能被吞进最后一段口播。"""
    blocks: list[dict] = []
    cur: dict | None = None
    in_pv = False                                   # 正在画面提示段落
    for raw in md.splitlines():
        ln = raw.strip()
        m = _HEADER.fullmatch(ln)
        if m:
            meta, _, title = m.group(1).partition("｜")
            cur = {"time": meta.strip(), "title": title.strip(), "lines": []}
            blocks.append(cur)
            in_pv = False
            continue
        if cur is None:
            continue
        if not ln:                                  # 空行 = 段落边界（先于分隔线判断！
            in_pv = False                            #  set('') <= {'-'} 恒为 True）
            continue
        if ln.startswith("#") or ln.startswith("---"):  # md 标题/分隔线 → 块终止
            cur = None
            in_pv = False
            continue
        if ln.startswith("【画面提示】") or in_pv:
            in_pv = True                            # 画面提示整段跳过
            continue
        if ln.startswith(("（需核对", "(需核对", "> ")):
            continue
        cur["lines"].append(ln.removeprefix("**").removesuffix("**"))
    return [b for b in blocks if b["lines"]]


_TIME = re.compile(r"(\d{1,2}):(\d{2})\s*[–-]\s*(\d{1,2}):(\d{2})")


def _expected_s(blocks: list[dict]) -> float:
    """分镜时间轴最后一段的结束秒数（全片口播预期时长）。"""
    end = 0.0
    for b in blocks:
        if m := _TIME.search(b.get("time", "")):
            end = int(m.group(3)) * 60 + int(m.group(4))
    return float(end)


def _kind(title: str) -> str:
    if "开场" in title:
        return "hook"
    if "收尾" in title:
        return "outro"
    return "item"


def _card(narration: str, title: str) -> dict:
    """卡面：headline 用分镜段标题（短、与稿子结构对齐），副题取口播首句。"""
    sents = [s for s in re.split(r"[。！？]", narration) if s.strip()]
    first = (sents[0] if sents else title).strip()
    return {"type": "headline", "headline": title[:18], "sub": first[:40],
            "badge": "", "lines": []}


def parse_script(md_path: Path, date: str = "", label: str = "") -> dict:
    """markdown 稿 → script.json 结构。解析不出段落块即报错（宁停不改稿）。"""
    md = Path(md_path).read_text(encoding="utf-8")
    blocks = _parse_blocks(md)
    if not blocks or blocks[0]["title"] and "开场" not in blocks[0]["title"]:
        raise RuntimeError("稿式不符：未找到【…｜开场钩子】起始段，请检查 markdown 格式")

    mt = _MAIN_TITLE.search(md)
    if not date:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", md[:400])
        date = m.group(1) if m else store.now()[:10]

    segs = []
    for b in blocks:
        kind = _kind(b["title"])
        narration = "".join(b["lines"])
        card = _card(narration, b["title"])
        card["type"] = ("hook" if kind == "hook" else
                        "outro" if kind == "outro" else card["type"])
        segs.append({"kind": kind, "narration": narration, "item_ref": 0,
                     "card": card})
    title = mt.group(1).strip() if mt else f"军事快讯 {date}"
    return {"title": title,
            "meta": {"date": date, "mode": "manual",
                     "expected_s": _expected_s(blocks),
                     "show_label": label or "军事快讯"},
            "segments": segs,
            "warnings": ["人工稿通道：文案来自人工逐字稿，未经过 AI 改写"]}


def ingest_script(md_path, date: str = "", label: str = "") -> str:
    """建项目、写 script.json、标记 ingest+script 完成。返回 pid。"""
    md_path = Path(md_path)
    script = parse_script(md_path, date=date, label=label)
    pid, pdir = store.new_project(md_path, script["meta"]["date"])
    save_json(script, pdir / "script.json")
    store.mark_stage(pid, "ingest", "manual script")
    store.mark_stage(pid, "script",
                     f"manual / {len(script['segments'])} 段 / 人工逐字稿")
    return pid
