"""Local dashboard access to input samples and the real LifeMate runner."""

from __future__ import annotations

import json
import os
import threading
from functools import lru_cache
from pathlib import Path
from uuid import UUID

from SOC_AI_TRANSFORM.config import load_settings
from SOC_AI_TRANSFORM.lifemate.runner import load_transcripts, prepare_sample
from SOC_AI_TRANSFORM.lifemate.skills import BusinessSkills, allowed_tools
from SOC_AI_TRANSFORM.lifemate.tools import official_environment

SPLITS = ("train", "public_test")
_LOCK = threading.Lock()
_ACTIVE: set[str] = set()


def data_root() -> Path:
    default = Path(__file__).resolve().parents[3] / "train+public_test"
    return Path(os.getenv("SOC_AI_TRANSFORM_LIFEMATE_DATA_ROOT", str(default))).resolve()


@lru_cache(maxsize=4)
def _inputs(path: Path, modified: int) -> dict[str, dict]:
    result = {}
    with path.open(encoding="utf-8") as source:
        for line in source:
            if line.strip():
                item = json.loads(line)
                # Never expose labels, final_state or gold tool results.
                result[item["id"]] = {key: item[key] for key in (
                    "id", "audio", "audio_text", "context", "history") if key in item}
    return result


def inputs(split: str) -> dict[str, dict]:
    if split not in SPLITS:
        raise ValueError("Unsupported split")
    path = data_root() / split / f"{split}.jsonl"
    return _inputs(path, path.stat().st_mtime_ns)


@lru_cache(maxsize=2)
def _transcripts(path: Path, modified: int) -> dict[str, str]:
    return load_transcripts(path)


def transcripts() -> dict[str, str]:
    default = data_root().parent / "transcripts.json"
    path = Path(os.getenv("SOC_AI_TRANSFORM_LIFEMATE_TRANSCRIPTS", str(default))).resolve()
    return _transcripts(path, path.stat().st_mtime_ns) if path.is_file() else {}


def _enriched(split: str, sample_id: str) -> dict:
    item = inputs(split).get(sample_id)
    if item is None:
        raise ValueError("Unknown sample ID")
    item = json.loads(json.dumps(item))
    mapping = transcripts()
    spoken = [item] + [t for t in item.get("history", []) if t.get("role") == "user"]
    for turn in spoken:
        if not turn.get("audio_text") and turn.get("audio"):
            key = Path(turn["audio"].replace("\\", "/")).stem
            turn["audio_text"] = mapping.get(key, "")
    return item


def _prepare(split: str, sample_id: str, text: str, asr_transcripts: dict | None = None) -> dict:
    item = _enriched(split, sample_id)
    if asr_transcripts is not None:
        if not isinstance(asr_transcripts, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) or not v.strip()
            for k, v in asr_transcripts.items()
        ):
            raise ValueError("Transcript ASR không hợp lệ")
        # Require every spoken history turn from the ASR request, never substitute gold.
        for turn in item.get("history", []):
            if turn.get("role") == "user" and turn.get("audio"):
                key = Path(turn["audio"].replace("\\", "/")).stem
                turn["audio_text"] = asr_transcripts.get(key, "")
    item["audio_text"] = text
    return prepare_sample(item)


def audio_path(split: str, sample_id: str, audio: str | None = None) -> Path:
    item = inputs(split).get(sample_id)
    if item is None:
        raise ValueError("Unknown sample ID")
    root = (data_root() / split).resolve()
    path = (root / (audio or item.get("audio", "")).replace("\\", "/")).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("Không tìm thấy audio trong bộ dữ liệu")
    return path


def recognize(payload: dict) -> dict:
    """Prepare all speech for a sample without creating or executing a ToolEnv."""
    import base64
    import binascii

    from SOC_AI_TRANSFORM.lifemate import asr

    split, sample_id = payload.get("split", ""), payload.get("sample_id", "")
    source = inputs(split).get(sample_id)
    if source is None:
        raise ValueError("Unknown sample ID")
    mode = payload.get("mode", "live")
    if mode not in ("live", "saved"):
        raise ValueError("Chế độ ASR không hợp lệ")
    item = json.loads(json.dumps(source))
    spoken = [item] + [t for t in item.get("history", []) if t.get("role") == "user"]
    saved = asr.predictions() if mode == "saved" else {}
    mapping, details = {}, []
    for index, turn in enumerate(spoken):
        if not turn.get("audio"):
            continue
        key = Path(turn["audio"].replace("\\", "/")).stem
        if mode == "saved":
            text = saved.get(key, "")
            if not text:
                raise ValueError(f"Chưa có prediction cho {key}. Hãy chọn Chạy ASR từ audio.")
            detail = {"source": "evaluation_improved_v2"}
        else:
            if index == 0 and payload.get("audio_base64"):
                try:
                    raw = base64.b64decode(payload["audio_base64"], validate=True)
                except (ValueError, binascii.Error) as exc:
                    raise ValueError("Dữ liệu audio tải lên không hợp lệ") from exc
            else:
                path = audio_path(split, sample_id, turn["audio"])
                if path.stat().st_size > asr.MAX_AUDIO_BYTES:
                    raise ValueError("Audio vượt quá 16 MB")
                raw = path.read_bytes()
            detail = asr.transcribe(raw)
            text = detail["text"]
        turn["audio_text"] = text
        mapping[key] = text
        details.append({"audio": key, "text": text, **detail})
    prepared = prepare_sample(item)
    return {"text": prepared["audio_text"], "history": prepared["history"],
            "transcripts": mapping, "mode": mode, "clips": details}


