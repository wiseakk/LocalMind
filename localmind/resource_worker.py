"""Private bounded first-run inference probe. No microphone or audio retention."""
import json
import re
import sys


def main():
    protocol = sys.stdout
    sys.stdout = sys.stderr
    try:
        kind = sys.argv[1]
        if kind == 'asr':
            import numpy as np
            from .voice import Recognizer, MODELS, PROFILES
            from .paths import ordinary_tree
            profile = sys.argv[2] if len(sys.argv) > 2 else 'balanced'
            config = PROFILES[profile]
            folder = sys.argv[3] if len(sys.argv) > 3 else config['model']
            if folder != config['model'] and not re.fullmatch(r'\.asr-stage-[a-f0-9]{32}', folder):
                raise ValueError('Unknown staging folder')
            # Readiness probe verifies CPU portability. GPU is only proven by
            # an actual recognition request and reported by that worker.
            model, _, _ = Recognizer().load(ordinary_tree(MODELS / 'whisper' / folder), 'cpu', 'int8')
            segments, _ = model.transcribe(np.zeros(16000, dtype=np.float32), language='ru', beam_size=1, vad_filter=False)
            list(segments)
        elif kind == 'tts':
            from .tts_worker import load_engine, synthesize
            voice = 'silero-v5_6-ru'
            audio = synthesize(load_engine(voice), voice, 'Проверка голоса.')
            if len(audio) < 100:
                raise ValueError('Empty speech')
        else:
            raise ValueError('Unknown probe')
    except Exception as exc:
        from .voice_diagnostics import classify_voice_error
        protocol.write(json.dumps({'code': classify_voice_error(exc)}))
        return 1
    protocol.write(json.dumps({'ready': True}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
