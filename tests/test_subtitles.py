# -*- coding: utf-8 -*-
"""字幕跟口播：词级时间来自 edge-tts，断行不切开词。"""
import json
from pathlib import Path

from src.scriptgen import Subtitles, narration_lines

# 2026-11-21 对 zh-CN-YunxiNeural、rate=+8% 抓到的 WordBoundary。
# 不是按字数摊出来的。
HOOK = "11月17日，美澳印日四国领导人在马尼拉举行四方安全对话峰会并发表联合新闻稿"
HOOK_WORDS = [
    ("11月17日", 0.096, 1.030),
    ("美", 1.485, 0.162),
    ("澳", 1.647, 0.116),
    ("印日", 1.775, 0.486),
    ("四", 2.365, 0.266),
    ("国", 2.631, 0.093),
    ("领导人", 2.735, 0.544),
    ("在", 3.372, 0.162),
    ("马尼拉", 3.545, 0.405),
    ("举行", 3.962, 0.336),
    ("四方", 4.321, 0.347),
    ("安全", 4.680, 0.301),
    ("对话", 4.992, 0.232),
    ("峰会", 5.235, 0.417),
    ("并", 5.744, 0.139),
    ("发表", 5.895, 0.336),
    ("联合", 6.254, 0.312),
    ("新闻稿", 6.578, 0.440),
]

BEAT1 = "11月17日，美澳印日四国领导人"
BEAT1_WORDS = [
    ("11月17日", 0.096, 1.076),
    ("美", 1.416, 0.185),
    ("澳", 1.601, 0.139),
    ("印日", 1.751, 0.289),
    ("四", 2.064, 0.232),
    ("国", 2.295, 0.104),
    ("领导人", 2.411, 0.544),
]
BEAT2 = "在马尼拉举行四方安全对话峰会"
BEAT2_WORDS = [
    ("在", 0.096, 0.232),
    ("马尼拉", 0.339, 0.394),
    ("举行", 0.744, 0.359),
    ("四方", 1.126, 0.347),
    ("安全", 1.485, 0.359),
    ("对话", 1.856, 0.243),
    ("峰会", 2.110, 0.405),
]
BEAT3 = "并发表联合新闻稿"
BEAT3_WORDS = [
    ("并", 0.096, 0.220),
    ("发表", 0.328, 0.301),
    ("联合", 0.652, 0.301),
    ("新闻稿", 0.964, 0.544),
]


def _words(rows):
    return [{"text": t, "offset": o, "duration": d} for t, o, d in rows]


def _intact(lines, token):
    assert any(token in ln for ln in lines), lines
    for left, right in zip(lines, lines[1:]):
        assert not (left.endswith(token[0]) and right.startswith(token[1:])), (
            left, right)


def test_plain_hook_breaks_on_phrases_and_keeps_juxing():
    lines = narration_lines(HOOK)
    assert lines == [
        "11月17日，",
        "美澳印日四国领导人",
        "在马尼拉举行四方安全对话峰会",
        "并发表联合新闻稿",
    ]
    assert "".join(lines) == HOOK
    _intact(lines, "举行")
    _intact(lines, "发表")
    _intact(lines, "领导人")


def test_word_clock_places_the_three_beats_on_their_words():
    words = _words(HOOK_WORDS)
    lines = Subtitles.lines(HOOK, words=words)
    assert lines == [
        "11月17日，美澳印日四国领导人",
        "在马尼拉举行四方安全对话峰会",
        "并发表联合新闻稿",
    ]
    _intact(lines, "举行")
    _intact(lines, "发表")
    ev = Subtitles.place(HOOK, words, 0.0)
    assert [e[2] for e in ev] == lines
    # 第一行在「在」开口时换走，不是按字数摊到整段。
    assert ev[0][0] == words[0]["offset"]
    assert ev[0][1] == words[7]["offset"]
    assert ev[1][0] == words[7]["offset"]
    assert ev[1][1] == words[14]["offset"]
    last = words[-1]
    assert ev[2][0] == words[14]["offset"]
    assert abs(ev[2][1] - (last["offset"] + last["duration"])) < 1e-9
    assert "举行" in ev[1][2] and "举行" not in ev[0][2] and "举行" not in ev[2][2]


def test_locked_beats_follow_each_cue_clock_not_the_editorial_window():
    from src.renderer import subtitle_events

    cues = [
        {"start": 0.0, "end": 6.0, "text": BEAT1},
        {"start": 6.0, "end": 12.0, "text": BEAT2},
        {"start": 12.0, "end": 15.0, "text": BEAT3},
    ]
    voice = {"cues": [
        {"at": 0.0, "words": _words(BEAT1_WORDS), "timing": Subtitles.TIMING},
        {"at": 6.0, "words": _words(BEAT2_WORDS), "timing": Subtitles.TIMING},
        {"at": 12.0, "words": _words(BEAT3_WORDS), "timing": Subtitles.TIMING},
    ]}
    seg = {"id": "seg01", "start": 0.0, "audio_in": 0.3, "audio_duration": 9.0}
    ev = subtitle_events(
        {"seg01": HOOK}, [seg], {"seg01": cues}, {"seg01": voice})
    assert [e[2] for e in ev] == [BEAT1, BEAT2, BEAT3]
    # 第一拍的字在 3 秒内说完，字幕不占满 0–6 的拍窗。
    assert abs(ev[0][0] - 0.096) < 1e-9
    assert ev[0][1] < 4
    assert abs(ev[0][1] - (2.411 + 0.544)) < 1e-9
    assert abs(ev[1][0] - (6.0 + 0.096)) < 1e-9
    assert ev[1][1] < 10
    assert "举行" in ev[1][2]
    assert abs(ev[2][0] - (12.0 + 0.096)) < 1e-9
    assert ev[2][1] < 14
    # 后一句不提前出现在前一句的声音里。
    assert ev[1][0] >= ev[0][1]
    assert ev[2][0] >= ev[1][1]


