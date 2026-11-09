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

from src import review, store  # noqa: E402
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


def publish(pid: str) -> dict:
    if review.status(pid) != "ready":
        raise RuntimeError("审片未放行（approve）——发布永远人工触发")
    rj = load_json(store.project_dir(pid) / "output" / "render.json") or {}
    if not rj.get("final"):
        raise RuntimeError("成片缺失，先跑 make")
    cfg = load_config()
    pconf = cfg["publish"]
    script = load_json(store.project_dir(pid) / "script.json") or {}
    title = script.get("title") or f"{cfg['show']['name']} {script.get('meta', {}).get('date', '')}"

    out = sau_bridge.upload(
        video_path=rj["final"], title=title, desc=_desc_from_upload_info(pid),
        tags=list(pconf["tags"]), tid=int(pconf.get("tid", 228)),
        cover=rj.get("cover"), copyright_self=True)
    bvid = ""
    m = re.search(r"(BV[0-9A-Za-z]{10})", out or "")
    if m:
        bvid = m.group(1)
    result = {"published_at": store.now(), "bvid": bvid,
              "url": f"https://www.bilibili.com/video/{bvid}" if bvid else "",
              "biliup_output": (out or "")[-400:]}
    save_json(result, store.project_dir(pid) / "output" / "publish_result.json")
    review._set(pid, "published", result["url"] or "投稿成功")
    return result
