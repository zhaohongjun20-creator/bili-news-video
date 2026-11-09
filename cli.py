# -*- coding: utf-8 -*-
"""bili-news-video 命令行入口。

    python cli.py doctor                            # 环境体检
    python cli.py sample                            # 生成示例简报（演示数据，标注清楚）
    python cli.py ingest briefings/xxx.md [--date YYYY-MM-DD]
    python cli.py make ep-001 [--offline]           # 全链：script→…→qc
    python cli.py redo ep-001 voice                 # 某阶段起重跑（含下游）
    python cli.py show ep-001                       # 状态/阶段/问题一览
    python cli.py approve ep-001 [--note "..."]     # 人工放行
    python cli.py reject ep-001 --note "..."
    python cli.py publish-prepare ep-001            # 生成上传物料（不投稿）
"""
import argparse
import json
import sys

from src import ingest, pipeline, preflight, publisher, review, store
from src.config import load_config


def _die(msg: str) -> None:
    print(f"错误: {msg}", file=sys.stderr)
    sys.exit(1)


def cmd_doctor(_a) -> None:
    bad = False
    for level, name, detail in preflight.doctor(load_config()):
        print(f"[{level:>4}] {name}: {detail}")
        bad = bad or level == "hard"
    sys.exit(1 if bad else 0)


def cmd_sample(_a) -> None:
    from pathlib import Path
    src = Path(__file__).parent / "briefings" / "sample-示例简报-演示数据.md"
    print(f"示例简报: {src}")
    print("下一步: python cli.py ingest " + src.name)


def cmd_ingest(a) -> None:
    pid, brief = ingest.ingest(a.file, a.date or "")
    mode = brief.get("ingest_mode")
    if brief.get("nothing_to_report"):
        print(f"{pid}: 简报为「今日无事」，本期可停（无事不硬凑）。mode={mode}")
        return
    print(f"{pid}: 简报解析完成（{mode}，{len(brief['items'])} 条）")
    print(f"下一步: python cli.py make {pid}")


def cmd_make(a) -> None:
    try:
        out = pipeline.make(a.pid, offline=a.offline)
    except pipeline.PipelineError as e:
        _die(str(e))
    print(f"{a.pid}: {', '.join(out['steps'])}")
    rj = store.project_dir(a.pid) / "output" / "final.mp4"
    if rj.exists():
        print(f"成片: {rj}")
        print(f"下一步: 看片后 python cli.py approve {a.pid} / reject {a.pid} --note ...")


def cmd_redo(a) -> None:
    if a.stage not in store.STAGES:
        _die(f"未知阶段: {a.stage}（可选 {store.STAGES}）")
    store.redo_stage(a.pid, a.stage)
    print(f"{a.pid}: {a.stage} 起已失效，重新 make 即可")


def cmd_show(a) -> None:
    m = store.manifest(a.pid)
    pdir = store.project_dir(a.pid)
    print(f"== {a.pid} ({m.get('date', '?')}) ==")
    for st in store.STAGES:
        mark = "✓" if m["stages"].get(st) == "done" else "·"
        note = m.get("notes", {}).get(st, "")
        print(f"  {mark} {st:<8} {note}")
    for f in ("hammer.json", "voice.json", "qc_report.json"):
        p = pdir / f
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            if f == "hammer.json":
                print(f"  锤稿: {d['status']} / 条目余 {d['items_left']}")
                for i in d["issues"]:
                    print(f"    - [{i['level']}] {i.get('seg', '')} {i['rule']}: {i['hit'][:40]}")
            elif f == "voice.json":
                print(f"  配音: {d['backend']} / {len(d['segments'])} 段")
            else:
                print(f"  QC: {'PASS' if d['ok'] else d['problems']}")
    print(f"  审片: {review.status(a.pid)}")


def cmd_approve(a) -> None:
    if (store.project_dir(a.pid) / "output" / "final.mp4").exists() is False:
        _die("还没有成片，先 make")
    review.approve(a.pid, a.note or "")
    print(f"{a.pid}: 已放行（ready）。下一步: publish-prepare")


def cmd_reject(a) -> None:
    review.reject(a.pid, a.note or "")
    print(f"{a.pid}: 已退稿。理由已记录")


def cmd_publish(a) -> None:
    if review.status(a.pid) != "ready":
        _die("未审片放行（approve）前不准备投稿物料——发布永远人工触发")
    p = publisher.prepare(a.pid)
    print(f"上传物料: {p}")
    print("投稿请人工执行（biliup 或网页上传），本期产线到此为止")


def main() -> None:
    ap = argparse.ArgumentParser(description="时政快讯视频线")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor").set_defaults(func=cmd_doctor)
    sub.add_parser("sample").set_defaults(func=cmd_sample)
    p = sub.add_parser("ingest")
    p.add_argument("file")
    p.add_argument("--date", default="")
    p.set_defaults(func=cmd_ingest)
    p = sub.add_parser("make")
    p.add_argument("pid")
    p.add_argument("--offline", action="store_true", help="强制模板降级（无网联调）")
    p.set_defaults(func=cmd_make)
    p = sub.add_parser("redo")
    p.add_argument("pid")
    p.add_argument("stage", choices=store.STAGES)
    p.set_defaults(func=cmd_redo)
    p = sub.add_parser("show")
    p.add_argument("pid")
    p.set_defaults(func=cmd_show)
    p = sub.add_parser("approve")
    p.add_argument("pid")
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_approve)
    p = sub.add_parser("reject")
    p.add_argument("pid")
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_reject)
    p = sub.add_parser("publish-prepare")
    p.add_argument("pid")
    p.set_defaults(func=cmd_publish)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
