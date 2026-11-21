# -*- coding: utf-8 -*-
"""把锁定口播变成同一事实的可念文本。

只做两件事，都不改事实、不改数值、不新造新闻句子：
1. 在长句的分句口加逗号，让云希有地方换气。
2. 把关键阿拉伯数字写成播音念法（分写）。年份、钟点按位分读；
   带单位或独立出现的数量按数值来念。单字数字、字母编号、前导零代号不动。

锁定稿本身不改。配音和这一次合成的字幕都用这里的结果。
"""
import re


class Speakable:
    """锁定句 → 送进 TTS 的那一句。静态方法，不写稿、不合成。"""

    _DIGITS = "零一二三四五六七八九"
    _MIN_STRETCH = 8
    _PUNCT = set("。！？；：，、,.;:!?…")
    _OPENERS = (
        "与此同时", "除此之外", "尽管如此",
        "而且", "并且", "同时", "此外", "另外", "其中",
        "随后", "此后", "因此", "所以", "但是", "不过", "然而",
        "以及", "还有",
    )
    # 「并」作连词。词内的「并」不能在前面加逗号。
    # 「发」不在这里：快讯里的「并发表」就是要换气，不能被「并发」一起挡住。
    _BING_NEXT = set("且肩列非排进用存重力")
    _BING_PREV = set("合吞兼归")
    # 「在」前面是这些字，才当作主语说完了。避开「正在 / 存在」。
    _ZAI_PREV = set("人方府会部军队员官社国港船机岛海局委团司")
    _DATE_HOLD = set("的前后起至到")
    _UNITS = (
        "公里", "千米", "海里", "英里", "公斤", "千克", "分钟", "小时", "秒钟",
        "美元", "欧元", "人民币", "架", "艘", "座", "枚", "发", "人", "名", "位",
        "个", "次", "项", "条", "份", "席", "吨", "米", "元", "秒", "万", "亿",
    )
    _CODE = re.compile(
        r"[A-Za-z]+(?:[-－/][A-Za-z0-9]+)+"
        r"|[A-Za-z]+\d+[A-Za-z0-9]*"
        r"|\d+[-－]?[A-Za-z]+"
    )
    _GROUPED = re.compile(r"(?<![0-9])\d{1,3}(?:[,，]\d{3})+(?![0-9])")
    _DATE_COMMA = re.compile(
        r"(?:(\d{4})\s*年\s*)?(\d{1,2})\s*月\s*(\d{1,2})\s*日"
    )
    _FULL_DATE = re.compile(
        r"(?<![0-9])(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日(?!\d)"
    )
    _YEAR_MONTH = re.compile(
        r"(?<![0-9])(\d{4})\s*年\s*(\d{1,2})\s*月(?![\d个日])"
    )
    _MONTH_DAY = re.compile(
        r"(?<![0-9年])(\d{1,2})\s*月\s*(\d{1,2})\s*日(?!\d)"
    )
    _YEAR = re.compile(r"(?<![0-9])(\d{4})\s*年(?!\d)")
    _CLOCK = re.compile(r"(?<![0-9])(\d{1,2})\s*[:：]\s*(\d{2})(?!\d)")
    _CLOCK_HM = re.compile(
        r"(?<![0-9])(\d{1,2})\s*(时|点)\s*(\d{1,2})\s*分"
    )
    _PERCENT = re.compile(r"(?<![0-9])(\d+(?:\.\d+)?)\s*[%％]")
    _LEAD0 = re.compile(r"(?<![0-9])0\d+(?![0-9])")
    _UNIT_RE = re.compile(
        r"(?<![0-9A-Za-z])(\d+\.\d+|\d{2,})("
        + "|".join(sorted(_UNITS, key=len, reverse=True))
        + r")"
    )
    _BARE = re.compile(r"(?<![0-9A-Za-z])(\d+\.\d+|\d{2,})(?![0-9A-Za-z])")

    @staticmethod
    def text(raw: str) -> str:
        """先加停顿，再分写数字。同一句再跑一次结果不变。"""
        if not raw:
            return raw or ""
        return Speakable.numbers(Speakable.pauses(raw))

    @staticmethod
    def pauses(raw: str) -> str:
        """长句在日期后、主语「在」之前、连词「并 / 而且 / 同时」之前加逗号。"""
        if not raw:
            return raw or ""
        s = Speakable._comma_after_date(raw)
        out: list[str] = []
        quote: list[str] = []
        i, n = 0, len(s)
        while i < n:
            ch = s[i]
            if not quote and ch not in Speakable._PUNCT:
                opener = Speakable._opener_at(s, i)
                if opener and Speakable._stretch(out) >= Speakable._MIN_STRETCH:
                    if i + len(opener) < n:
                        out.append("，")
                        out.append(opener)
                        i += len(opener)
                        continue
            if ((ch == "并" and Speakable._bing_break(s, i, out))
                    or (ch == "在" and Speakable._zai_break(s, i, out))):
                out.append("，")
            out.append(ch)
            quote = Speakable._track_quote(quote, ch)
            i += 1
        return "".join(out)

    @staticmethod
    def numbers(raw: str) -> str:
        """关键数字写成念法。对不上规则的原样留下。"""
        if not raw:
            return raw or ""
        slots: list[str] = []
        text = Speakable._hold(slots, raw, Speakable._CODE)
        text = Speakable._GROUPED.sub(
            lambda m: m.group(0).replace(",", "").replace("，", ""), text)
        text = Speakable._FULL_DATE.sub(Speakable._full_date, text)
        text = Speakable._YEAR_MONTH.sub(Speakable._year_month, text)
        text = Speakable._MONTH_DAY.sub(Speakable._month_day, text)
        text = Speakable._YEAR.sub(Speakable._year_only, text)
        text = Speakable._CLOCK.sub(Speakable._clock, text)
        text = Speakable._CLOCK_HM.sub(Speakable._clock_hm, text)
        text = Speakable._PERCENT.sub(Speakable._percent, text)
        text = Speakable._hold(slots, text, Speakable._LEAD0)
        text = Speakable._UNIT_RE.sub(
            lambda m: Speakable._read_token(m.group(1)) + m.group(2), text)
        text = Speakable._BARE.sub(
            lambda m: Speakable._read_token(m.group(1)), text)
        return Speakable._release(text, slots)

    @staticmethod
    def integer_reading(n: int) -> str:
        """数量念法。10 → 十，140 → 一百四十，101 → 一百零一，200 → 二百。

        只负责把一个整数念出来。年份不走这里（二零二六，不是二千零二十六）。
        大于等于一兆的数不在快讯里猜「兆 / 万亿」，调用方应保持原数字。
        """
        if n < 0 or n >= 10**12:
            raise ValueError(n)
        if n == 0:
            return "零"
        groups = []
        x = n
        while x:
            groups.append(x % 10000)
            x //= 10000
        big = ("", "万", "亿")
        result = ""
        highest = len(groups) - 1
        for i in range(highest, -1, -1):
            g = groups[i]
            if g == 0:
                if result and any(groups[:i]) and not result.endswith("零"):
                    result += "零"
                continue
            piece = Speakable._four(g)
            if i == highest and piece.startswith("一十"):
                piece = piece[1:]
            if result and g < 1000 and not result.endswith("零"):
                result += "零"
            result += piece + big[i]
        return result

    # ---------------------------------------------------------------- 停顿

    @staticmethod
    def _stretch(out: list[str]) -> int:
        n = 0
        for ch in reversed(out):
            if ch in Speakable._PUNCT:
                break
            n += 1
        return n

    @staticmethod
    def _opener_at(text: str, i: int) -> str:
        for opener in Speakable._OPENERS:
            if text.startswith(opener, i):
                return opener
        return ""

    @staticmethod
    def _bing_break(text: str, i: int, out: list[str]) -> bool:
        if Speakable._stretch(out) < Speakable._MIN_STRETCH:
            return False
        if i + 1 >= len(text):
            return False
        prev = out[-1] if out else ""
        if prev in Speakable._BING_PREV or prev in Speakable._PUNCT:
            return False
        return text[i + 1] not in Speakable._BING_NEXT

    @staticmethod
    def _zai_break(text: str, i: int, out: list[str]) -> bool:
        if Speakable._stretch(out) < Speakable._MIN_STRETCH or i + 1 >= len(text):
            return False
        prev = out[-1] if out else ""
        return prev in Speakable._ZAI_PREV

    @staticmethod
    def _track_quote(stack: list[str], ch: str) -> list[str]:
        pairs = {"「": "」", "『": "』", "“": "”"}
        if ch in pairs:
            return stack + [pairs[ch]]
        if stack and ch == stack[-1]:
            return stack[:-1]
        if ch == '"':
            if stack and stack[-1] == '"':
                return stack[:-1]
            return stack + ['"']
        return stack

    @staticmethod
    def _comma_after_date(text: str) -> str:
        def repl(m: re.Match) -> str:
            month, day = int(m.group(2)), int(m.group(3))
            if not (1 <= month <= 12 and 1 <= day <= 31):
                return m.group(0)
            j = m.end()
            while j < len(text) and text[j].isspace():
                j += 1
            if j >= len(text) or text[j] in Speakable._PUNCT | Speakable._DATE_HOLD:
                return m.group(0)
            return m.group(0).rstrip() + "，"

        return Speakable._DATE_COMMA.sub(repl, text)

    # ---------------------------------------------------------------- 数字

    @staticmethod
    def _token(i: int) -> str:
        n, chars = i + 1, []
        while n:
            n, r = divmod(n - 1, 26)
            chars.append(chr(ord("A") + r))
        return "\uE000" + "".join(reversed(chars)) + "\uE001"

    @staticmethod
    def _hold(slots: list[str], text: str, pattern: re.Pattern) -> str:
        def repl(m: re.Match) -> str:
            slots.append(m.group(0))
            return Speakable._token(len(slots) - 1)
        return pattern.sub(repl, text)

    @staticmethod
    def _release(text: str, slots: list[str]) -> str:
        for i, original in enumerate(slots):
            text = text.replace(Speakable._token(i), original)
        return text

    @staticmethod
    def _four(n: int) -> str:
        out: list[str] = []
        zero = False
        for div, unit in ((1000, "千"), (100, "百"), (10, "十")):
            d = (n // div) % 10
            if d == 0:
                if out:
                    zero = True
            else:
                if zero:
                    out.append("零")
                    zero = False
                out.append(Speakable._DIGITS[d] + unit)
        d = n % 10
        if d:
            if zero:
                out.append("零")
            out.append(Speakable._DIGITS[d])
        return "".join(out)

    @staticmethod
    def _read_token(token: str) -> str:
        if "." in token:
            whole, frac = token.split(".", 1)
            if not whole.isdigit() or not frac.isdigit() or not frac:
                return token
            if int(whole) >= 10**12:
                return token
            head = Speakable.integer_reading(int(whole))
            tail = "".join(Speakable._DIGITS[int(c)] for c in frac)
            return head + "点" + tail
        if not token.isdigit() or token[0] == "0":
            return token
        n = int(token)
        if n >= 10**12:
            return token
        return Speakable.integer_reading(n)

    @staticmethod
    def _ymd(year: str | None, month: str, day: str) -> str | None:
        m, d = int(month), int(day)
        if not (1 <= m <= 12 and 1 <= d <= 31):
            return None
        if year is not None and (len(year) != 4 or year[0] == "0"):
            return None
        head = (Speakable._year_digits(year) + "年") if year else ""
        return f"{head}{Speakable.integer_reading(m)}月{Speakable.integer_reading(d)}日"

    @staticmethod
    def _year_digits(year: str) -> str:
        return "".join(Speakable._DIGITS[int(c)] for c in year)

    @staticmethod
    def _full_date(m: re.Match) -> str:
        spoken = Speakable._ymd(m.group(1), m.group(2), m.group(3))
        return m.group(0) if spoken is None else spoken

    @staticmethod
    def _month_day(m: re.Match) -> str:
        spoken = Speakable._ymd(None, m.group(1), m.group(2))
        return m.group(0) if spoken is None else spoken

    @staticmethod
    def _year_month(m: re.Match) -> str:
        year, month = m.group(1), int(m.group(2))
        if len(year) != 4 or year[0] == "0" or not (1 <= month <= 12):
            return m.group(0)
        return Speakable._year_digits(year) + "年" + Speakable.integer_reading(month) + "月"

    @staticmethod
    def _year_only(m: re.Match) -> str:
        year = m.group(1)
        if len(year) != 4 or year[0] == "0":
            return m.group(0)
        return Speakable._year_digits(year) + "年"

    @staticmethod
    def _minute(m: int) -> str:
        if m < 10:
            return "零" + Speakable._DIGITS[m]
        return Speakable.integer_reading(m)

    @staticmethod
    def _clock(m: re.Match) -> str:
        hour, minute = int(m.group(1)), int(m.group(2))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return m.group(0)
        hs = Speakable.integer_reading(hour)
        if minute == 0:
            return hs + "点"
        return f"{hs}点{Speakable._minute(minute)}分"

    @staticmethod
    def _clock_hm(m: re.Match) -> str:
        hour, mark, minute = int(m.group(1)), m.group(2), int(m.group(3))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return m.group(0)
        return Speakable.integer_reading(hour) + mark + Speakable._minute(minute) + "分"

    @staticmethod
    def _percent(m: re.Match) -> str:
        token = m.group(1)
        # 一位数的「5%」云希读得清，保持原样；两位和小数才分写。
        if re.fullmatch(r"\d", token):
            return m.group(0)
        spoken = Speakable._read_token(token)
        if spoken == token:
            return m.group(0)
        return "百分之" + spoken
