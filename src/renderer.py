# -*- coding: utf-8 -*-
"""渲染：卡片动效片段 → 顺序拼接 → 配音混流 + ASS 字幕烧录 → final.mp4。

动效按段型区分（不再是统一缓推+淡入出）：
    hook     台标起幅：1.05→1.00 定机位，硬切进第一条
    item(map) 推向焦点标记（焦点比例由 cards.json 提供）
    item(其他) 1.08 定zoom短促滑入（0.6s），条目间硬切
    outro    卡住不动，仅收尾 0.4s 淡黑
字幕：54 号、贴近底边安全区（避开地图注记），行时长按字数加权分配。
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

ASS_SIZE = 54
ASS_MARGIN_RATIO = 0.040          # 底边距 4%：字幕带在地图注记下方，不重叠


def _ts(sec: float) -> str:
    h = int(sec // 3600)
    m = int(sec % 3600 // 60)
    s = sec % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def _ass_escaped(t: str) -> str:
    return t.replace("\n", r"\N")


def subtitle_events(narr_map: dict, tl_segs: list) -> list[tuple[float, float, str]]:
    """字幕事件：行时长按字数加权分配段内音频窗口（长行多占时，不是均分）。"""
    events: list[tuple[float, float, str]] = []
    for seg in tl_segs:
        lines = scriptgen.narration_lines(narr_map[seg["id"]])
        if not lines:
            continue
        a0 = seg["start"] + seg["audio_in"]
        a1 = a0 + seg["audio_duration"]
        total = sum(max(1, len(ln)) for ln in lines)
        t = a0
        for i, ln in enumerate(lines):
            end = a1 if i == len(lines) - 1 else min(a1, t + (a1 - a0) * len(ln) / total)
            events.append((t, max(end, t + 0.4), ln))
            t = end
    return events


def build_ass(pid: str, tl: dict) -> Path:
    script = scriptgen.load_script(pid)
    nar = {s["id"]: s["narration"] for s in script["segments"]}
    lines = [f"Dialogue: 0,{_ts(s0)},{_ts(s1)},News,,0,0,0,,{_ass_escaped(ln)}"
             for s0, s1, ln in subtitle_events(nar, tl["segments"])]
    ass = store.project_dir(pid) / "output" / "subs.ass"
    ass.parent.mkdir(exist_ok=True)
    ass.write_text(ASS_HEADER.format(w=tl["width"], h=tl["height"],
                                     size=ASS_SIZE,
                                     mv=int(tl["height"] * ASS_MARGIN_RATIO))
                   + "\n".join(lines) + "\n", encoding="utf-8")
    return ass


def _render_clip(png: str, length: float, out: Path, fps: int,
                 kind: str = "item", focus: tuple | None = None) -> Path:
    """单段动效（见模块 docstring）。kind: hook/map-item/headline/outro。"""
    frames = max(2, int(length * fps))
    if kind == "hook":
        # 台标起幅：1 秒内 1.05→1.00 定机位
        z = f"max(1.001,1.05-0.05*min(on/{max(1, int(fps))},1))"
        x, y = "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"
    elif kind == "map" and focus:
        # 推向焦点标记（fx/fy 为焦点在卡面的比例坐标）
        z = f"1+0.05*on/{frames}"
        x = f"(iw-iw/zoom)*{focus[0]:.4f}"
        y = f"(ih-ih/zoom)*{focus[1]:.4f}"
    elif kind == "outro":
        z, x, y = "1.001", "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"
    else:
        # 标题/正文卡：1.08 定 zoom，0.6s 短促滑入后停住
        in_f = max(1, int(fps * 0.6))
        z = "1.08"
        x = f"(iw-iw/zoom)*(0.36+0.14*min(on/{in_f},1))"
        y = "(ih-ih/zoom)/2"
    vf = (f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s=1920x1080:fps={fps}")
    if kind == "outro":
        vf += f",fade=t=out:st={max(0.0, length - 0.4):.2f}:d=0.4"
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

    # 1) 逐段视频片段（断点续跑：卡或动效参数变了就重渲）
    card_entries = _load_cards(pid)
    cards = {c["id"]: c["png"] for c in card_entries}
    focuses = {c["id"]: tuple(c["focus"]) for c in card_entries if c.get("focus")}
    clip_paths = []
    for seg in tl["segments"]:
        kind = "hook" if seg["kind"] == "hook" else \
            "outro" if seg["kind"] == "outro" else "item"
        focus = focuses.get(seg["id"])
        if kind == "item":
            kind = "map" if focus else "headline"
        cp = clips_dir / f"{seg['id']}.mp4"
        stale = cp.exists() and Path(cards[seg["id"]]).stat().st_mtime > cp.stat().st_mtime
        if not cp.exists() or stale:          # 卡片更新过 → 片段作废重渲
            if cp.exists():
                cp.unlink()
            _render_clip(cards[seg["id"]], seg["length"], cp, tl["fps"],
                         kind=kind, focus=focus)
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

    # 4) 封面：独立 16:9 主标题卡（不是片头卡缩放）
    from src import cards as cards_mod
    cover = cards_mod.make_cover(pid)
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
