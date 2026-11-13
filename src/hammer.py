# -*- coding: utf-8 -*-
"""锤稿：script.json 过红线 + 信源/涉华锚点检查 → hammer.json。

处理策略（宁缺毋滥，与任务D「无事不硬凑」一致）：
- BLOCK 命中：GLM 稿走一次定向重写；模板稿直接剔除该条目段。仍不过 → 拒稿。
- WARN 命中：记录 issue，人工审片时裁量，不拦产线。
- 条目段缺信源徽标 / 涉华段缺官方锚点：同 BLOCK 处理。
全稿只剩开场+收尾（条目清零）→ 拒稿：本期无可发内容。
"""
from src import redlines, scriptgen, store
from src.config import api_keys, load_config
from src.glm_client import chat_json_ex
from src.jsonio import load_json, save_json

_REPAIR_PROMPT = """下面是一份新闻快讯逐字稿（JSON）。其中部分段落命中了红线，请只修改
这些段落（保持其余段落逐字不动，保持 JSON 结构与卡片字段完整），重写时遵守红线：
{rules}

命中的问题（seg_id -> 问题）：
{issues}

原稿：
{script}

只输出修改后的完整 JSON。"""


def _check_segment(seg: dict, item_sources: dict, manual: bool = False) -> list[dict]:
    issues = redlines.check_text(seg.get("narration", ""))
    if seg.get("kind") == "item" and not manual:
        # 信源徽标检查仅约束 AI 稿；人工稿的信源表述在行文里，只守硬红线
        ref = seg.get("item_ref", 0)
        tier = item_sources.get(ref, "")
        if tier != "单方声称待核实" and not redlines.check_badge(seg["narration"]):
            issues.append({"rule": "RL-SRC", "level": "block", "hit": "缺信源徽标"})
        if tier == "单方声称待核实" and "尚待核实" not in seg["narration"]:
            issues.append({"rule": "RL-UNVERIF", "level": "block",
                           "hit": "待核实信源未标注「尚待核实」"})
    if seg.get("kind") == "china" and not redlines.check_china_anchor(seg["narration"]):
        issues.append({"rule": "RL-CHINA", "level": "block",
                       "hit": "涉华段缺官方口径锚点"})
    return issues


