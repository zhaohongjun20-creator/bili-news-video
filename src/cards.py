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
    d.rectangle([120, 260, 520, 276], fill=ACCENT)
    d.text((120, 296), f"{date.year}年{date.month}月{date.day}日",
           font=_font(56), fill=DIM)
    d.text((120, 380), meta.get("show_label") or load_config()["show"]["name"],
           font=_font(92, True), fill=INK)
    # 当日钩子句：第一条动态的标题放大上画（没有就跳过）
    y = 540
    hook_line = meta.get("hook_line") or ""
    if hook_line:
        fh = _font(48, True)
        for ln in _wrap(hook_line, fh, d, W - 800, max_lines=2):
            d.text((120, y), ln, font=fh, fill=GOLD)
            y += 74
    n = meta.get("n_items", 0)
    sub = f"本期 {n} 条动态 · 只讲事实和各方说法" if n else "本期动态"
    d.text((120, max(y + 40, 730)), sub, font=_font(40), fill=DIM)
    # 开场地球仪：转到当期主地点（无地点则不画，保持原版式）
    place = meta.get("hook_place")
    if place and _load_world():
        _draw_globe(d, place, R=280, cx=1400, cy=620,
                    focus_iso=place.get("iso") or "")


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


# ---- 全球自动定位：地名坐标表 + 动态视口 + 地球仪 ------------------------
# 手工地名表（坐标为示意级精度，卡面标注「底图 Natural Earth」）。
# 刻意不含中国地名：涉华内容走大字卡，不给错误地域暗示。
# entry: (lon, lat, 视野半径°, 类型, 焦点国ISO)；类型 city/country/sea
GAZETTEER = {
    "乌斯季卢加": (28.4, 59.66, 3, "city", "RUS"),
    "圣彼得堡": (30.3, 59.95, 4, "city", "RUS"),
    "芬兰湾": (26.5, 59.8, 6, "sea", None),
    "波罗的海": (19.0, 57.0, 10, "sea", None),
    "立陶宛": (23.9, 55.2, 4, "country", "LTU"),
    "拉脱维亚": (24.9, 56.9, 4, "country", "LVA"),
    "爱沙尼亚": (25.5, 58.7, 4, "country", "EST"),
    "维尔纽斯": (25.28, 54.69, 3, "city", "LTU"),
    "里加": (24.1, 56.95, 3, "city", "LVA"),
    "霍尔木兹": (56.5, 26.6, 5, "sea", None),
    "阿曼湾": (58.8, 24.4, 6, "sea", None),
    "波斯湾": (51.5, 27.0, 8, "sea", None),
    "哈伊马角": (55.95, 25.75, 3, "city", "ARE"),
    "阿联酋": (54.2, 24.0, 5, "country", "ARE"),
    "阿曼": (57.0, 21.5, 6, "country", "OMN"),
    "伊朗": (53.7, 32.4, 9, "country", "IRN"),
    "德黑兰": (51.4, 35.7, 3, "city", "IRN"),
    "以色列": (34.9, 31.4, 4, "country", "ISR"),
    "特拉维夫": (34.78, 32.08, 2.5, "city", "ISR"),
    "红海": (38.0, 20.5, 10, "sea", None),
    "苏伊士": (32.55, 30.0, 3, "city", "EGY"),
    "黑海": (34.0, 43.5, 8, "sea", None),
    "乌克兰": (31.5, 49.0, 9, "country", "UKR"),
    "基辅": (30.52, 50.45, 3, "city", "UKR"),
    "敖德萨": (30.73, 46.48, 3, "city", "UKR"),
    "俄罗斯": (40.0, 57.5, 14, "country", "RUS"),
    "莫斯科": (37.62, 55.75, 4, "city", "RUS"),
    "哈萨克斯坦": (67.0, 48.0, 12, "country", "KAZ"),
    "吉尔吉斯斯坦": (74.5, 41.5, 5, "country", "KGZ"),
    "塔吉克斯坦": (71.0, 38.8, 5, "country", "TJK"),
    "亚美尼亚": (45.0, 40.2, 4, "country", "ARM"),
    "土耳其": (35.0, 39.0, 7, "country", "TUR"),
    "安卡拉": (32.85, 39.93, 3, "city", "TUR"),
    "阿根廷": (-64.5, -36.5, 12, "country", "ARG"),
    "布宜诺斯艾利斯": (-58.4, -34.6, 3, "city", "ARG"),
    "英国": (-1.6, 52.8, 7, "country", "GBR"),
    "伦敦": (-0.12, 51.5, 3, "city", "GBR"),
    "米尔德霍尔": (0.49, 52.36, 2.5, "city", "GBR"),
    "Mildenhall": (0.49, 52.36, 2.5, "city", "GBR"),
    "德国": (10.3, 51.2, 7, "country", "DEU"),
    "法国": (2.5, 46.6, 7, "country", "FRA"),
    "北大西洋": (-28.0, 47.0, 15, "sea", None),
    "大西洋网": (-12.0, 54.0, 9, "sea", "GBR"),
    "大西洋": (-32.0, 38.0, 20, "sea", None),
}
_KIND_RANK = {"city": 0, "country": 1, "sea": 2}      # 同长度时 city 优先于 sea

