"""The dashboard chat uses LifeMate tools, with no fallback to demo actions."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import replace
from uuid import uuid4

from SOC_AI_TRANSFORM.config import load_settings
from SOC_AI_TRANSFORM.db import connect
from SOC_AI_TRANSFORM.lifemate import ui
from SOC_AI_TRANSFORM.memory import Memory


def is_tool_question(text: str) -> bool:
    folded = unicodedata.normalize("NFKD", text.casefold()).replace("đ", "d")
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    folded = " ".join(re.findall(r"[a-z0-9]+", folded))
    folded = re.sub(r"^(?:hay |cho toi biet |cho minh biet )", "", folded)
    return bool(re.fullmatch(
        r"(?:ban (?:hien |dang )?co (?:nhung |cac )?(?:tool|tools|cong cu)(?: gi| nao)?"
        r"|(?:liet ke|danh sach) (?:cac |nhung )?(?:tool|tools|cong cu)(?: hien co| cua ban)?"
        r"|ban (?:co the )?lam (?:duoc )?gi"
        r"|what (?:tools (?:do you have|are available)|are your tools|can you do)"
        r"|which tools can you use|list your tools)", folded))


def _record(message: str, reply: str, session_id: str, meta: dict) -> None:
    settings = replace(load_settings(), semantic_store="sqlite", episodic_store="sqlite")
    settings.ensure_home()
    conn = connect(settings.home)
    try:
        Memory(conn, settings, client=None).log_chat(message, reply, session_id=session_id,
                                                    source="dashboard", meta=meta)
    finally:
        conn.close()


def stream(message: str, emit, *, scope: dict | None = None, session_id: str,
           run_id: str | None = None) -> None:
    scope = scope or {}
    if not isinstance(scope, dict):
        raise TypeError("LifeMate scope must contain split and sample_id")
    split, sample_id = scope.get("split", "public_test"), scope.get("sample_id", "")
    settings = load_settings()
    metadata = {"mode": "lifemate", "split": split, "sample_id": sample_id,
                "model": settings.model, "provider": settings.provider,
                "usage": {"in": 0, "out": 0, "calls": 0}, "tools": [], "iterations": 0}
    if is_tool_question(message):
        catalog = ui.tools(split, sample_id)
        available = [tool for tool in catalog["tools"] if tool["enabled"] or not sample_id]
        heading = (f"Trong mẫu **{split}/{sample_id}**, tôi được dùng {len(available)} tool của BTC:"
                   if sample_id else f"Catalog **{split}** có {len(available)} tool của BTC:")
        lines = [heading, ""]
        lines.extend(f"- `{tool['name']}` — {tool.get('description', '')}" for tool in available)
        lines.extend(["", "Các tool này chạy qua SDK zaic_tools trên môi trường giả lập của mẫu."])
        if not sample_id:
            lines.append("Chọn mẫu ở LifeMate để xác định tool nào được phép thực thi.")
        reply = "\n".join(lines)
        metadata["operation"] = "tool_catalog"
        _record(message, reply, session_id, metadata)
        emit("done", {"reply": reply, **metadata})
        return
    if not sample_id:
        reply = "Chọn bộ dữ liệu và mẫu ở trang LifeMate trước khi gửi yêu cầu thực thi trong chat."
        _record(message, reply, session_id, metadata)
        emit("done", {"reply": reply, **metadata, "operation": "scope_required"})
        return
    ui.stream({"run_id": run_id or str(uuid4()), "split": split, "sample_id": sample_id,
               "text": message}, emit, session_id=session_id, source="dashboard")
