# -*- coding: utf-8 -*-
"""红线与措辞规则 —— 全部来自实测教训，不是拍脑袋：

- bili-news 时政线首篇被 B站判「不适宜内容」（state -3）：街头抗议/游行/警力
  部署这类社会运动叙事过线（见 bili-news/时政线首篇复盘.md）。
- grokbot 讨论（2026-11-09）定稿：不站队、不评论、不预测；信源分级；
  单位口径（英里/海里/公里必须写清）；「待核实」只进线索位。

锤稿（hammer.py）按此逐段检查：BLOCK 类命中即拒稿，WARN 类列出由人工裁量。
数字口径（加「约」、注机构、单位换算）由逐字稿提示词约束 + 人工审片把关，
不做机械正则检查（误报率过高：年份/里程/编号无法区分）。
"""
import re


# ---- BLOCK：命中即拒稿 ----------------------------------------------
BLOCK_PATTERNS = {
    "RL-SOCIAL": (
        # 社会运动叙事——首篇被毙的直接原因，宁枉勿纵
        r"抗议|游行|示威|罢工|骚乱|暴乱|镇压|清场|街头冲突|警力部署|催泪弹|"
        r"封锁学校|占领|静坐"
    ),
    "RL-CASUALTY": (
        # 战争伤亡渲染；事实通报走「官方通报」句式，不做画面化描写
        r"尸横遍野|血肉横飞|惨死|大量平民死|尸体|血流成河|满地残骸"
    ),
    "RL-SIDE": (
        # 站队定性词当旁白结论——只复述各方说法，不替历史法庭宣判
        r"侵略者|正义之师|邪恶轴心|罪有应得|活该|民族的耻辱"
    ),
    "RL-SENSITIVE": (
        # 涉华红线（与 bili-news exclude_keywords 同源）：不由旁白下结论
        r"中国必须|中国应该|北京当局|中共当局"
    ),
}

# ---- WARN：列出由人工裁量 / 触发一次重写 ----------------------------
WARN_PATTERNS = {
    "RL-PREDICT": (
        # 预测性断言——改为「各方关注/有待观察」句式
        r"(?<!不)将会?引发|必将|恐怕会|大概率会|注定|迟早会|下一步必然"
    ),
    "RL-HYPE": (
        # 标题党渲染词
        r"震惊|吓死|疯狂|末日|毁灭性打击|惊天"
    ),
    "RL-UNIT": (
        # 英里/海里必须带公里换算——霍尔木兹脚本里的教训
        r"\d+\s*(英里|海里)(?![^。]{0,12}公里)"
    ),
}

# 信源四级（与 Grok 任务D 提示词一致）
SOURCE_TIERS = ("官方", "主流媒体", "区域专家", "单方声称待核实")

# 信源分级徽标（每条动态的口播里至少出现一次）。两种认可写法：
#   ① 原样念徽标：【官方】／【主流媒体】…
#   ② 口播化：信源级别为官方／信源：区域专家…
_BADGE = re.compile(
    r"【(官方|主流媒体|区域专家|单方声称待核实)】"
    r"|(信源级别|信源等级|信源)[^。；;]{0,6}(官方|主流媒体|区域专家|单方声称待核实)")

# 涉华段落必须有官方口径锚点
_CHINA_ANCHOR = re.compile(r"中方表示|中国外交部|商务部|官方回应|据中方|中方多次强调|"
                           "中国驻.{1,6}(使馆|大使馆)")


def check_text(text: str) -> list[dict]:
    """对一段口播文本跑全部规则，返回 [{rule, level, hit}]。"""
    issues = []
    for rule, pat in BLOCK_PATTERNS.items():
        if m := re.search(pat, text):
            issues.append({"rule": rule, "level": "block", "hit": m.group(0)})
    for rule, pat in WARN_PATTERNS.items():
        if m := re.search(pat, text):
            issues.append({"rule": rule, "level": "warn", "hit": m.group(0)})
    return issues


def check_badge(text: str) -> bool:
    """动态条目口播是否带信源分级（徽标原样念或口播化表述均可）。"""
    return bool(_BADGE.search(text))


def check_china_anchor(text: str) -> bool:
    """涉华表述是否有官方口径锚点。"""
    return bool(_CHINA_ANCHOR.search(text))


# ---- hook 条数口径（GLM 偶发把 6 条念成 5 条） --------------------------
_CN_DIGIT = {"零": 0, "一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
             "六": 6, "七": 7, "八": 8, "九": 9}
_INT2CN = {1: "一", 2: "两", 3: "三", 4: "四", 5: "五",
           6: "六", 7: "七", 8: "八", 9: "九"}


def _cn2int(s: str) -> int | None:
    if s.isdigit():
        return int(s)
    if s == "十":
        return 10
    if "十" in s:
        a, _, b = s.partition("十")
        if (a and a not in _CN_DIGIT) or (b and b not in _CN_DIGIT):
            return None
        return (int(_CN_DIGIT.get(a, 1))) * 10 + (int(_CN_DIGIT.get(b, 0)) if b else 0)
    return _CN_DIGIT.get(s)


def _int2cn(n: int) -> str:
    if n < 10:
        return _INT2CN.get(n, str(n))
    if n == 10:
        return "十"
    if n < 20:
        return "十" + _INT2CN.get(n - 10, "")
    return str(n)


def fix_hook_count(text: str, n_items: int) -> tuple[str, str | None]:
    """hook 口播念的条数与实际条目数不符时做最小替换修正；没提条数则不动。
    返回 (修正后文本, 说明)。"""
    matches = list(re.finditer(r"([一二两三四五六七八九十\d]+)\s*条", text))
    if not matches:
        return text, None
    claimed = _cn2int(matches[0].group(1))
    if claimed is None or claimed == n_items:
        return text, None
    fixed = text[:matches[0].start()] + _int2cn(n_items) + "条" + text[matches[0].end():]
    return fixed, (f"hook条数口径{claimed}≠实际{n_items}，"
                   f"已修正为「{_int2cn(n_items)}条」")
