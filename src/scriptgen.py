# -*- coding: utf-8 -*-
"""逐字稿生成：briefing.json → script.json（口播文本 + 每段卡片字段）。

主路：GLM 一次生成全稿（含卡片字段）。降级：确定性模板拼稿——新闻快讯
结构固定（开场→逐条→涉华→主线→收尾），模板稿可用，只是不如 GLM 灵动。
口播语速按 4.5 字/秒估算段时长，配音后以实测音频时长为准。
"""
import datetime as _dt
import json
import re
from pathlib import Path

from src import ingest, redlines, store
from src.config import api_keys, load_config
from src.glm_client import chat_json_ex
from src.jsonio import load_json, save_json

SEC_PER_CHAR = 1 / 4.5

_PROMPT = """你是中文军事地缘快讯栏目的主编。栏目「{show}」，只讲"发生了什么"和
"各方怎么说"，不站队、不评论、不预测。语速约 4.5 字/秒，全片目标 {target_s} 秒左右。

红线（违反即废稿）：
1. 不出现：抗议/游行/示威/罢工/骚乱/镇压/警力部署等社会运动叙事；伤亡画面化描写。
2. 不做预测（"将会引发/必将/恐怕会"一律改成"各方关注/有待观察"）。
3. 不站队定性；涉华内容必须以官方口径锚定（"中方表示/中国外交部"句式）。
4. 每条动态口播里必须出现信源徽标【官方】/【主流媒体】/【区域专家】/【单方声称待核实】；
   待核实信源口播必须说"据某方单方面说法，尚待核实"。
5. 数字加"约"或注明机构；英里/海里必须换算成"约合X公里"。

结构要求（依次，段落数量必须对齐）：
- hook：开场钩子（今天几条、最有钩子的一条一句话预告），恰好 1 段
- 简报里每一条动态单独一段（kind=item）：3 条动态 = 3 个 item 段，一条都不能丢、
  不能合并。每段：发生了什么(2句) + 信源分级念出来 + 各方说法/棋盘含义(2句)
- 若任一条的 china_link 非空：恰好 1 段涉华关联（kind=china，官方口径锚定）
- 若 mainlines 非空：恰好 1 段主线追踪（kind=mainline，多条主线并成一句）
- outro：收尾（简短道别+下期见，不加任何立场表态），恰好 1 段

卡片字段：item 段的 card.headline 必须是本条标题的压缩（≤18字）；
map 卡用于普通条目、quote 卡仅用于「待核实」条目。

item 段口播示范（信源分级必须念出来，每段 60-100 字）：
"第一条，塞尔维亚与美国签署关键矿产合作备忘录。据塞尔
维亚政府公告，协议涉及锂矿勘探许可框架。信源级别为官方。棋盘上看，西方
在俄罗斯传统势力范围再落一子，贝尔格莱德继续左右逢源。"

只输出 JSON：
{{
  "title": "本期标题（含日期，格式：{show} YYYY年M月D日：<主线钩子>）",
  "segments": [
    {{"kind": "hook|item|china|mainline|outro",
      "narration": "口播文本，口语化短句，不要书面长句",
      "item_ref": 对应简报条目的 ref 字段（简报 items 里给出的 ref，1起），非条目段为0,
      "card": {{"type": "hook|headline|quote|map|china|mainline|outro",
                "headline": "卡面大字（≤18字）",
                "sub": "卡面副题（≤40字，可为空串）",
                "badge": "【官方】等徽标，非条目段为空串",
                "lines": ["要点/大数字，最多3条，可为空数组"]}}}}
  ]
}}

简报（JSON）：
{brief}"""


def _estimate_s(text: str) -> float:
    return round(len(text) * SEC_PER_CHAR, 2)


def _card(kind: str, it: dict | None) -> dict:
    """模板稿的卡片字段。"""
    if kind == "hook":
        return {"type": "hook", "headline": "", "sub": "", "badge": "", "lines": []}
    if it is None:
        return {"type": {"china": "china", "mainline": "mainline",
                         "outro": "outro"}.get(kind, "headline"),
                "headline": "", "sub": "", "badge": "", "lines": []}
    tier = (it.get("sources") or [{}])[0].get("tier", "主流媒体")
    return {"type": "map" if tier != "单方声称待核实" else "quote",
            "headline": it.get("title", "")[:18],
            "sub": (it.get("summary", "") or "")[:40],
            "badge": f"【{tier}】",
            "lines": ([it.get("chess", "")[:30]] if it.get("chess") else [])}


