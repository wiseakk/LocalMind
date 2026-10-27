import json
import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')

@dataclass(frozen=True)
class Settings:
    host: str = os.getenv('LOCALMIND_HOST', '127.0.0.1')
    port: int = int(os.getenv('LOCALMIND_PORT', '8765'))
    key: str = os.getenv('LOCALMIND_KEY', '')
    model: str = os.getenv('OLLAMA_MODEL', 'qwen3:4b')
    ollama_url: str = os.getenv('OLLAMA_URL', 'http://127.0.0.1:11434').rstrip('/')
    demo: bool = os.getenv('DEMO_MODE', 'true').strip().lower() in ('true', '1', 'yes')
    ha_url: str = os.getenv('HOME_ASSISTANT_URL', '').rstrip('/')
    ha_token: str = os.getenv('HOME_ASSISTANT_TOKEN', '')
    whisper_model: str = os.getenv('WHISPER_MODEL', 'base')

settings = Settings()
DEVICES = json.loads((ROOT / 'config' / 'devices.json').read_text(encoding='utf-8'))
