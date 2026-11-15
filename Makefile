PY := $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python)

.PHONY: run dashboard voice telegram discord whatsapp brief gather trace eval eval-judge gate shootout shootout-coding lint

run:            ## chat with SOC_AI_TRANSFORM in the terminal
	$(PY) -m SOC_AI_TRANSFORM

voice:          ## talk to it — push-to-talk, or always-on with SOC_AI_TRANSFORM_WAKE_WORD
	$(PY) -m SOC_AI_TRANSFORM voice

telegram:       ## phone → laptop (needs TELEGRAM_BOT_TOKEN in .env)
	$(PY) -m SOC_AI_TRANSFORM telegram

discord:        ## Discord → laptop (needs DISCORD_BOT_TOKEN in .env)
	$(PY) -m SOC_AI_TRANSFORM discord
whatsapp:       ## WhatsApp → laptop (needs WHATSAPP_TOKEN in .env, public URL)
	$(PY) -m SOC_AI_TRANSFORM whatsapp

brief:          ## morning briefing from calendar + mail + memory (as a LOOP)
	$(PY) -m SOC_AI_TRANSFORM brief

gather:         ## same job as a GRAPH: 4 sources in parallel, then one digest
	$(PY) -m SOC_AI_TRANSFORM gather

dashboard:      ## everything on one page — http://localhost:9000 (restart after a backend pull)
	$(PY) -m SOC_AI_TRANSFORM.ops.dashboard

trace:          ## deep trace waterfalls (Phoenix) at http://localhost:6006
	$(PY) -m phoenix.server.main serve

eval:           ## deterministic evals (0/1, no judge involved)
	$(PY) -m pytest -q evals/deterministic

eval-judge:     ## LLM-as-judge evals (scored %, needs an API key)
	$(PY) -m pytest -q evals/judge

gate:           ## the release gate: deterministic must pass, judge must clear threshold
	$(PY) -m SOC_AI_TRANSFORM.ops.release_gate

shootout:       ## same tasks, different brains: make shootout RUNS="kimi:kimi-k3 anthropic:claude-opus-4-8"
	$(PY) scripts/shootout.py $(RUNS)

shootout-coding: ## coding round via pi, scored by tests: make shootout-coding RUNS="kimi:kimi-k3 anthropic:claude-opus-4-8"
	$(PY) scripts/shootout.py $(RUNS) --coding

lint:
	$(PY) -m ruff check SOC_AI_TRANSFORM evals scripts
