"""Load the split's official SDK and adapt its call, trace and state-hash APIs."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from SOC_AI_TRANSFORM.lifemate.skills import allowed_tools
from SOC_AI_TRANSFORM.tools.registry import Tool, ToolRegistry


@dataclass(frozen=True)
class EnvironmentAdapter:
    """Bind these to ONE ToolEnv per sample, or inject a test environment.

    call must execute through that environment, enforcing schemas/app access and
    recording every attempt, including rejected calls. Log/hash come from ToolEnv,
    never from the LLM, local chat database, or a reimplementation of its state.
    """

    call: Callable[[str, dict], Any]
    get_tool_calls: Callable[[], list[dict]]
    get_state_hash: Callable[[], str]


@lru_cache
def load_sdk(data_root: Path, split: str):
    """Import the provided SDK under a split-specific namespace, without copying it."""
    package = (data_root / split / "zaic_tools").resolve()
    entry = package / "__init__.py"
    if not entry.is_file():
        raise FileNotFoundError(f"Official SDK not found: {entry}")
    suffix = hashlib.sha256(str(package).encode()).hexdigest()[:12]
    name = f"_soc_zaic_{suffix}"
    spec = importlib.util.spec_from_file_location(name, entry,
                                                submodule_search_locations=[str(package)])
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load official SDK at {package}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def official_environment(data_root: Path, split: str, sample_id: str) -> EnvironmentAdapter:
    sdk = load_sdk(data_root.resolve(), split)
    session = sdk.ToolEnv(split, sample_id, root=data_root)
    return EnvironmentAdapter(session.call, session.get_tool_calls, session.get_state_hash)


class EnvironmentRegistry(ToolRegistry):
    def __init__(self, context: dict, schemas: Sequence[dict], env: EnvironmentAdapter):
        super().__init__()
        self.env = env
        self.names: dict[str, str] = {}
        allowed = allowed_tools(context)
        canonical_names: set[str] = set()
        for schema in schemas:
            name = schema["name"]
            if name not in allowed:
                continue
            # Provider-facing aliases keep dotted tool names portable. ToolEnv
            # and submission always receive the original names from the catalog.
            alias = name.replace(".", "__")
            if alias in self.names:
                raise ValueError(f"Duplicate/colliding tool name: {name}")
            self.names[alias] = name
            canonical_names.add(name)
            self.register(Tool(
                name=alias, description=schema.get("description", ""),
                input_schema=schema["parameters"], fn=lambda: "",
            ))
        missing = allowed - canonical_names
        if missing:
            raise ValueError(f"Official schemas missing for installed tools: {sorted(missing)}")

    def execute(self, name: str, args: dict, notify=None) -> str:
        canonical = self.names.get(name, name)
        if (canonical == "sys.ask_missing_info" and isinstance(args, dict)
                and isinstance(args.get("tool_name"), str)):
            args = {**args, "tool_name": self.names.get(args["tool_name"], args["tool_name"])}
        # Even unknown/schema-invalid attempts go to the authoritative runtime
        # so its rejection is recorded and can be replayed by the evaluator.
        try:
            output = self.env.call(canonical, args)
            return output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
        except Exception as exc:
            return f"Error running {canonical}: {exc}"
