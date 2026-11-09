# -*- coding: utf-8 -*-
"""配音：cosy(可选批量) → edge-tts(免费默认) → zhipu cogtts → 报错停线。

质量闸门沿 see-china 惯例：神经后端全部不可用时抛错，绝不放机械音上线。
逐段合成 audio/segNN.wav（44.1k mono），断点续跑按文件存在跳过。
"""
import asyncio
import subprocess
from pathlib import Path

import edge_tts
import requests

from src import ffmpeg, scriptgen, store
from src.config import api_keys, load_config

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
    async def run():
        await edge_tts.Communicate(text, voice, rate=rate).save(str(out))
    asyncio.run(run())
    return out


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
        dst = audio_dir / f"{s['id']}.wav"
        outs.append(dst)
        if dst.exists():
            continue
        mp3 = audio_dir / f"{s['id']}_cosy.wav"
        jobs.append({**base, "text": s["narration"],
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


def voice(pid: str) -> dict:
    """全稿配音。返回 {segments: [{id, wav, duration}], backend}。"""
    script = scriptgen.load_script(pid)
    cfg = load_config()
    vcfg = cfg["voice"]
    audio_dir = store.project_dir(pid) / "audio"
    audio_dir.mkdir(exist_ok=True)
    key = api_keys()["zhipu"]
    backend = ""

    if vcfg.get("cosy", {}).get("enable") and cosy_ready():
        try:
            _synth_cosy_batch(script["segments"], audio_dir, vcfg["cosy"])
            backend = "cosy"
        except RuntimeError:
            backend = ""                                  # 降级逐段链路

    for s in script["segments"]:
        wav = audio_dir / f"{s['id']}.wav"
        if wav.exists():
            continue
        if backend == "cosy":
            src = audio_dir / f"{s['id']}_cosy.wav"   # 批量产物 → 统一规范 wav
            if not src.exists():
                raise RuntimeError(f"段 {s['id']} cosy 产物缺失: {src}")
            _to_wav(src, wav)
            continue
        mp3 = audio_dir / f"{s['id']}.mp3"
        if not mp3.exists():
            errs = []
            try:
                _synth_edge(s["narration"], mp3,
                            vcfg["edge_voice"], vcfg.get("edge_rate", "+0%"))
                backend = backend or "edge"
            except Exception as e:
                errs.append(f"edge: {type(e).__name__}: {str(e)[:80]}")
                if key:
                    try:
                        _synth_zhipu(s["narration"], mp3, key,
                                     vcfg.get("zhipu_model", "cogtts"),
                                     vcfg.get("zhipu_voice", "tongtong"))
                        backend = backend or "zhipu"
                    except Exception as e2:
                        errs.append(f"zhipu: {type(e2).__name__}: {str(e2)[:80]}")
            if not mp3.exists():
                raise RuntimeError(f"段 {s['id']} 配音全后端失败：{'；'.join(errs)}")
        _to_wav(mp3, wav)

    segs_out = []
    for s in script["segments"]:
        wav = audio_dir / f"{s['id']}.wav"
        segs_out.append({"id": s["id"], "wav": str(wav),
                         "duration": round(ffmpeg.probe_duration(wav), 3)})
    result = {"backend": backend or "cache", "segments": segs_out}
    from src.jsonio import save_json
    save_json(result, store.project_dir(pid) / "voice.json")
    store.mark_stage(pid, "voice", f"{result['backend']} / {len(segs_out)} 段")
    return result
