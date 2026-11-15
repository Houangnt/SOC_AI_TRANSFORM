"""The wake-word matcher is a pure function — so it gets deterministic evals.
Whisper mangles phrases in predictable ways; these cases pin the fuzziness."""

import pytest

from SOC_AI_TRANSFORM.gateway.voice import matches_wake

SHOULD_WAKE = [
    ("SOC_AI_TRANSFORM SOC_AI_TRANSFORM", "SOC_AI_TRANSFORM SOC_AI_TRANSFORM"),
    ("SOC_AI_TRANSFORM, SOC_AI_TRANSFORM!", "SOC_AI_TRANSFORM SOC_AI_TRANSFORM"),            # punctuation
    ("SOC_AI_TRANSFORMSOC_AI_TRANSFORM", "SOC_AI_TRANSFORM SOC_AI_TRANSFORM"),               # whisper drops the space
    ("so anyway SOC_AI_TRANSFORM SOC_AI_TRANSFORM schedule it", "SOC_AI_TRANSFORM SOC_AI_TRANSFORM"),  # embedded in speech
    ("SOC_AI_TRANSFORM tuni", "SOC_AI_TRANSFORM SOC_AI_TRANSFORM"),              # one-letter mangle → fuzzy match
    ("Hey SOC_AI_TRANSFORM", "hey SOC_AI_TRANSFORM"),
    ("hey computer, what's up", "hey computer"),
    # regression from the first live session: whisper wrote the wake word in
    # kana — variants after a comma cover other scripts
    ("わくわく", "SOC_AI_TRANSFORM SOC_AI_TRANSFORM,わくわく"),
    ("わくわくわく", "SOC_AI_TRANSFORM SOC_AI_TRANSFORM,わくわく"),
    ("小助手你好", "SOC_AI_TRANSFORM SOC_AI_TRANSFORM,小助手"),
]

SHOULD_NOT_WAKE = [
    ("what a nice day", "SOC_AI_TRANSFORM SOC_AI_TRANSFORM"),
    ("wake up call at nine", "SOC_AI_TRANSFORM SOC_AI_TRANSFORM"),
    ("", "SOC_AI_TRANSFORM SOC_AI_TRANSFORM"),
    ("SOC_AI_TRANSFORM SOC_AI_TRANSFORM", ""),                        # no wake word configured
    ("walk to work", "SOC_AI_TRANSFORM SOC_AI_TRANSFORM"),
]


@pytest.mark.parametrize("heard,wake", SHOULD_WAKE, ids=[h for h, _ in SHOULD_WAKE])
def test_wakes(heard, wake):
    assert matches_wake(heard, wake)


@pytest.mark.parametrize("heard,wake", SHOULD_NOT_WAKE, ids=[h or "empty" for h, _ in SHOULD_NOT_WAKE])
def test_stays_asleep(heard, wake):
    assert not matches_wake(heard, wake)
