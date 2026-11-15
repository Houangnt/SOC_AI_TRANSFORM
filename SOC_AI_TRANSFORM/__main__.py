"""Entrypoints — installed as the `SOC_AI_TRANSFORM` command (and `python -m SOC_AI_TRANSFORM`):

  SOC_AI_TRANSFORM                       chat in the terminal (default)
    SOC_AI_TRANSFORM dashboard             the browser cockpit → localhost:9000 (+ Telegram if configured)
  SOC_AI_TRANSFORM connections           list configured integrations and their health
  SOC_AI_TRANSFORM lifemate inspect      inspect the bundled LifeMate business skills
  SOC_AI_TRANSFORM lifemate route --text "..."   select skills without executing tools
  SOC_AI_TRANSFORM voice                 talk to it (needs the [voice] extra)
  SOC_AI_TRANSFORM telegram              phone → laptop (needs TELEGRAM_BOT_TOKEN)
  SOC_AI_TRANSFORM discord               Discord → laptop (needs DISCORD_BOT_TOKEN)
  SOC_AI_TRANSFORM whatsapp              WhatsApp → laptop (needs WHATSAPP_TOKEN, public URL)
  SOC_AI_TRANSFORM brief                 morning briefing (calendar + mail + memory) — as a LOOP
  SOC_AI_TRANSFORM gather                same job as a GRAPH: github, web, calendar and
                             memory fetched together, then one digest
  SOC_AI_TRANSFORM skill install <url>   install a community skill
"""

from __future__ import annotations

import sys


def main() -> None:
    args = sys.argv[1:]
    if not args:
        from SOC_AI_TRANSFORM.gateway.cli import main as cli_main

        cli_main()
    elif args[0] == "dashboard":
        from SOC_AI_TRANSFORM.ops.dashboard import main as dash_main

        dash_main()
    elif args[0] == "connections":
        from SOC_AI_TRANSFORM.integrations import cli_main

        sys.exit(cli_main())
    elif args[0] == "lifemate":
        from SOC_AI_TRANSFORM.lifemate.runner import main as lifemate_main

        lifemate_main(args[1:])
    elif args[0] == "voice":
        from SOC_AI_TRANSFORM.gateway.voice import main as voice_main

        voice_main()
    elif args[0] == "telegram":
        from SOC_AI_TRANSFORM.gateway.telegram import main as tg_main

        tg_main()
    elif args[0] == "discord":
        from SOC_AI_TRANSFORM.gateway.discord import main as discord_main

        discord_main()
    elif args[0] == "whatsapp":
        from SOC_AI_TRANSFORM.gateway.whatsapp import main as wa_main

        wa_main()
    elif args[0] == "brief":
        from SOC_AI_TRANSFORM.ops.brief import main as brief_main

        brief_main()
    elif args[0] == "gather":
        from SOC_AI_TRANSFORM.ops.gather import main as gather_main

        gather_main()
    elif args[0] == "skill" and len(args) >= 3 and args[1] == "install":
        from SOC_AI_TRANSFORM.memory.procedural.installer import install

        install(args[2])
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
