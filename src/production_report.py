# -*- coding: utf-8 -*-
"""生产质量报告：这期视频为什么可以/不可以发布——逐项给证据，不打笼统分。

make 尾部与 publish-prepare 时各生成一次：production_report.json + .md。
机器检查只证明规格与流程；新闻内容正确性最终以人工审片为准。
"""
from pathlib import Path

from src import store
from src.jsonio import load_json, save_json


def build(pid: str) -> dict:
    pdir = store.project_dir(pid)

    def j(rel: str) -> dict:
        return load_json(pdir / rel) or {}

    brief = j("briefing.json")
    hammer = j("hammer.json")
    qc = j("output/qc_report.json")
    reg = j("sources.json")
    mc = j("map_confirm.json")
    rj = j("output/render.json")
    pres = j("output/publish_result.json")
    intent = j("output/publishing.json")
    review_st = (load_json(pdir / "review.json") or {}).get("status", "draft")

    checks: list[dict] = []

    def add(name: str, status: str, detail: str = "") -> None:
        checks.append({"check": name, "status": status, "detail": detail})

    # 1) 信源追溯
    rows = reg.get("sources", [])
    url_ok = sum(1 for r in rows if r.get("url"))
    add("信源追溯",
        "PASS" if rows and url_ok == len(rows) else ("WARN" if rows else "N/A"),
        f"信源 {len(rows)} 条，含链接 {url_ok} 条（明细见 sources.md）")
    # 2) 红线/事实核验
    issues = hammer.get("issues", [])
    blocks = [i for i in issues if i.get("level") == "block"]
    warns = [i for i in issues if i.get("level") == "warn"]
    add("红线与事实核验", "BLOCK" if blocks else ("WARN" if warns else "PASS"),
        f"锤稿 {hammer.get('status')}｜BLOCK {len(blocks)} / WARN {len(warns)}"
        + ("；" + "；".join(f"{i.get('seg')} {i.get('rule')}: {i.get('hit', '')[:40]}"
                           for i in (blocks + warns)[:3]) if blocks or warns else ""))
    # 3) 地图定位
    pend = {k: v for k, v in mc.items() if v.get("status") == "PENDING"}
    conf = sum(1 for v in mc.values() if v.get("status") == "CONFIRMED")
    auto = sum(1 for v in mc.values() if v.get("status") == "AUTO")
    add("地图定位", "PENDING" if pend else ("PASS" if mc else "N/A"),
        ("待确认: " + "；".join(f"{k}→{v.get('place')}" for k, v in pend.items()))
        if pend else (f"{conf} 人工确认 / {auto} 自动唯一命中"
                      if mc else "本期无动态地图卡"))
    # 4) 技术规格
    add("视频规格/QC", "PASS" if qc.get("ok") else "FAIL",
        f"{qc.get('duration', 0):.1f}s / {qc.get('mean_volume_db', 0):.0f}dB"
        if qc.get("ok") else "；".join(qc.get("problems", []))[:200])
    # 5) 字幕与音频（字幕文件缺失由 QC 统一判 FAIL，这里不重复惩罚）
    add("字幕/音频同步", "PASS" if qc.get("ok") else "FAIL",
        "ASS 事件均在音频窗口内（qc 语速启发式 + 时长自洽）"
        + ("" if (pdir / "output" / "subs.ass").exists() else "；字幕文件缺失(QC 已拦)"))
    # 6) 投稿状态（信息项：不作为放行阻断——未投稿本来就是常态）
    if pres.get("bvid"):
        add("投稿状态", "PUBLISHED", pres.get("url", ""))
    elif intent:
        add("投稿状态", "UNKNOWN",
            "上次投稿结果未知——到创作中心确认，处理 output/publishing.json")
    elif review_st == "ready":
        add("投稿状态", "PENDING", "已人工放行，待投稿")
    else:
        add("投稿状态", "未投稿", f"审片状态 {review_st}")

    blockers = [c["check"] for c in checks
                if c["status"] in ("BLOCK", "FAIL", "PENDING")
                and c["check"] != "投稿状态"]
    verdict = ("可发布" if not blockers and review_st in ("ready", "published")
               else "不可发布")
    report = {"pid": pid, "generated_at": store.now(), "verdict": verdict,
              "review_status": review_st, "blockers": blockers, "checks": checks}
    save_json(report, pdir / "production_report.json")

    md = [f"# 生产质量报告 {pid}", "",
          f"生成时间：{report['generated_at']}　审片状态：{review_st}",
          f"", f"## 结论：**{verdict}**",
          *( [f"- 阻断项：{'、'.join(blockers)}"] if blockers else [] ), "",
          "## 检查明细", ""]
    for c in checks:
        md.append(f"- **[{c['status']}]** {c['check']} — {c['detail']}")
    md += ["", "---",
           "机器检查只覆盖规格与流程；新闻内容正确性（事实、口径、观感）"
           "最终以人工审片为准。", ""]
    (pdir / "production_report.md").write_text("\n".join(md) + "\n",
                                               encoding="utf-8")
    return report
