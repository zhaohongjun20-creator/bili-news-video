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
import json
import math
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from src import scriptgen, store
from src.config import load_config
from src.jsonio import save_json

ROOT = Path(__file__).resolve().parent.parent
GEO_PATH = ROOT / "assets" / "geo" / "balkans_base.json"

W, H = 1920, 1080
BG = (13, 27, 42)          # 深蓝夜色
BG2 = (19, 38, 58)         # 面板蓝
ACCENT = (217, 4, 41)      # 台标红
INK = (240, 244, 248)      # 主文字
DIM = (148, 163, 184)      # 次文字
GOLD = (233, 196, 106)     # 对华关联点缀金
GRAY = (100, 116, 139)

SEA = (10, 20, 33)         # 海
LAND = (36, 52, 71)        # 陆地
BORDER = (74, 96, 118)     # 国界
LAND_DIM = (27, 41, 56)    # 非焦点陆地（更暗）

# 地图视口（固定取景，观众每期看到同样的版面）——比例对齐左侧画布 870x660
VIEW = (13.0, 39.0, 30.0, 48.2)
MAP_BOX = (170, 290, 1040, 950)

# 核心六国（要标中文名、可被红色高亮）——与 config show.region_nodes 同区
CORE_ISO = {"SRB": "塞尔维亚", "KOS": "科索沃", "BIH": "波黑",
            "MNE": "黑山", "MKD": "北马其顿", "ALB": "阿尔巴尼亚"}

# 标题/文案里的地名 → 国家（含首都与惯用简称）
ALIAS = {"塞尔维亚": "SRB", "科索沃": "KOS", "波黑": "BIH", "波斯尼亚": "BIH",
         "黑山": "MNE", "北马其顿": "MKD", "马其顿": "MKD", "阿尔巴尼亚": "ALB",
         "贝尔格莱德": "SRB", "普里什蒂纳": "KOS", "萨拉热窝": "BIH",
         "波德戈里察": "MNE", "地拉那": "ALB", "斯科普里": "MKD",
         "匈塞": "SRB"}

# 外围行为者：右栏固定标签位（x, y）+ 触发关键词——仅当该段 narration 提及
# 才画 chip 和连线，否则不画（避免把没出场的博弈方画进画面造成误导）
EXTERNAL = [("西方/欧盟", (1120, 380)), ("俄罗斯", (1120, 530)),
            ("土耳其", (1120, 680))]
EXTERNAL_TRIGGERS = {"西方/欧盟": ("欧盟", "西方", "北约"),
                     # 精确称谓：单字「俄」会误触发「俄语资料」等无关词
                     "俄罗斯": ("俄罗斯", "俄方", "俄军", "俄联邦",
                               "克里姆林宫", "莫斯科"),
                     "土耳其": ("土耳其",)}


