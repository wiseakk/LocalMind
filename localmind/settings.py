import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

from .paths import APP_ROOT as ROOT, DATA_ROOT
load_dotenv(DATA_ROOT / '.env')
# Source checkout compatibility; release preferences take precedence.
load_dotenv(ROOT / '.env')

@dataclass(frozen=True)
class Settings:
    # This release is deliberately local-only. Do not make the listener host
    # configurable until authenticated and encrypted pairing exists.
    host: str = '127.0.0.1'
    port: int = int(os.getenv('LOCALMIND_PORT', '8765'))
    key: str = os.getenv('LOCALMIND_KEY', '')
    model: str = os.getenv('OLLAMA_MODEL', 'gemma4:12b-it-q4_K_M' if sys.platform == 'linux' else 'gemma4:12b')
    ollama_url: str = os.getenv('OLLAMA_URL', 'http://127.0.0.1:11434').rstrip('/')
    demo: bool = os.getenv('DEMO_MODE', 'true').strip().lower() in ('true', '1', 'yes')
    ha_url: str = os.getenv('HOME_ASSISTANT_URL', '').rstrip('/')
    ha_token: str = os.getenv('HOME_ASSISTANT_TOKEN', '')
    # Legacy base is a compatible fast-mode preference, never a model download.
    whisper_model: str = 'small' if os.getenv('WHISPER_MODEL', 'small') == 'base' else os.getenv('WHISPER_MODEL', 'small')

settings = Settings()
DEVICES = json.loads((ROOT / 'config' / 'devices.json').read_text(encoding='utf-8'))
