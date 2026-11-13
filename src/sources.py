# -*- coding: utf-8 -*-
"""信源档案：把 briefing 里的每条信源（分级/名称/链接/支持事实/核验状态/事件时间）
固化成 sources.json + sources.md，存进项目目录。

价值：出现事实争议时能直接追溯到原始报道，而不是翻 Grok 简报；
报道时间与事件发生时间分开记录。不做任何内容判断——判断在 factcheck/人工。
"""
from src import store
from src.jsonio import load_json, save_json


def build_registry(pid: str) -> dict:
    """从 briefing.json 生成信源档案。返回统计（总条数 / 无链接数）。"""
    brief = load_json(store.project_dir(pid) / "briefing.json") or {}
    rows: list[dict] = []
    for i, it in enumerate(brief.get("items", []), 1):
        for s in it.get("sources", []):
            rows.append({"ref": i, "item": it.get("title", ""),
                         "tier": s.get("tier", ""), "name": s.get("name", ""),
                         "url": s.get("url", ""), "claim": s.get("claim", ""),
                         "verification": s.get("verification", ""),
                         "event_time": it.get("event_time", "")})
    save_json({"built_at": store.now(), "sources": rows},
              store.project_dir(pid) / "sources.json")

    lines = ["# 信源档案（ingest 自动生成）", ""]
    cur_ref = None
    for r in rows:
        if r["ref"] != cur_ref:
            cur_ref = r["ref"]
            lines.append(f"## 条目{r['ref']} {r['item']}")
            if r["event_time"]:
                lines.append(f"- 事件时间：{r['event_time']}")
        lines.append(f"- 【{r['tier']}】{r['name']}")
        if r["url"]:
            lines.append(f"  - 链接：{r['url']}")
        if r["claim"]:
            lines.append(f"  - 支持事实：{r['claim']}")
        lines.append(f"  - 核验状态：{r['verification']}")
    (store.project_dir(pid) / "sources.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    return {"rows": len(rows), "no_url": sum(1 for r in rows if not r["url"])}


def load_registry(pid: str) -> dict:
    return load_json(store.project_dir(pid) / "sources.json") or {}
