# -*- coding: utf-8 -*-
"""配置加载：默认值 <- config.yaml <- .env（密钥）。单一来源，所有模块经 load_config() 取配置。"""
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = {
    "video": {"width": 1920, "height": 1080, "fps": 30,
              "max_segment_s": 40, "segment_tail_s": 0.8, "hook_lead_s": 0.3},
    "voice": {"edge_voice": "zh-CN-YunxiNeural", "edge_rate": "+8%",
              "zhipu_model": "cogtts", "zhipu_voice": "tongtong",
              "cosy": {"enable": False, "mode": "zero_shot", "spk": ""}},
    "glm": {"model": "glm-4-flash", "temperature": 0.6, "timeout_s": 90,
            "max_tokens": 4000, "repair_retries": 1},
    "show": {"name": "巴尔干快讯", "region_nodes": [], "region_edges": []},
    "review": {"min_target_s": 60, "max_target_s": 200},
    "qc": {"min_mean_volume_db": -45.0, "max_volume_db": -0.5,
           "duration_tolerance_s": 8.0},
    "publish": {"category": 17, "tags": [], "disclaimer": ""},
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config() -> dict:
    load_dotenv(ROOT / ".env")
    cfg = DEFAULTS
    yml = ROOT / "config.yaml"
    if yml.exists():
        cfg = _deep_merge(cfg, yaml.safe_load(yml.read_text(encoding="utf-8")) or {})
    return cfg


def api_keys() -> dict:
    if os.environ.get("NEWS_OFFLINE") == "1":   # pipeline offline 模式：强制模板降级
        return {"zhipu": ""}
    return {"zhipu": os.environ.get("ZHIPU_API_KEY", "").strip()}