WORLD_GEO_PATH = ROOT / "assets" / "geo" / "world_50m.json"
_WORLD_CACHE: list | None = None


def _load_world() -> list:
    global _WORLD_CACHE
    if _WORLD_CACHE is None:
        _WORLD_CACHE = (json.loads(WORLD_GEO_PATH.read_text(encoding="utf-8"))["features"]
                        if WORLD_GEO_PATH.exists() else [])
    return _WORLD_CACHE


def resolve_place(headline: str = "", narration: str = "") -> dict | None:
    """标题优先（同长取 city>country>sea），标题无命中再扫口播。"""
    for text in (headline or "", narration or ""):
        if not text:
            continue
        best = None
        for name, val in GAZETTEER.items():
            if name in text:
                key = (-len(name), _KIND_RANK.get(val[3], 3))
                if best is None or key < best[0]:
                    best = (key, {"name": name, "lon": val[0], "lat": val[1],
                                  "radius": val[2], "kind": val[3], "iso": val[4]})
        if best:
            return best[1]
    return None


def _merc_bbox_viewport(lon: float, lat: float, radius: float,
                        box: tuple) -> tuple:
    """以 (lon,lat) 为中心、纬向半径 radius° 的 Mercator 视口 bbox。"""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    m_c = _merc_y(max(-75.0, min(75.0, lat)))
    half_m = math.radians(radius)
    lat1 = min(80.0, 2 * math.degrees(math.atan(math.exp(min(10.0, m_c + half_m)))) - 90)
    lat0 = max(-80.0, 2 * math.degrees(math.atan(math.exp(max(-10.0, m_c - half_m)))) - 90)
    dlon = min(math.degrees((2 * half_m) * (w / h) / 2), 179.0)
    return lon - dlon, lat0, lon + dlon, lat1


def _proj_view(pt: tuple, view: tuple, box: tuple) -> tuple[int, int]:
    lon0, lat0, lon1, lat1 = view
    m = _merc_y(max(-85.0, min(85.0, pt[1])))
    m0, m1 = _merc_y(lat0), _merc_y(lat1)
    x0, y0, x1, y1 = box
    return (int((pt[0] - lon0) / (lon1 - lon0) * (x1 - x0) + x0),
            int((m1 - m) / (m1 - m0) * (y1 - y0) + y0))


def _globe_project(pt: tuple, lon0: float, lat0: float,
                   R: float, cx: float, cy: float) -> tuple[float, float, float]:
    """正交投影（地球仪）。返回 (screen_x, screen_y, cosc)；cosc<0 为背面。"""
    lam = math.radians(pt[0] - lon0)
    phi = math.radians(pt[1])
    phi0 = math.radians(lat0)
    cosc = math.sin(phi0) * math.sin(phi) + math.cos(phi0) * math.cos(phi) * math.cos(lam)
    x = R * math.cos(phi) * math.sin(lam)
    y = R * (math.cos(phi0) * math.sin(phi) - math.sin(phi0) * math.cos(phi) * math.cos(lam))
    return cx + x, cy - y, cosc


def _limb_point(a: tuple, b: tuple, lon0, lat0, R, cx, cy) -> tuple[float, float]:
    """经纬度两点间二分求地平线交点（a 可见，b 不可见）。"""
    for _ in range(10):
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        _, _, c = _globe_project(mid, lon0, lat0, R, cx, cy)
        if c >= 0:
            a = mid
        else:
            b = mid
    x, y, _ = _globe_project(a, lon0, lat0, R, cx, cy)
    return x, y


def _globe_ring(ring: list, lon0, lat0, R, cx, cy) -> list[tuple[float, float]]:
    """环投影到地球仪：背面点裁掉，跨地平线的边插到地平线上。"""
    pts: list[tuple[float, float]] = []
    prev = None                                     # (lon, lat, vis)
    for pt in ring:
        _, _, c = _globe_project(pt, lon0, lat0, R, cx, cy)
        vis = c >= 0
        if prev is not None and vis != prev[2]:
            a, b = (prev[:2], pt) if prev[2] else (pt, prev[:2])
            pts.append(_limb_point(a, b, lon0, lat0, R, cx, cy))
        if vis:
            x, y, _ = _globe_project(pt, lon0, lat0, R, cx, cy)
            pts.append((x, y))
        prev = (pt[0], pt[1], vis)
    return pts


