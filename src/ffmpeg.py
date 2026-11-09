# -*- coding: utf-8 -*-
"""ffmpeg/ffprobe 工具：优先 PATH，退回 imageio-ffmpeg；时长探测双路兜底。"""
import re
import shutil
import subprocess
from pathlib import Path

import imageio_ffmpeg


def ffmpeg_exe() -> str:
    return shutil.which("ffmpeg") or imageio_ffmpeg.get_ffmpeg_exe()


def ffprobe_exe() -> str | None:
    return shutil.which("ffprobe")


def run(cmd: list, timeout: int = 1800,
        cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([str(c) for c in cmd], capture_output=True,
                          text=True, timeout=timeout, cwd=cwd)


_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def parse_duration(stderr: str) -> float | None:
    """纯函数：从 `ffmpeg -i` 的 stderr 解析时长（秒）；解析不到返回 None。"""
    if m := _DURATION.search(stderr):
        h, mi, s = m.groups()
        return int(h) * 3600 + int(mi) * 60 + float(s)
    return None


def probe_duration(path) -> float:
    """音频/视频时长（秒）。ffprobe 优先，失败退回 ffmpeg -i stderr 解析。"""
    p = Path(path)
    pp = ffprobe_exe()
    if pp:
        r = run([pp, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", p])
        try:
            return float(r.stdout.strip())
        except ValueError:
            pass
    err = (run([ffmpeg_exe(), "-i", p]).stderr or "")
    d = parse_duration(err)
    if d is not None:
        return d
    raise RuntimeError(f"无法探测时长: {p} :: {err[:200]}")


def parse_video_spec(stderr: str) -> dict:
    """纯函数：从 `ffmpeg -i` 的 stderr 解析视频规格（无 ffprobe 的降级路径）。

    分辨率取 Video 流行里的 \\d{3,5}x\\d{3,5}，帧率取同行的 `N fps`。
    解析不到的字段保持零值（width=0/height=0/fps=0.0），由上层 QC 判定。
    """
    spec = {"width": 0, "height": 0, "fps": 0.0}
    for ln in stderr.splitlines():
        if "Video:" not in ln:
            continue
        if m := re.search(r"\b(\d{3,5})x(\d{3,5})\b", ln):
            spec["width"], spec["height"] = int(m.group(1)), int(m.group(2))
        if m := re.search(r"([\d.]+)\s*fps", ln):
            try:
                spec["fps"] = round(float(m.group(1)), 2)
            except ValueError:
                pass
        break                                     # 只认第一条视频流
    return spec


def probe_video(path) -> dict:
    """成片规格：duration/width/height/fps。"""
    p = Path(path)
    pp = ffprobe_exe()
    info = {"duration": 0.0, "width": 0, "height": 0, "fps": 0.0}
    if pp:
        r = run([pp, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height,r_frame_rate:format=duration",
                 "-of", "default=noprint_wrappers=1", p])
        for line in (r.stdout or "").splitlines():
            k, _, v = line.partition("=")
            if k == "width":
                info["width"] = int(v or 0)
            elif k == "height":
                info["height"] = int(v or 0)
            elif k == "duration":
                try:
                    info["duration"] = float(v)
                except ValueError:
                    pass
            elif k == "r_frame_rate" and "/" in v:
                n, d = v.split("/")
                try:
                    info["fps"] = round(float(n) / float(d), 2)
                except (ValueError, ZeroDivisionError):
                    pass
        return info
    # 无 ffprobe：一次 `ffmpeg -i`，时长与分辨率/帧率都从 stderr 降级解析
    err = (run([ffmpeg_exe(), "-i", p]).stderr or "")
    info["duration"] = parse_duration(err)
    if info["duration"] is None:
        info["duration"] = probe_duration(p)
    info.update(parse_video_spec(err))
    return info


def mean_volume_db(path) -> float:
    """响度粗测（ffmpeg volumedetect 均值）。探测失败返回 -99（会触发 QC 拦截）。"""
    r = run([ffmpeg_exe(), "-i", str(path), "-af", "volumedetect", "-f", "null", "-"])
    m = re.search(r"mean_volume:\s*(-?[\d.]+)\s*dB", r.stderr or "")
    return float(m.group(1)) if m else -99.0
