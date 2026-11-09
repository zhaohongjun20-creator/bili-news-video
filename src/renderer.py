# -*- coding: utf-8 -*-
"""渲染：卡片 zoompan 动效片段 → 顺序拼接 → 配音混流 + ASS 字幕烧录 → final.mp4。

新闻快讯不需要花哨转场：片段内缓慢放大（Ken Burns）+ 0.35s 淡入出，
顺序硬切——信息密度优先，稳定压倒一切。
字幕：口播按 ≤16 字切行，按段音频窗口均布，ASS 白字黑边烧录。
"""
from pathlib import Path

from src import ffmpeg, scriptgen, store, timeline
from src.config import load_config
from src.jsonio import save_json

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, BorderStyle
Style: News,Microsoft YaHei,{size},&H00F8F8F8,&H00101010,&H00000000,1,3,1,2,60,60,{mv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ts(sec: float) -> str:
    h = int(sec // 3600)
    m = int(sec % 3600 // 60)
    s = sec % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def _ass_escaped(t: str) -> str:
    return t.replace("\n", r"\N")


def build_ass(pid: str, tl: dict) -> Path:
    """逐段：字幕行在 [audio_in, audio_in+audio_duration] 窗口内均布。"""
    script = scriptgen.load_script(pid)
    nar = {s["id"]: s["narration"] for s in script["segments"]}
    lines: list[str] = []
    for seg in tl["segments"]:
        text_lines = scriptgen.narration_lines(nar[seg["id"]])
        a0 = seg["start"] + seg["audio_in"]
        a1 = a0 + seg["audio_duration"]
        span = (a1 - a0) / max(1, len(text_lines))
        for i, ln in enumerate(text_lines):
            s0 = a0 + i * span
            s1 = min(a1, s0 + span + 0.15)
            lines.append(f"Dialogue: 0,{_ts(s0)},{_ts(s1)},News,,0,0,0,,"
                         f"{_ass_escaped(ln)}")
    ass = store.project_dir(pid) / "output" / "subs.ass"
    ass.parent.mkdir(exist_ok=True)
    ass.write_text(ASS_HEADER.format(w=tl["width"], h=tl["height"],
                                     size=64, mv=int(tl["height"] * 0.10))
                   + "\n".join(lines) + "\n", encoding="utf-8")
    return ass


def _render_clip(png: str, length: float, out: Path, fps: int) -> Path:
    """单段：静帧 zoompan 缓推（1.00→1.06）+ 淡入淡出。"""
    frames = max(2, int(length * fps))
    vf = (f"zoompan=z='1+0.06*on/{frames}':x='iw/2-(iw/zoom/2)':"
          f"y='ih/2-(ih/zoom/2)':d={frames}:s={1920}x{1080}:fps={fps},"
          f"fade=t=in:st=0:d=0.35,fade=t=out:st={max(0.0, length - 0.35):.2f}"
          f":d=0.35,format=yuv420p")
    r = ffmpeg.run([ffmpeg.ffmpeg_exe(), "-y", "-loop", "1", "-i", png,
                    "-t", f"{length:.3f}", "-vf", vf, "-r", str(fps),
                    "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                    "-an", out], timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"clip 渲染失败 {png}: {r.stderr[-300:]}")
    return out


def render(pid: str) -> dict:
    cfg = load_config()
    tl = timeline.build_timeline(pid)
    pdir = store.project_dir(pid)
    out_dir = pdir / "output"
    clips_dir = pdir / "clips"
    clips_dir.mkdir(exist_ok=True)

    # 1) 逐段视频片段（断点续跑：存在即跳过）
    cards = {c["id"]: c["png"] for c in _load_cards(pid)}
    clip_paths = []
    for seg in tl["segments"]:
        cp = clips_dir / f"{seg['id']}.mp4"
        stale = cp.exists() and Path(cards[seg["id"]]).stat().st_mtime > cp.stat().st_mtime
        if not cp.exists() or stale:          # 卡片更新过 → 片段作废重渲
            if cp.exists():
                cp.unlink()
            _render_clip(cards[seg["id"]], seg["length"], cp, tl["fps"])
        clip_paths.append(cp)

    # 2) 顺序拼接
    lst = clips_dir / "concat.txt"
    lst.write_text("\n".join(f"file '{p.as_posix()}'" for p in clip_paths),
                   encoding="utf-8")
    silent = out_dir / "_silent.mp4"
    r = ffmpeg.run([ffmpeg.ffmpeg_exe(), "-y", "-f", "concat", "-safe", "0",
                    "-i", lst, "-c", "copy", silent], timeout=1200)
    if r.returncode != 0:
        raise RuntimeError(f"拼接失败: {r.stderr[-300:]}")

    # 3) 配音轨按时间轴摆位（adelay）+ 混流 + 字幕烧录 + 响度规范
    voice = _load_voice(pid)
    filters, mix_in = [], []
    for i, seg in enumerate(voice["segments"]):
        tseg = next(s for s in tl["segments"] if s["id"] == seg["id"])
        delay_ms = int((tseg["start"] + tseg["audio_in"]) * 1000)
        mix_in += ["-i", str(seg["wav"])]
        filters.append(f"[{i + 1}:a]adelay={delay_ms}|{delay_ms}[a{i}]")
    filters.append("".join(f"[a{i}]" for i in range(len(voice["segments"])))
                   + f"amix=inputs={len(voice['segments'])}:normalize=0,"
                   "loudnorm=I=-16:TP=-1.5:LRA=11[aout]")
    ass = build_ass(pid, tl)
    final = out_dir / "final.mp4"
    cmd = [ffmpeg.ffmpeg_exe(), "-y", "-i", str(silent), *mix_in,
           "-filter_complex", ";".join(filters),
           "-map", "0:v", "-map", "[aout]",
           "-vf", "subtitles=subs.ass",       # cwd=out_dir：躲开 C: 冒号被滤镜解析
           "-c:v", "libx264", "-preset", "medium", "-crf", "20",
           "-c:a", "aac", "-b:a", "192k", "-shortest", "final.mp4"]
    r = ffmpeg.run(cmd, timeout=1800, cwd=str(out_dir))
    if r.returncode != 0:
        raise RuntimeError(f"成片合成失败: {r.stderr[-400:]}")

    # 4) 封面 = 片头卡
    from PIL import Image
    hook_png = cards[tl["segments"][0]["id"]]
    cover = out_dir / "cover.jpg"
    Image.open(hook_png).resize((1280, 720)).save(cover, quality=90)
    silent.unlink(missing_ok=True)

    info = ffmpeg.probe_video(final)
    save_json({"final": str(final), "cover": str(cover),
               "duration": info["duration"], "width": info["width"],
               "height": info["height"], "fps": info["fps"]},
              out_dir / "render.json")
    store.mark_stage(pid, "render", f"{info['duration']:.1f}s @{info['height']}p")
    return {"final": str(final), "duration": info["duration"]}


def _load_cards(pid: str) -> list[dict]:
    from src.jsonio import load_json
    c = load_json(store.project_dir(pid) / "cards.json")
    if not c:
        raise RuntimeError(f"cards.json 缺失: {pid}")
    return c["cards"]


def _load_voice(pid: str) -> dict:
    from src.jsonio import load_json
    v = load_json(store.project_dir(pid) / "voice.json")
    if not v:
        raise RuntimeError(f"voice.json 缺失: {pid}")
    return v
