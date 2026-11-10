# -*- coding: utf-8 -*-
"""质检：规格、时长、响度、音轨、字幕时间、字幕文件存在性 → output/qc_report.json。"""
import re
from pathlib import Path

from src import ffmpeg, store
from src.config import load_config
from src.jsonio import save_json

_DIALOGUE = re.compile(r"^Dialogue:\s*[^,]*,([^,]+),([^,]+)")


def ass_dialogue_span(ass_text: str) -> tuple[float, float] | None:
    """纯函数：ASS 字幕全部 Dialogue 的 (首条开始, 末条结束) 秒数。
    无 Dialogue 行返回 None。时间格式 0:00:03.20（ centisecond，逗号变体兼容）。"""
    def _t(s: str) -> float:
        h, m, sec = s.strip().split(":")
        return int(h) * 3600 + int(m) * 60 + float(sec.replace(",", "."))

    starts, ends = [], []
    for ln in ass_text.splitlines():
        if m := _DIALOGUE.match(ln.strip()):
            starts.append(_t(m.group(1)))
            ends.append(_t(m.group(2)))
    if not starts:
        return None
    return min(starts), max(ends)


def qc(pid: str) -> dict:
    from src.jsonio import load_json
    cfg = load_config()
    rj = load_json(store.project_dir(pid) / "output" / "render.json")
    if not rj:
        raise RuntimeError(f"render.json 缺失: {pid}")
    final = Path(rj["final"])
    problems: list[str] = []

    spec = ffmpeg.probe_video(final)
    if spec["height"] != cfg["video"]["height"]:
        problems.append(f"分辨率异常: {spec['width']}x{spec['height']}")
    if abs(spec["duration"] - rj["duration"]) > 1.0:
        problems.append(f"时长自洽性: probe {spec['duration']:.1f}s vs render "
                        f"{rj['duration']:.1f}s")
    total = load_json(store.project_dir(pid) / "timeline.json")["total_s"]
    tol = cfg["qc"]["duration_tolerance_s"]
    if abs(spec["duration"] - total) > tol:
        problems.append(f"成片时长 {spec['duration']:.1f}s 偏离时间轴 {total:.1f}s"
                        f"（>±{tol}s）")
    mv = ffmpeg.mean_volume_db(final)
    if mv < cfg["qc"]["min_mean_volume_db"]:
        problems.append(f"平均响度过低 {mv:.1f}dB（疑似静音轨）")
    if mv > cfg["qc"]["max_volume_db"]:
        problems.append(f"削波风险 {mv:.1f}dB")
    if not ffmpeg.has_audio_stream(final):
        problems.append("无音轨：成片缺音频流（配音混流失败？）")

    # 语速启发式：音频时长 vs 文案字数（约4.5字/秒 ±45%容差）。
    # 抓「字幕是A内容、音频是B内容」的缓存错配——规格指标查不出这种错。
    script = load_json(store.project_dir(pid) / "script.json") or {}
    voice = load_json(store.project_dir(pid) / "voice.json") or {}
    dur = {s["id"]: s["duration"] for s in voice.get("segments", [])}
    for seg in script.get("segments", []):
        d = dur.get(seg["id"])
        if not d:
            continue
        est = max(1.5, len(seg["narration"]) / 4.5)
        if not (est * 0.55 <= d <= est * 1.45):
            problems.append(f"段 {seg['id']} 音画疑似错配：音频 {d:.1f}s vs "
                            f"文案约 {est:.1f}s（字数 {len(seg['narration'])}）")

    # 人工稿预期时长守卫：分镜时间轴（manual.expected_s）与成片实际时长差
    # 超 90s → 大概率解析器吞了稿子后半部分（语速启发式抓不住这种自洽错误）
    expected_s = (script.get("meta") or {}).get("expected_s") or 0
    if expected_s:
        if abs(spec["duration"] - float(expected_s)) > 90:
            problems.append(f"成片 {spec['duration']:.0f}s 偏离分镜预期 "
                            f"{float(expected_s):.0f}s（>90s）——疑似解析吞段")

    subs = store.project_dir(pid) / "output" / "subs.ass"
    if not subs.exists():
        problems.append("字幕文件缺失")
    else:
        # 字幕 Dialogue 首末时间不得超出成片时长（±1s 容差，与本文件
        # 时长自洽性检查同一口径）——烧录越界会裁字/露黑屏
        span = ass_dialogue_span(subs.read_text(encoding="utf-8"))
        if span and (span[0] < 0 or span[1] > spec["duration"] + 1.0):
            problems.append(f"字幕时间越界：Dialogue 首末 {span[0]:.2f}s–"
                            f"{span[1]:.2f}s 超出成片 {spec['duration']:.1f}s")
    if not Path(rj["cover"]).exists():
        problems.append("封面缺失")

    report = {"pid": pid, "checked_at": store.now(),
              "duration": spec["duration"], "mean_volume_db": mv,
              "problems": problems, "ok": not problems}
    save_json(report, store.project_dir(pid) / "output" / "qc_report.json")
    store.mark_stage(pid, "qc", "PASS" if report["ok"] else f"{len(problems)} 项问题")
    return report
