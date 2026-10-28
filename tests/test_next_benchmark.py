import importlib.util
import io
from pathlib import Path
import wave

import httpx
import pytest

spec = importlib.util.spec_from_file_location('benchmark_next', Path(__file__).resolve().parents[1] / 'scripts/benchmark_next.py')
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


@pytest.fixture(autouse=True)
def no_hardware_probes(monkeypatch):
    monkeypatch.setattr(benchmark, 'gpu', lambda: {'unavailable': 'test'})
    monkeypatch.setattr(benchmark, 'memory', lambda: {'unavailable': 'test'})


def test_wav_duration_and_rtf_are_measured_without_inventing_playback():
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b'\0' * 32000)
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=buffer.getvalue()))) as client:
        row, audio = benchmark.measure_voice(client, 'http://127.0.0.1:8765', 'ru_RU-denis-medium', 'Привет')
    assert row['audio_duration_s'] == 1
    assert row['real_time_factor'] == row['synthesis_ms'] / 1000
    assert row['first_audible_audio_ms'] is None
    assert row['voice_total_ms'] is None
    assert audio == buffer.getvalue()


def test_missing_voice_counts_as_failed_attempt_without_zero_latency():
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503))) as client:
        row, audio = benchmark.measure_voice(client, 'http://127.0.0.1:8765', 'silero-v5_6-ru', 'Привет')
    assert row['error']
    assert row['synthesis_ms'] is None and row['real_time_factor'] is None
    assert not audio
    assert benchmark.summarize([row])['failures'] == 1
    assert benchmark.summarize([row])['first_audible_audio_ms']['n'] == 0


def test_streamed_http_delta_is_not_reported_as_raw_token_or_browser_paint():
    content = '\n'.join(['{"type":"status","data":{}}', '{"type":"delta","text":"Привет","sequence":1}',
                         '{"type":"final","data":{"answer":"Привет"}}'])
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=content))) as client:
        row = benchmark.measure_dialogue(client, 'http://127.0.0.1:8765', {'server_instance': 'test'}, 'Привет')
    assert row['first_delta_ms'] is not None
    assert row['delta_count'] == 1
    assert row['raw_first_token_ms'] is None
    assert row['first_browser_visible_text_ms'] is None
    assert row['first_audible_audio_ms'] is None


def test_truncated_stream_remains_a_failure_even_after_a_delta():
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text='{"type":"delta","text":"x"}'))) as client:
        row = benchmark.measure_dialogue(client, 'http://127.0.0.1:8765', {}, 'Привет')
    assert row['error'] and row['delta_count'] == 1
