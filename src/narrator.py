# -*- coding: utf-8 -*-
"""配音：cosy(可选批量) → edge-tts(免费默认) → zhipu cogtts → 报错停线。

质量闸门沿 see-china 惯例：神经后端全部不可用时抛错，绝不放机械音上线。
逐段合成 audio/segNN.wav（44.1k mono），断点续跑按文件存在跳过。

送进引擎的是同一事实的可念文本（停顿标点 + 数字分写）。锁定稿不改。
voice.json 记下这句 spoken，字幕跟这一次合成的词界走。
"""
import asyncio
import hashlib
import subprocess
from pathlib import Path

import edge_tts
import requests

from src import ffmpeg, scriptgen, store
from src.config import api_keys, load_config
from src.speakable import Speakable


def _audio_key(seg: dict) -> str:
    """缓存键含可念文本。稿子或念法变了就不再复用旧音频；两者都没变时键与原来相同。"""
    spoken = Speakable.text(seg["narration"])
    h = hashlib.md5(spoken.encode("utf-8")).hexdigest()[:8]
    return f"{seg['id']}_{h}"

ZHIPU_SPEECH_URL = "https://open.bigmodel.cn/api/paas/v4/audio/speech"

_COSY_ROOT = Path(__file__).resolve().parent.parent.parent / "cosyvoice"
_COSY_PY = _COSY_ROOT / ".venv" / "Scripts" / "python.exe"
_COSY_CLI = _COSY_ROOT / "synth_cli.py"
_COSY_MANIFEST = _COSY_ROOT / "_jobs_news_video.json"


def cosy_ready() -> bool:
    return _COSY_PY.exists() and _COSY_CLI.exists()


def _to_wav(src: Path, dst: Path) -> Path:
    r = ffmpeg.run([ffmpeg.ffmpeg_exe(), "-y", "-i", src, "-ar", "44100",
                    "-ac", "1", "-vn", dst], timeout=120)
    if not dst.exists() or dst.stat().st_size < 1000:
        raise RuntimeError(f"wav 转换失败: {r.stderr[:150]}")
    return dst


def _synth_edge(text: str, out: Path, voice: str, rate: str) -> Path:
    """同一条合成里留下 WordBoundary。offset 仍是引擎的 100 纳秒时钟。"""
    meta = Path(str(out) + ".boundaries.jsonl")

    async def run():
        await edge_tts.Communicate(
            text, voice, rate=rate, boundary="WordBoundary",
        ).save(str(out), str(meta))
    asyncio.run(run())
    words = []
    if meta.exists():
        words = scriptgen.Subtitles.words_from_jsonl(
            meta.read_text(encoding="utf-8"))
        meta.unlink()
    scriptgen.Subtitles.write_words(out, words)
    return out


def _carry_words(src: Path, dst: Path, scale: float = 1.0) -> list:
    """词级时间跟着实际播放的 wav 走。只在 atempo 真正改变时长时缩放。"""
    words = scriptgen.Subtitles.read_words(src)
    if not words:
        return []
    if abs(float(scale) - 1.0) > 1e-6:
        words = scriptgen.Subtitles.scale(words, scale)
    scriptgen.Subtitles.write_words(dst, words)
    return words


def _synth_zhipu(text: str, out: Path, key: str, model: str, voice: str) -> Path:
    r = requests.post(ZHIPU_SPEECH_URL,
                      headers={"Authorization": f"Bearer {key}"},
                      json={"model": model, "input": text, "voice": voice},
                      timeout=120)
    if r.status_code != 200 or len(r.content) < 2000:
        raise RuntimeError(f"zhipu tts failed: {r.status_code} {r.text[:120]}")
    out.write_bytes(r.content)
    return out


