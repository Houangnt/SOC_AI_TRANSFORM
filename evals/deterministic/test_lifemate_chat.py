"""Overview chat must use the same competition tool scope as the LifeMate page."""

import json

import pytest

from evals.deterministic.test_lifemate_ui import handler
from evals.deterministic.test_lifemate_ui import world as _world
from SOC_AI_TRANSFORM.db import connect
from SOC_AI_TRANSFORM.lifemate import chat
from SOC_AI_TRANSFORM.ops import dashboard

world = _world


@pytest.fixture
def chat_world(world, monkeypatch):
    monkeypatch.setattr(chat, "load_settings", lambda: world.settings)
    monkeypatch.setattr(dashboard.browser_agent, "current", lambda: None)
    monkeypatch.setattr(dashboard, "dash_session", lambda: "chat-test-session")
    monkeypatch.setattr(dashboard, "get_agent", lambda: pytest.fail("Legacy chat agent was used"))
    return world


@pytest.mark.parametrize("message", ["Bạn có những tool nào?", "What tools do you have?",
                                     "Liệt kê các công cụ", "Bạn làm được gì?"])
def test_capabilities_use_installed_catalog_without_sdk_or_llm(chat_world, message):
    result = dashboard.chat(message, scope={"split": "public_test", "sample_id": "synthetic"})
    assert "contacts.search" in result["reply"]
    assert "sys.ask_missing_info" in result["reply"]
    assert "banking.transfer" not in result["reply"]
    assert "save_note" not in result["reply"] and "local outbox" not in result["reply"]
    assert result["usage"]["calls"] == 0
    assert chat_world.created == []
    conn = connect(chat_world.settings.home)
    saved = conn.execute("SELECT meta FROM chat_log WHERE role='assistant'").fetchone()
    assert json.loads(saved[0])["operation"] == "tool_catalog"
    conn.close()


def test_execution_request_is_not_mistaken_for_a_tool_catalog_question(chat_world):
    assert not chat.is_tool_question("Hãy đặt xe rồi liệt kê các tool đã dùng")
    result = dashboard.chat("Tìm liên hệ Test", scope={"split": "public_test", "sample_id": "synthetic"})
    assert result["submission"]["tool_calls"] == chat_world.calls
    assert len(chat_world.created) == 1
    conn = connect(chat_world.settings.home)
    row = conn.execute("SELECT session_id,source,meta FROM chat_log WHERE role='assistant'").fetchone()
    assert row["session_id"] == "chat-test-session" and row["source"] == "dashboard"
    assert json.loads(row["meta"])["mode"] == "lifemate"
    conn.close()


def test_missing_scope_never_falls_back_to_local_demo_tools(chat_world):
    result = dashboard.chat("Đặt lịch họp ngày mai")
    assert result["operation"] == "scope_required"
    assert chat_world.created == []


@pytest.mark.parametrize("path", ["/api/chat", "/api/chat/stream"])
def test_chat_http_routes_forward_the_selected_sample(chat_world, path):
    request = handler(path, {"message": "Bạn có tool gì?",
                            "lifemate": {"split": "public_test", "sample_id": "synthetic"}})
    request.do_POST()
    body = request.wfile.getvalue().decode()
    if path.endswith("/stream"):
        result = json.loads(next(line[6:] for line in body.splitlines() if line.startswith("data: ")))
    else:
        result = json.loads(body)
    assert "contacts.search" in result["reply"]
    assert "banking.transfer" not in result["reply"]
    assert chat_world.created == []


def test_default_registry_and_display_catalog_no_longer_expose_retired_tools(chat_world, monkeypatch):
    from SOC_AI_TRANSFORM.tools import build_registry

    chat_world.settings.ensure_home()
    conn = connect(chat_world.settings.home)
    registry = build_registry(conn, chat_world.settings)
    retired = {"create_event", "list_events", "save_note", "send_message"}
    assert not retired.intersection(t["name"] for t in registry.schemas())
    monkeypatch.setattr(dashboard, "load_settings", lambda: chat_world.settings)
    assert not retired.intersection(t["name"] for t in dashboard.tools_info()["catalog"])
    conn.close()