def test_short_width_does_not_split_juxing():
    text = "马尼拉举行峰会"
    words = [
        {"text": "马尼拉", "offset": 0.1, "duration": 0.4},
        {"text": "举行", "offset": 0.5, "duration": 0.3},
        {"text": "峰会", "offset": 0.8, "duration": 0.4},
    ]
    lines = Subtitles.lines(text, width=4, words=words)
    assert lines == ["马尼拉", "举行峰会"]
    assert "".join(lines) == text
    _intact(lines, "举行")
    ev = Subtitles.place(text, words, 1.5, width=4)
    assert ev[0] == (1.6, 2.0, "马尼拉")
    assert ev[1][2] == "举行峰会"
    assert abs(ev[1][0] - 2.0) < 1e-9
    assert abs(ev[1][1] - (1.5 + 0.8 + 0.4)) < 1e-9


def test_mismatched_words_keep_the_cue_window():
    from src.renderer import subtitle_events

    cues = [{"start": 0.0, "end": 6.0, "text": BEAT2}]
    voice = {"cues": [{"at": 0.0, "words": [
        {"text": "你好", "offset": 0.2, "duration": 0.3}],
        "timing": Subtitles.TIMING}]}
    seg = {"id": "seg01", "start": 0.0, "audio_in": 0.0, "audio_duration": 6.0}
    ev = subtitle_events({"seg01": BEAT2}, [seg], {"seg01": cues}, {"seg01": voice})
    assert ev == [(0.0, 6.0, BEAT2)]


def test_scale_follows_the_atempo_already_applied():
    scaled = Subtitles.scale(
        [{"text": "举行", "offset": 1.0, "duration": 0.4}], 0.5)
    assert scaled == [{"text": "举行", "offset": 0.5, "duration": 0.2}]


def test_words_jsonl_uses_the_engine_tick():
    raw = '{"type":"WordBoundary","offset":960000,"duration":3360000,"text":"举行"}\n'
    raw += '{"type":"SentenceBoundary","offset":1,"duration":1,"text":"忽略"}\n'
    assert Subtitles.words_from_jsonl(raw) == [
        {"text": "举行", "offset": 0.096, "duration": 0.336}]


def test_synth_edge_requests_word_boundary(tmp_path, monkeypatch):
    from src import narrator

    captured = {}

    class FakeComm:
        def __init__(self, text, voice, rate="+0%", boundary="SentenceBoundary", **kw):
            captured["boundary"] = boundary
            captured["text"] = text
            captured["voice"] = voice
            captured["rate"] = rate

        async def save(self, audio, metadata=None):
            captured["metadata"] = metadata
            Path(audio).write_bytes(b"x" * 3000)
            Path(metadata).write_text(
                '{"type":"WordBoundary","offset":960000,"duration":3360000,"text":"举行"}\n',
                encoding="utf-8")

    monkeypatch.setattr(narrator.edge_tts, "Communicate", FakeComm)
    out = tmp_path / "a.mp3"
    narrator._synth_edge("在马尼拉举行峰会", out, "zh-CN-YunxiNeural", "+8%")
    assert captured["boundary"] == "WordBoundary"
    assert captured["rate"] == "+8%"
    assert captured["voice"] == "zh-CN-YunxiNeural"
    assert narrator.scriptgen.Subtitles.read_words(out) == [
        {"text": "举行", "offset": 0.096, "duration": 0.336}]
    assert not Path(str(out) + ".boundaries.jsonl").exists()


def test_locked_voice_scales_word_clock_onto_the_fitted_wav(tmp_path, monkeypatch):
    from src import narrator

    seg = {"id": "seg01", "narration": BEAT2, "cues": [
        {"start": 6.0, "end": 12.0, "text": BEAT2}]}

    def fake_speak(text, mp3, vcfg, key):
        mp3.write_bytes(b"m" * 2000)
        narrator.scriptgen.Subtitles.write_words(mp3, [
            {"text": BEAT2, "offset": 1.0, "duration": 2.0}])
        return "edge"

    def fake_to_wav(src, dst):
        dst.write_bytes(src.read_bytes())
        return dst

    def fake_fit(src, dst, window):
        dst.write_bytes(b"f" * 2000)
        return 2.0

    monkeypatch.setattr(narrator, "_speak", fake_speak)
    monkeypatch.setattr(narrator, "_to_wav", fake_to_wav)
    monkeypatch.setattr(narrator, "_fit_window", fake_fit)
    monkeypatch.setattr(narrator, "_concat_wavs", lambda paths, dst: 2.0)
    monkeypatch.setattr(narrator.ffmpeg, "probe_duration", lambda path: 4.0)

    item, backend = narrator._voice_locked(seg, tmp_path, {}, "", "")
    cue = item["cues"][0]
    assert backend == "edge"
    assert cue["at"] == 6.0
    assert cue["timing"] == "edge-tts-word"
    assert cue["words"] == [{"text": BEAT2, "offset": 0.5, "duration": 1.0}]
    assert json.loads(Path(cue["wav"] + ".words.json").read_text(encoding="utf-8")) == cue["words"]
