# -*- coding: utf-8 -*-
"""投稿：复用 bili-autopost-sau 的 sau_bridge（biliup 二进制管理 + 账号 cookie），
不重造轮子。前置条件：审片 ready + publish-prepare 已生成 upload_info.txt。

版权类型走「自制」（--copyright 1，AI 辅助创作）：信源引用写进简介，
不是转载某篇具体稿件；正文红线（不站队不预测）在锤稿阶段已把过关。
"""
import re
import sys
from pathlib import Path

_SAU = Path(__file__).resolve().parent.parent.parent / "bili-autopost-sau"
sys.path.insert(0, str(_SAU))
import sau_bridge  # noqa: E402

from src import publisher, review, store  # noqa: E402
from src.config import load_config  # noqa: E402
from src.jsonio import load_json, save_json  # noqa: E402


def check_account() -> bool:
    """登录态检查（biliup renew）。失效则 cli login 扫码。"""
    return sau_bridge.check_account()


def login() -> None:
    """终端二维码扫码登录/续期。"""
    sau_bridge.login_interactive()


def _desc_from_upload_info(pid: str) -> str:
    """从 upload_info.txt 取「简介:」之后的内容，去掉内部备忘段。"""
    txt = (store.project_dir(pid) / "output" / "upload_info.txt")
    if not txt.exists():
        raise RuntimeError("upload_info.txt 缺失，先跑 publish-prepare")
    body = txt.read_text(encoding="utf-8")
    m = re.search(r"简介:\n(.*?)(?:\n（内部备忘，发布前删除）|\Z)", body, re.S)
    desc = (m.group(1) if m else body).strip()
    return re.sub(r"\n（内部备忘，发布前删除）.*\Z", "", desc, flags=re.S).strip()


def _video_fingerprint(path) -> dict:
    """成片指纹（sha256 前 16 位 + size）：重复投稿判定的持久化依据。"""
    import hashlib
    p = Path(path)
    return {"path": str(p), "size": p.stat().st_size,
            "sha256_16": hashlib.sha256(p.read_bytes()).hexdigest()[:16]}


def _already_published(pid: str) -> str:
    """重复投稿守卫。返回拒绝原因，空串 = 可投：
    ① 审片状态 published → 拒；
    ② 有投稿成功记录且成片指纹一致（旧记录 + 同一成片）→ 拒；
    ③ 有记录但成片已变（redo 重做的新片）→ 放行，走正常首次投稿流程。"""
    rec = load_json(store.project_dir(pid) / "output" / "publish_result.json") or {}
    if review.status(pid) == "published":
        return ("本项目已投稿"
                + (f"：{rec.get('url')}" if rec.get("url") else "")
                + "，拒绝重复投稿（如需重投请 redo 后重新生成并审片）")
    if rec.get("video"):
        rj = load_json(store.project_dir(pid) / "output" / "render.json") or {}
        final = rj.get("final", "")
        if final and Path(final).exists() and _video_fingerprint(final) == rec["video"]:
            return ("当前成片已投稿过"
                    + (f"：{rec.get('url')}" if rec.get("url") else "")
                    + "（成片指纹一致），拒绝重复投稿")
    return ""


def publish(pid: str) -> dict:
    dup = _already_published(pid)
    if dup:
        raise RuntimeError(dup)
    if review.status(pid) != "ready":
        raise RuntimeError("审片未放行（approve）——发布永远人工触发")
    rj = load_json(store.project_dir(pid) / "output" / "render.json") or {}
    if not rj.get("final"):
        raise RuntimeError("成片缺失，先跑 make")
    # 发布安全闸门（二次校验）：不只信审片状态——与 approve 同一套 gate：
    # 阶段必须全完成、QC 必须通过、QC 报告必须对应当前成片（旧 QC 残留拦截）
    gate_problems = review.gate(pid)
    if gate_problems:
        raise RuntimeError("投稿前置检查未过：" + "；".join(gate_problems))
    m = store.manifest(pid)
    missing = [s for s in store.STAGES if m["stages"].get(s) != "done"]
    if missing:
        raise RuntimeError(f"阶段未完成，拒绝投稿：{missing}（先跑 make）")
    cfg = load_config()
    pconf = cfg["publish"]
    script = load_json(store.project_dir(pid) / "script.json") or {}
    title = script.get("title") or f"{cfg['show']['name']} {script.get('meta', {}).get('date', '')}"

    out = sau_bridge.upload(
        video_path=rj["final"], title=title, desc=_desc_from_upload_info(pid),
        tags=publisher.publish_tags(script.get("meta", {}).get("show_label", ""), cfg),
        tid=int(pconf.get("tid", 228)),
        cover=rj.get("cover"), copyright_self=True)
    bvid = ""
    m = re.search(r"(BV[0-9A-Za-z]{10})", out or "")
    if m:
        bvid = m.group(1)
    result = {"published_at": store.now(), "bvid": bvid,
              "url": f"https://www.bilibili.com/video/{bvid}" if bvid else "",
              "video": _video_fingerprint(rj["final"]),
              "biliup_output": (out or "")[-400:]}
    save_json(result, store.project_dir(pid) / "output" / "publish_result.json")
    review._set(pid, "published", result["url"] or "投稿成功")
    return result
