"""The agent's auxiliary tools: web search, memory
self-management (manage_memory/update_soul/create_skill), and opt-in adapters:
Apple ecosystem (SOC_AI_TRANSFORM_APPLE_TOOLS=1) and MCP servers (.SOC_AI_TRANSFORM/mcp.json)."""

from __future__ import annotations

import sqlite3

from SOC_AI_TRANSFORM.config import Settings
from SOC_AI_TRANSFORM.tools import memory_admin, search
from SOC_AI_TRANSFORM.tools.registry import ToolRegistry


def build_registry(conn: sqlite3.Connection, settings: Settings, memory=None) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(search.make_tool())

    if getattr(settings, "youtube", False):
        from SOC_AI_TRANSFORM.tools import youtube

        registry.register(youtube.make_tool())

    # Memory self-management — the agent can correct/forget memory, learn rules,
    # and author its own skills (feels like a personal agent, not a black box).
    if memory is not None:
        registry.register(memory_admin.make_manage_memory_tool(memory))
        registry.register(memory_admin.make_update_soul_tool(settings))
        registry.register(memory_admin.make_create_skill_tool(settings, memory))

    # Experimental tools — off by default; opt in with SOC_AI_TRANSFORM_EXPERIMENTAL=1.
    # delegate_task (sub-agents via pi) and the constrained terminal are live;
    # browser/cron are still skeletons that report "coming soon".
    #
    # Trust settings.experimental ALONE. load_settings() already defaults it from
    # SOC_AI_TRANSFORM_EXPERIMENTAL, so re-checking the env here would let the global switch
    # override an explicit False — and the arena passes experimental=False for
    # every non-coding race. Once the dashboard could write SOC_AI_TRANSFORM_EXPERIMENTAL=1,
    # that OR silently forced delegate_task into races that never asked for it.
    if getattr(settings, "experimental", False):
        from SOC_AI_TRANSFORM.tools import experimental

        for t in experimental.make_tools(settings):
            registry.register(t)

    # Apple ecosystem readers/writers (opt-in; first use triggers macOS prompts).
    if settings.apple_tools:
        from SOC_AI_TRANSFORM.tools import apple

        for t in apple.make_tools():
            registry.register(t)

    # Read-only GitHub via the gh CLI (opt-in; uses gh's own auth, no token here).
    if getattr(settings, "gh_tool", False):
        from SOC_AI_TRANSFORM.tools import github

        registry.register(github.make_tool(default_repo=getattr(settings, "gh_repo", "")))

    # MCP servers (opt-in via .SOC_AI_TRANSFORM/mcp.json).
    mcp_config = settings.home / "mcp.json"
    if mcp_config.exists():
        try:
            from SOC_AI_TRANSFORM.tools.mcp_client import MCPBridge

            bridge = MCPBridge(mcp_config)
            for t in bridge.start():
                registry.register(t)
            registry.mcp_bridge = bridge  # so SOC_AI_TRANSFORM.close() can stop the servers
        except ImportError:
            print("mcp.json found but the 'mcp' package is missing — pip install 'SOC_AI_TRANSFORM[mcp]'")

    return registry
