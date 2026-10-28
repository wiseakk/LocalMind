"""Local voice services, isolated in a killable, bounded worker.

Only setup commands download models. HTTP callers select declared profiles/voices;
they never supply filesystem paths, URLs, subprocess arguments, or commands.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import wave

from .settings import ROOT

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_RECORDING_SECONDS = 30
MAX_TTS_CHARACTERS = 1200
MAX_TTS_SECONDS = 120
WORKER_TIMEOUT_SECONDS = 120
SAMPLE_RATE = 16000
SUPPORTED_SUFFIXES = frozenset(('.webm', '.ogg', '.mp4', '.wav', '.m4a'))
PROFILES = {
    'cpu-fast': {'model': 'base', 'device': 'cpu', 'compute_type': 'int8', 'label': 'CPU · быстро'},
    'balanced': {'model': 'small', 'device': 'cpu', 'compute_type': 'int8', 'label': 'CPU · баланс'},
    'gpu-quality': {'model': 'medium', 'device': 'cuda', 'compute_type': 'float16', 'label': 'GPU · точность'},
}
DEFAULT_VOICE = 'ru_RU-denis-medium'
VOICES = {DEFAULT_VOICE: {'label': 'Денис · русский', 'dataset_license': 'CC0'}}
MODELS = ROOT / 'models'
_operation = threading.BoundedSemaphore(1)
_temporary_directory = tempfile.TemporaryDirectory


class VoiceError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _installed(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _stt_ready(profile: str) -> bool:
    directory = MODELS / 'whisper' / PROFILES[profile]['model']
    try:
        return all((directory / name).is_file() and (directory / name).stat().st_size > 0
                   for name in ('model.bin', 'config.json', 'tokenizer.json'))
    except OSError:
        return False


def _tts_ready(voice: str) -> bool:
    directory = MODELS / 'piper'
    model, config = directory / (voice + '.onnx'), directory / (voice + '.onnx.json')
    try:
        if not model.is_file() or model.stat().st_size < 1000000 or not config.is_file() or config.stat().st_size > 1024 * 1024:
            return False
        metadata = json.loads(config.read_text(encoding='utf-8'))
        return metadata.get('language', {}).get('code') == 'ru_RU'
    except (OSError, ValueError, AttributeError):
        return False


def voice_status() -> dict:
    stt_installed = _installed('faster_whisper') and _installed('av')
    tts_installed = _installed('piper')
    return {
        'stt_installed': stt_installed,
        'tts_installed': tts_installed,
        'default_profile': 'balanced',
        'max_recording_seconds': MAX_RECORDING_SECONDS,
        'max_upload_bytes': MAX_UPLOAD_BYTES,
        'profiles': [{'id': key, **value, 'ready': stt_installed and _stt_ready(key)} for key, value in PROFILES.items()],
        'voices': [{'id': key, **value, 'ready': tts_installed and _tts_ready(key)} for key, value in VOICES.items()],
        'setup': 'См. docs/VOICE.md. Установите requirements-voice.txt и загрузите выбранную модель отдельно.',
        'local_only': True,
    }


def _run_worker(kind: str, selection: str, data: bytes, suffix: str) -> tuple[dict, bytes]:
    if not _operation.acquire(blocking=False):
        raise VoiceError(429, 'Голосовой модуль занят. Дождитесь завершения текущей записи или озвучивания.')
    try:
        with _temporary_directory(prefix='localmind-voice-') as directory:
            folder = Path(directory)
            source, result, audio = folder / ('input' + suffix), folder / 'result.json', folder / 'output.wav'
            source.write_bytes(data)
            # Arguments and module are server-owned constants. No shell or user path.
            command = [sys.executable, '-m', 'localmind.voice', '_worker', kind, selection, str(source), str(result), str(audio)]
            environment = {**os.environ, 'HF_HUB_OFFLINE': '1', 'HF_HUB_DISABLE_TELEMETRY': '1', 'DO_NOT_TRACK': '1'}
            try:
                subprocess.run(command, shell=False, cwd=ROOT, env=environment, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=WORKER_TIMEOUT_SECONDS, check=True,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except subprocess.TimeoutExpired as exc:
                raise VoiceError(504, 'Голосовой модуль превысил лимит времени. Попробуйте CPU · быстро или более короткую запись.') from exc
            except (OSError, subprocess.CalledProcessError) as exc:
                raise VoiceError(503, 'Не удалось запустить локальный голосовой модуль. Проверьте установку в docs/VOICE.md.') from exc
            if not result.is_file() or result.stat().st_size > 16384:
                raise VoiceError(503, 'Голосовой модуль вернул некорректный результат.')
            try:
                payload = json.loads(result.read_text(encoding='utf-8'))
            except (ValueError, OSError) as exc:
                raise VoiceError(503, 'Голосовой модуль вернул некорректный результат.') from exc
            if not isinstance(payload, dict):
                raise VoiceError(503, 'Голосовой модуль вернул некорректный результат.')
            if 'error' in payload:
                status = payload.get('status_code', 422)
                if status not in (413, 415, 422, 429, 503, 504) or not isinstance(payload['error'], str):
                    raise VoiceError(503, 'Голосовой модуль вернул некорректный результат.')
                raise VoiceError(status, payload['error'])
            if kind == 'tts':
                if not audio.is_file() or audio.stat().st_size > 12 * 1024 * 1024:
                    raise VoiceError(503, 'Некорректный размер синтезированной речи.')
                return payload, audio.read_bytes()
            if not isinstance(payload.get('text'), str) or len(payload['text']) > 4000:
                raise VoiceError(503, 'Голосовой модуль вернул некорректный текст.')
            return payload, b''
    except OSError as exc:
        raise VoiceError(503, 'Временное хранилище голосового модуля недоступно. Проверьте права ОС и свободное место.') from exc
    finally:
        _operation.release()


def transcribe_audio(data: bytes, suffix: str, profile: str = 'balanced') -> dict:
    if profile not in PROFILES:
        raise VoiceError(422, 'Неизвестный профиль распознавания.')
    if suffix.lower() not in SUPPORTED_SUFFIXES:
        raise VoiceError(415, 'Поддерживаются webm, ogg, mp4, wav, m4a.')
    if len(data) > MAX_UPLOAD_BYTES:
        raise VoiceError(413, 'Аудио слишком большое: максимум 8 МБ.')
    if len(data) < 128:
        raise VoiceError(422, 'Запись пустая или слишком короткая.')
    if not _installed('faster_whisper') or not _installed('av'):
        raise VoiceError(503, 'Для локального распознавания установите requirements-voice.txt. См. docs/VOICE.md.')
    if not _stt_ready(profile):
        raise VoiceError(503, f'Модель не загружена. Выполните: python -m localmind.voice setup-stt --profile {profile}')
    return _run_worker('stt', profile, data, suffix.lower())[0]


def synthesize_speech(text: str, voice: str = DEFAULT_VOICE) -> bytes:
    if voice not in VOICES:
        raise VoiceError(422, 'Неизвестный локальный голос.')
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TTS_CHARACTERS:
        raise VoiceError(422, 'Для озвучивания нужен текст от 1 до 1200 символов.')
    if not _installed('piper') or not _tts_ready(voice):
        raise VoiceError(503, 'Локальный голос Piper не установлен. Установите requirements-voice.txt и выполните python -m localmind.voice setup-tts. См. docs/VOICE.md.')
    return _run_worker('tts', voice, text.encode('utf-8'), '.txt')[1]


def _decode_bounded(source: Path):
    """Decode incrementally; never allocate an unbounded complete recording."""
    import av
    import numpy as np

    chunks, samples = [], 0
    started = time.monotonic()
    demuxers = {'.webm': 'matroska', '.ogg': 'ogg', '.mp4': 'mov', '.m4a': 'mov', '.wav': 'wav'}
    if source.suffix.lower() not in demuxers:
        raise VoiceError(415, 'Неподдерживаемый формат записи.')
    # A media upload is not a playlist. Forcing the declared container prevents
    # format sniffing from opening HLS/concat files containing network/file URLs.
    with av.open(str(source), mode='r', format=demuxers[source.suffix.lower()],
                 options={'protocol_whitelist': 'file', 'enable_drefs': '0', 'use_absolute_path': '0'}) as container:
        if not container.streams.audio:
            raise VoiceError(422, 'В файле нет звуковой дорожки.')
        resampler = av.AudioResampler(format='s16', layout='mono', rate=SAMPLE_RATE)
        for index, frame in enumerate(container.decode(audio=0)):
            if index > 10000 or time.monotonic() - started > 15:
                raise VoiceError(422, 'Превышен лимит декодирования записи.')
            # Reject absurd decoder frames before converting to a numpy array.
            if frame.samples > 192000 or (frame.sample_rate and frame.samples / frame.sample_rate > 2):
                raise VoiceError(422, 'Некорректный звуковой кадр.')
            for decoded in resampler.resample(frame):
                samples += decoded.samples
                if samples > MAX_RECORDING_SECONDS * SAMPLE_RATE:
                    raise VoiceError(413, 'Запись длиннее 30 секунд. Запишите более короткую фразу.')
                chunks.append(decoded.to_ndarray().reshape(-1))
        for decoded in resampler.resample(None):
            samples += decoded.samples
            if samples > MAX_RECORDING_SECONDS * SAMPLE_RATE:
                raise VoiceError(413, 'Запись длиннее 30 секунд.')
            chunks.append(decoded.to_ndarray().reshape(-1))
    if samples < SAMPLE_RATE // 5:
        raise VoiceError(422, 'Запись слишком короткая: говорите хотя бы секунду.')
    signal = np.concatenate(chunks).astype(np.float32) / 32768.0
    if float(np.sqrt(np.mean(signal * signal))) < 0.001:
        raise VoiceError(422, 'Речь не обнаружена. Проверьте микрофон и повторите запись.')
    return signal


def _recognize(source: Path, profile: str) -> dict:
    from faster_whisper import WhisperModel

    signal = _decode_bounded(source)
    config = PROFILES[profile]
    model_directory = MODELS / 'whisper' / config['model']
    device, compute_type = config['device'], config['compute_type']
    fallback = False

    def run(selected_device, selected_compute):
        model = WhisperModel(str(model_directory), device=selected_device, compute_type=selected_compute,
                             cpu_threads=4, num_workers=1, local_files_only=True)
        segments, _ = model.transcribe(signal, language='ru', vad_filter=True, beam_size=5,
                                      condition_on_previous_text=False,
                                      initial_prompt='Русская речь. Пельмени, Codex, Кодекс, Obsidian, Discord, Visual Studio Code, блокнот, калькулятор.')
        words = []
        for segment in segments:
            words.append(segment.text.strip())
            if sum(map(len, words)) > 4000:
                raise VoiceError(422, 'Слишком длинная расшифровка.')
        return ' '.join(words).strip()

    try:
        text = run(device, compute_type)
    except (RuntimeError, ValueError, OSError):
        if device != 'cuda':
            raise
        device, compute_type, fallback = 'cpu', 'int8', True
    if fallback:
        # Leave the exception handler first so its traceback no longer retains
        # the failed GPU model while loading the CPU fallback.
        text = run(device, compute_type)
    if not text:
        raise VoiceError(422, 'Речь не обнаружена. Говорите ближе к микрофону.')
    return {'text': text, 'profile': profile, 'device': device, 'fallback': fallback,
            'recording_seconds': round(len(signal) / SAMPLE_RATE, 3)}


def _synthesize(source: Path, voice: str, destination: Path) -> dict:
    from piper import PiperVoice

    text = source.read_text(encoding='utf-8')
    engine = PiperVoice.load(str(MODELS / 'piper' / (voice + '.onnx')), use_cuda=False)
    with wave.open(str(destination), 'wb') as output:
        engine.synthesize_wav(text, output)
    with wave.open(str(destination), 'rb') as audio:
        seconds = audio.getnframes() / audio.getframerate()
        if seconds > MAX_TTS_SECONDS:
            raise VoiceError(422, 'Озвучивание длиннее двух минут. Сократите текст.')
    return {'voice': voice, 'duration_seconds': round(seconds, 3)}


def _worker(kind: str, selection: str, source: Path, result: Path, destination: Path):
    started = time.monotonic()
    try:
        if kind == 'stt' and selection in PROFILES:
            payload = _recognize(source, selection)
        elif kind == 'tts' and selection in VOICES:
            payload = _synthesize(source, selection, destination)
        else:
            raise VoiceError(422, 'Неизвестный режим голосового модуля.')
        payload['duration_ms'] = round((time.monotonic() - started) * 1000)
    except VoiceError as exc:
        payload = {'error': exc.detail, 'status_code': exc.status_code}
    except Exception:
        # Do not log user audio, transcripts, model paths, tokens, or native diagnostics.
        payload = {'error': 'Не удалось обработать голос. Проверьте файл, модель и зависимости в docs/VOICE.md.', 'status_code': 422}
    result.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description='LocalMind: explicit voice setup and isolated inference')
    commands = parser.add_subparsers(dest='command', required=True)
    stt = commands.add_parser('setup-stt', help='Download an STT model (network only during setup)')
    stt.add_argument('--profile', choices=PROFILES, default='balanced')
    commands.add_parser('setup-tts', help='Download the declared Russian Piper voice')
    commands.add_parser('status')
    worker = commands.add_parser('_worker')
    worker.add_argument('kind', choices=('stt', 'tts'))
    worker.add_argument('selection')
    worker.add_argument('source', type=Path)
    worker.add_argument('result', type=Path)
    worker.add_argument('destination', type=Path)
    args = parser.parse_args()
    if args.command == '_worker':
        _worker(args.kind, args.selection, args.source, args.result, args.destination)
    elif args.command == 'setup-stt':
        # Setup may download, but it must not write caches/logs into the user's
        # home directory. These settings affect only this explicit CLI process.
        os.environ['HF_HOME'] = str(MODELS / '.download-cache')
        os.environ['HF_HUB_CACHE'] = str(MODELS / '.download-cache' / 'hub')
        os.environ['HF_XET_CACHE'] = str(MODELS / '.download-cache' / 'xet')
        os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
        from faster_whisper.utils import download_model
        directory = MODELS / 'whisper' / PROFILES[args.profile]['model']
        directory.mkdir(parents=True, exist_ok=True)
        download_model(PROFILES[args.profile]['model'], output_dir=str(directory),
                       cache_dir=str(MODELS / '.download-cache' / 'hub'))
        print('STT model downloaded. Inference will use local files only.')
    elif args.command == 'setup-tts':
        from piper.download_voices import download_voice
        directory = MODELS / 'piper'
        directory.mkdir(parents=True, exist_ok=True)
        download_voice(DEFAULT_VOICE, directory)
        print('Russian voice downloaded. See docs/VOICE.md for engine and voice licenses.')
    else:
        print(json.dumps(voice_status(), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
