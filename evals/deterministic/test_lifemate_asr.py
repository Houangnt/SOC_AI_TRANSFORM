"""ASR must pass recognized history to the agent, never evaluation references."""

import base64
import json
from uuid import uuid4

import pytest

from evals.deterministic import test_lifemate_ui as fixtures
from SOC_AI_TRANSFORM.lifemate import asr, runner, ui

world = fixtures.world
handler = fixtures.handler


@pytest.fixture
def evaluation(tmp_path, monkeypatch):
    root = tmp_path / "evaluation"
    root.mkdir()
    monkeypatch.setenv("SOC_AI_TRANSFORM_ASR_EVALUATION_ROOT", str(root))
    rows = [{"id": "synthetic", "prediction": "predicted current", "reference": "SECRET GOLD"},
            {"id": "synthetic_u1", "prediction": "predicted history", "reference": "SECRET GOLD"}]
    (root / "test_predictions.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return root


def test_evaluation_format_never_reads_reference(evaluation):
    mapping = runner.load_transcripts(evaluation / "test_predictions.jsonl")
    assert mapping == {"synthetic": "predicted current", "synthetic_u1": "predicted history"}
    assert "SECRET GOLD" not in json.dumps(asr.status())


def test_saved_predictions_flow_into_agent_history(world, evaluation, monkeypatch):
    result = ui.recognize({"split": "public_test", "sample_id": "synthetic", "mode": "saved"})
    assert result["history"][0]["text"] == "predicted history"
    assert "SECRET GOLD" not in json.dumps(result)
    seen = []

    def run(item, env, *args, **kwargs):
        seen.append(item)
        return {"id": item["id"], "tool_calls": [], "state_hash": "hash"}

    monkeypatch.setattr(runner, "run_sample", run)
    ui.stream({"split": "public_test", "sample_id": "synthetic", "run_id": str(uuid4()),
               "text": "user corrected current", "asr_transcripts": result["transcripts"]},
              lambda *args: None)
    assert seen[0]["audio_text"] == "user corrected current"
    assert seen[0]["history"][0]["text"] == "predicted history"


def test_missing_saved_history_does_not_fall_back_to_reference(world, evaluation):
    (evaluation / "test_predictions.jsonl").write_text(
        '{"id":"synthetic","prediction":"current","reference":"GOLD"}\n')
    with pytest.raises(ValueError, match="synthetic_u1"):
        ui.recognize({"split": "public_test", "sample_id": "synthetic", "mode": "saved"})
    assert world.created == []


def test_live_upload_recognizes_current_and_dataset_history(world, monkeypatch):
    path = world.data / "public_test" / "audio" / "synthetic"
    path.mkdir(parents=True)
    (path / "synthetic_u1.wav").write_bytes(b"history audio")
    seen = []

    def decode(raw):
        seen.append(raw)
        return {"text": raw.decode(), "device": "cpu", "seconds": 1}

    monkeypatch.setattr(asr, "transcribe", decode)
    request = handler("/api/lifemate/asr", {
        "split": "public_test", "sample_id": "synthetic", "mode": "live",
        "audio_base64": base64.b64encode(b"uploaded audio").decode()})
    request.do_POST()
    result = json.loads(request.wfile.getvalue())
    assert seen == [b"uploaded audio", b"history audio"]
    assert result["text"] == "uploaded audio"
    assert result["history"][0]["text"] == "history audio"
    assert world.created == []


def test_incomplete_asr_history_blocks_execution(world):
    with pytest.raises(ValueError, match="Missing transcript"):
        ui.stream({"split": "public_test", "sample_id": "synthetic", "run_id": str(uuid4()),
                   "text": "current", "asr_transcripts": {"synthetic": "current"}},
                  lambda *args: None)
    assert world.created == []


def test_audio_paths_stay_inside_dataset(world, tmp_path):
    outside = tmp_path / "secret.wav"
    outside.write_bytes(b"secret")
    with pytest.raises(ValueError, match="audio"):
        ui.audio_path("public_test", "synthetic", str(outside))
    with pytest.raises(ValueError, match="Unsupported"):
        ui.audio_path("../private", "synthetic")


def test_bad_upload_is_reported_without_environment(world):
    request = handler("/api/lifemate/asr", {
        "split": "public_test", "sample_id": "synthetic", "audio_base64": "not base64!"})
    request.do_POST()
    assert "error" in json.loads(request.wfile.getvalue())
    assert world.created == []


def test_audio_decode_resamples_and_rejects_overlong_files(monkeypatch):
    import io
    from types import SimpleNamespace

    np = pytest.importorskip("numpy")
    sf = pytest.importorskip("soundfile")
    torch = pytest.importorskip("torch")
    pytest.importorskip("scipy")
    chunks = []

    class Processor:
        def __call__(self, audio, **kwargs):
            chunks.append((len(audio), kwargs))
            return SimpleNamespace(input_features=torch.zeros(1), attention_mask=torch.ones(1))

        def batch_decode(self, ids, **kwargs):
            return ["recognized"]

    class Model:
        def generate(self, **kwargs):
            assert kwargs["language"] == "vi" and kwargs["num_beams"] == 1
            assert kwargs["max_new_tokens"] == 224
            return [1]

    monkeypatch.setattr(asr, "_model", lambda *args: (Processor(), Model(), "cpu", torch.float32))
    stream = io.BytesIO()
    sf.write(stream, np.zeros((31 * 8000, 2)), 8000, format="WAV")
    result = asr.transcribe(stream.getvalue())
    assert result["text"] == "recognized recognized"
    assert result["seconds"] == 31
    assert [size for size, _ in chunks] == [30 * 16000, 16000]
    stream = io.BytesIO()
    sf.write(stream, np.zeros(121 * 8000), 8000, format="WAV")
    with pytest.raises(ValueError, match="120"):
        asr.transcribe(stream.getvalue())
    with pytest.raises(ValueError, match="audio"):
        asr.transcribe(b"invalid wave")
