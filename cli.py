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


def ensure_interpreter() -> None:
    """防解释器漂移：本机裸 `python` 会命中 LibreOffice 自带的解释器。"""
    if "libreoffice" in sys.executable.lower():
        _die("当前 Python 来自 LibreOffice（解释器漂移）。请改用:\n"
             "  C:\\Users\\15804\\AppData\\Local\\Programs\\Python"
             "\\Python314\\python.exe cli.py ...")


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
    pid, brief = ingest.ingest(a.file, a.date or "", a.label or "")
    mode = brief.get("ingest_mode")
    if brief.get("nothing_to_report"):
        print(f"{pid}: 简报为「今日无事」，本期可停（无事不硬凑）。mode={mode}")
        return
    print(f"{pid}: 简报解析完成（{mode}，{len(brief['items'])} 条）")
    if brief.get("show_label"):
        print(f"栏目名: {brief['show_label']}")
    print(f"下一步: python cli.py make {pid}")


def cmd_ingest_script(a) -> None:
    from src import manual
    pid = manual.ingest_script(a.file, date=a.date or "", label=a.label or "")
    print(f"{pid}: 人工稿解析完成")
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
    if review.status(a.pid) == "published":
        _die("已投稿项目不可重复放行（重复投稿风险）。"
             "如需重投：redo 生成新成片后重走全链")
    problems = review.gate(a.pid)
    if problems:
        _die("放行前置检查未过：" + "；".join(problems))
    try:
        review.approve(a.pid, a.note or "")
    except RuntimeError as e:
        _die(str(e))
    print(f"{a.pid}: 已放行（ready）。下一步: publish-prepare")


def cmd_reject(a) -> None:
    review.reject(a.pid, a.note or "")
    print(f"{a.pid}: 已退稿。理由已记录")


def cmd_map_confirm(a) -> None:
    """人工确认地图定位（PENDING → CONFIRMED），解除发布闸门。"""
    from src.jsonio import load_json
    pdir = store.project_dir(a.pid)
    mc = load_json(pdir / "map_confirm.json") or {}
    if a.seg not in mc:
        _die(f"{a.seg} 不在 map_confirm.json 中（现有: {sorted(mc) or '无'}）。"
             "只有多候选命中的动态地图卡需要确认")
    mc[a.seg]["status"] = "CONFIRMED"
    if a.place:
        mc[a.seg]["chosen"] = a.place
    mc[a.seg]["confirmed_at"] = store.now()
    save_json(mc, pdir / "map_confirm.json")
    # 确认必须实际进入画面：作废 render 及下游，强制重渲重审
    store.redo_stage(a.pid, "render")
    print(f"{a.pid}/{a.seg}: 地图定位已人工确认 → "
          f"{mc[a.seg].get('chosen') or mc[a.seg]['place']}")
    print("render 已作废：运行 python cli.py make 重新出片，看片后再 approve")


def cmd_publish_prepare(a) -> None:
    st = review.status(a.pid)
    if st not in ("ready", "draft"):
        _die(f"审片状态为 {st}（已退稿/已发布），先 reset 或另开一期")
    if st != "ready":
        print("提示：尚未 approve，物料仅供预览；publish 仍要求先放行")
    p = publisher.prepare(a.pid)
    print(f"上传物料: {p}")
    print(f"看片放行后: python cli.py approve {a.pid} && python cli.py publish {a.pid}")


def cmd_reset(a) -> None:
    review.reset(a.pid, a.note or "")
    print(f"{a.pid}: 已回到 draft")


def cmd_publish(a) -> None:
    from src import uploader
    if not uploader.check_account():
        _die("B站登录态缺失/过期。先运行: python cli.py login 扫码")
    try:
        r = uploader.publish(a.pid)
    except RuntimeError as e:
        _die(str(e))
    print(f"{a.pid}: 投稿成功 {r['url'] or '(biliup 无返回 BV 号，去创作中心确认)'}")
    print("审核通过后公开可见；如需撤回请在创作中心操作")


def cmd_login(_a) -> None:
    from src import uploader
    uploader.login()


def main() -> None:
    ensure_interpreter()
    ap = argparse.ArgumentParser(description="时政快讯视频线")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor").set_defaults(func=cmd_doctor)
    sub.add_parser("sample").set_defaults(func=cmd_sample)
    p = sub.add_parser("ingest")
    p.add_argument("file")
    p.add_argument("--date", default="")
    p.add_argument("--label", default="", help="栏目名覆盖（默认取 config show.name）")
    p.set_defaults(func=cmd_ingest)
    p = sub.add_parser("ingest-script")
    p.add_argument("file", help="已成稿的口播逐字稿 markdown（Grok 出稿模板式）")
    p.add_argument("--date", default="")
    p.add_argument("--label", default="", help="卡面栏目名（默认「军事快讯」）")
    p.set_defaults(func=cmd_ingest_script)
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
    p = sub.add_parser("reset")
    p.add_argument("pid")
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_reset)
    p = sub.add_parser("map-confirm")
    p.add_argument("pid")
    p.add_argument("seg")
    p.add_argument("place", nargs="?", default="",
                   help="确认的地点名（默认取首选候选）")
    p.set_defaults(func=cmd_map_confirm)
    p = sub.add_parser("publish-prepare")
    p.add_argument("pid")
    p.set_defaults(func=cmd_publish_prepare)
    p = sub.add_parser("publish")
    p.add_argument("pid")
    p.set_defaults(func=cmd_publish)
    sub.add_parser("login").set_defaults(func=cmd_login)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
