# -*- coding: utf-8 -*-
"""流水线编排：script → hammer → voice → cards → render → qc。

断点续跑：manifest 里 done 的阶段自动跳过；任一阶段重做用 cli redo。
锤稿拒稿（rejected）即刻停线——"产线可以断，烂片不能发"。
"""
from src import cards, hammer, narrator, qc as qc_mod, renderer, scriptgen, store


class PipelineError(RuntimeError):
    pass


def make(pid: str, offline: bool = False) -> dict:
    """跑完所有未完成阶段。offline 强制模板降级（联调/无网用）。"""
    import os
    if offline:
        os.environ["NEWS_OFFLINE"] = "1"
    steps = []

    if not store.stage_done(pid, "script"):
        scriptgen.build_script(pid)
        steps.append("script")
    if not store.stage_done(pid, "hammer"):
        report = hammer.hammer(pid)
        if report["status"] == "rejected":
            raise PipelineError(
                f"锤稿拒稿：条目余 {report['items_left']}，"
                f"问题：{[i['rule'] + ':' + i.get('hit', '') for i in report['issues']]}。"
                "请修订简报（剔除风险条目）后 redo script。")
        steps.append(f"hammer({report['status']})")
    if not store.stage_done(pid, "voice"):
        narrator.voice(pid)
        steps.append("voice")
    if not store.stage_done(pid, "render"):
        cards.render_cards(pid)
        renderer.render(pid)
        steps.append("render")
    if not store.stage_done(pid, "qc"):
        report = qc_mod.qc(pid)
        if not report["ok"]:
            raise PipelineError(f"QC 未过：{report['problems']}")
        steps.append("qc")
    from src import production_report
    production_report.build(pid)
    steps.append("report")
    return {"pid": pid, "steps": steps or ["全部阶段已完成（断点续跑）"]}
