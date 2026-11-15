# PhoWhisper medium — LifeMate improved v2

This directory contains the fine-tuned LoRA adapter used by the LifeMate ASR UI.
It is not a standalone base model.

- Base: `vinai/PhoWhisper-medium` on Hugging Face.
- Base revision: `55a7e3eb6c906de891f8f06a107754427dd3be79`.
- Training checkpoint: `run_ce_lifemate/step_00000080/adapter`.
- Adapter SHA-256: `48321b01b6dbaacb6a41b9fb18b60321bf3e62bc9520995618d630603869b792`.
- LoRA: rank 16, alpha 32, dropout 0.05, targets `q_proj` and `v_proj`.
- Evaluation supplied with the checkpoint: test WER 13.9496%, CER 10.2374%, 155 clips.
  Full aggregate results and decoding settings are in `metrics.json`.

The source adapter model card did not specify a separate adapter license or
complete training provenance. No new license or additional training claims are
asserted here. Consult the base model card and competition terms before reuse.

## Run from this checkout

Install `uv sync --frozen --extra asr`. The ASR loader automatically finds this
adapter when `SOC_AI_TRANSFORM_ASR_ADAPTER` is unset. Alternatively set:

```dotenv
SOC_AI_TRANSFORM_ASR_ADAPTER=models/phowhisper-medium-improved-v2/adapter
```

The base weights are downloaded to the Hugging Face cache on first use. Do not
copy them into Git. Dataset audio, references, predictions and API keys are not
included. Supply the authorised LifeMate dataset and business skills separately
as described in the repository README. This adapter directory is a checkout
asset, not included in the Python wheel.
