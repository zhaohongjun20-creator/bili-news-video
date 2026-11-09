# -*- coding: utf-8 -*-
"""一次性工具：下载 Natural Earth 50m 国界 GeoJSON，裁剪到巴尔干周边 bbox，
简化精度后存 assets/geo/balkans_base.json（入库，渲染时离线可用）。

    python tools/build_basegeo.py

Natural Earth 是公有领域，无署名义务；卡面右下角仍标注底图来源（好习惯）。
"""
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "geo" / "balkans_base.json"

# bbox 覆盖巴尔干 + 土耳其西部 + 意大利东南角 + 多瑙河以北邻居
LON0, LAT0, LON1, LAT1 = 12.5, 34.5, 30.0, 48.5

URLS = [
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
    "geojson/ne_50m_admin_0_countries.geojson",
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
    "geojson/ne_110m_admin_0_countries.geojson",          # 兜底：更粗但能跑
]

KEEP_PROPS = ("NAME", "NAME_ZH", "ADM0_A3", "ISO_A2", "ISO_A3")


def _ring_in_bbox(ring) -> bool:
    return any(LON0 <= x <= LON1 and LAT0 <= y <= LAT1 for x, y in ring)


def _clip_geom(geom) -> dict | None:
    """粗裁剪：任一环落在 bbox 内就保留该多边形（不精确裁边，渲染层再视口裁剪）。"""
    polys = (geom.get("coordinates") if geom.get("type") == "MultiPolygon"
             else [geom.get("coordinates")] if geom.get("type") == "Polygon" else [])
    kept = [p for p in polys if p and _ring_in_bbox(p[0])]
    if not kept:
        return None
    kept = [[[[round(x, 3), round(y, 3)] for x, y in ring] for ring in p]
            for p in kept]
    return {"type": "MultiPolygon", "coordinates": kept}


def main() -> None:
    raw = None
    for url in URLS:
        try:
            print("下载:", url[:80])
            with urllib.request.urlopen(url, timeout=120) as r:
                raw = json.loads(r.read().decode("utf-8"))
            break
        except Exception as e:
            print("  失败:", e)
    if raw is None:
        sys.exit("所有镜像下载失败")

    features = []
    for f in raw.get("features", []):
        g = f.get("geometry") or {}
        clipped = _clip_geom(g)
        if clipped is None:
            continue
        props = {k: f.get("properties", {}).get(k, "") for k in KEEP_PROPS}
        features.append({"type": "Feature", "properties": props,
                         "geometry": clipped})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"type": "FeatureCollection",
                               "features": features},
                              ensure_ascii=False), encoding="utf-8")
    print(f"完成: {len(features)} 国 -> {OUT} "
          f"({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
