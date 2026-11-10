# -*- coding: utf-8 -*-
"""发布物料：upload_info.txt（标题/简介/标签/封面路径）。投稿永远人工触发。

标题公式沿 grokbot 讨论定稿：栏目名 + 日期 + 主线钩子；简介固定带
信源说明与免责声明（红线字幕的延伸），标签走 publish.tags。
"""
from pathlib import Path

from src import store
from src.config import load_config
from src.jsonio import load_json, save_json


def prepare(pid: str) -> Path:
    """生成 upload_info.txt。draft 阶段即可预览物料；真正投稿闸门在 publish（须 ready）。"""
    cfg = load_config()
    pdir = store.project_dir(pid)
    script = load_json(pdir / "script.json") or {}
    brief = load_json(pdir / "briefing.json") or {}
    hammer = load_json(pdir / "hammer.json") or {}
    rj = load_json(pdir / "output" / "render.json") or {}
    if not rj:
        raise RuntimeError("先跑 make 渲染成片再准备发布物料")

    date = script.get("meta", {}).get("date", brief.get("date", ""))
    title = script.get("title") or f"{cfg['show']['name']} {date}"
    excluded = set(brief.get("excluded_refs", []))
    item_titles = [it.get("title", "") for i, it in enumerate(brief.get("items", []), 1)
                   if i not in excluded and it.get("title")]
    if not item_titles:      # 人工稿通道：没有 briefing，用各段卡面标题
        item_titles = [s["card"].get("headline", "")
                       for s in script.get("segments", [])
                       if s.get("kind") == "item" and s.get("card", {}).get("headline")]
    tiers = sorted({s.get("tier") for it in brief.get("items", [])
                    for s in it.get("sources", []) if s.get("tier")})

    lines = [
        f"标题: {title}",
        f"备选标题: {date} 巴尔干发生了什么｜本期{len(item_titles)}条",
        "",
        f"分区: tid {cfg['publish'].get('tid', 228)}（知识·时事）",
        f"标签: {','.join(cfg['publish']['tags'])}",
        f"封面: {rj.get('cover', '')}",
        f"成片: {rj.get('final', '')}",
        "",
        "简介:",
        f"「{cfg['show']['name']}」{date} 期。本期覆盖：",
        *[f"· {t}" for t in item_titles],
        "",
        f"信源分级：{'、'.join(tiers) or '见片中标注'}；"
        "所有表述以信源原文为准，无法交叉验证的内容已在片中标注「待核实」。",
        "",
        cfg["publish"]["disclaimer"],
    ]
    if hammer.get("issues"):
        lines += ["", "（内部备忘，发布前删除）锤稿遗留：",
                  *[f"- {i.get('seg', '')} {i['rule']}: {i.get('hit', '')}"
                    for i in hammer["issues"]]]
    out = pdir / "output" / "upload_info.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    save_json({"upload_info": str(out), "prepared_at": store.now()},
              pdir / "output" / "publish.json")
    return out