def hammer(pid: str) -> dict:
    script = scriptgen.load_script(pid)
    brief = load_json(store.project_dir(pid) / "briefing.json") or {}
    refs = scriptgen.valid_refs(brief)   # 有效条目 ref 集合（与 scriptgen 同一定义）
    items = {i + 1: it for i, it in enumerate(brief.get("items", []))}
    item_sources = {k: (v.get("sources") or [{}])[0].get("tier", "")
                    for k, v in items.items()}
    cfg = load_config()

    rules_txt = "\n".join(f"- {k}: {v}" for k, v in redlines.BLOCK_PATTERNS.items())
    rules_txt += (
        "\n- RL-SRC: 每条动态口播必须念出信源分级，两种写法任选其一："
        "原样念徽标「【官方】…」，或口播化「信源级别为官方」"
        "\n- RL-CHINA: 涉华段必须含官方口径锚点句，如「中国外交部此前表示」"
        "「中国驻塞尔维亚使馆称」")

    all_issues: list[dict] = []
    repaired = False
    manual = script.get("meta", {}).get("mode") == "manual"
    for attempt in range(2):
        flagged: dict[str, list] = {}
        all_issues = []
        for seg in script["segments"]:
            iss = _check_segment(seg, item_sources, manual=manual)
            if iss:
                flagged[seg["id"]] = iss
                all_issues.extend([dict(i, seg=seg["id"]) for i in iss])
        if not flagged:
            break
        block_hits = [i for i in all_issues if i["level"] == "block"]
        if not block_hits:
            break                                    # 只有 WARN：人工裁量
        if script["meta"]["mode"] == "glm" and attempt == 0 and not repaired:
            key = api_keys()["zhipu"]
            iss_txt = "\n".join(f"- {i['seg']}: {i['rule']} -> 「{i['hit']}」"
                                for i in block_hits)
            obj, _ = chat_json_ex(
                key, _REPAIR_PROMPT.format(rules=rules_txt, issues=iss_txt,
                                           script=_dump(script)),
                model=cfg["glm"]["model"], temperature=0.3,
                max_tokens=cfg["glm"]["max_tokens"], timeout=cfg["glm"]["timeout_s"],
                required_keys=("title", "segments"))
            if obj is not None and scriptgen._validate(obj, refs):
                script["segments"] = obj["segments"]
                script["title"] = obj.get("title", script["title"])
                script["meta"]["mode"] = "glm_repaired"
                repaired = True
                continue
        # 模板稿或重写失败：按「宁缺毋滥」剔除——条目段剔除；
        # china/mainline 是辅助段，命中也剔除而不是毙整期
        bad_ids = {s["id"] for s in script["segments"]
                   if flagged.get(s["id"])
                   and s.get("kind") in ("item", "china", "mainline")}
        dropped_refs = sorted({seg.get("item_ref") for seg in script["segments"]
                               if seg["id"] in bad_ids
                               and seg.get("kind") == "item"})
        dropped_aux = sorted({seg["kind"] for seg in script["segments"]
                              if seg["id"] in bad_ids
                              and seg.get("kind") in ("china", "mainline")})
        script["segments"] = [s for s in script["segments"] if s["id"] not in bad_ids]
        drops = {"rule": "DROP-SEG", "level": "info",
                 "hit": f"剔除条目 {dropped_refs} / 辅助段 {dropped_aux}"}
        # 关键：剔除后对剩余段落重判，丢掉已剔除段落的旧 issue——
        # 否则残留的 block 会把本可发布的稿子误判成拒稿
        all_issues = [drops]                        # 保留剔除记录供审计
        for seg in script["segments"]:
            for i in _check_segment(seg, item_sources):
                all_issues.append(dict(i, seg=seg["id"]))
        break

    # hook 条数口径：GLM 偶发把条数念错（如 6 条念成 5 条），最小替换修正
    hook = next((s for s in script["segments"] if s.get("kind") == "hook"), None)
    if hook:
        n_all = sum(1 for s in script["segments"] if s.get("kind") == "item")
        fixed, note = redlines.fix_hook_count(hook.get("narration", ""), n_all)
        if note:
            hook["narration"] = fixed
            all_issues.append({"rule": "RL-COUNT", "level": "info",
                               "hit": note, "seg": hook.get("id", "seg01")})

    # 事实一致性核验（数字/日期须见于简报、待核实须对冲、声明保真、新实体）。
    # 人工稿没有简报基线 → 跳过数字/日期比对，改走来源可追溯检查（RL-SRC-M）
    from src import factcheck
    if brief.get("items"):
        all_issues.extend(factcheck.check_script(brief, script))
        all_issues.extend(factcheck.check_attribution(brief, script))
        all_issues.extend(factcheck.check_entities(brief, script))
    if manual:
        all_issues.extend(factcheck.check_manual_sources(script))

    n_items_left = sum(1 for s in script["segments"] if s.get("kind") == "item")
    status = "ok"
    if n_items_left == 0:
        status = "rejected"
    elif any(i["level"] == "block" for i in all_issues):
        status = "rejected"
    elif all_issues:
        status = "fixed" if repaired else "warned"

    for i, s in enumerate(script["segments"], 1):    # 重排序号
        s["id"] = f"seg{i:02d}"
    report = {"status": status, "checked_at": store.now(),
              "items_left": n_items_left, "issues": all_issues}
    save_json(script, store.project_dir(pid) / "script.json")
    save_json(report, store.project_dir(pid) / "hammer.json")
    store.mark_stage(pid, "hammer",
                     f"{status} / 条目余 {n_items_left} / 问题 {len(all_issues)}")
    return report


def _dump(script: dict) -> str:
    import json as _j
    return _j.dumps({"title": script["title"], "segments": script["segments"]},
                    ensure_ascii=False)


def load_report(pid: str) -> dict:
    r = load_json(store.project_dir(pid) / "hammer.json")
    if not r:
        raise RuntimeError(f"hammer.json 缺失: {pid}")
    return r
