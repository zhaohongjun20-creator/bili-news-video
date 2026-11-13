# -*- coding: utf-8 -*-
"""环境体检：doctor 子命令。hard=必须修，soft=有降级路径可容忍。"""
import shutil
import sys

from src import narrator
from src.config import api_keys, load_config
from src.ffmpeg import ffmpeg_exe, ffprobe_exe


def doctor(_cfg: dict | None = None) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    cfg = load_config()

    exe = sys.executable.lower()
    if "libreoffice" in exe:
        rows.append(("hard", "python 解释器",
                     f"漂移到 LibreOffice（{exe[:52]}）——请用 Python314"))
    else:
        rows.append(("ok", "python 解释器", exe[:60]))

    if shutil.which("ffmpeg"):
        rows.append(("ok", "ffmpeg", "PATH 可用"))
    else:
        rows.append(("ok", "ffmpeg", f"imageio 兜底: {ffmpeg_exe()[:48]}…"))

    if ffprobe_exe():
        rows.append(("ok", "ffprobe", "PATH 可用（规格/时长探测走主路）"))
    else:
        rows.append(("soft", "ffprobe",
                     "缺失：probe 降级为 ffmpeg -i stderr 解析"
                     "（时长/分辨率/帧率，QC 精度略降但可用）"))

    from pathlib import Path
    for f in ("msyh.ttc", "msyhbd.ttc"):
        p = Path(r"C:\Windows\Fonts") / f
        rows.append(("ok" if p.exists() else "hard", f"字体 {f}",
                     "存在" if p.exists() else "缺失：卡面中文会乱码"))

    try:
        import edge_tts  # noqa: F401
        rows.append(("ok", "edge-tts", "可导入（默认配音后端，需联网）"))
    except ImportError:
        rows.append(("hard", "edge-tts", "未安装：pip install edge-tts"))

    if narrator.cosy_ready():
        rows.append(("ok", "cosyvoice", f"就绪（enable={cfg['voice']['cosy'].get('enable')}）"))
    else:
        rows.append(("soft", "cosyvoice", "环境不在（可选，缺省走 edge）"))

    if api_keys()["zhipu"]:
        rows.append(("ok", "ZHIPU_API_KEY", "已配置（简报结构化+逐字稿主路）"))
    else:
        rows.append(("soft", "ZHIPU_API_KEY", "未配置：ingest/scriptgen 走模板降级"))

    import edge_tts  # noqa
    rows.append(("ok", "edge 音色", cfg["voice"]["edge_voice"]))
    return rows
