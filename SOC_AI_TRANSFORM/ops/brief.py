"""`python -m SOC_AI_TRANSFORM brief` — a morning briefing that runs through the normal
harness (so it traces and animates like any turn), composing your real calendar,
mail, and memory into a focus-first summary. Cron it for a daily greeting:

    30 7 * * *  cd ~/SOC_AI_TRANSFORM && make brief

The briefing request is handled by the configured agent — this just kicks off
the turn and saves the result to the outbox.
"""

from __future__ import annotations

from datetime import date

from rich.console import Console

from SOC_AI_TRANSFORM.app import SOC_AI_TRANSFORM

PROMPT = "Brief me on my week: what's on my calendar, what's in my mail that needs attention, and what I should focus on today."


def main() -> None:
    console = Console()
    soc_ai_transform = SOC_AI_TRANSFORM()
    if not soc_ai_transform.settings.apple_tools:
        console.print("[dim]Tip: set SOC_AI_TRANSFORM_APPLE_TOOLS=1 to brief from your real Calendar and Mail.[/dim]")
    result = soc_ai_transform.respond(PROMPT, source="brief")
    console.print(result.reply)
    out = soc_ai_transform.settings.home / "outbox" / f"brief-{date.today().isoformat()}.txt"
    out.write_text(result.reply + "\n", encoding="utf-8")
    console.print(f"[dim]saved to {out}[/dim]")


if __name__ == "__main__":
    main()