def valid_refs(brief: dict) -> set[int]:
    """有效条目 ref 集合：简报条目序号(1起)剔除 excluded_refs。

    scriptgen 与 hammer 共用这一份定义——item 段的 item_ref 全链都以
    简报原始序号为准，避免剔除条目后各环节序号错位。
    """
    excluded = set(brief.get("excluded_refs", []))
    return {i for i in range(1, len(brief.get("items", [])) + 1)} - excluded


def _template_script(brief: dict, cfg: dict) -> dict:
    """无 GLM 降级：确定性拼稿。句子模板本身就按红线设计。"""
    show = brief.get("show_label") or cfg["show"]["name"]
    d = _dt.date.fromisoformat(brief["date"])
    kept = [(i, it) for i, it in enumerate(brief["items"], 1)
            if i in valid_refs(brief)]              # item_ref 用原始 ref，不重排
    n = len(kept)
    segs: list[dict] = []
    hook = (f"{d.month}月{d.day}日，{show}，本期{n}条动态。今天带你看"
            + (kept[0][1].get("title", "最新动态") if n else "主线动向")
            + "。只讲事实和各方说法。")
    segs.append({"kind": "hook", "narration": hook, "item_ref": 0,
                 "card": _card("hook", None)})
    for i, it in kept:
        tier = (it.get("sources") or [{}])[0].get("tier", "主流媒体")
        title = re.sub(r"【[^】]*】", "", it.get("title", "")).strip()
        parts = [f"第{i}条，{title}。"]
        if tier == "单方声称待核实":
            parts.append(f"据单方面说法：{it.get('summary', '')}，尚待核实。")
        else:
            parts.append(f"{it.get('summary', '')}。信源级别【{tier}】。")
        if it.get("chess"):
            parts.append(f"棋盘上看，{it.get('chess')}")
        segs.append({"kind": "item", "narration": "".join(parts), "item_ref": i,
                     "card": _card("item", it)})
    if brief.get("china_link") or any(it.get("china_link") for it in brief["items"]):
        cl = next((it.get("china_link") for it in brief["items"] if it.get("china_link")),
                  brief.get("china_link", ""))
        segs.append({"kind": "china",
                     "narration": f"对华关联方面，{cl}。以上以中国外交部及官方渠道"
                                  "最终表述为准。",
                     "item_ref": 0, "card": _card("china", None)})
    if brief.get("mainlines"):
        ml = "；".join(brief["mainlines"])
        segs.append({"kind": "mainline",
                     "narration": f"主线追踪：{ml}。这几条线的后续，我们持续盯。",
                     "item_ref": 0, "card": _card("mainline", None)})
        segs[-1]["card"]["lines"] = [m[:30] for m in brief["mainlines"][:4]]
    segs.append({"kind": "outro",
                 "narration": f"以上是本期{show}，我们下期见。",
                 "item_ref": 0, "card": _card("outro", None)})
    title = f"{show} {d.year}年{d.month}月{d.day}日"
    return {"title": title, "segments": segs,
            "warnings": ["模板降级稿：文案为确定性拼接，可直接用但较平"]}


def _validate(obj: dict, refs: set[int]) -> bool:
    """结构校验（精确覆盖）：hook 开场、outro 收尾、item 段与有效条目
    （excluded_refs 剔除后的 ref 集合）严格一一对应——
    ① 每段必须是 dict；② hook 恰好 1 个且在首段、outro 恰好 1 个且在末段；
    ③ item_ref 必须是整数（禁布尔——Python 里 {True}=={1} 会漏网）、
    唯一且恰好全覆盖 refs；④ item 段 card.headline 非空。任一不满足 → 模板降级。"""
    segs = obj.get("segments")
    if not isinstance(segs, list) or not segs:
        return False
    if not all(isinstance(s, dict) for s in segs):
        return False
    kinds = [s.get("kind") for s in segs]
    if kinds[0] != "hook" or kinds[-1] != "outro":
        return False
    if kinds.count("hook") != 1 or kinds.count("outro") != 1:
        return False
    unknown = set(kinds) - {"hook", "item", "china", "mainline", "outro"}
    if unknown:
        return False
    item_segs = [s for s in segs if s.get("kind") == "item"]
    got = [s.get("item_ref") for s in item_segs]
    # 布尔是 int 子类，{True}=={1} 会让 True 冒充条目 1——显式拒绝
    if any(not isinstance(r, int) or isinstance(r, bool) for r in got):
        return False
    if len(got) != len(set(got)) or set(got) != set(refs):
        return False
    if any(not str((s.get("card") or {}).get("headline") or "").strip()
           for s in item_segs):
        return False
    return all(isinstance(s.get("narration"), str) and len(s["narration"].strip()) >= 8
               for s in segs) \
        and all(isinstance(s.get("card"), dict) for s in segs)


