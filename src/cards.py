# -*- coding: utf-8 -*-
"""画面卡生成：每段一张 1920x1080 PNG（news 深蓝底 + 红色台标条 + 徽标）。

卡片类型：
    hook     片头：栏目名 + 日期 + 期数
    headline 大字标题卡：徽标 + 标题 + 副题 + 要点
    quote    待核实条目卡：灰徽标 + 「单方说法 待核实」
    map      棋盘示意卡：地区节点关系图（config 固定布局，非地理图）
    china    对华关联卡：金色点缀
    mainline 主线追踪卡
    outro    收尾卡：栏目声明 + 红线字幕

「示意图，非地理图」小字常驻棋盘卡右下角——军事地理内容的自保习惯。
"""
import datetime as _dt
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from src import scriptgen, store
from src.config import load_config
from src.jsonio import save_json

W, H = 1920, 1080
BG = (13, 27, 42)          # 深蓝夜色
BG2 = (19, 38, 58)         # 面板蓝
ACCENT = (217, 4, 41)      # 台标红
INK = (240, 244, 248)      # 主文字
DIM = (148, 163, 184)      # 次文字
GOLD = (233, 196, 106)     # 对华关联点缀金
GRAY = (100, 116, 139)

BADGE_COLORS = {"官方": (31, 122, 90), "主流媒体": (42, 90, 168),
                "区域专家": (180, 105, 32), "单方声称待核实": GRAY}

_FONTS: dict[int, ImageFont.FreeTypeFont] = {}


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    key = size * 2 + bold
    if key not in _FONTS:
        path = r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc"
        _FONTS[key] = ImageFont.truetype(path, size)
    return _FONTS[key]


def _fit(draw: ImageDraw.ImageDraw, text: str, size: int, max_w: int,
         bold: bool = False) -> ImageFont.FreeTypeFont:
    """按宽度收缩字号。"""
    while size > 20:
        f = _font(size, bold)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 4
    return _font(size, bold)


def _wrap(text: str, f: ImageFont.FreeTypeFont, draw, max_w: int,
          max_lines: int = 3) -> list[str]:
    lines, cur = [], ""
    for ch in text:
        if draw.textlength(cur + ch, font=f) > max_w or len(cur) >= 42:
            lines.append(cur)
            cur = ch
            if len(lines) == max_lines:
                break
        else:
            cur += ch
    if len(lines) < max_lines and cur:
        lines.append(cur)
    return lines


def _chrome(img: Image.Image, d: ImageDraw.ImageDraw, badge: str = "",
            label: str = "") -> None:
    """公共装饰：顶部台标条 + 徽标 + 右下角栏目名。"""
    d.rectangle([0, 0, W, 12], fill=ACCENT)
    name = label or load_config()["show"]["name"]
    d.text((60, 48), name, font=_font(44, True), fill=DIM)
    if badge:
        m = re.match(r"【(.+?)】", badge)
        tier = m.group(1) if m else badge
        color = BADGE_COLORS.get(tier, GRAY)
        f = _font(36, True)
        tw = d.textlength(tier, font=f)
        x, y = W - 60 - tw - 48, 40
        d.rounded_rectangle([x, y, x + tw + 48, y + 60], 12, fill=color)
        d.text((x + 24, y + 8), tier, font=f, fill=INK)


def _draw_hook(img, d, seg, meta) -> None:
    date = _dt.date.fromisoformat(meta["date"])
    d.rectangle([120, 300, 520, 316], fill=ACCENT)
    d.text((120, 340), f"{date.year}年{date.month}月{date.day}日",
           font=_font(64), fill=DIM)
    d.text((120, 430), load_config()["show"]["name"], font=_font(110, True),
           fill=INK)
    n = meta.get("n_items", 0)
    sub = f"本期 {n} 条动态" if n else "本期动态"
    d.text((120, 600), sub, font=_font(56), fill=DIM)


def _draw_headline(img, d, seg, meta) -> None:
    card = seg.get("card", {})
    headline = card.get("headline") or seg["narration"][:16]
    d.rectangle([120, 300, 220, 420], fill=ACCENT)
    f = _fit(d, headline, 96, W - 300, bold=True)
    lines = _wrap(headline, f, d, W - 300, max_lines=2)
    y = 300
    for ln in lines:
        d.text((260, y), ln, font=f, fill=INK)
        y += int(f.size * 1.25)
    if card.get("sub"):
        fs = _fit(d, card["sub"], 44, W - 320)
        y += 28
        for ln in _wrap(card["sub"], fs, d, W - 320, max_lines=2):
            d.text((260, y), ln, font=fs, fill=DIM)
            y += int(fs.size * 1.4)
    y = max(y + 40, 700)
    for i, ln in enumerate(card.get("lines", [])[:3]):
        if not ln:
            continue
        fl = _fit(d, "· " + ln, 40, W - 360)
        d.text((260, y), "· " + ln, font=fl, fill=(196, 181, 253))
        y += 64