def _synth_cosy_batch(segs: list, audio_dir: Path, cosy_cfg: dict) -> list[Path]:
    """CosyVoice2 批量合成，一次加载模型全部出片。任一段失败即抛错降级。"""
    mode = cosy_cfg.get("mode", "zero_shot")
    if mode == "instruct2":
        base = {"mode": "instruct2",
                "prompt_wav": str(_COSY_ROOT / cosy_cfg["prompt_wav"]),
                "instruct": cosy_cfg.get("instruct", "")}
    else:
        base = {"spk_id": cosy_cfg.get("spk", "")}
    jobs = []
    outs = []
    for s in segs:
        dst = audio_dir / f"{_audio_key(s)}.wav"
        outs.append(dst)
        if dst.exists():
            continue
        mp3 = audio_dir / f"{_audio_key(s)}_cosy.wav"
        jobs.append({**base, "text": Speakable.text(s["narration"]),
                     "out": str(mp3.resolve())})
    if jobs:
        _COSY_MANIFEST.write_text(
            '{"jobs": ' + __import__("json").dumps(jobs, ensure_ascii=False) + "}",
            encoding="utf-8")
        r = subprocess.run([str(_COSY_PY), str(_COSY_CLI), str(_COSY_MANIFEST)],
                           capture_output=True, text=True, timeout=3600,
                           cwd=str(_COSY_ROOT))
        missing = [j["out"] for j in jobs if not Path(j["out"]).exists()]
        if missing or r.returncode != 0:
            raise RuntimeError(f"cosy batch incomplete: missing={missing} "
                               f"err={r.stderr.strip()[:200]}")
    return outs


def _speak(text: str, mp3: Path, vcfg: dict, key: str) -> str:
    errs = []
    try:
        _synth_edge(text, mp3, vcfg["edge_voice"], vcfg.get("edge_rate", "+0%"))
        return "edge"
    except Exception as e:
        errs.append(f"edge: {type(e).__name__}: {str(e)[:80]}")
        if key:
            try:
                _synth_zhipu(text, mp3, key, vcfg.get("zhipu_model", "cogtts"),
                             vcfg.get("zhipu_voice", "tongtong"))
                return "zhipu"
            except Exception as e2:
                errs.append(f"zhipu: {type(e2).__name__}: {str(e2)[:80]}")
    raise RuntimeError(f"配音失败：{'；'.join(errs)}")


def _fit_window(src: Path, dst: Path, window: float) -> float:
    """一句配音长过这一拍时只加速，不改字。加速上限 2 倍。"""
    dur = ffmpeg.probe_duration(src)
    limit = max(0.35, window - 0.05)
    if dur <= limit + 1e-3:
        if src.resolve() != dst.resolve():
            dst.write_bytes(src.read_bytes())
        return dur
    tempo = min(2.0, dur / limit)
    r = ffmpeg.run([ffmpeg.ffmpeg_exe(), "-y", "-i", str(src),
                    "-filter:a", f"atempo={tempo:.4f}",
                    "-ar", "44100", "-ac", "1", str(dst)], timeout=120)
    if r.returncode != 0 or not dst.exists() or dst.stat().st_size < 1000:
        raise RuntimeError(f"口播压进时码失败: {r.stderr[:150]}")
    return ffmpeg.probe_duration(dst)