def _draw_globe(d: ImageDraw.ImageDraw, place: dict, R: float,
                cx: float, cy: float, focus_iso: str = "") -> None:
    """正交投影地球仪：海洋圆盘 + 经纬网 + 陆地 + 焦点标记。"""
    lon0, lat0 = place["lon"], place["lat"]
    d.ellipse([cx - R, cy - R, cx + R, cy + R], fill=SEA, outline=BORDER, width=3)
    # 经纬网（每 30°）
    for mer in range(-180, 180, 30):
        pts = _globe_ring([(mer, lat) for lat in range(-80, 81, 8)],
                          lon0, lat0, R - 2, cx, cy)
        if len(pts) >= 2:
            d.line(pts, fill=(28, 46, 66), width=1)
    for par in range(-60, 81, 30):
        pts = _globe_ring([(lon, par) for lon in range(-180, 181, 8)],
                          lon0, lat0, R - 2, cx, cy)
        if len(pts) >= 2:
            d.line(pts, fill=(28, 46, 66), width=1)
    for feat in _load_world():
        iso = feat["properties"].get("ADM0_A3", "")
        is_focus = iso == focus_iso
        fill = ACCENT if is_focus else (LAND if iso in CORE_ISO else LAND_DIM)
        for poly in feat["geometry"]["coordinates"]:
            for ring in poly:
                pts = _globe_ring(ring, lon0, lat0, R - 2, cx, cy)
                if len(pts) >= 3:
                    d.polygon(pts, fill=fill, outline=BORDER)
    # 焦点标记
    x, y, c = _globe_project((place["lon"], place["lat"]), lon0, lat0, R - 2, cx, cy)
    if c > 0.05:
        d.ellipse([x - 9, y - 9, x + 9, y + 9], fill=ACCENT, outline=(255, 255, 255), width=2)
        fl = _font(30, True)
        d.text((x + 16, y - 40), place["name"], font=fl, fill=INK)


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
        place = resolve_place(headline, seg.get("narration", ""))
        if place and _load_world():
            _draw_map_dynamic(img, d, seg, meta, place)
            return
        # 真的没有可定位地名：退回大字卡
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


def _draw_map_dynamic(img, d, seg, meta, place: dict) -> None:
    """自动定位地图卡：视口对准口播提到的地方——城市/海峡给近景+标记点，
    国家红色高亮，海/区域给中景。数据缺失时由调用方退大字卡。"""
    card = seg.get("card", {})
    headline = card.get("headline") or place["name"]
    fh = _fit(d, headline, 52, W - 420, bold=True)
    d.text((200, 185), headline, font=fh, fill=INK)
    if card.get("sub"):
        fs = _fit(d, card["sub"], 36, W - 420)
        d.text((200, 244), card["sub"], font=fs, fill=DIM)

    feats = _load_world()
    x0, y0, x1, y1 = MAP_BOX
    mw, mh = x1 - x0, y1 - y0
    view = _merc_bbox_viewport(place["lon"], place["lat"], place["radius"],
                               (0, 0, mw, mh))
    canvas = Image.new("RGB", (mw, mh), SEA)
    cd = ImageDraw.Draw(canvas)
    # 仅国家级焦点才整国涂红；城市级只做标记点（否则大国铺满全屏全是红）
    focus_iso = place.get("iso") if place.get("kind") == "country" else ""
    for feat in feats:
        iso = feat["properties"].get("ADM0_A3", "")
        is_focus = iso == focus_iso
        fill = ACCENT if is_focus else LAND       # 动态视口统一陆色，海陆对比清晰
        for poly in feat["geometry"]["coordinates"]:
            for ring in poly:
                # 视口预筛：环 bbox 与视口不相交就跳过（大幅省时）
                lons = [pt[0] for pt in ring]
                lats = [pt[1] for pt in ring]
                if (max(lons) < view[0] - 2 or min(lons) > view[2] + 2
                        or max(lats) < view[1] - 2 or min(lats) > view[3] + 2):
                    continue
                pts = [_proj_view(pt, view, (0, 0, mw, mh)) for pt in ring]
                cd.polygon(pts, fill=fill, outline=(255, 122, 140) if is_focus else BORDER)
    # 地名标记（城市/海峡/海：红点 + 名称牌）
    px, py = _proj_view((place["lon"], place["lat"]), view, (0, 0, mw, mh))
    fl = _font(34, True)
    tw = cd.textlength(place["name"], font=fl)
    cd.ellipse([px - 8, py - 8, px + 8, py + 8], fill=ACCENT,
               outline=(255, 255, 255), width=2)
    lx = min(max(px + 14, 8), mw - tw - 40)
    cd.rounded_rectangle([lx, py - 26, lx + tw + 24, py + 22], 8,
                         fill=BG2, outline=BORDER, width=2)
    cd.text((lx + 12, py - 20), place["name"], font=fl, fill=INK)
    img.paste(canvas, (x0, y0))
    d.rectangle([x0, y0, x1, y1], outline=BORDER, width=2)

    # 右栏：本条要点（来自卡面 lines）
    fy = 330
    for ln in (card.get("lines") or [])[:4]:
        if not ln:
            continue
        fline = _fit(d, "· " + ln, 40, 640)
        d.text((1120, fy), "· " + ln, font=fline, fill=(196, 181, 253))
        fy += 66
    d.text((1075, 905), "底图 Natural Earth（公有领域）", font=_font(26), fill=GRAY)
    return ((x0 + px) / W, (y0 + py) / H)     # 焦点比例：渲染时 zoompan 推向此点