def info() -> dict:
    from SOC_AI_TRANSFORM.lifemate import asr

    catalog = BusinessSkills()
    available = [split for split in SPLITS if (data_root() / split / f"{split}.jsonl").is_file()]
    settings = load_settings()
    return {"available": bool(available), "splits": available,
            "provider": settings.provider, "model": settings.model,
            "skills": [{"id": item["skill"], "title": item.get("title", item["skill"]),
                        "description": item["description"]} for item in catalog.index.values()],
            "orchestration": 1, "rules": len(catalog.architecture["shared_rules"]),
            "asr": asr.status()}


def samples(split: str) -> dict:
    return {"samples": [{"id": item["id"]} for item in inputs(split).values()]}


def sample(split: str, sample_id: str) -> dict:
    from SOC_AI_TRANSFORM.lifemate import asr

    item = _enriched(split, sample_id)
    text = item.get("audio_text", "")
    missing = ""
    try:
        # A blank current transcript can be entered in the UI. Historical speech
        # must still be available before execution is allowed.
        prepared = prepare_sample({**item, "audio_text": text or "(preview)"})
    except ValueError as exc:
        missing = str(exc)
        prepared = {"history": []}
    key = Path(item.get("audio", "").replace("\\", "/")).stem
    return {"id": sample_id, "text": text, "context": item["context"],
            "audio_available": bool(item.get("audio")),
            "saved_asr_available": key in asr.predictions(),
            "history": prepared["history"], "transcript_error": missing}


def skill(skill_id: str) -> dict:
    catalog = BusinessSkills()
    if skill_id == "dieu-phoi-nghiep-vu":
        path = catalog.architecture["orchestration"]
    elif skill_id in catalog.index:
        path = catalog.index[skill_id]["path"]
    else:
        raise ValueError("Unknown business skill")
    return {"id": skill_id, "instructions": catalog.read(path)}


def catalog_for(split: str) -> dict:
    if split not in SPLITS:
        raise ValueError("Unsupported split")
    path = data_root() / split / f"{split}_tools_catalog.json"
    return json.loads(path.read_text(encoding="utf-8"))


def tools(split: str, sample_id: str = "") -> dict:
    catalog = catalog_for(split)
    allowed = None
    if sample_id:
        item = inputs(split).get(sample_id)
        if item is None:
            raise ValueError("Unknown sample ID")
        allowed = allowed_tools(item["context"])
    result = [{**tool, "app": app["id"],
               "enabled": tool["name"] in allowed if allowed is not None else None}
              for app in catalog["apps"] for tool in app["tools"]]
    return {"split": split, "sample_id": sample_id, "tools": result,
            "enabled_count": sum(t["enabled"] is True for t in result),
            "schema_version": catalog.get("schema_version", "")}


def stream(payload: dict, emit, *, session_id: str | None = None, source: str = "lifemate") -> None:
    from SOC_AI_TRANSFORM.app import SOC_AI_TRANSFORM

    run_id = str(UUID(payload.get("run_id", "")))
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Nhập transcript trước khi chạy")
    split, sample_id = payload.get("split", ""), payload.get("sample_id", "")
    item = _prepare(split, sample_id, text.strip(), payload.get("asr_transcripts"))
    catalog = BusinessSkills()
    root = data_root()
    catalog_data = catalog_for(split)
    schemas = [tool for app in catalog_data["apps"] for tool in app["tools"]]
    aliases = {tool["name"].replace(".", "__"): tool["name"] for tool in schemas}
    settings = load_settings()
    output = settings.home / "lifemate" / "ui" / f"{run_id}.json"
    with _LOCK:
        if run_id in _ACTIVE:
            emit("done", {"error": "Lượt này đang chạy; không tạo lại môi trường."})
            return
        if output.is_file():
            emit("done", json.loads(output.read_text(encoding="utf-8")))
            return
        _ACTIVE.add(run_id)
    result = {"run_id": run_id, "split": split, "sample_id": sample_id,
              "mode": "lifemate", "provider": settings.provider, "model": settings.model,
              "skills": [], "rules": [], "tools": [], "reply": ""}
    env = None
    harness = None

    def observer(kind, event):
        event = dict(event)
        if kind == "business_skills":
            result.update(skills=event["skills"], rules=event["rules"])
        elif kind == "tool":
            event["tool"] = aliases.get(event["tool"], event["tool"])
            result["tools"].append(event)
        elif kind == "lifemate_reply":
            result.update(event)
        emit(kind, event)

    try:
        emit("started", {"run_id": run_id, "sample_id": sample_id})
        env = official_environment(root, split, sample_id)
        harness = SOC_AI_TRANSFORM.for_lifemate(item, env, schemas, settings=settings)
        result["submission"] = harness.respond_lifemate(
            item, catalog=catalog, observer=observer,
            session_id=session_id or f"lifemate-{run_id}", source=source)
    except (Exception, SystemExit) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        if env is not None:
            result["submission"] = {"id": sample_id, "tool_calls": env.get_tool_calls(),
                                    "state_hash": env.get_state_hash()}
    finally:
        if harness is not None:
            harness.close()
            harness.conn.close()
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x", encoding="utf-8") as destination:
                destination.write(json.dumps(result, ensure_ascii=False))
        finally:
            with _LOCK:
                _ACTIVE.discard(run_id)
    emit("done", result)