def external_actors(narration: str) -> list[str]:
    """纯函数：本段口播提及的外围行为者标签（按 EXTERNAL 固定顺序）。"""
    return [label for label, _ in EXTERNAL
            if any(k in narration for k in EXTERNAL_TRIGGERS[label])]

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
    d.text((120, 430), meta.get("show_label") or load_config()["show"]["name"],
           font=_font(110, True),
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


_GEO_CACHE: list | None = None


def _load_geo() -> list:
    global _GEO_CACHE
    if _GEO_CACHE is None:
        if not GEO_PATH.exists():
            _GEO_CACHE = []
        else:
            _GEO_CACHE = json.loads(GEO_PATH.read_text(encoding="utf-8"))["features"]
    return _GEO_CACHE


def _merc_y(lat: float) -> float:
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def _proj(pt: tuple[float, float], box: tuple[int, int, int, int]) -> tuple[int, int]:
    """lon/lat → 像素（Mercator，固定视口 VIEW）。"""
    lon0, lat0, lon1, lat1 = VIEW
    x0, y0, x1, y1 = box
    px = (pt[0] - lon0) / (lon1 - lon0) * (x1 - x0) + x0
    y1m, y0m = _merc_y(lat1), _merc_y(lat0)
    py = (y1m - _merc_y(pt[1])) / (y1m - y0m) * (y1 - y0) + y0
    return int(px), int(py)


def _match_focus(headline: str) -> list[str]:
    """从标题里匹配核心国家 ISO 码（含首都/简称），按出现顺序。"""
    out = []
    for name, iso in ALIAS.items():
        if name in headline and iso not in out:
            out.append(iso)
    return out


def _centroid(feat) -> tuple[float, float] | None:
    """最大环的点平均（标签定位用，巴尔干六国紧凑形状够用）。"""
    best, best_n = None, 0
    for p in feat["geometry"]["coordinates"]:
        if len(p[0]) > best_n:
            best, best_n = p[0], len(p[0])
    if not best:
        return None
    return (sum(x for x, _ in best) / best_n, sum(y for _, y in best) / best_n)


def map_applicable(headline: str) -> bool:
    """纯函数：本条新闻是否适用巴尔干底图——至少命中一个核心国（含首都别名）。
    波罗的海/中亚/中东等条目命中不了，退回大字卡，不给错误地域暗示。"""
    return bool(_match_focus(headline))


def _draw_map(img, d, seg, meta) -> None:
    """真实底图卡：Natural Earth 50m 国界，焦点国家红色高亮，外围行为者
    右栏标签+细线指向焦点。数据缺失时退回棋盘格示意卡（老版）。"""
    feats = _load_geo()
    card = seg.get("card", {})
    headline = card.get("headline") or "巴尔干动向"

    if not map_applicable(headline):
        # 本条与本图无关（如波罗的海/中亚条目）：整卡退回大字标题卡，
        # 不画一张没有焦点还带行为者连线的巴尔干图误导观众
        _draw_headline(img, d, seg, meta)
        return

    # 标题条（地图上方，独立区域不与图打架）
    fh = _fit(d, headline, 52, W - 420, bold=True)
    d.text((200, 215), headline, font=fh, fill=INK)

    if not feats:
        _draw_map_chessboard(img, d, seg, meta)
        return

    focus = _match_focus(headline)
    x0, y0, x1, y1 = MAP_BOX
    mw, mh = x1 - x0, y1 - y0

    # 地图画布独立绘制（PIL 自动裁掉越界多边形），再整体贴回卡面
    canvas = Image.new("RGB", (mw, mh), SEA)
    cd = ImageDraw.Draw(canvas)
    for feat in feats:
        iso = feat["properties"].get("ADM0_A3", "")
        is_focus = iso in focus
        fill = ACCENT if is_focus else (LAND if iso in CORE_ISO else LAND_DIM)
        for poly in feat["geometry"]["coordinates"]:
            for ring in poly:
                pts = [_proj(pt, (0, 0, mw, mh)) for pt in ring]
                cd.polygon(pts, fill=fill,
                           outline=(255, 122, 140) if is_focus else BORDER)
    for feat in feats:                       # 标签画在地图画布上（跟随裁剪）
        iso = feat["properties"].get("ADM0_A3", "")
        if iso not in CORE_ISO:
            continue
        c = _centroid(feat)
        if not c or not (VIEW[0] <= c[0] <= VIEW[2] and VIEW[1] <= c[1] <= VIEW[3]):
            continue
        name = CORE_ISO[iso]
        px, py = _proj(c, (0, 0, mw, mh))
        fl = _font(36, True) if iso in focus else _font(30)
        tw = cd.textlength(name, font=fl)
        cd.text((px - tw / 2, py - fl.size * 0.7), name, font=fl,
                fill=INK if iso in focus else (176, 190, 205))
    img.paste(canvas, (x0, y0))
    d.rectangle([x0, y0, x1, y1], outline=BORDER, width=2)

    # 外围行为者：右栏标签 + 细线指向首个焦点国——只画本段口播提及的
    target = None
    for feat in feats:
        if feat["properties"].get("ADM0_A3") == focus[0]:
            c = _centroid(feat)
            target = _proj(c, MAP_BOX) if c else None
    fc = _font(34, True)
    mentioned = external_actors(seg.get("narration", ""))
    for label, (lx, ly) in EXTERNAL:
        if label not in mentioned:
            continue                        # 口播未提及：不画 chip、不画连线
        tw = d.textlength(label, font=fc)
        d.rounded_rectangle([lx - 14, ly - 10, lx + tw + 14, ly + 50], 10,
                            fill=BG2, outline=BORDER, width=2)
        d.text((lx, ly + 2), label, font=fc, fill=DIM)
        if target:                            # 从标签左侧进入地图
            d.line([lx - 14, ly + 20, target[0], target[1]],
                   fill=(88, 110, 134), width=2)

    d.text((1075, 905), "底图 Natural Earth（公有领域）", font=_font(26), fill=GRAY)


def _draw_map_chessboard(img, d, seg, meta) -> None:
    """降级版棋盘示意卡（底图数据缺失时才用）。外围行为者与主路同规则：
    仅当该段 narration 提及才画节点/连线。"""
    cfg = load_config()
    mentioned = set(external_actors(seg.get("narration", "")))
    nodes = {n["label"]: (int(n["x"] * (W - 480)) + 240, int(n["y"] * (H - 420)) + 300)
             for n in cfg["show"].get("region_nodes", [])
             if n["label"] not in EXTERNAL_TRIGGERS or n["label"] in mentioned}
    for a, b in cfg["show"].get("region_edges", []):
        if a in nodes and b in nodes:
            d.line([nodes[a], nodes[b]], fill=(51, 65, 85), width=3)
    focus = seg.get("card", {}).get("headline", "")
    for label, (x, y) in nodes.items():
        fw = _font(38, True)
        tw = d.textlength(label, font=fw)
        pad = 20
        is_focus = focus and (focus[:4] in label or label in focus)
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
    name = meta.get("show_label") or load_config()["show"]["name"]
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
        _chrome(img, d, badge=seg.get("card", {}).get("badge", ""),
                label=script["meta"].get("show_label", ""))
        _DRAWERS.get(seg["card"].get("type", "headline"), _draw_headline)(
            img, d, seg, script["meta"])
        png = cards_dir / f"{seg['id']}.png"
        img.save(png)
        out.append({"id": seg["id"], "png": str(png)})
    save_json({"cards": out}, store.project_dir(pid) / "cards.json")
    return out
