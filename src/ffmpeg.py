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
    r = run([ffmpeg_exe(), "-i", p])
    err = r.stderr or ""
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", err)
    if m:
        h, mi, s = m.groups()
        return int(h) * 3600 + int(mi) * 60 + float(s)
    raise RuntimeError(f"无法探测时长: {p} :: {err[:200]}")


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
    info["duration"] = probe_duration(p)
    return info


def mean_volume_db(path) -> float:
    """响度粗测（ffmpeg volumedetect 均值）。探测失败返回 -99（会触发 QC 拦截）。"""
    r = run([ffmpeg_exe(), "-i", str(path), "-af", "volumedetect", "-f", "null", "-"])
    m = re.search(r"mean_volume:\s*(-?[\d.]+)\s*dB", r.stderr or "")
    return float(m.group(1)) if m else -99.0