_DRAWERS = {"hook": _draw_hook, "headline": _draw_headline, "quote": _draw_quote,
            "map": _draw_map, "china": _draw_china, "mainline": _draw_mainline,
            "outro": _draw_outro}


def render_cards(pid: str) -> list[dict]:
    """全稿出卡。返回 [{id, png}]。同段重跑直接覆盖（卡是纯函数）。"""
    script = scriptgen.load_script(pid)
    cards_dir = store.project_dir(pid) / "cards"
    cards_dir.mkdir(exist_ok=True)
    first_item = next((s for s in script["segments"] if s.get("kind") == "item"), None)
    hook_place = None
    if first_item:
        hook_place = resolve_place(first_item.get("card", {}).get("headline", ""),
                                   first_item.get("narration", ""))
    meta = dict(script["meta"], hook_place=hook_place,
                hook_line=(first_item.get("card", {}).get("headline", "")
                           if first_item else ""))
    out = []
    for seg in script["segments"]:
        img = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(img)
        # 每张卡一层淡面板底（四周 80px 边框感），避免纯背景太空
        d.rounded_rectangle([80, 180, W - 80, H - 80], 24, fill=BG2)
        img.paste(Image.new("RGB", (W - 320, H - 420), BG), (160, 260))
        _chrome(img, d, badge=seg.get("card", {}).get("badge", ""),
                label=script["meta"].get("show_label", ""))
        ret = _DRAWERS.get(seg["card"].get("type", "headline"), _draw_headline)(
            img, d, seg, meta)
        png = cards_dir / f"{seg['id']}.png"
        img.save(png)
        entry = {"id": seg["id"], "png": str(png)}
        if isinstance(ret, tuple) and len(ret) == 2:
            entry["focus"] = ret              # 动态地图焦点比例 → 渲染推向该点
        out.append(entry)
    save_json({"cards": out}, store.project_dir(pid) / "cards.json")
    return out


def make_cover(pid: str) -> Path:
    """独立 16:9 封面：主标题大字 + 钩子副题 + 地球仪，不是片头卡缩放。"""
    script = scriptgen.load_script(pid)
    meta = script["meta"]
    out = store.project_dir(pid) / "output" / "cover.jpg"
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 16], fill=ACCENT)
    label = meta.get("show_label") or load_config()["show"]["name"]
    d.text((140, 120), f"{label} · {meta['date']}", font=_font(44, True), fill=ACCENT)
    title = script.get("title", "")
    f = _fit(d, title, 84, 1060, bold=True)
    y = 230
    for ln in _wrap(title, f, d, 1060, max_lines=3):
        d.text((140, y), ln, font=f, fill=INK)
        y += int(f.size * 1.28)
    first_item = next((s for s in script["segments"] if s.get("kind") == "item"), None)
    if first_item:
        hl = first_item.get("card", {}).get("headline", "")
        if hl and hl not in title:
            fh2 = _fit(d, hl, 44, 1000)
            d.text((140, y + 26), "· " + hl, font=fh2, fill=GOLD)
    d.text((140, 910), "只讲发生了什么 · 各方怎么说　|　不站队 · 不评论 · 不预测",
           font=_font(34), fill=DIM)
    place = resolve_place(first_item.get("card", {}).get("headline", "")
                          if first_item else "",
                          first_item.get("narration", "") if first_item else "")
    if place and _load_world():
        _draw_globe(d, place, R=320, cx=1480, cy=610,
                    focus_iso=place.get("iso") or "")
    img.resize((1280, 720)).save(out, quality=90)
    return out
