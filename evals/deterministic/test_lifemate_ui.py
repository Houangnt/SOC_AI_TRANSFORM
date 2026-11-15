"""LifeMate dashboard contracts, using synthetic inputs and an injected runner."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from SOC_AI_TRANSFORM.config import Settings
from SOC_AI_TRANSFORM.lifemate import runner, ui
from SOC_AI_TRANSFORM.lifemate.tools import EnvironmentAdapter
from SOC_AI_TRANSFORM.ops.dashboard import Handler


@pytest.fixture
def world(tmp_path, monkeypatch):
    data = tmp_path / "data"
    split = data / "public_test"
    split.mkdir(parents=True)
    item = {"id": "synthetic", "audio": "audio/synthetic/synthetic.wav",
            "context": {"current_time": "2026-11-01T09:00:00+07:00", "timezone": "Asia/Ho_Chi_Minh",
                        "installed_apps": {"contacts": {"tools": ["contacts.search"]}}},
            "history": [{"role": "user", "audio": "audio/synthetic/synthetic_u1.wav"},
                        {"role": "assistant", "text": "previous reply"}],
            "label": {"final_state": "GOLD_MUST_NEVER_BE_EXPOSED"}}
    (split / "public_test.jsonl").write_text(json.dumps(item) + "\n", encoding="utf-8")
    (split / "public_test_tools_catalog.json").write_text(json.dumps({"apps": [
        {"id": "contacts", "tools": [
            {"name": "contacts.search", "parameters": {"type": "object", "properties": {}}}]},
        {"id": "sys", "tools": [
            {"name": "sys.ask_missing_info", "parameters": {"type": "object"}}]},
        {"id": "banking", "tools": [
            {"name": "banking.transfer", "parameters": {"type": "object"}}]},
    ]}))
    transcript_path = tmp_path / "transcripts.json"
    transcript_path.write_text(json.dumps([
        {"audio": item["audio"], "transcript": "ASR current"},
        {"audio": item["history"][0]["audio"], "transcript": "ASR history"},
    ]))
    monkeypatch.setenv("SOC_AI_TRANSFORM_LIFEMATE_DATA_ROOT", str(data))
    monkeypatch.setenv("SOC_AI_TRANSFORM_LIFEMATE_TRANSCRIPTS", str(transcript_path))
    settings = Settings(home=tmp_path / "home", provider="fake", model="fake-model")
    monkeypatch.setattr(ui, "load_settings", lambda: settings)
    monkeypatch.setattr("SOC_AI_TRANSFORM.app.get_client", lambda _: object())
    catalog = SimpleNamespace(
        index={"contacts": {"skill": "contacts", "title": "Danh bạ", "description": "Sửa liên hệ",
                            "path": "skills/contacts/SKILL.md"}},
        architecture={"shared_rules": ["rules/test.md"], "orchestration": "skills/router/SKILL.md"},
        read=lambda path: "SYNTHETIC INSTRUCTIONS " + path,
    )
    monkeypatch.setattr(ui, "BusinessSkills", lambda: catalog)
    calls, created = [], []

    def environment(*args):
        created.append(args)
        def call(name, arguments):
            calls.append({"name": name, "arguments": arguments})
            return {"ok": True}
        return EnvironmentAdapter(call, lambda: calls, lambda: "official_hash")

    def run(item, env, schemas, **kwargs):
        observer = kwargs["observer"]
        observer("business_skills", {"skills": ["contacts"], "rules": []})
        output = env.call("contacts.search", {"query": item["audio_text"]})
        observer("tool", {"tool": "contacts__search", "args": {"query": item["audio_text"]},
                          "output": json.dumps(output)})
        observer("lifemate_reply", {"reply": "Done", "iterations": 1})
        return {"id": item["id"], "tool_calls": env.get_tool_calls(),
                "state_hash": env.get_state_hash()}

    monkeypatch.setattr(ui, "official_environment", environment)
    monkeypatch.setattr(runner, "run_sample", run)
    return SimpleNamespace(data=data, settings=settings, calls=calls, created=created,
                           item=item, transcripts=transcript_path)


def handler(path, payload=None):
    request = Handler.__new__(Handler)
    request.path = path
    body = json.dumps(payload or {}).encode()
    request.headers = {"Content-Length": str(len(body))}
    request.rfile = io.BytesIO(body)
    request.wfile = io.BytesIO()
    request.send_response = lambda status: None
    request.send_header = lambda *args: None
    request.end_headers = lambda: None
    return request


def test_preview_uses_asr_history_and_never_opens_an_environment(world):
    metadata = ui.info()
    assert metadata["available"] is True
    preview = ui.sample("public_test", "synthetic")
    assert preview["text"] == "ASR current"
    assert preview["history"][0]["text"] == "ASR history"
    assert preview["transcript_error"] == ""
    assert "GOLD_MUST_NEVER_BE_EXPOSED" not in json.dumps(preview)
    assert world.created == []
    with pytest.raises(ValueError, match="Unsupported"):
        ui.samples("../../secrets")
    with pytest.raises(ValueError, match="Unknown"):
        ui.sample("public_test", "../private")


def test_missing_history_blocks_run_before_sdk_creation(world):
    world.transcripts.write_text(json.dumps([
        {"audio": world.item["audio"], "transcript": "only current"}]))
    assert ui.sample("public_test", "synthetic")["transcript_error"]
    with pytest.raises(ValueError, match="Missing transcript"):
        ui.stream({"run_id": str(uuid4()), "split": "public_test", "sample_id": "synthetic",
                   "text": "manual current"}, lambda *args: None)
    assert world.created == []


def test_stream_exports_real_trace_and_duplicate_run_does_not_reset(world):
    payload = {"run_id": str(uuid4()), "split": "public_test", "sample_id": "synthetic",
               "text": "edited current"}
    events = []
    ui.stream(payload, lambda kind, data: events.append((kind, data)))
    assert len(world.created) == 1
    assert events[-1][0] == "done"
    result = events[-1][1]
    assert result["submission"]["tool_calls"] == world.calls
    assert result["submission"]["state_hash"] == "official_hash"
    assert result["tools"][0]["tool"] == "contacts.search"
    assert world.calls[0]["arguments"]["query"] == "edited current"
    ui.stream(payload, lambda *args: None)
    assert len(world.created) == 1


def test_failure_saves_partial_calls_without_retry(world, monkeypatch):
    def fail(item, env, *args, **kwargs):
        env.call("contacts.search", {})
        raise RuntimeError("provider disconnected")
    monkeypatch.setattr(runner, "run_sample", fail)
    events = []
    payload = {"run_id": str(uuid4()), "split": "public_test", "sample_id": "synthetic",
               "text": "request"}
    ui.stream(payload, lambda kind, data: events.append((kind, data)))
    result = events[-1][1]
    assert "provider disconnected" in result["error"]
    assert result["submission"]["tool_calls"] == world.calls
    assert len(world.created) == 1
    ui.stream(payload, lambda *args: None)
    assert len(world.created) == 1


@pytest.mark.parametrize("url", ["/api/lifemate", "/api/lifemate/samples?split=public_test",
                                "/api/lifemate/sample?split=public_test&id=synthetic",
                                "/api/lifemate/skill?id=contacts",
                                "/api/lifemate/tools?split=public_test&id=synthetic"])
def test_get_endpoints_are_wired_without_model_or_sdk_calls(world, url):
    request = handler(url)
    request.do_GET()
    payload = json.loads(request.wfile.getvalue())
    assert "error" not in payload
    assert "GOLD_MUST_NEVER_BE_EXPOSED" not in request.wfile.getvalue().decode()
    assert world.created == []


def test_post_endpoint_streams_selected_business_and_submission(world):
    request = handler("/api/lifemate/run", {
        "run_id": str(uuid4()), "split": "public_test", "sample_id": "synthetic", "text": "request"})
    request.do_POST()
    events = [json.loads(line.removeprefix("data: "))
              for line in request.wfile.getvalue().decode().splitlines() if line.startswith("data: ")]
    assert any(event["kind"] == "business_skills" for event in events)
    assert events[-1]["submission"]["state_hash"] == "official_hash"
    assert len(world.created) == 1


def test_tool_catalog_marks_only_installed_tools_and_sys_enabled(world):
    payload = ui.tools("public_test", "synthetic")
    assert {t["name"] for t in payload["tools"] if t["enabled"]} == {
        "contacts.search", "sys.ask_missing_info"}
    assert payload["enabled_count"] == 2
    assert len(payload["tools"]) == 3
    assert world.created == []
