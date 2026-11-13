# -*- coding: utf-8 -*-
"""一次性工具：下载 Natural Earth 50m 全球国界，抽稀后存 assets/geo/world_50m.json。

与 build_basegeo.py（巴尔干精细底图）并存：全球数据供「自动定位地图卡」与
地球仪使用，抽稀到约 8 万点控制仓库体积。

    python tools/build_worldgeo.py
"""
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "geo" / "world_50m.json"

URLS = [
    "https://cdn.jsdelivr.net/gh/nvkelso/natural-earth-vector@master/"
    "geojson/ne_50m_admin_0_countries.geojson",
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
    "geojson/ne_50m_admin_0_countries.geojson",
]

KEEP_PROPS = ("ADM0_A3", "NAME")
TARGET_POINTS = 80000           # 抽稀后的全局点数预算
DROP_ANTARCTICA = False         # 地球仪南极视角仍需要


def _decimate_ring(ring: list, factor: int) -> list:
    """按步长抽稀；保留首尾（GeoJSON 环首尾重复，保证闭合）。"""
    if factor <= 1 or len(ring) <= 8:
        return ring
    step = max(1, len(ring) // max(4, len(ring) // factor))
    kept = ring[::step]
    if kept[-1] != ring[-1]:
        kept.append(ring[-1])
    return kept


def main() -> None:
    raw = None
    for url in URLS:
        try:
            print("下载:", url[:76])
            with urllib.request.urlopen(url, timeout=300) as r:
                raw = json.loads(r.read().decode("utf-8"))
            break
        except Exception as e:
            print("  失败:", e)
    if raw is None:
        sys.exit("所有镜像下载失败")

    # 先统计总点数，决定抽稀步长
    total = 0
    for f in raw["features"]:
        g = f.get("geometry") or {}
        for poly in (g.get("coordinates") if g.get("type") == "MultiPolygon"
                     else [g.get("coordinates")] if g.get("type") == "Polygon" else []):
            for ring in poly:
                total += len(ring)
    factor = max(1, round(total / TARGET_POINTS))
    print(f"总点数 {total} → 抽稀步长 {factor}")

    features = []
    for f in raw["features"]:
        g = f.get("geometry") or {}
        polys = (g.get("coordinates") if g.get("type") == "MultiPolygon"
                 else [g.get("coordinates")] if g.get("type") == "Polygon" else [])
        kept_polys = []
        for poly in polys:
            kept_rings = []
            for ring in poly:
                r2 = _decimate_ring(ring, factor)
                if len(r2) >= 4:
                    kept_rings.append([[round(x, 2), round(y, 2)] for x, y in r2])
            if kept_rings:
                kept_polys.append(kept_rings)
        if not kept_polys:
            continue
        props = {k: f.get("properties", {}).get(k, "") for k in KEEP_PROPS}
        features.append({"type": "Feature", "properties": props,
                         "geometry": {"type": "MultiPolygon",
                                      "coordinates": kept_polys}})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"type": "FeatureCollection", "features": features},
                              ensure_ascii=False), encoding="utf-8")
    npts = sum(len(r) for f in features
               for p in f["geometry"]["coordinates"] for r in p)
    print(f"完成: {len(features)} 国 / {npts} 点 / "
          f"{OUT.stat().st_size // 1024} KB → {OUT}")


if __name__ == "__main__":
    main()
