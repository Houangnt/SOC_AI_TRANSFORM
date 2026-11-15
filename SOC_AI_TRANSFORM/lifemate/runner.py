"""Transcript-first LifeMate runner with the dataset's own per-split SDK."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from SOC_AI_TRANSFORM.config import Settings, load_settings
from SOC_AI_TRANSFORM.lifemate.skills import BusinessSkills
from SOC_AI_TRANSFORM.lifemate.tools import (
    EnvironmentAdapter,
    EnvironmentRegistry,
    official_environment,
)
from SOC_AI_TRANSFORM.loop.agent import run_loop
from SOC_AI_TRANSFORM.loop.models import get_client

EXECUTION_PROMPT = """Bạn là agent LifeMate thực thi yêu cầu bằng tool của phiên.
Dùng context.current_time và context.timezone; không dùng đồng hồ máy hoặc ngày ví dụ.
History đã được thực thi trong trạng thái ban đầu: chỉ dùng lại thông tin, không phát lại.
Không bịa ID, observation, tool hoặc trạng thái. Chỉ dùng các tool được cung cấp.
Có thể gọi cùng tool nhiều lần cho mục tiêu khác nhau khi cần; không gửi lại thao tác
ghi có kết quả chưa rõ. Đọc kết quả trước khi chọn nhánh hoặc hành động phụ thuộc.
Các quy tắc được nạp bên dưới; không đọc filesystem hay file môi trường giả lập.
Schema API của phiên là nguồn quyết định, kể cả khi khác schema tham khảo trong skill.
Tên hàm API dùng __ thay cho dấu chấm; trong tool_name của sys.ask_missing_info dùng
tên gốc, ví dụ banking.transfer. Thiếu thông tin không thể suy ra: gọi sys.ask_missing_info.
Quy trình/plan nội bộ không phải tool_calls; không gửi bindings hoặc placeholder vào tool.
Chỉ trả lời hoàn tất khi kết quả xác nhận; không tự tạo state_hash.
Nếu không có skill phù hợp, vẫn xử lý theo schema thật của phiên; thiếu skill không
đồng nghĩa ngoài phạm vi. Yêu cầu ngoài các app đã cài hoặc chỉ trò chuyện: không gọi tool.
"""


def run_sample(sample: dict, env: EnvironmentAdapter, schemas: list[dict], *,
               client=None, settings: Settings | None = None,
               catalog: BusinessSkills | None = None, observer=None,
               registry: EnvironmentRegistry | None = None) -> dict:
    """Run current transcript only; return the environment's replayable submission.

    Caller supplies official tool schemas and one already-created sample ToolEnv
    via env. This runner never creates or resets it and never reads label/state files.
    """
    text = sample.get("audio_text", sample.get("text"))
    context, history = sample.get("context"), sample.get("history", [])
    if not isinstance(text, str) or not text.strip() or not sample.get("id"):
        raise ValueError("Sample needs id and a nonempty audio_text/text transcript")
    if not isinstance(context, dict) or not context.get("current_time") or not context.get("timezone"):
        raise ValueError("Sample context needs current_time and timezone")
    if not isinstance(history, list):
        raise TypeError("Sample history must be a list")
    registry = registry if registry is not None else EnvironmentRegistry(context, schemas, env)
    if registry.env is not env:
        raise ValueError("Tool registry and sample must use the same environment")
    settings = settings or load_settings()
    client = client if client is not None else get_client(settings)
    model = settings.model
    if not model:
        raise ValueError("A model must be configured when injecting a client")
    catalog = catalog or BusinessSkills()
    selected = catalog.select(client, settings.small_model or model, text, context, history)
    if observer:
        observer("business_skills", asdict(selected))
    aliases = json.dumps(registry.names, ensure_ascii=False)
    result = run_loop(
        client, model,
        EXECUTION_PROMPT + "\nAPI aliases → canonical tool names:\n" + aliases
        + "\n" + catalog.instructions(selected, context),
        [{"role": "user", "content": json.dumps(
            {"text": text, "context": context, "history": history}, ensure_ascii=False)}],
        registry, max_iterations=settings.max_iterations,
        max_tokens=settings.max_tokens, observer=observer,
    )
    if observer:
        observer("lifemate_reply", {"reply": result.reply, "iterations": result.iterations,
                                    "usage": result.usage})
    # Final hash and trace belong to the supplied official environment, including
    # the no-action branch. Do not substitute run_loop's alias-bearing trace.
    state_hash = env.get_state_hash()
    calls = env.get_tool_calls()
    if not isinstance(state_hash, str) or not isinstance(calls, list):
        raise TypeError("Environment did not return a valid state hash and call log")
    return {"id": sample["id"], "tool_calls": calls, "state_hash": state_hash}


def load_transcripts(path: Path) -> dict[str, str]:
    """Support both existing ASR exports; filenames also identify history audio."""
    if path.suffix == ".jsonl":
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                   if line.strip()]
    else:
        records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise TypeError("Transcript file must contain a list or JSONL records")
    result: dict[str, str] = {}
    for record in records:
        key = record.get("audio", record.get("audio_path", record.get("id")))
        text = record.get("transcript", record.get("phowhisper_transcript", record.get("prediction")))
        if not isinstance(key, str) or not isinstance(text, str):
            raise TypeError("Transcript record needs audio/audio_path/id and transcript/prediction text")
        key = Path(key.replace("\\", "/")).stem
        if key in result and result[key] != text:
            raise ValueError(f"Conflicting transcripts for {key}")
        result[key] = text
    return result


def prepare_sample(item: dict, transcripts: dict[str, str] | None = None) -> dict:
    """Use only inputs, never labels; require ASR for every spoken history turn too."""
    def text_for(turn: dict) -> str:
        if transcripts is None:
            text = turn.get("audio_text", turn.get("text"))
        else:
            key = Path(turn["audio"].replace("\\", "/")).stem
            text = transcripts.get(key)
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"Missing transcript for {turn.get('audio', item['id'])}")
        return text

    history = []
    for turn in item.get("history", []):
        if turn.get("role") == "user":
            history.append({"role": "user", "text": text_for(turn)})
        else:
            history.append({key: turn[key] for key in ("role", "text", "tool_calls", "tool_results")
                            if key in turn})
    return {"id": item["id"], "audio_text": text_for(item),
            "context": item["context"], "history": history}


def run_split(args, catalog: BusinessSkills) -> None:
    from SOC_AI_TRANSFORM.app import SOC_AI_TRANSFORM

    root = args.data_root.resolve()
    tools = json.loads((root / args.split / f"{args.split}_tools_catalog.json").read_text(
        encoding="utf-8"))
    schemas = [tool for app in tools["apps"] for tool in app["tools"]]
    transcripts = load_transcripts(args.transcripts) if args.transcripts else None
    items = []
    with (root / args.split / f"{args.split}.jsonl").open(encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            item = json.loads(line)
            if args.ids and item["id"] not in args.ids:
                continue
            items.append(prepare_sample(item, transcripts))
            if len(items) >= args.limit:
                break
    if not items:
        raise ValueError("No samples match the requested IDs")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    settings = load_settings()
    client = get_client(settings)
    # Exclusive create avoids overwriting an earlier run. No environment reset or
    # implicit retries: if inference fails, persist its actual trace before stopping.
    with args.output.open("x", encoding="utf-8") as destination:
        for item in items:
            env = official_environment(root, args.split, item["id"])
            harness = None
            try:
                harness = SOC_AI_TRANSFORM.for_lifemate(item, env, schemas,
                                                       client=client, settings=settings)
                row = harness.respond_lifemate(item, catalog=catalog)
            except Exception:
                row = {"id": item["id"], "tool_calls": env.get_tool_calls(),
                       "state_hash": env.get_state_hash()}
                destination.write(json.dumps(row, ensure_ascii=False) + "\n")
                destination.flush()
                print(f"{item['id']}: stopped; partial environment trace saved", file=sys.stderr)
                raise
            finally:
                if harness is not None:
                    harness.close()
                    harness.conn.close()
            destination.write(json.dumps(row, ensure_ascii=False) + "\n")
            destination.flush()
            print(f"{item['id']}: {len(row['tool_calls'])} calls", file=sys.stderr)
    print(f"{len(items)} samples → {args.output}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="LifeMate business skills (transcript-first)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("inspect", help="Validate bundled references without API calls")
    route = commands.add_parser("route", help="Select business skills; does not execute tools")
    source = route.add_mutually_exclusive_group(required=True)
    source.add_argument("--text", help="Vietnamese transcript (no app restrictions without --sample)")
    source.add_argument("--sample", type=Path, help="JSON object with audio_text, context and history")
    run = commands.add_parser("run", help="Run transcripts through the provided official ToolEnv")
    run.add_argument("--data-root", type=Path, required=True, help="Directory holding split folders")
    run.add_argument("--split", choices=("train", "public_test", "private_test"), default="train")
    run.add_argument("--transcripts", type=Path, help="ASR JSON/JSONL; otherwise use train audio_text")
    run.add_argument("--ids", nargs="+", help="Only these sample IDs")
    run.add_argument("--limit", type=int, default=1, help="Maximum samples (default: 1)")
    run.add_argument("--output", type=Path, required=True, help="New JSONL file; never overwritten")
    args = parser.parse_args(argv)
    catalog = BusinessSkills()
    if args.command == "run":
        if args.limit < 1:
            parser.error("--limit must be positive")
        run_split(args, catalog)
        return
    if args.command == "inspect":
        for name, item in catalog.businesses.items():
            catalog.read(item["path"])
            for rule in item["shared_rules"]:
                catalog.read(rule)
            json.loads(catalog.read(f"skills/{name}/references/tools.json"))
        catalog.read(catalog.architecture["orchestration"])
        print(json.dumps({"businesses": len(catalog.index), "orchestration": 1,
                          "shared_rules": len(catalog.architecture["shared_rules"])}, indent=2))
        return
    sample = json.loads(args.sample.read_text(encoding="utf-8")) if args.sample else {}
    text = args.text or sample.get("audio_text", sample.get("text"))
    if not isinstance(text, str) or not text.strip():
        parser.error("A nonempty transcript is required")
    settings = load_settings()
    client = get_client(settings)
    selection = catalog.select(client, settings.small_model or settings.model,
                               text, sample.get("context"), sample.get("history", []))
    print(json.dumps({"mode": "routing_only", **asdict(selection)}, ensure_ascii=False, indent=2))
