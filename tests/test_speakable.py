# -*- coding: utf-8 -*-
"""可念文本：长句加逗号换气，关键数字分写，字幕跟这一次合成的词界。"""
import hashlib
import re

import pytest

from src.scriptgen import Subtitles
from src.speakable import Speakable

HOOK = "11月17日，美澳印日四国领导人在马尼拉举行四方安全对话峰会并发表联合新闻稿"
HOOK_SPOKEN = (
    "十一月十七日，美澳印日四国领导人，在马尼拉举行四方安全对话峰会，并发表联合新闻稿"
)
FIXTURE = (
    "演示样本，勿发布。11月20日约140架飞机与90艘舰船在邻近海域完成通过"
    "并在18:45结束会合。"
)
FIXTURE_SPOKEN = (
    "演示样本，勿发布。十一月二十日，约一百四十架飞机与九十艘舰船，"
    "在邻近海域完成通过，并在十八点四十五分结束会合。"
)


def _core(text: str) -> str:
    return "".join(ch for ch in text if ch not in Speakable._PUNCT and not ch.isspace())


@pytest.mark.parametrize("n,zh", [
    (0, "零"), (1, "一"), (2, "二"), (10, "十"), (11, "十一"), (19, "十九"),
    (20, "二十"), (21, "二十一"), (99, "九十九"), (100, "一百"),
    (101, "一百零一"), (110, "一百一十"), (111, "一百一十一"), (140, "一百四十"),
    (200, "二百"), (999, "九百九十九"), (1000, "一千"), (1001, "一千零一"),
    (1010, "一千零一十"), (1100, "一千一百"), (2026, "二千零二十六"),
    (10000, "一万"), (10001, "一万零一"), (10010, "一万零一十"),
    (10100, "一万零一百"), (11000, "一万一千"), (100000, "十万"),
    (101000, "十万一千"), (100000000, "一亿"), (100000001, "一亿零一"),
    (100010000, "一亿零一万"),
])
def test_integer_reading_keeps_the_same_value(n, zh):
    assert Speakable.integer_reading(n) == zh


def test_long_sentence_gains_pause_commas_without_new_words():
    paused = Speakable.pauses(HOOK)
    assert paused == (
        "11月17日，美澳印日四国领导人，在马尼拉举行四方安全对话峰会，并发表联合新闻稿"
    )
    assert _core(paused) == _core(HOOK)
    assert paused.count("，") == HOOK.count("，") + 2
    spoken = Speakable.text(HOOK)
    assert spoken == HOOK_SPOKEN
    assert Speakable.text(spoken) == spoken


def test_clause_opener_gets_a_comma_when_the_stretch_is_long():
    raw = "联合新闻稿已经发表因此各方保持接触。"
    assert Speakable.pauses(raw) == "联合新闻稿已经发表，因此各方保持接触。"
    assert _core(Speakable.pauses(raw)) == _core(raw)


def test_key_numbers_are_written_out_as_the_same_figure():
    assert Speakable.numbers("约140席") == "约一百四十席"
    assert Speakable.integer_reading(140) == "一百四十"
    assert Speakable.numbers("约90分钟") == "约九十分钟"
    assert Speakable.integer_reading(90) == "九十"
    assert Speakable.numbers("101人") == "一百零一人"
    assert Speakable.numbers("约200公里") == "约二百公里"
    assert Speakable.numbers("1,400架") == "一千四百架"
    assert Speakable.integer_reading(1400) == "一千四百"
    assert Speakable.numbers("12万人") == "十二万人"
    assert Speakable.numbers("3.5亿") == "三点五亿"
    assert Speakable.numbers("12.5%") == "百分之十二点五"
    assert Speakable.numbers("12%") == "百分之十二"
    assert Speakable.numbers("百分之12") == "百分之十二"
    assert Speakable.numbers("11月17日") == "十一月十七日"
    assert Speakable.numbers("10月1日") == "十月一日"
    assert Speakable.numbers("2026年11月17日") == "二零二六年十一月十七日"
    assert Speakable.numbers("2026 年11月17日") == "二零二六年十一月十七日"
    assert Speakable.numbers("2026年") == "二零二六年"
    assert "二千零二十六" not in Speakable.numbers("2026年")
    assert Speakable.numbers("2026") == "二千零二十六"
    assert Speakable.numbers("18:45") == "十八点四十五分"
    assert Speakable.integer_reading(18) == "十八"
    assert Speakable.integer_reading(45) == "四十五"
    assert Speakable.numbers("19时45分") == "十九时四十五分"
    assert Speakable.numbers("9:05") == "九点零五分"
    assert Speakable.numbers("18:00") == "十八点"
    assert Speakable.numbers("11个月") == "十一个月"
    assert "十一月" not in Speakable.numbers("11个月")
    assert Speakable.text(FIXTURE) == FIXTURE_SPOKEN
    assert Speakable.text(FIXTURE_SPOKEN) == FIXTURE_SPOKEN


