# -*- coding: utf-8 -*-
"""审片：状态机 draft→rendered→review→ready（→published 人工投稿后登记）。

审美与内容裁量永远是人工的事——机器只保证规格合格（qc），不放行发布。
"""
from pathlib import Path

from src import store
from src.jsonio import load_json, save_json


def status(pid: str) -> str:
    r = load_json(store.project_dir(pid) / "review.json")
    return (r or {}).get("status", "draft")


def gate(pid: str) -> list[str]:
    """放行/投稿统一前置闸门，approve 与 publish 共用——缺一不放行：
    ① manifest 里 render、qc 阶段都已完成（redo 之后旧 QC 文件不算数）；
    ② render.json 存在且指向的成片真实存在；
    ③ qc_report.json 属于当前项目（pid 一致）且 ok；
    ④ QC 报告对应当前成片而非历史产物：mtime 不早于成片、时长一致（±1s）。"""
    pdir = store.project_dir(pid)
    problems: list[str] = []
    stages = store.manifest(pid).get("stages", {})
    for st in ("render", "qc"):
        if stages.get(st) != "done":
            problems.append(f"{st} 阶段未完成（旧产物不算数，先 make）")

    rj = load_json(pdir / "output" / "render.json") or {}
    final = rj.get("final", "")
    if not final or not Path(final).exists():
        problems.append("render.json 缺失或成片文件不存在（先 make）")

    qc = load_json(pdir / "output" / "qc_report.json") or {}
    if not qc.get("ok"):
        problems.append("QC 未通过或未运行（明细见 output/qc_report.json）")
    elif qc.get("pid") != pid:
        problems.append(f"QC 报告不属于本项目：pid={qc.get('pid')!r} ≠ {pid}")
    elif final and Path(final).exists():
        qc_fp = pdir / "output" / "qc_report.json"
        if qc_fp.stat().st_mtime < Path(final).stat().st_mtime:
            problems.append("QC 报告早于当前成片（旧 QC 残留）——redo qc")
        elif abs(float(qc.get("duration", -1)) - float(rj.get("duration", -2))) > 1.0:
            problems.append("QC 报告与当前成片时长不一致（疑似旧 QC）——redo qc")
    return problems


def approve(pid: str, note: str = "") -> dict:
    """放行。published 是终态：重复放行 = 重复投稿风险，底层直接拒绝
    （CLI 层另有友好预检；如需重投，redo 生成新成片后重走全链）。"""
    if status(pid) == "published":
        rec = load_json(store.project_dir(pid) / "output" / "publish_result.json") or {}
        url = rec.get("url") or (f"https://www.bilibili.com/video/{rec['bvid']}"
                                 if rec.get("bvid") else "")
        raise RuntimeError("已投稿项目不可重复放行"
                           + (f"（已发布：{url}）" if url else "")
                           + "。如需重投请 redo 后重新生成并审片")
    return _set(pid, "ready", note)


def reject(pid: str, note: str = "") -> dict:
    return _set(pid, "rejected", note)


def reset(pid: str, note: str = "") -> dict:
    """退回 draft（审片状态误操作/需重审时用）。"""
    return _set(pid, "draft", note)


def _set(pid: str, st: str, note: str) -> dict:
    r = load_json(store.project_dir(pid) / "review.json") or {"history": []}
    r["status"] = st
    r["note"] = note
    r["updated_at"] = store.now()
    r["history"].append({"status": st, "note": note, "at": store.now()})
    save_json(r, store.project_dir(pid) / "review.json")
    return r