def _draw_quote(img, d, seg, meta) -> None:
    """待核实条目：大引号 + 灰色徽标（_chrome 已按 tier 配灰）。"""
    card = seg.get("card", {})
    headline = card.get("headline") or "单方说法，尚待核实"
    d.text((120, 260), "“", font=_font(220, True), fill=(51, 65, 85))
    f = _fit(d, headline, 84, W - 420, bold=True)
    y = 480
    for ln in _wrap(headline, f, d, W - 420, max_lines=2):
        d.text((260, y), ln, font=f, fill=INK)
        y += int(f.size * 1.3)
    tag = "单方说法 · 尚待核实"
    d.text((260, y + 60), tag, font=_font(44, True), fill=GRAY)


def _draw_map(img, d, seg, meta) -> None:
    """棋盘示意卡：config 固定节点布局 + 边。节点=圆角块，边=细线。"""
    cfg = load_config()
    nodes = {n["label"]: (int(n["x"] * (W - 480)) + 240, int(n["y"] * (H - 420)) + 300)
             for n in cfg["show"].get("region_nodes", [])}
    for a, b in cfg["show"].get("region_edges", []):
        if a in nodes and b in nodes:
            d.line([nodes[a], nodes[b]], fill=(51, 65, 85), width=3)
    focus = seg.get("card", {}).get("headline", "")
    for label, (x, y) in nodes.items():
        fw = _font(38, True)
        tw = d.textlength(label, font=fw)
        pad = 20
        is_focus = focus and focus[:4] and (focus[:4] in label or label in focus)
        color = ACCENT if is_focus else BG2
        outline = ACCENT if is_focus else (51, 65, 85)
        d.rounded_rectangle([x - tw / 2 - pad, y - 30, x + tw / 2 + pad, y + 30],
                            14, fill=color, outline=outline, width=2)
        d.text((x - tw / 2, y - 22), label, font=fw,
               fill=INK if is_focus else DIM)
    d.text((W - 560, H - 90), "示意图，非地理图", font=_font(30), fill=GRAY)


def _draw_china(img, d, seg, meta) -> None:
    card = seg.get("card", {})
    headline = card.get("headline") or "对华关联"
    d.rectangle([120, 300, 220, 420], fill=GOLD)
    f = _fit(d, headline, 88, W - 300, bold=True)
    y = 300
    for ln in _wrap(headline, f, d, W - 300, max_lines=2):
        d.text((260, y), ln, font=f, fill=INK)
        y += int(f.size * 1.3)
    if card.get("sub"):
        fs = _fit(d, card["sub"], 44, W - 320)
        y += 30
        for ln in _wrap(card["sub"], fs, d, W - 320, max_lines=2):
            d.text((260, y), ln, font=fs, fill=DIM)
            y += int(fs.size * 1.4)
    d.text((260, max(y + 40, 780)), "相关表述以官方口径为准",
           font=_font(38), fill=GOLD)


def _draw_mainline(img, d, seg, meta) -> None:
    card = seg.get("card", {})
    d.text((120, 260), "主线追踪", font=_font(72, True), fill=INK)
    d.rectangle([120, 380, 360, 394], fill=ACCENT)
    y = 440
    for ln in card.get("lines", [])[:4]:
        if not ln:
            continue
        fl = _fit(d, ln, 42, W - 360)
        d.text((160, y), "▸ " + ln, font=fl, fill=DIM)
        y += 80


def _draw_outro(img, d, seg, meta) -> None:
    name = load_config()["show"]["name"]
    d.text((W // 2 - len(name) * 55, 380), name, font=_font(110, True), fill=INK)
    lines = ["只讲发生了什么、各方怎么说", "不站队 · 不评论 · 不预测",
             "下期见"]
    y = 580
    for ln in lines:
        f = _font(48)
        tw = d.textlength(ln, font=f)
        d.text(((W - tw) / 2, y), ln, font=f, fill=DIM)
        y += 92


_DRAWERS = {"hook": _draw_hook, "headline": _draw_headline, "quote": _draw_quote,
            "map": _draw_map, "china": _draw_china, "mainline": _draw_mainline,
            "outro": _draw_outro}


def render_cards(pid: str) -> list[dict]:
    """全稿出卡。返回 [{id, png}]。同段重跑直接覆盖（卡是纯函数）。"""
    script = scriptgen.load_script(pid)
    cards_dir = store.project_dir(pid) / "cards"
    cards_dir.mkdir(exist_ok=True)
    out = []
    for seg in script["segments"]:
        img = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(img)
        # 每张卡一层淡面板底（四周 80px 边框感），避免纯背景太空
        d.rounded_rectangle([80, 180, W - 80, H - 80], 24, fill=BG2)
        img.paste(Image.new("RGB", (W - 320, H - 420), BG), (160, 260))
        _chrome(img, d, badge=seg.get("card", {}).get("badge", ""))
        _DRAWERS.get(seg["card"].get("type", "headline"), _draw_headline)(
            img, d, seg, script["meta"])
        png = cards_dir / f"{seg['id']}.png"
        img.save(png)
        out.append({"id": seg["id"], "png": str(png)})
    save_json({"cards": out}, store.project_dir(pid) / "cards.json")
    return out
