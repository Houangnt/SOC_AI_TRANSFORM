"""Local PhoWhisper + LoRA inference and saved evaluation predictions.

Heavy dependencies and model weights are loaded only on an explicit ASR request.
Evaluation references are never used as transcripts.
"""

from __future__ import annotations

import io
import json
import math
import os
import threading
from functools import lru_cache
from pathlib import Path

_MODEL_LOCK = threading.Lock()
MAX_AUDIO_BYTES = 16 * 1024 * 1024
MAX_SECONDS = 120


def evaluation_root() -> Path:
    default = Path(__file__).resolve().parents[3] / "ASR_model" / "evaluation_improved_v2"
    return Path(os.getenv("SOC_AI_TRANSFORM_ASR_EVALUATION_ROOT", str(default))).resolve()


def adapter_path() -> Path:
    bundled = Path(__file__).resolve().parents[2] / "models" / "phowhisper-medium-improved-v2" / "adapter"
    default = bundled if bundled.is_dir() else (evaluation_root().parent / "phowhisper_improved_ckpt_v2" / "run_ce_lifemate"
               / "step_00000080" / "adapter")
    return Path(os.getenv("SOC_AI_TRANSFORM_ASR_ADAPTER", str(default))).resolve()


def predictions() -> dict[str, str]:
    from SOC_AI_TRANSFORM.lifemate.runner import load_transcripts

    path = evaluation_root() / "test_predictions.jsonl"
    return load_transcripts(path) if path.is_file() else {}


def status() -> dict:
    path = evaluation_root() / "metrics.json"
    metrics = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    return {"name": "PhoWhisper medium · improved v2", "checkpoint": "step_00000080",
            "adapter_available": (adapter_path() / "adapter_model.safetensors").is_file(),
            "saved_predictions": len(predictions()),
            "test_metrics": metrics.get("metrics", {}).get("test", {}).get("step_80", {}),
            "max_seconds": MAX_SECONDS}


@lru_cache(maxsize=1)
def _model(adapter: str, device_setting: str):
    try:
        import torch
        from peft import PeftModel
        from transformers import WhisperForConditionalGeneration, WhisperProcessor
    except ImportError as exc:
        raise RuntimeError("Thiếu thư viện ASR. Chạy: uv sync --extra asr") from exc
    path = Path(adapter)
    config = json.loads((path / "adapter_config.json").read_text(encoding="utf-8"))
    base = config["base_model_name_or_path"]
    # Revision used by evaluation_improved_v2, configurable for another base checkpoint.
    revision = os.getenv("SOC_AI_TRANSFORM_ASR_REVISION",
                         "55a7e3eb6c906de891f8f06a107754427dd3be79")
    if device_setting not in ("auto", "cpu", "cuda"):
        raise ValueError("SOC_AI_TRANSFORM_ASR_DEVICE phải là auto, cpu hoặc cuda")
    device = ("cuda" if torch.cuda.is_available() else "cpu") if device_setting == "auto" else device_setting
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA không khả dụng; chọn SOC_AI_TRANSFORM_ASR_DEVICE=cpu")
    dtype = torch.float16 if device == "cuda" else torch.float32
    processor = WhisperProcessor.from_pretrained(base, revision=revision)
    model = WhisperForConditionalGeneration.from_pretrained(
        base, revision=revision, torch_dtype=dtype)
    model = PeftModel.from_pretrained(model, adapter).merge_and_unload().to(device).eval()
    model.generation_config.forced_decoder_ids = None
    return processor, model, device, dtype


def transcribe(raw: bytes) -> dict:
    """Decode WAV/FLAC/OGG locally; split long audio rather than silently truncate it."""
    if not raw or len(raw) > MAX_AUDIO_BYTES:
        raise ValueError("Audio phải có dung lượng từ 1 byte đến 16 MB")
    try:
        import numpy as np
        import soundfile as sf
        import torch
        from scipy.signal import resample_poly
    except ImportError as exc:
        raise RuntimeError("Thiếu thư viện ASR. Chạy: uv sync --extra asr") from exc
    try:
        with sf.SoundFile(io.BytesIO(raw)) as source:
            rate = source.samplerate
            duration = len(source) / rate
            if not 0 < duration <= MAX_SECONDS:
                raise ValueError(f"Audio phải dài hơn 0 và tối đa {MAX_SECONDS} giây")
            audio = source.read(dtype="float32", always_2d=True).mean(axis=1)
    except (RuntimeError, sf.LibsndfileError) as exc:
        raise ValueError("Không đọc được audio. Hãy dùng WAV, FLAC hoặc OGG hợp lệ") from exc
    if not np.isfinite(audio).all():
        raise ValueError("Audio chứa giá trị không hợp lệ")
    if rate != 16000:
        factor = math.gcd(rate, 16000)
        audio = resample_poly(audio, 16000 // factor, rate // factor)
    # Serialize both loading and inference: one model and one GPU request at a time.
    with _MODEL_LOCK:
        processor, model, device, dtype = _model(
            str(adapter_path()), os.getenv("SOC_AI_TRANSFORM_ASR_DEVICE", "auto"))
        texts = []
        with torch.inference_mode():
            for start in range(0, len(audio), 30 * 16000):
                features = processor(audio[start:start + 30 * 16000], sampling_rate=16000,
                                     return_tensors="pt", return_attention_mask=True)
                ids = model.generate(
                    input_features=features.input_features.to(device=device, dtype=dtype),
                    attention_mask=features.attention_mask.to(device),
                    language="vi", task="transcribe", do_sample=False, num_beams=1,
                    max_new_tokens=224, use_cache=True, return_timestamps=False)
                texts.append(processor.batch_decode(ids, skip_special_tokens=True)[0].strip())
    text = " ".join(texts).strip()
    if not text:
        raise ValueError("ASR không nhận dạng được lời nói trong audio")
    return {"text": text, "device": device, "seconds": round(duration, 2)}
