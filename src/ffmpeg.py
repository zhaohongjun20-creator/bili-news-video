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


def _ffprobe_run(args: list) -> subprocess.CompletedProcess | None:
    """执行一次 ffprobe；启动失败（OSError）或超时（TimeoutExpired）
    视为 ffprobe 不可用，返回 None 由调用方走 stderr 降级。
    非零返回码不算异常，原样交调用方判断。"""
    try:
        return run(args, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None


def probe_duration(path) -> float:
    """音频/视频时长（秒）。ffprobe 优先，失败退回 ffmpeg -i stderr 解析。"""
    p = Path(path)
    pp = ffprobe_exe()
    if pp:
        r = _ffprobe_run([pp, "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=noprint_wrappers=1:nokey=1", p])
        if r is not None:
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
    """成片规格：duration/width/height/fps。三路降级：
    ffprobe 成功 → ffmpeg -i stderr 解析 → 报错。
    宽高解析不出来（0x0）不算探测成功——宁可在这里炸，也不把 0x0
    当有效规格写进 render.json / qc_report.json。"""
    p = Path(path)
    pp = ffprobe_exe()
    info = {"duration": 0.0, "width": 0, "height": 0, "fps": 0.0}
    if pp:
        r = _ffprobe_run([pp, "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "stream=width,height,r_frame_rate:format=duration",
                          "-of", "default=noprint_wrappers=1", p])
        if r is not None and r.returncode == 0 and "width=" in (r.stdout or ""):
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
            if info["width"] and info["height"]:
                return info
        # ffprobe 执行失败 / 输出为空 / 宽高为 0 → 不当成功，掉到 stderr 降级
    # 无 ffprobe（或 ffprobe 不可用）：一次 `ffmpeg -i`，时长与规格都从 stderr 解析
    err = (run([ffmpeg_exe(), "-i", p]).stderr or "")
    info["duration"] = parse_duration(err)
    if info["duration"] is None:
        info["duration"] = probe_duration(p)
    info.update(parse_video_spec(err))
    if not (info["width"] and info["height"]):
        raise RuntimeError(
            f"视频规格探测失败（无视频流或文件损坏，拒绝以 0x0 充数）: "
            f"{p} :: {err[-200:]}")
    return info


_AUDIO_STREAM = re.compile(r"Stream #\d+:\d+.*: Audio:")


def stderr_has_audio(stderr: str) -> bool:
    """纯函数：`ffmpeg -i` 的 stderr 里是否存在音频流（无 ffprobe 降级用）。"""
    return _AUDIO_STREAM.search(stderr) is not None


def parse_blackdetect(stderr: str) -> list[tuple[float, float]]:
    """纯函数：blackdetect stderr → [(start, duration)]。"""
    return [(float(m.group(1)), float(m.group(2))) for m in
            re.finditer(r"black_start:\s*([\d.]+)[^\n]*?black_duration:\s*([\d.]+)",
                        stderr)]


def parse_freezedetect(stderr: str) -> list[tuple[float, float]]:
    """纯函数：freezedetect stderr → [(start, duration)]（freeze_start 与
    后续 freeze_duration 配对；无配对的 start 丢弃）。"""
    out: list[tuple[float, float]] = []
    starts = [float(m.group(1)) for m in
              re.finditer(r"freeze_start:\s*([\d.]+)", stderr)]
    durs = [float(m.group(1)) for m in
            re.finditer(r"freeze_duration:\s*([\d.]+)", stderr)]
    return list(zip(starts, durs))


def parse_silencedetect(stderr: str) -> list[tuple[float, float]]:
    """纯函数：silencedetect stderr → [(start, duration)]。"""
    return [(float(m.group(1)), float(m.group(2))) for m in
            re.finditer(r"silence_start:\s*([\d.]+)[\s\S]*?silence_duration:\s*([\d.]+)",
                        stderr)]


def has_audio_stream(path) -> bool:
    """媒体是否含音轨。ffprobe 查流；ffprobe 异常/缺失时从 ffmpeg -i stderr 找 Audio 流行。"""
    p = Path(path)
    pp = ffprobe_exe()
    if pp:
        r = _ffprobe_run([pp, "-v", "error", "-select_streams", "a",
                          "-show_entries", "stream=index", "-of", "csv=p=0", p])
        if r is not None:
            return bool((r.stdout or "").strip())
    return stderr_has_audio(run([ffmpeg_exe(), "-i", p]).stderr or "")


def mean_volume_db(path) -> float:
    """响度粗测（ffmpeg volumedetect 均值）。探测失败返回 -99（会触发 QC 拦截）。"""
    r = run([ffmpeg_exe(), "-i", str(path), "-af", "volumedetect", "-f", "null", "-"])
    m = re.search(r"mean_volume:\s*(-?[\d.]+)\s*dB", r.stderr or "")
    return float(m.group(1)) if m else -99.0
