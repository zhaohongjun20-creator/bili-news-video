# -*- coding: utf-8 -*-
"""本地端到端回归：演示简报 → 全链 → 真实 MP4 → QC/报告断言。

- 素材固定用 briefings/sample-示例简报-演示数据.md（文件头自带「勿直接发布」）
- 配音注入确定性静音轨（离线可跑）；卡面/渲染/字幕/QC/报告全走真实代码
- 结束自动 reject（演示数据，绝不进入投稿流程）
运行：python tools/regression.py   （或 RUN_REGRESSION=1 pytest）
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["NEWS_OFFLINE"] = "1"                  # 强制模板/降级路径，确定性

from src import (cards, hammer, ingest, production_report, qc as qc_mod,  # noqa: E402
                 renderer, scriptgen, store)
from src.config import load_config  # noqa: E402
from src.ffmpeg import ffmpeg_exe, run  # noqa: E402
from src.jsonio import save_json  # noqa: E402


def main() -> int:
    print("== bili-news-video 端到端回归（演示数据，不投稿）==")
    pid, brief = ingest.ingest(
        ROOT / "briefings" / "sample-示例简报-演示数据.md", label="回归测试")
    print(f"[1/7] ingest: {pid}（{brief.get('ingest_mode')}，{len(brief['items'])} 条）")

    scriptgen.build_script(pid)
    script = scriptgen.load_script(pid)
    print(f"[2/7] script: {script['meta']['mode']} / {len(script['segments'])} 段")

    rep = hammer.hammer(pid)
    assert rep["status"] != "rejected", f"锤稿拒稿: {rep['issues']}"
    print(f"[3/7] hammer: {rep['status']} / 条目余 {rep['items_left']}")

    # 确定性低音量正弦配音（替代 TTS）：响度/静音指标与真实片同轨可比
    script = scriptgen.load_script(pid)
    audio_dir = store.project_dir(pid) / "audio"
    segs_out = []
    for s in script["segments"]:
        dur = max(2.0, round(len(s["narration"]) / 4.5, 3))
        wav = audio_dir / f"{s['id']}_reg.wav"
        run([ffmpeg_exe(), "-y", "-f", "lavfi", "-i",
             "sine=frequency=200:sample_rate=44100:duration=" + f"{dur:.3f}",
             "-af", "volume=0.1", str(wav)], timeout=120)
        assert wav.exists()
        segs_out.append({"id": s["id"], "wav": str(wav), "duration": dur})
    save_json({"backend": "regression-silence", "segments": segs_out},
              store.project_dir(pid) / "voice.json")
    store.mark_stage(pid, "voice", "regression-silence")
    print(f"[4/7] voice: 低音量正弦轨 {len(segs_out)} 段（离线确定性）")

    cards.render_cards(pid)
    renderer.render(pid)
    print("[5/7] render: final.mp4 完成")

    report = qc_mod.qc(pid)
    assert report["ok"], f"QC 未过: {report['problems']}"
    print(f"[6/7] qc: PASS / {report['duration']:.1f}s")

    pr = production_report.build(pid)
    assert not pr["blockers"], f"报告阻断项: {pr['blockers']}"
    review_st = (store.project_dir(pid) / "review.json")
    from src import review as review_mod
    from src.jsonio import load_json
    review_mod.reject(pid, "回归测试产物：演示数据，禁止投稿")
    print(f"[7/7] report: {pr['verdict']}（审片 {pr['review_status']}，已自动退稿防误投）")

    final = store.project_dir(pid) / "output" / "final.mp4"
    assert final.exists() and final.stat().st_size > 100_000
    print(f"== 回归通过：{final}（{final.stat().st_size // 1024} KB）==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
