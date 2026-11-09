# -*- coding: utf-8 -*-
"""审片：状态机 draft→rendered→review→ready（→published 人工投稿后登记）。

审美与内容裁量永远是人工的事——机器只保证规格合格（qc），不放行发布。
"""
from src import store
from src.jsonio import load_json, save_json


def status(pid: str) -> str:
    r = load_json(store.project_dir(pid) / "review.json")
    return (r or {}).get("status", "draft")


def approve(pid: str, note: str = "") -> dict:
    return _set(pid, "ready", note)


def reject(pid: str, note: str = "") -> dict:
    return _set(pid, "rejected", note)


def _set(pid: str, st: str, note: str) -> dict:
    r = load_json(store.project_dir(pid) / "review.json") or {"history": []}
    r["status"] = st
    r["note"] = note
    r["updated_at"] = store.now()
    r["history"].append({"status": st, "note": note, "at": store.now()})
    save_json(r, store.project_dir(pid) / "review.json")
    return r