def _concat_wavs(paths: list[Path], dst: Path) -> float:
    if len(paths) == 1:
        if paths[0].resolve() != dst.resolve():
            dst.write_bytes(paths[0].read_bytes())
        return ffmpeg.probe_duration(dst)
    lst = dst.with_suffix(".concat.txt")
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in paths),
                   encoding="utf-8")
    r = ffmpeg.run([ffmpeg.ffmpeg_exe(), "-y", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c", "copy", str(dst)], timeout=120)
    if r.returncode != 0 or not dst.exists():
        raise RuntimeError(f"口播拼接失败: {r.stderr[:150]}")
    return ffmpeg.probe_duration(dst)


def _voice_locked(seg: dict, audio_dir: Path, vcfg: dict, key: str,
                  backend: str) -> tuple[dict, str]:
    """按字幕拍合成。duration 只计说话，不含拍与拍之间的静音。"""
    cues_out = []
    pieces = []
    for i, cue in enumerate(seg["cues"]):
        spoken_line = Speakable.text(cue["text"])
        h = hashlib.md5(spoken_line.encode("utf-8")).hexdigest()[:8]
        fitted = audio_dir / f"{seg['id']}_c{i}_{h}.wav"
        window = float(cue["end"]) - float(cue["start"])
        mp3 = audio_dir / f"{seg['id']}_c{i}_{h}.mp3"
        if not fitted.exists() or fitted.stat().st_size < 1000:
            raw = audio_dir / f"{seg['id']}_c{i}_{h}.raw.wav"
            if not raw.exists():
                if not mp3.exists():
                    backend = _speak(spoken_line, mp3, vcfg, key) or backend
                _to_wav(mp3, raw)
            raw_dur = ffmpeg.probe_duration(raw)
            fit_dur = _fit_window(raw, fitted, window)
            scale = 1.0
            if raw_dur > 0 and abs(fit_dur - raw_dur) > 0.03:
                scale = fit_dur / raw_dur
            _carry_words(mp3 if scriptgen.Subtitles.read_words(mp3) else raw,
                         fitted, scale)
        dur = round(ffmpeg.probe_duration(fitted), 3)
        spoken = {"at": float(cue["start"]), "wav": str(fitted),
                  "duration": dur, "spoken": spoken_line}
        words = scriptgen.Subtitles.read_words(fitted)
        if words:
            spoken["words"] = words
            spoken["timing"] = scriptgen.Subtitles.TIMING
        cues_out.append(spoken)
        pieces.append(fitted)
    wav = audio_dir / f"{_audio_key(seg)}.wav"
    duration = round(_concat_wavs(pieces, wav), 3)
    return ({"id": seg["id"], "wav": str(wav), "duration": duration,
             "cues": cues_out}, backend or "edge")


def voice(pid: str) -> dict:
    """全稿配音。返回 {segments: [{id, wav, duration}], backend}。"""
    script = scriptgen.load_script(pid)
    cfg = load_config()
    vcfg = cfg["voice"]
    audio_dir = store.project_dir(pid) / "audio"
    audio_dir.mkdir(exist_ok=True)
    key = api_keys()["zhipu"]
    backend = ""
    has_cues = any(s.get("cues") for s in script["segments"])

    if (not has_cues) and vcfg.get("cosy", {}).get("enable") and cosy_ready():
        try:
            _synth_cosy_batch(script["segments"], audio_dir, vcfg["cosy"])
            backend = "cosy"
        except RuntimeError:
            backend = ""                                  # 降级逐段链路

    for s in script["segments"]:
        if s.get("cues"):
            continue
        wav = audio_dir / f"{_audio_key(s)}.wav"
        if wav.exists():
            continue
        spoken_line = Speakable.text(s["narration"])
        if backend == "cosy":
            src = audio_dir / f"{_audio_key(s)}_cosy.wav"  # 批量产物 → 统一规范 wav
            if not src.exists():
                raise RuntimeError(f"段 {s['id']} cosy 产物缺失: {src}")
            _to_wav(src, wav)
            continue
        mp3 = audio_dir / f"{_audio_key(s)}.mp3"
        if not mp3.exists():
            errs = []
            try:
                _synth_edge(spoken_line, mp3,
                            vcfg["edge_voice"], vcfg.get("edge_rate", "+0%"))
                backend = backend or "edge"
            except Exception as e:
                errs.append(f"edge: {type(e).__name__}: {str(e)[:80]}")
                if key:
                    try:
                        _synth_zhipu(spoken_line, mp3, key,
                                     vcfg.get("zhipu_model", "cogtts"),
                                     vcfg.get("zhipu_voice", "tongtong"))
                        backend = backend or "zhipu"
                    except Exception as e2:
                        errs.append(f"zhipu: {type(e2).__name__}: {str(e2)[:80]}")
            if not mp3.exists():
                raise RuntimeError(f"段 {s['id']} 配音全后端失败：{'；'.join(errs)}")
        _to_wav(mp3, wav)
        _carry_words(mp3, wav, 1.0)

    segs_out = []
    for s in script["segments"]:
        if s.get("cues"):
            item, backend = _voice_locked(s, audio_dir, vcfg, key, backend)
            segs_out.append(item)
            continue
        wav = audio_dir / f"{_audio_key(s)}.wav"
        item = {"id": s["id"], "wav": str(wav),
                "duration": round(ffmpeg.probe_duration(wav), 3),
                "spoken": Speakable.text(s["narration"])}
        words = scriptgen.Subtitles.read_words(wav)
        if words:
            item["words"] = words
            item["timing"] = scriptgen.Subtitles.TIMING
        segs_out.append(item)
    result = {"backend": backend or "cache", "segments": segs_out}
    from src.jsonio import save_json
    save_json(result, store.project_dir(pid) / "voice.json")
    store.mark_stage(pid, "voice", f"{result['backend']} / {len(segs_out)} 段")
    return result