def build_script(pid: str) -> dict:
    brief = ingest.load_briefing(pid)
    refs = valid_refs(brief)        # 有效条目 ref 集合（excluded_refs 剔除后）
    cfg = load_config()
    target_s = max(60, min(200, int(len(refs) * 32 + 24)))

    script = None
    fail_reason = ""
    key = api_keys()["zhipu"]
    if key and refs:
        tokens = int(cfg["glm"]["max_tokens"])
        for attempt in (1, 2):                    # 二次重试给足 tokens
            obj, err = chat_json_ex(
                key, _PROMPT.format(show=brief.get("show_label") or cfg["show"]["name"],
                                    target_s=target_s,
                                    brief=_brief_digest(brief)),
                model=cfg["glm"]["model"], temperature=cfg["glm"]["temperature"],
                max_tokens=tokens, timeout=cfg["glm"]["timeout_s"],
                required_keys=("title", "segments"))
            if obj is not None and _validate(obj, refs):
                script = obj
                break
            reason = err if obj is None else "JSON 可解析但未过结构校验（缺段/重复 ref 等）"
            fail_reason = f"第{attempt}次：{reason}"
            tokens *= 2
    mode = "glm"
    if script is None:
        script = _template_script(brief, cfg)
        mode = "template_fallback"
        if fail_reason:
            script["warnings"].append(f"GLM 稿未采用（{fail_reason}）")

    script["meta"] = {"pid": pid, "date": brief["date"],
                      "show": cfg["show"]["name"],
                      "show_label": brief.get("show_label") or cfg["show"]["name"],
                      "target_s": target_s, "mode": mode,
                      "n_items": sum(1 for s in script["segments"]
                                     if s["kind"] == "item"),
                      "est_duration_s": round(sum(_estimate_s(s["narration"])
                                                  for s in script["segments"]), 1)}
    for i, s in enumerate(script["segments"], 1):
        s.setdefault("card", {})
        s["card"].setdefault("type", {"hook": "hook", "outro": "outro"}
                             .get(s["kind"], "headline"))
        s["id"] = f"seg{i:02d}"
        s["est_s"] = _estimate_s(s["narration"])
    save_json(script, store.project_dir(pid) / "script.json")
    note = f"{mode} / {len(script['segments'])} 段"
    if fail_reason:
        note += f" / GLM未采用({fail_reason[:60]})"
    store.mark_stage(pid, "script", note)
    return script


def _brief_digest(brief: dict) -> str:
    import json as _j
    excluded = set(brief.get("excluded_refs", []))
    slim = {"date": brief["date"], "region": brief.get("region", ""),
            "items": [{"ref": i}
                      | {k: it.get(k, "") for k in
                         ("title", "summary", "chess", "china_link", "risk")}
                      | {"sources": it.get("sources", [])}
                      for i, it in enumerate(brief["items"], 1) if i not in excluded],
            "mainlines": brief.get("mainlines", [])}
    return _j.dumps(slim, ensure_ascii=False)


def load_script(pid: str) -> dict:
    s = load_json(store.project_dir(pid) / "script.json")
    if not s:
        raise RuntimeError(f"script.json 缺失: {pid}")
    return s


# 锤稿通过后供渲染使用的小工具
def narration_lines(narration: str, width: int = 16) -> list[str]:
    """口播切字幕行。有词级时间时按词界切，否则断在标点或虚词前。"""
    return Subtitles.lines(narration, width)