def test_readings_that_should_stay_as_written():
    untouched = [
        "今天没有新的动态。",
        "会谈正在举行。",
        "峰会并发表联合新闻稿。",
        "约5座储罐受损。",
        "约一百四十席。",
        "第007号编组。",
        "P-8和P-3C",
        "保持F-16巡航。",
        "G20",
        "COVID-19",
        "5%",
        "1000000000000",
        "美澳印日四国领导人把两份公报合并后公布。",
    ]
    for raw in untouched:
        assert Speakable.text(raw) == raw, raw


def test_cosyvoice_stays_off_by_default():
    from src.config import DEFAULTS, load_config
    assert DEFAULTS["voice"]["cosy"]["enable"] is False
    assert load_config()["voice"]["cosy"]["enable"] is False


def test_audio_key_matches_the_spoken_line():
    from src.narrator import _audio_key

    plain = {"id": "seg01", "narration": "今天没有新的动态。"}
    assert _audio_key(plain) == "seg01_" + hashlib.md5(
        plain["narration"].encode("utf-8")).hexdigest()[:8]

    raw = {"id": "seg01", "narration": "约140席。"}
    spoken = Speakable.text(raw["narration"])
    assert spoken != raw["narration"]
    assert _audio_key(raw) == "seg01_" + hashlib.md5(
        spoken.encode("utf-8")).hexdigest()[:8]
    assert _audio_key(raw) != "seg01_" + hashlib.md5(
        raw["narration"].encode("utf-8")).hexdigest()[:8]


def _clause_words(text: str) -> list[dict]:
    clauses = [c for c in re.split(r"[，。]", text) if c]
    words = []
    t = 0.12
    for i, clause in enumerate(clauses):
        words.append({"text": clause, "offset": round(t, 4), "duration": 0.7})
        t += 0.7 + (0.35 if i + 1 < len(clauses) else 0.0)
    return words


def test_rewritten_line_subtitles_follow_the_spoken_word_clock():
    from src.renderer import subtitle_events

    spoken = FIXTURE_SPOKEN
    words = _clause_words(spoken)
    assert Subtitles.align(FIXTURE, words) is None
    spans = Subtitles.align(spoken, words)
    assert spans is not None
    number = next(s for s in spans if "一百四十" in s["slice"])
    assert number["offset"] == words[3]["offset"]
    assert number["duration"] == words[3]["duration"]
    bing = next(w for w in words if w["text"].startswith("并"))

    seg = {"id": "seg01", "start": 1.0, "audio_in": 0.3, "audio_duration": 12.0}
    voice = {"spoken": spoken, "words": words, "timing": Subtitles.TIMING}
    ev = subtitle_events({"seg01": FIXTURE}, [seg], {}, {"seg01": voice})
    shown = "".join(e[2] for e in ev)
    assert "140" not in shown and "18:45" not in shown
    assert "一百四十" in shown and "十八点四十五分" in shown
    origin = seg["start"] + seg["audio_in"]
    assert abs(ev[0][0] - (origin + words[0]["offset"])) < 1e-9
    bing_ev = next(e for e in ev if "并在十八点四十五分" in e[2])
    assert abs(bing_ev[0] - (origin + bing["offset"])) < 1e-9
    assert bing_ev[0] > ev[0][1]

    # 没有 spoken 记录时，词界对不上锁定稿，不能拿这套时钟去套「140」。
    fallback = subtitle_events(
        {"seg01": FIXTURE}, [seg], {}, {"seg01": {"words": words}})
    assert "140" in "".join(e[2] for e in fallback)
    assert "一百四十" not in "".join(e[2] for e in fallback)
    assert abs(fallback[0][0] - origin) < 1e-9
    flat = next(e for e in fallback if "140" in e[2])
    assert abs(flat[0] - (origin + words[3]["offset"])) > 0.2


def test_pause_commas_keep_the_word_clock_on_the_spoken_line():
    raw = "美澳印日四国领导人在马尼拉举行四方安全对话峰会并发表联合新闻稿"
    spoken = Speakable.pauses(raw)
    assert "领导人，在马尼拉" in spoken
    assert "峰会，并发表" in spoken
    assert _core(spoken) == raw
    words = _clause_words(spoken)
    assert Subtitles.align(spoken, words) is not None
    bing = next(w for w in words if w["text"].startswith("并"))
    ev = Subtitles.place(spoken, words, 4.0)
    bing_ev = next(e for e in ev if e[2].startswith("并"))
    assert abs(bing_ev[0] - (4.0 + bing["offset"])) < 1e-9
    # 逗号只负责换气，词界仍然贴在念出来的字上，而不是按字数摊开。
    assert bing_ev[0] != 4.0


