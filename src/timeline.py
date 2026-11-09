# -*- coding: utf-8 -*-
"""时间轴：配音实测时长 + 卡片 → timeline.json（渲染与字幕的唯一定位依据）。"""
from src import scriptgen, store
from src.config import load_config
from src.jsonio import load_json, save_json


def build_timeline(pid: str) -> dict:
    script = scriptgen.load_script(pid)
    voice = load_json(store.project_dir(pid) / "voice.json")
    if not voice:
        raise RuntimeError(f"voice.json 缺失: {pid}")
    cfg = load_config()
    vcfg = cfg["video"]
    dur = {s["id"]: s["duration"] for s in voice["segments"]}

    segs, t = [], 0.0
    for seg in script["segments"]:
        audio_s = dur[seg["id"]]
        lead = vcfg["hook_lead_s"] if seg["kind"] == "hook" else 0.0
        length = round(lead + audio_s + vcfg["segment_tail_s"], 3)
        segs.append({"id": seg["id"], "kind": seg["kind"],
                     "start": round(t, 3), "length": length,
                     "audio_in": round(lead, 3),
                     "audio_duration": round(audio_s, 3),
                     "card": seg.get("card", {}).get("type", "headline")})
        t += length
    tl = {"segments": segs, "total_s": round(t, 2),
          "fps": vcfg["fps"], "width": vcfg["width"], "height": vcfg["height"]}
    save_json(tl, store.project_dir(pid) / "timeline.json")
    return tl


def load_timeline(pid: str) -> dict:
    tl = load_json(store.project_dir(pid) / "timeline.json")
    if not tl:
        raise RuntimeError(f"timeline.json 缺失: {pid}")
    return tl
