import os
import sys
from pathlib import Path

# evals/ sits next to SOC_AI_TRANSFORM/, not inside it — make both importable when
# running `pytest evals` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Offline tests must not inherit keys or feature flags from the developer's .env.
# Restore dotenv behavior before subprocess tests exercise actual .env discovery.
if os.getenv("SOC_AI_TRANSFORM_RUN_LIVE_EVALS") != "1":
    previous_dotenv = os.environ.get("PYTHON_DOTENV_DISABLED")
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    import SOC_AI_TRANSFORM.config  # noqa: E402, F401

    if previous_dotenv is None:
        os.environ.pop("PYTHON_DOTENV_DISABLED", None)
    else:
        os.environ["PYTHON_DOTENV_DISABLED"] = previous_dotenv
