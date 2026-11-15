"""LifeMate routing/execution contracts using synthetic assets and environments."""

from __future__ import annotations

import copy
import json

import pytest

from evals.helpers import ScriptedClient, response, text_block, tool_block
from SOC_AI_TRANSFORM.app import SOC_AI_TRANSFORM
from SOC_AI_TRANSFORM.config import Settings
from SOC_AI_TRANSFORM.db import connect
from SOC_AI_TRANSFORM.lifemate import runner
from SOC_AI_TRANSFORM.lifemate.runner import load_transcripts, prepare_sample, run_sample
from SOC_AI_TRANSFORM.lifemate.skills import BusinessSkills, Selection
from SOC_AI_TRANSFORM.lifemate.tools import (
    EnvironmentAdapter,
    EnvironmentRegistry,
    load_sdk,
    official_environment,
)


class RecordingClient(ScriptedClient):
    def __init__(self, script):
        super().__init__(script)
        self.requests = []

    def _create(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        return super()._create(**kwargs)


class FakeEnvironment:
    def __init__(self):
        self.calls = []

    def call(self, name, arguments):
        self.calls.append({"name": name, "arguments": arguments})
        if name == "contacts.search":
            return {"ok": True, "contacts": [{"id": "observed_contact_id", "name": "Test"}]}
        if name == "contacts.update" and not arguments.get("contact_id"):
            return {"ok": False, "error": "missing contact_id"}
        return {"ok": True}

    def adapter(self):
        return EnvironmentAdapter(self.call, lambda: self.calls, lambda: "ENV_HASH")


def schema(name, properties=None, required=None):
    return {"name": name, "description": name,
            "parameters": {"type": "object", "properties": properties or {},
                           "required": required or []}}


SCHEMAS = [
    schema("contacts.search", {"query": {"type": "string"}}),
    schema("contacts.update", {"contact_id": {"type": "string"}, "phone": {"type": "string"}},
           ["contact_id"]),
    schema("sms.send", {"content": {"type": "string"}}, ["content"]),
    schema("banking.transfer", {"amount": {"type": "integer"}}, ["amount"]),
    schema("sys.ask_missing_info", {"tool_name": {"type": "string"}, "params": {"type": "array"}},
           ["tool_name", "params"]),
    schema("translator.translate", {"text": {"type": "string"}}, ["text"]),
]


@pytest.fixture
def catalog(tmp_path):
    root = tmp_path / "skills_package"
    core = ["rules/thuc-thi-tool.md", "rules/doi-tuong.md", "rules/hop-dong-ke-hoach.md"]
    items = [
        {"skill": "contacts", "description": "Sửa số điện thoại liên hệ",
         "primary_actions": ["contacts.search", "contacts.update"],
         "path": "skills/contacts/SKILL.md"},
        {"skill": "sms", "description": "Gửi tin nhắn",
         "primary_actions": ["sms.send"], "path": "skills/sms/SKILL.md"},
        {"skill": "banking", "description": "Chuyển tiền ngân hàng",
         "primary_actions": ["banking.transfer"], "path": "skills/banking/SKILL.md"},
    ]
    architecture = {"orchestration": "skills/router/SKILL.md", "shared_rules": core,
                    "businesses": [{**item, "shared_rules": core} for item in items]}
    files = {"architecture.json": json.dumps(architecture),
             "business_index.json": json.dumps(items),
             "skills/router/SKILL.md": "SYNTHETIC ROUTER"}
    files.update({item["path"]: f"INSTRUCTIONS {item['skill']}" for item in items})
    files.update({path: f"RULE {path}" for path in core})
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return BusinessSkills(root)


def sample(apps=None):
    return {"id": "synthetic_001", "audio_text": "Đổi số của Test thành 0901234567",
            "context": {"current_time": "2026-11-28T07:10:00+07:00",
                        "timezone": "Asia/Ho_Chi_Minh",
                        "installed_apps": apps if apps is not None else {
                            "contacts": {"tools": ["contacts.search", "contacts.update"]}}},
            "history": [], "label": "GOLD_LABEL_MUST_NOT_ENTER_PROMPT"}


def routed(*skills):
    return response([text_block(json.dumps({"skills": list(skills), "rules": []}))])


def test_router_supports_more_than_two_businesses_and_uses_history(catalog):
    item = sample({"contacts": {"tools": ["contacts.update"]},
                   "sms": {"tools": ["sms.send"]}, "banking": {"tools": ["banking.transfer"]}})
    client = RecordingClient([routed("contacts", "sms", "banking")])
    history = [{"role": "user", "text": "Nhắn mẹ sau khi chuyển tiền thành công"}]
    selected = catalog.select(client, "fake", "Chuyển tiền, nhắn mẹ và sửa số", item["context"], history)
    assert selected.skills == ("contacts", "sms", "banking")
    assert json.loads(client.requests[0]["messages"][0]["content"])["history"] == history
    with pytest.raises(ValueError, match="unavailable"):
        catalog.validate(selected, sample()["context"])
    with pytest.raises(ValueError, match="inapplicable"):
        catalog.validate(Selection(("contacts",), ("../../private.txt",)))
    with pytest.raises(ValueError, match="escapes"):
        catalog.read("../private.txt")


def test_runner_uses_observations_repeats_tools_and_exports_environment_trace(catalog):
    env = FakeEnvironment()
    client = RecordingClient([
        routed("contacts"),
        response([tool_block("contacts__search", {"query": "Test"}, "first")], "tool_use"),
        response([tool_block("contacts__search", {"query": "Test other"}, "second")], "tool_use"),
        response([tool_block("contacts__update", {"contact_id": "observed_contact_id",
                                                  "phone": "0901234567"})], "tool_use"),
        response([text_block("Done")]),
    ])
    item = sample()
    item["history"] = [{"role": "assistant", "tool_calls": [
        {"name": "sms.send", "arguments": {"content": "already sent"}}]}]
    out = run_sample(item, env.adapter(), SCHEMAS, client=client,
                     settings=Settings(model="fake"), catalog=catalog)
    assert out == {"id": item["id"], "tool_calls": env.calls, "state_hash": "ENV_HASH"}
    assert [call["name"] for call in env.calls] == [
        "contacts.search", "contacts.search", "contacts.update"]
    assert "observed_contact_id" in json.dumps(client.requests[-1]["messages"], default=vars)
    assert "GOLD_LABEL_MUST_NOT_ENTER_PROMPT" not in json.dumps(client.requests, default=vars)
    assert {t["name"] for t in client.requests[1]["tools"]} == {
        "contacts__search", "contacts__update", "sys__ask_missing_info"}
    assert "2026-11-28T07:10:00+07:00" in client.requests[1]["messages"][0]["content"]


def test_missing_info_keeps_canonical_tool_name_and_schema_errors_are_not_lost(catalog):
    env = FakeEnvironment()
    client = RecordingClient([
        routed("contacts"),
        response([tool_block("contacts__update", {})], "tool_use"),
        response([tool_block("sys__ask_missing_info", {
            "tool_name": "contacts__update", "params": ["contact_id"]})], "tool_use"),
        response([text_block("Need a contact")]),
    ])
    out = run_sample(sample(), env.adapter(), SCHEMAS, client=client,
                     settings=Settings(model="fake"), catalog=catalog)
    assert len(out["tool_calls"]) == 2
    assert out["tool_calls"][0] == {"name": "contacts.update", "arguments": {}}
    assert out["tool_calls"][1]["arguments"]["tool_name"] == "contacts.update"
    registry = EnvironmentRegistry(sample()["context"], SCHEMAS, env.adapter())
    registry.execute("unknown_tool", {})
    assert env.calls[-1]["name"] == "unknown_tool"
    registry.execute("sys__ask_missing_info", ["invalid object"])
    assert env.calls[-1] == {"name": "sys.ask_missing_info", "arguments": ["invalid object"]}


def test_unseen_app_uses_live_schema_even_without_a_business_skill(catalog):
    env = FakeEnvironment()
    client = RecordingClient([
        response([tool_block("translator__translate", {"text": "hello"})], "tool_use"),
        response([text_block("xin chào")]),
    ])
    item = sample({"translator": {"tools": ["translator.translate"]}})
    item["audio_text"] = "Dịch hello sang tiếng Việt"
    out = run_sample(item, env.adapter(), SCHEMAS, client=client,
                     settings=Settings(model="fake"), catalog=catalog)
    assert out["tool_calls"][0]["name"] == "translator.translate"
    assert len(client.requests) == 2  # no router call when no business candidate exists


def test_no_action_preserves_empty_calls_and_official_hash(catalog):
    env = FakeEnvironment()
    item = sample({})
    item["audio_text"] = "Cảm ơn bạn"
    out = run_sample(item, env.adapter(), SCHEMAS,
                     client=RecordingClient([response([text_block("Không có gì")])]),
                     settings=Settings(model="fake"), catalog=catalog)
    assert out["tool_calls"] == []
    assert out["state_hash"] == "ENV_HASH"


def test_transcripts_require_current_and_history_audio_without_gold_fallback(tmp_path):
    item = sample()
    item.update(audio="audio/synthetic_001/synthetic_001.wav", audio_text="GOLD TEXT")
    item["history"] = [{"role": "user", "audio": "audio/synthetic_001/synthetic_001_u1.wav",
                        "audio_text": "GOLD HISTORY"}]
    path = tmp_path / "transcripts.json"
    path.write_text(json.dumps([
        {"audio": item["audio"], "transcript": "ASR CURRENT"},
        {"audio": item["history"][0]["audio"], "transcript": "ASR HISTORY"},
    ]))
    data = load_transcripts(path)
    prepared = prepare_sample(item, data)
    assert prepared["audio_text"] == "ASR CURRENT"
    assert prepared["history"][0]["text"] == "ASR HISTORY"
    assert "label" not in prepared
    with pytest.raises(ValueError, match="Missing transcript"):
        prepare_sample(item, {"synthetic_001": "only current"})
    whisper = tmp_path / "whisper.jsonl"
    whisper.write_text(json.dumps({"id": "synthetic_001", "phowhisper_transcript": "ASR"}) + "\n")
    assert load_transcripts(whisper) == {"synthetic_001": "ASR"}


def test_sdk_imports_are_isolated_by_split_and_sessions_are_created_once(tmp_path):
    for split in ("train", "public_test"):
        path = tmp_path / split / "zaic_tools" / "__init__.py"
        path.parent.mkdir(parents=True)
        path.write_text(f"""TAG = {split!r}
created = []
class ToolEnv:
    def __init__(self, split, sample_id, root):
        created.append(sample_id)
    def call(self, name, args): return {{'tag': TAG}}
    def get_tool_calls(self): return []
    def get_state_hash(self): return TAG
""")
    train = official_environment(tmp_path, "train", "synthetic")
    public = official_environment(tmp_path, "public_test", "synthetic")
    assert train.call("x", {}) == {"tag": "train"}
    assert public.call("x", {}) == {"tag": "public_test"}
    assert load_sdk(tmp_path.resolve(), "train").created == ["synthetic"]
    assert load_sdk(tmp_path.resolve(), "public_test").created == ["synthetic"]


def test_router_errors_do_not_turn_into_out_of_scope_predictions(catalog):
    with pytest.raises(ValueError, match="valid JSON"):
        catalog.select(RecordingClient([response([text_block("not json")])]),
                       "fake", "Sửa số Test", sample()["context"])


def test_failed_run_saves_attempts_without_reset_or_overwrite(tmp_path, catalog, monkeypatch):
    from types import SimpleNamespace

    root = tmp_path / "dataset"
    split = root / "train"
    split.mkdir(parents=True)
    (split / "train_tools_catalog.json").write_text(json.dumps({"apps": [{"tools": SCHEMAS}]}))
    (split / "train.jsonl").write_text(json.dumps(sample()) + "\n")
    created = []
    env = FakeEnvironment()

    def factory(*args):
        created.append(args)
        return env.adapter()

    def fail_after_call(item, environment, *args, **kwargs):
        environment.call("contacts.update", {})
        raise RuntimeError("provider unavailable after first attempt")

    monkeypatch.setattr(runner, "official_environment", factory)
    monkeypatch.setattr(runner, "get_client", lambda _: object())
    monkeypatch.setattr(runner, "load_settings", lambda: Settings(home=tmp_path / "home", model="fake"))
    monkeypatch.setattr(runner, "run_sample", fail_after_call)
    output = tmp_path / "submission.jsonl"
    args = SimpleNamespace(data_root=root, split="train", transcripts=None,
                           ids=None, limit=1, output=output)
    with pytest.raises(RuntimeError, match="provider unavailable"):
        runner.run_split(args, catalog)
    assert len(created) == 1
    saved = json.loads(output.read_text())
    assert saved["tool_calls"] == env.calls
    assert saved["state_hash"] == "ENV_HASH"
    with pytest.raises(FileExistsError):
        runner.run_split(args, catalog)
    assert len(created) == 1


def test_main_harness_keeps_memory_and_records_sdk_calls_without_leaking_other_runs(tmp_path, catalog):
    home = tmp_path / "home"
    home.mkdir()
    conn = connect(home)
    conn.execute("INSERT INTO facts(subject, content, source) VALUES (?,?,?)",
                 ("owner", "PRIVATE_MEMORY_FROM_ANOTHER_RUN", "user"))
    conn.commit()
    env = FakeEnvironment()
    client = RecordingClient([
        routed("contacts"),
        response([tool_block("contacts__search", {"query": "Test"})], "tool_use"),
        response([text_block("Read the contact")]),
    ])
    item = sample()
    agent = SOC_AI_TRANSFORM.for_lifemate(item, env.adapter(), SCHEMAS, conn=conn, client=client,
                                        settings=Settings(home=home, model="fake"))
    agent.session.history = [{"role": "user", "content": "OTHER_RUN_SHOULD_NOT_BE_REPLAYED"}]

    def no_personal_retrieval(*args, **kwargs):
        raise AssertionError("Personal memory must not enter competition inference")

    agent.memory.gated_retrieve = no_personal_retrieval
    out = agent.respond_lifemate(item, catalog=catalog, session_id="lifemate-test")
    assert out["tool_calls"] == env.calls
    assert conn.execute("SELECT content FROM facts").fetchone()[0] == "PRIVATE_MEMORY_FROM_ANOTHER_RUN"
    saved = conn.execute("SELECT meta FROM chat_log WHERE role='assistant' AND source='lifemate'").fetchone()
    meta = json.loads(saved[0])
    assert meta["state_hash"] == "ENV_HASH"
    assert meta["tool_calls"] == env.calls
    assert meta["skills"] == ["contacts"]
    assert "PRIVATE_MEMORY_FROM_ANOTHER_RUN" not in json.dumps(client.requests, default=vars)
    assert "OTHER_RUN_SHOULD_NOT_BE_REPLAYED" not in json.dumps(client.requests, default=vars)
    assert not {"save_note", "create_event", "send_message"}.intersection(
        tool["name"] for tool in agent.tools.schemas())
    assert any('"tool": "contacts.search"' in line for line in agent.tracer.path.read_text().splitlines())
    with pytest.raises(RuntimeError, match="no implicit retry"):
        agent.respond_lifemate(item, catalog=catalog)
    assert len(env.calls) == 1
    conn.close()


def test_main_harness_logs_partial_execution_when_model_fails(tmp_path, catalog):
    env = FakeEnvironment()
    client = RecordingClient([
        routed("contacts"),
        response([tool_block("contacts__update", {})], "tool_use"),
    ])
    item = sample()
    agent = SOC_AI_TRANSFORM.for_lifemate(item, env.adapter(), SCHEMAS, client=client,
                                        settings=Settings(home=tmp_path / "home", model="fake"))
    with pytest.raises(IndexError):
        agent.respond_lifemate(item, catalog=catalog)
    saved = agent.conn.execute("SELECT meta FROM chat_log WHERE role='assistant'").fetchone()
    meta = json.loads(saved[0])
    assert meta["error"].startswith("IndexError")
    assert meta["tool_calls"] == [{"name": "contacts.update", "arguments": {}}]
    assert meta["state_hash"] == "ENV_HASH"
    agent.conn.close()