def test_locked_voice_speaks_the_rewritten_line(tmp_path, monkeypatch):
    from src import narrator

    raw = "约140席，会谈约90分钟。"
    spoken = Speakable.text(raw)
    captured = {}

    def fake_speak(text, mp3, vcfg, key):
        captured["text"] = text
        mp3.write_bytes(b"m" * 2000)
        narrator.scriptgen.Subtitles.write_words(mp3, _clause_words(text))
        return "edge"

    def fake_to_wav(src, dst):
        dst.write_bytes(src.read_bytes())
        return dst

    def fake_fit(src, dst, window):
        dst.write_bytes(b"f" * 2000)
        return 3.0

    monkeypatch.setattr(narrator, "_speak", fake_speak)
    monkeypatch.setattr(narrator, "_to_wav", fake_to_wav)
    monkeypatch.setattr(narrator, "_fit_window", fake_fit)
    monkeypatch.setattr(narrator, "_concat_wavs", lambda paths, dst: 3.0)
    monkeypatch.setattr(narrator.ffmpeg, "probe_duration", lambda path: 3.0)

    seg = {"id": "seg01", "narration": raw, "cues": [
        {"start": 1.0, "end": 8.0, "text": raw}]}
    item, backend = narrator._voice_locked(seg, tmp_path, {}, "", "")
    assert backend == "edge"
    assert captured["text"] == spoken
    assert seg["cues"][0]["text"] == raw
    cue = item["cues"][0]
    assert cue["spoken"] == spoken
    assert cue["at"] == 1.0
    assert cue["timing"] == "edge-tts-word"

    from src.renderer import subtitle_events
    ev = subtitle_events(
        {"seg01": raw},
        [{"id": "seg01", "start": 0.0, "audio_in": 0.0, "audio_duration": 3.0}],
        {"seg01": seg["cues"]},
        {"seg01": item},
    )
    assert "140" not in "".join(e[2] for e in ev)
    assert "一百四十" in "".join(e[2] for e in ev)
    assert abs(ev[0][0] - (cue["at"] + cue["words"][0]["offset"])) < 1e-9


def test_segment_voice_sends_speakable_text_and_records_it(tmp_path, monkeypatch):
    from src import narrator
    from src.jsonio import save_json as real_save

    raw = FIXTURE
    spoken = FIXTURE_SPOKEN
    captured = {}
    saved = {}

    def fake_edge(text, out, voice, rate):
        captured["text"] = text
        captured["voice"] = voice
        captured["rate"] = rate
        out.write_bytes(b"m" * 2000)
        narrator.scriptgen.Subtitles.write_words(out, _clause_words(text))
        return out

    def fake_to_wav(src, dst):
        dst.write_bytes(src.read_bytes())
        narrator._carry_words(src, dst, 1.0)
        return dst

    monkeypatch.setattr(narrator, "_synth_edge", fake_edge)
    monkeypatch.setattr(narrator, "_to_wav", fake_to_wav)
    monkeypatch.setattr(narrator, "_synth_cosy_batch",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("cosy")))
    monkeypatch.setattr(narrator.ffmpeg, "probe_duration", lambda path: 4.0)
    monkeypatch.setattr(narrator, "load_config", lambda: {
        "voice": {"edge_voice": "zh-CN-YunxiNeural", "edge_rate": "+8%",
                  "cosy": {"enable": False}}})
    monkeypatch.setattr(narrator, "api_keys", lambda: {"zhipu": ""})
    monkeypatch.setattr(narrator.scriptgen, "load_script", lambda pid: {
        "segments": [{"id": "seg01", "narration": raw}]})
    monkeypatch.setattr(narrator.store, "project_dir", lambda pid: tmp_path)
    monkeypatch.setattr(narrator.store, "mark_stage", lambda *a, **k: None)

    def grab(obj, path):
        saved["obj"] = obj
        real_save(obj, path)

    monkeypatch.setattr("src.jsonio.save_json", grab)
    (tmp_path / "audio").mkdir()
    result = narrator.voice("ep-demo")
    assert captured["text"] == spoken
    assert captured["voice"] == "zh-CN-YunxiNeural"
    assert captured["rate"] == "+8%"
    assert result["backend"] == "edge"
    assert result["segments"][0]["spoken"] == spoken
    assert saved["obj"]["segments"][0]["spoken"] == spoken
    words = result["segments"][0]["words"]
    assert Subtitles.align(spoken, words) is not None
    assert Subtitles.align(raw, words) is None
