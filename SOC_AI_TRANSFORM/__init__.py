"""SOC_AI_TRANSFORM — a minimal, transparent, local-first SOC_AI_TRANSFORM.

Four pillars, one module each:
  harness  → SOC_AI_TRANSFORM/runtime + SOC_AI_TRANSFORM/gateway  (scaffolding around the raw LLM)
  loop     → SOC_AI_TRANSFORM/loop                      (observe → reason → act → repeat)
             SOC_AI_TRANSFORM/graph                     (opt-in structure around the loop — extends this pillar)
  memory   → SOC_AI_TRANSFORM/memory                    (procedural / semantic / episodic)
  ops      → SOC_AI_TRANSFORM/ops + evals/              (trace → eval → gate → release)
"""

__version__ = "0.1.0"
