"""Offline harness regressions for history, stopping and iteration limits."""

from __future__ import annotations

from evals.helpers import (
    ScriptedClient,
    make_soc_ai_transform,
    response,
    text_block,
    tool_block,
)


def test_history_records_tool_use(tmp_path):
    """Regression companion: the next turn's working memory must show the
    [tools used: ...] line so the model knows it already acted."""
    gate = response([text_block('{"retrieve": false, "query": "", "reason": "test"}')])
    script = [gate] + [
        response([tool_block("unknown_tool", {"value": "X"})], "tool_use"),
        response([text_block("Done.")]),
    ]
    app = make_soc_ai_transform(tmp_path / "home", client=ScriptedClient(script))
    app.respond("book X monday 9am")
    assert "[tools used: unknown_tool" in app.session.history[-1]["content"]


def test_no_tool_turn_ends_loop_in_one_iteration(tmp_path):
    script = [
        response([text_block('{"retrieve": false, "query": "", "reason": "test"}')]),
        response([text_block("Paris.")]),
    ]
    app = make_soc_ai_transform(tmp_path / "home", client=ScriptedClient(script))
    result = app.respond("capital of france?")
    assert result.reply == "Paris." and result.iterations == 1 and result.tool_calls == []


def test_iteration_guardrail_stops_runaway_loop(tmp_path):
    gate = response([text_block('{"retrieve": false, "query": "", "reason": "test"}')])
    runaway = [
        response([tool_block("unknown_tool", {"value": "x"}, f"tu_{i}")], "tool_use")
        for i in range(99)
    ]
    app = make_soc_ai_transform(tmp_path / "home", client=ScriptedClient([gate] + runaway), max_iterations=3)
    result = app.respond("loop forever")
    assert result.iterations == 3 and "iteration limit" in result.reply