class Subtitles:
    """字幕行与出现时间。

    口播文本只用稿子里已经锁住的句子。出现时间只用配音写进 voice.json 的
    edge-tts WordBoundary（秒）。没有这份词级时间时，锁定字幕拍仍用拍上的时码；
    其余才按字数分整段音频窗口。不另造一条时钟。

    断行只发生在标点或词与词之间。一个词（例如「举行」「发表」）不拆到两行。
    """

    WIDTH = 16
    TIMING = "edge-tts-word"
    _PUNCT = "。！？；：，、,.:;!?\"“”''‘’（）()【】[]《》<>…—～~-—"
    _SENTENCE = "。！？；：.!?"
    _CLAUSE = "，。！？；：、,"
    _PARTICLE = "在与和及并而对从为把被将向"

    @staticmethod
    def sidecar(audio) -> Path:
        return Path(str(audio) + ".words.json")

    @staticmethod
    def read_words(audio) -> list:
        path = Subtitles.sidecar(audio)
        if not path.is_file():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        return data if isinstance(data, list) else []

    @staticmethod
    def write_words(audio, words: list) -> None:
        Subtitles.sidecar(audio).write_text(
            json.dumps(words, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def words_from_jsonl(text: str) -> list:
        """edge-tts metadata 一行一个 WordBoundary。offset 单位是 100 纳秒。"""
        words = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            msg = json.loads(line)
            if msg.get("type") != "WordBoundary":
                continue
            token = str(msg.get("text") or "")
            if not token.strip():
                continue
            words.append({
                "text": token,
                "offset": round(float(msg["offset"]) / 10_000_000, 4),
                "duration": round(float(msg["duration"]) / 10_000_000, 4),
            })
        return words

    @staticmethod
    def scale(words: list, factor: float) -> list:
        """同一条词级时钟乘上已经施加在音频上的倍率（atempo）。"""
        if not words:
            return []
        factor = float(factor)
        if factor <= 0:
            return []
        return [{
            "text": w["text"],
            "offset": round(float(w["offset"]) * factor, 4),
            "duration": round(float(w["duration"]) * factor, 4),
        } for w in words]

    @staticmethod
    def _sig(text: str) -> str:
        return "".join(ch for ch in text
                       if not ch.isspace() and ch not in Subtitles._PUNCT)

    @staticmethod
    def align(text: str, words: list) -> list[dict] | None:
        """把词级时间贴回原文。对不上就返回 None，调用方不得自行补时间。"""
        if not text or not words:
            return None
        pieces = []
        for w in words:
            sig = Subtitles._sig(str(w.get("text") or ""))
            if sig:
                pieces.append((w, sig))
        if not pieces or "".join(sig for _, sig in pieces) != Subtitles._sig(text):
            return None
        i = 0
        located = []
        for w, sig in pieces:
            consumed = 0
            start = None
            while consumed < len(sig) and i < len(text):
                if text[i].isspace() or text[i] in Subtitles._PUNCT:
                    i += 1
                    continue
                if text[i] != sig[consumed]:
                    return None
                if start is None:
                    start = i
                i += 1
                consumed += 1
            if consumed != len(sig) or start is None:
                return None
            located.append({
                "sig_start": start,
                "offset": float(w["offset"]),
                "duration": float(w["duration"]),
            })
        spans = []
        for k, loc in enumerate(located):
            a = 0 if k == 0 else loc["sig_start"]
            b = located[k + 1]["sig_start"] if k + 1 < len(located) else len(text)
            spans.append({
                "slice": text[a:b],
                "offset": loc["offset"],
                "duration": loc["duration"],
            })
        if "".join(s["slice"] for s in spans) != text:
            return None
        return spans

    @staticmethod
    def _len(spans: list[dict]) -> int:
        return len("".join(s["slice"] for s in spans).strip())

    @staticmethod
    def _sentence_end(slice_: str) -> bool:
        return slice_.rstrip().endswith(tuple(Subtitles._SENTENCE))

    @staticmethod
    def _lone_particle(slice_: str) -> bool:
        core = slice_.strip().strip(Subtitles._CLAUSE + Subtitles._SENTENCE)
        return len(core) == 1 and core in Subtitles._PARTICLE

    @staticmethod
    def wrap_spans(spans: list[dict], width: int) -> list[list[dict]]:
        """装满一行再断。断点在下一个词之前；行尾若只剩一个虚词，虚词跟下一行。"""
        groups: list[list[dict]] = []
        i, n = 0, len(spans)
        while i < n:
            best = i
            closed = False
            k = i
            while k < n:
                if best > i and Subtitles._len(spans[i:k + 1]) > width:
                    break
                best = k + 1
                if Subtitles._sentence_end(spans[k]["slice"]):
                    closed = True
                    break
                k += 1
            if (not closed and best < n and best > i + 1
                    and Subtitles._lone_particle(spans[best - 1]["slice"])):
                best -= 1
            if best == i:
                best = i + 1
            groups.append(spans[i:best])
            i = best
        return groups

    @staticmethod
    def _clean(line: str) -> str:
        return re.sub(r"([。！？；，、,.])\1+", r"\1", line.strip())

    @staticmethod
    def place(text: str, words: list, origin: float,
              width: int = 16) -> list[tuple[float, float, str]]:
        """一行的起止 = 该行第一个词的 offset 到最后一个词的结束，再加 origin。"""
        spans = Subtitles.align(text, words)
        if not spans:
            return []
        groups = Subtitles.wrap_spans(spans, width)
        timed = []
        for group in groups:
            line = Subtitles._clean("".join(s["slice"] for s in group))
            if not line:
                continue
            start = float(origin) + group[0]["offset"]
            last = group[-1]
            end = float(origin) + last["offset"] + last["duration"]
            timed.append([start, end, line])
        events = []
        for i, ev in enumerate(timed):
            if i + 1 < len(timed):
                ev[1] = timed[i + 1][0]
            if ev[1] <= ev[0]:
                ev[1] = ev[0] + 0.01
            events.append((ev[0], ev[1], ev[2]))
        return events

    @staticmethod
    def lines(text: str, width: int = 16, words: list | None = None) -> list[str]:
        if words:
            spans = Subtitles.align(text, words)
            if spans:
                out = [Subtitles._clean("".join(s["slice"] for s in group))
                       for group in Subtitles.wrap_spans(spans, width)]
                out = [ln for ln in out if ln]
                if out:
                    return out
        return Subtitles._plain(text, width)

    @staticmethod
    def _cut_at(piece: str, width: int) -> int:
        """无词级时间时的断点：先标点，再虚词前，最后才按字数。"""
        if len(piece) <= width:
            return len(piece)
        hi = min(width, len(piece) - 1)
        for j in range(hi, 0, -1):
            if piece[j - 1] in Subtitles._CLAUSE:
                return j
        for j in range(hi, 1, -1):
            if piece[j] in Subtitles._PARTICLE:
                return j
        return width

    @staticmethod
    def _plain(narration: str, width: int) -> list[str]:
        parts = [p for p in re.split(r"(?<=[。！？；：,.])\s*", narration) if p]
        lines: list[str] = []
        for p in parts:
            while len(p) > width:
                cut = Subtitles._cut_at(p, width)
                if cut <= 0 or cut >= len(p):
                    cut = min(width, len(p))
                lines.append(p[:cut].strip())
                p = p[cut:]
            if p.strip():
                lines.append(p.strip())
        merged: list[str] = []
        for ln in lines:
            core = re.sub(r"[。！？；：，、,.]+", "", ln).strip()
            if merged and len(core) <= 1:
                prev = merged[-1]
                if prev.endswith(tuple("。！？；，,")) and ln.startswith(tuple("。！？；，,")):
                    ln = ln.lstrip("。！？；，,")
                merged[-1] = (prev + ln).strip()
            elif core:
                merged.append(ln)
        lines = [Subtitles._clean(ln) for ln in merged]
        return lines or [narration]

    @staticmethod
    def for_segment(narration: str, seg: dict, cues: list | None,
                    voice_seg: dict | None, width: int = 16
                    ) -> list[tuple[float, float, str]]:
        """一段字幕。词级时间对得上原文才用；对不上不估。"""
        voice_seg = voice_seg or {}
        if cues:
            voice_cues = list(voice_seg.get("cues") or [])
            if (len(voice_cues) == len(cues)
                    and all(c.get("words") for c in voice_cues)):
                placed = []
                for cue, spoken in zip(cues, voice_cues):
                    origin = float(spoken.get("at", cue["start"]))
                    chunk = Subtitles.place(cue["text"], spoken["words"], origin, width)
                    if not chunk:
                        placed = []
                        break
                    placed.extend(chunk)
                if placed:
                    return placed
            return [(float(c["start"]), float(c["end"]), c["text"]) for c in cues]

        words = voice_seg.get("words") or []
        origin = float(seg["start"]) + float(seg.get("audio_in") or 0)
        if words:
            placed = Subtitles.place(narration, words, origin, width)
            if placed:
                return placed
        lines = Subtitles.lines(narration, width)
        if not lines:
            return []
        a0 = origin
        a1 = a0 + float(seg["audio_duration"])
        total = sum(max(1, len(ln)) for ln in lines)
        events = []
        t = a0
        for i, ln in enumerate(lines):
            end = a1 if i == len(lines) - 1 else min(a1, t + (a1 - a0) * len(ln) / total)
            events.append((t, max(end, t + 0.4), ln))
            t = end
        return events
